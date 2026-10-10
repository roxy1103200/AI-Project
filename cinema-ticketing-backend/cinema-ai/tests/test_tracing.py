"""Verify environment gating, outbound data filtering and real callback propagation."""

import asyncio
import json
import os
import unittest
from typing import TypedDict
from unittest.mock import patch
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph import END, START, StateGraph
from langsmith import Client

from app.failures import describe_failure
from app.tracing import AgentTracing, MetadataOnlyClient, SdkLogFilter, current_trace_id, tool_span

SECRET = "PRIVATE-ORDER-13800138000-sk-dummy-secret"


class DiagnosticState(TypedDict, total=False):
    """Synthetic state used only to check actual LangGraph/LangChain instrumentation."""

    question: str
    answer: str
    intent: str


class TracingTests(unittest.IsolatedAsyncioTestCase):
    """Exercise SDK transport boundaries without network or paid model calls."""

    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {"LANGSMITH_TRACING": "false", "AI_ENVIRONMENT": "test"})
        self.environment.start()
        self.client = MetadataOnlyClient(api_key="test-key", auto_batch_tracing=False, info={})
        self.create = patch.object(Client, "_create_run")
        self.update = patch.object(Client, "_update_run")
        self.created = self.create.start()
        self.updated = self.update.start()

    async def asyncTearDown(self) -> None:
        await asyncio.to_thread(wait_for_all_tracers)
        self.update.stop()
        self.create.stop()
        self.environment.stop()

    def test_production_and_unset_environment_never_create_a_client(self) -> None:
        for environment in ("production", "prod", ""):
            with (
                patch.dict(os.environ, {"AI_ENVIRONMENT": environment, "LANGSMITH_TRACING": "true"}),
                patch("app.tracing.MetadataOnlyClient") as constructor,
            ):
                tracing = AgentTracing()
                self.assertIsNone(tracing.client)
                constructor.assert_not_called()

    def test_disabled_scope_does_not_upload_even_with_global_tracing_switch(self) -> None:
        with patch.dict(os.environ, {"AI_ENVIRONMENT": "production", "LANGSMITH_TRACING": "true"}):
            tracing = AgentTracing()
            with tracing.turn(9, "private-session", SECRET, "live") as turn:
                self.assertEqual(current_trace_id(), str(turn.trace_id))
                with tool_span("query_order", {"order_no": SECRET}):
                    pass
                turn.observe({"type": "complete"})
        self.created.assert_not_called()
        self.updated.assert_not_called()
        self.assertEqual(current_trace_id(), "none")

    def test_workspace_id_is_sent_as_tenant_header(self) -> None:
        workspace_id = str(uuid4())
        with (
            patch.dict(
                os.environ,
                {"AI_ENVIRONMENT": "local", "LANGSMITH_TRACING": "true", "LANGSMITH_WORKSPACE_ID": workspace_id},
            ),
            patch("app.tracing.load_langsmith_key", return_value="test-key"),
            patch("app.tracing.MetadataOnlyClient") as constructor,
        ):
            AgentTracing()
        self.assertEqual(constructor.call_args.kwargs["session"].headers["X-Tenant-Id"], workspace_id)

    def test_invalid_workspace_id_disables_tracing_without_breaking_business(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"AI_ENVIRONMENT": "local", "LANGSMITH_TRACING": "true", "LANGSMITH_WORKSPACE_ID": "invalid"},
            ),
            patch("app.tracing.load_langsmith_key", return_value="test-key"),
        ):
            self.assertIsNone(AgentTracing().client)

    def test_sdk_writes_filter_prompts_results_errors_metadata_events_and_attachments(self) -> None:
        run_id = uuid4()
        with patch.dict(os.environ, {"LANGSMITH_EXTRA_PRIVATE": SECRET}):
            self.client.create_run(
                "ChatOpenAI",
                {"question": SECRET, "user_id": 9, "messages": [{"content": SECRET}]},
                "llm",
                id=run_id,
                outputs={"answer": SECRET},
                serialized={"api_key": SECRET},
                error=f"RuntimeError: {SECRET}",
                extra={"metadata": {"private": SECRET, "stage": "react_tool"}},
                tags=[SECRET],
                attachments={SECRET: ("text/plain", b"private")},
            )
            self.client.update_run(
                run_id,
                outputs={"data": [{"order_no": SECRET}], "error_code": "business_unavailable"},
                error=f"RuntimeError: {SECRET}",
                extra={"metadata": {"question": SECRET}},
                events=[{"name": "new_token", "kwargs": {"token": SECRET}}],
            )
        self.assertEqual(self.created.call_count, 1)
        self.assertEqual(self.updated.call_count, 1)
        payloads = [self.created.call_args.args[0], self.updated.call_args.args[0]]
        encoded = json.dumps(payloads, default=str)
        self.assertNotIn(SECRET, encoded)
        self.assertNotIn("user_id", encoded)
        self.assertNotIn("order_no", encoded)
        self.assertNotIn("serialized", encoded)
        self.assertEqual(payloads[0]["error"], "execution_failed")
        self.assertEqual(payloads[1]["outputs"]["row_count"], 1)

    async def test_native_graph_model_and_explicit_tool_are_children_of_same_root(self) -> None:
        model = FakeListChatModel(responses=[SECRET])

        async def agent(_: DiagnosticState) -> dict:
            reply = await model.ainvoke(SECRET)
            return {"answer": reply.content}

        def tools(_: DiagnosticState) -> dict:
            with tool_span("search_movies", {"query": SECRET}) as run:
                run.end(outputs={"data": [{"title": SECRET}]})
            return {}

        graph = StateGraph(DiagnosticState)
        graph.add_node("prepare", lambda state: {"intent": "movies"})
        graph.add_node("agent", agent)
        graph.add_node("tools", tools)
        graph.add_node("respond", lambda state: {})
        for source, destination in (
            (START, "prepare"),
            ("prepare", "agent"),
            ("agent", "tools"),
            ("tools", "respond"),
            ("respond", END),
        ):
            graph.add_edge(source, destination)
        tracing = AgentTracing()
        tracing.environment, tracing.project, tracing.client = "test", "cinema-agent-test", self.client
        with tracing.turn(9, "private-session", SECRET, "live") as turn:
            result = await graph.compile().ainvoke({"question": SECRET})
            turn.observe({"type": "context", **result})
            turn.observe({"type": "complete"})
            root_id = turn.trace_id
        await asyncio.to_thread(wait_for_all_tracers)
        payloads = [call.args[0] for call in self.created.call_args_list]
        names = {run["name"] for run in payloads}
        self.assertTrue({"prepare", "agent", "tools", "respond", "FakeListChatModel", "tool.search_movies"} <= names)
        self.assertTrue(all(str(run["trace_id"]) == str(root_id) for run in payloads))
        self.assertNotIn(SECRET, json.dumps(payloads, default=str))

    def test_caught_error_and_missing_stream_completion_are_visible(self) -> None:
        tracing = AgentTracing()
        tracing.environment, tracing.project, tracing.client = "test", "cinema-agent-test", self.client
        with tracing.turn(9, "private-session", SECRET, "live") as turn:
            describe_failure(RuntimeError(SECRET), "react_response")
            turn.observe({"type": "error", "code": "business_unavailable"})
            turn.observe({"type": "complete"})
        result = self.updated.call_args.args[0]
        self.assertEqual(result["error"], "business_unavailable")
        self.assertEqual(result["outputs"]["failure_count"], 1)
        self.assertNotIn(SECRET, json.dumps(result, default=str))
        with tracing.turn(9, "private-session", SECRET, "live"):
            pass
        self.assertEqual(self.updated.call_args.args[0]["error"], "stream_incomplete")

    def test_timeout_preserves_safe_error_code(self) -> None:
        tracing = AgentTracing()
        tracing.environment, tracing.project, tracing.client = "test", "cinema-agent-test", self.client
        with self.assertRaises(TimeoutError), tracing.turn(9, "private-session", SECRET, "live"):
            raise TimeoutError(SECRET)
        result = self.updated.call_args.args[0]
        self.assertEqual(result["error"], "query_timeout")
        self.assertNotIn(SECRET, json.dumps(result, default=str))

    async def test_actual_live_stream_reports_failure_and_cancellation(self) -> None:
        from app.main import Assistant, LiveChatRequest

        with patch("app.main.create_model", return_value=None):
            assistant = Assistant()
        assistant.tracing.client = self.client

        async def failed(_):
            describe_failure(RuntimeError(SECRET), "react_response")
            yield 'data: {"type":"error","code":"agent_error"}\n\n'

        assistant._live = failed
        request = LiveChatRequest(user_id=9, session_id="private-session", question=SECRET)
        try:
            packets = [json.loads(packet.removeprefix("data: ")) async for packet in assistant.live(request)]
            self.assertEqual(packets[0]["type"], "trace")
            self.assertEqual(self.updated.call_args.args[0]["error"], "agent_error")
            stream = assistant.live(request)
            await anext(stream)
            await stream.aclose()
            self.assertEqual(self.updated.call_args.args[0]["error"], "interrupted")
        finally:
            await assistant.client.aclose()
            await assistant.reranker.aclose()

    def test_unavailable_upload_does_not_fail_business_request(self) -> None:
        self.created.side_effect = RuntimeError(SECRET)
        tracing = AgentTracing()
        tracing.client = self.client
        with tracing.turn(9, "private-session", SECRET, "live") as turn:
            turn.observe({"type": "complete"})
        self.assertEqual(turn.status, "completed")

    def test_sdk_log_filter_removes_credential_fragments_and_tracebacks(self) -> None:
        import logging

        record = logging.LogRecord("langsmith.client", logging.WARNING, "", 0, SECRET, (), None)
        SdkLogFilter().filter(record)
        self.assertNotIn(SECRET, record.getMessage())


if __name__ == "__main__":
    unittest.main()
