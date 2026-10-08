"""Exercise the real graph with scripted model decisions and isolated business tools."""

import asyncio
import json
import unittest
from collections.abc import AsyncIterator
from datetime import date
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage

from app.failures import CinemaQueryError
from app.intent import understand
from app.react_tools import TOOL_SPECS, validate_arguments

with patch("app.model_config.create_model", return_value=None):
    from app.main import Assistant, ChatRequest, HistoryMessage, LiveChatRequest


def decision(name: str, arguments: dict, call_id: str = "call-1") -> AIMessage:
    """Represent a provider function call without any hidden reasoning text."""
    return AIMessage(
        content="内部规划不会发到前端",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def screening(screening_id: int) -> dict:
    """Return the minimum factual screening contract and a real identifier."""
    return {
        "id": screening_id,
        "title": "测试电影",
        "start_time": "2026-10-08T18:00:00",
        "cinema_name": "测试影院",
        "hall_name": "测试厅",
        "price": 30,
    }


class ScriptedModel:
    """Capture each decision context; generate a separate final answer stream."""

    def __init__(self, decisions: list[AIMessage], answer: str = "查到场次及座位，状态为查询时快照。") -> None:
        self.decisions = list(decisions)
        self.answer = answer
        self.requests: list[list[BaseMessage]] = []
        self.schemas: list[dict] = []

    def bind_tools(self, schemas: list[dict], **_: object) -> "ScriptedModel":
        """Match the existing ChatOpenAI tool-binding interface."""
        self.schemas = schemas
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        """Consume one decision in order and retain the actual observations."""
        self.requests.append(list(messages))
        return self.decisions.pop(0)

    async def astream(self, _: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        """Emit real async answer chunks instead of replaying planning messages."""
        yield AIMessageChunk(content=self.answer[:5])
        yield AIMessageChunk(content=self.answer[5:])


class ReActAgentTests(unittest.IsolatedAsyncioTestCase):
    """Verify multi-hop decisions, the live path, provenance, limits and cancellation."""

    async def asyncSetUp(self) -> None:
        self.date_patch = patch("app.intent.beijing_today", return_value=date(2026, 10, 8))
        self.date_patch.start()

        # Keep extraction deterministic; only the ReAct decision model is scripted.
        async def extract(_, question, history):
            return await understand(None, question, history)

        self.intent_patch = patch("app.react_agent.understand", side_effect=extract)
        self.intent_patch.start()
        with patch("app.main.create_model", return_value=None):
            self.assistant = Assistant()
        self.assistant.memory.recall = AsyncMock(return_value=[])
        self.assistant.mcp.call_tool = AsyncMock()

    async def asyncTearDown(self) -> None:
        await self.assistant.client.aclose()
        self.intent_patch.stop()
        self.date_patch.stop()

    async def packets(self, question: str, history: list[HistoryMessage] | None = None) -> list[dict]:
        """Read the actual website entry point's wire protocol."""
        return [
            json.loads(packet.removeprefix("data: ").strip())
            async for packet in self.assistant.live(
                LiveChatRequest(user_id=2, session_id="react", question=question, history=history or [])
            )
        ]

    async def test_live_discovers_screenings_then_queries_multiple_seats_with_observations(self) -> None:
        model = ScriptedModel(
            [
                decision("search_screenings", {}),
                decision("query_seats", {"screening_id": 12}, "seat-12"),
                decision("query_seats", {"screening_id": 13}, "seat-13"),
                AIMessage(content="查询完成"),
            ]
        )
        self.assistant.model = model
        self.assistant.mcp.call_tool.side_effect = [
            [screening(12), screening(13)],
            [{"seat_code": "1-1", "booking_status": "AVAILABLE"}],
            [{"seat_code": "2-1", "booking_status": "SOLD"}],
        ]
        packets = await self.packets("《测试电影》今天的场次和各场空座")
        calls = self.assistant.mcp.call_tool.call_args_list
        self.assertEqual([item.args[0] for item in calls], ["search_screenings", "query_seats", "query_seats"])
        self.assertTrue(all(item.kwargs["user_id"] == 2 for item in calls))
        self.assertEqual(calls[0].args[1]["screening_date"], "2026-10-08")
        self.assertEqual(calls[0].args[1]["query_scope"], "scheduled")
        observations = [message for message in model.requests[1] if isinstance(message, ToolMessage)]
        self.assertEqual(len(observations), 1)
        self.assertIn('"id": 12', observations[0].content)
        self.assertEqual(sum(isinstance(message, ToolMessage) for message in model.requests[-1]), 3)
        self.assertEqual(
            [p for p in packets if p["type"] == "context"][-1]["tool_calls"],
            ["search_screenings", "query_seats", "query_seats"],
        )
        self.assertEqual("".join(p["text"] for p in packets if p["type"] == "delta"), model.answer)
        self.assertEqual(packets[-1]["type"], "complete")
        self.assertNotIn("内部规划", json.dumps(packets, ensure_ascii=False))

    async def test_chat_uses_same_loop_and_preserves_refund_envelope(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("query_order", {"order_no": "OTEST12"}),
                decision("query_ticket_policy", {"question": "退票规则"}, "policy"),
                AIMessage(content="查询完成"),
            ]
        )
        self.assistant.mcp.call_tool.return_value = {"order_no": "OTEST12", "status": "ISSUED", "can_refund": True}
        self.assistant.tools["query_ticket_policy"] = AsyncMock()
        self.assistant.tools["query_ticket_policy"].ainvoke.return_value = {
            "policy": {"version": 3},
            "answer_context": ["退票规则"],
            "sources": [{"source": "rules.md"}],
        }
        result = await self.assistant.chat(ChatRequest(user_id=9, session_id="refund", question="OTEST12 能退票吗"))
        self.assertEqual(result.tool_calls, ["query_order", "query_ticket_policy"])
        self.assertTrue(result.data["order"]["can_refund"])
        self.assertEqual(result.sources, [{"source": "rules.md"}])
        self.assistant.mcp.call_tool.assert_awaited_once_with("query_order", {"order_no": "OTEST12"}, user_id=9)
        self.assertIs(self.assistant.graph, self.assistant.workflow.graph)

    async def test_missing_order_is_clarified_without_model_or_tool_call(self) -> None:
        model = ScriptedModel([])
        self.assistant.model = model
        packets = await self.packets("我的订单能退票吗")
        self.assertIn("订单号", "".join(p.get("text", "") for p in packets))
        self.assertEqual(model.requests, [])
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_invented_screening_in_assistant_history_cannot_authorize_seat_query(self) -> None:
        model = ScriptedModel(
            [
                decision("query_seats", {"screening_id": 999}),
                decision("ask_user", {"question": "请选择要查询的场次。"}, "clarify"),
            ]
        )
        self.assistant.model = model
        packets = await self.packets("《测试电影》今天的空座", [HistoryMessage(role="assistant", content="场次999")])
        self.assistant.mcp.call_tool.assert_not_awaited()
        self.assertTrue(any("请选择" in p.get("text", "") for p in packets))
        errors = [message for message in model.requests[1] if isinstance(message, ToolMessage)]
        self.assertIn("invalid_tool_call", errors[0].content)

    async def test_unknown_write_tool_and_identity_override_never_reach_backend(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("refund_order", {"order_no": "OTEST12"}),
                decision("query_order", {"order_no": "OTEST12", "user_id": 9}, "identity"),
                decision("query_order", {"order_no": "OTEST12"}, "valid"),
                AIMessage(content="完成"),
            ]
        )
        self.assistant.mcp.call_tool.return_value = {"status": "ISSUED"}
        packets = await self.packets("OTEST12 的状态")
        self.assistant.mcp.call_tool.assert_awaited_once_with("query_order", {"order_no": "OTEST12"}, user_id=2)
        self.assertEqual(packets[-1]["type"], "complete")
        self.assertEqual([p for p in packets if p["type"] == "context"][-1]["tool_calls"], ["query_order"])

    async def test_duplicate_queries_consume_budget_without_repeating_upstream(self) -> None:
        self.assistant.workflow.max_tool_calls = 2
        model = ScriptedModel(
            [
                decision("query_order", {"order_no": "OTEST12"}),
                decision("query_order", {"order_no": "OTEST12"}, "repeat"),
            ]
        )
        self.assistant.model = model
        self.assistant.mcp.call_tool.return_value = {"status": "ISSUED"}
        packets = await self.packets("OTEST12 的状态")
        self.assistant.mcp.call_tool.assert_awaited_once()
        self.assertEqual(len(model.requests), 2)
        self.assertIn("查询上限", "".join(p.get("text", "") for p in packets))

    async def test_oversized_batch_stops_at_call_budget(self) -> None:
        self.assistant.workflow.max_tool_calls = 2
        call = AIMessage(
            content="",
            tool_calls=[
                {"name": "query_order", "args": {"order_no": number}, "id": number, "type": "tool_call"}
                for number in ("OTEST12", "OTEST13", "OTEST14")
            ],
        )
        model = ScriptedModel([call])
        self.assistant.model = model
        self.assistant.mcp.call_tool.return_value = {"status": "ISSUED"}
        packets = await self.packets("查询 OTEST12 OTEST13 OTEST14 的状态")
        self.assertEqual(self.assistant.mcp.call_tool.await_count, 2)
        self.assertEqual(len(model.requests), 1)
        self.assertIn("查询上限", "".join(p.get("text", "") for p in packets))

    async def test_wrong_scope_result_stops_graph_before_fact_generation(self) -> None:
        self.assistant.model = ScriptedModel([decision("search_movies", {})])
        self.assistant.mcp.call_tool.return_value = [{"id": 3, "title": "缺少排期依据"}]
        packets = await self.packets("今天已排期的电影有哪些")
        self.assertTrue(any(p.get("code") == "query_contract_mismatch" for p in packets))
        self.assertFalse(any(p["type"] == "delta" for p in packets))
        self.assertFalse(any(p["type"] == "complete" for p in packets))

    async def test_model_cannot_answer_business_question_without_any_tool_evidence(self) -> None:
        self.assistant.model = ScriptedModel([AIMessage(content="你的订单已经支付成功。")])
        packets = await self.packets("OTEST12 的状态")
        self.assertTrue(any(p.get("code") == "agent_no_evidence" for p in packets))
        self.assertFalse(any("支付成功" in p.get("text", "") for p in packets))

    async def test_partial_evidence_cannot_generate_unqueried_order_facts(self) -> None:
        model = ScriptedModel(
            [decision("search_movies", {"query": ""}), AIMessage(content="订单已支付。")],
            answer="订单已支付。",
        )
        self.assistant.model = model
        self.assistant.mcp.call_tool.return_value = [{"id": 3, "title": "测试电影"}]
        packets = await self.packets("OTEST12 的状态")
        answer = "".join(p.get("text", "") for p in packets)
        self.assertNotIn("订单已支付", answer)
        self.assertIn("尚未完成查询本人订单", answer)

    async def test_mismatched_order_owner_never_becomes_model_evidence(self) -> None:
        self.assistant.model = ScriptedModel([decision("query_order", {"order_no": "OTEST12"})])
        self.assistant.mcp.call_tool.return_value = {
            "order_no": "OTEST12",
            "user_id": 9,
            "status": "ISSUED",
            "movie_title": "他人的电影",
        }
        packets = await self.packets("OTEST12 的状态")
        self.assertTrue(any(p.get("code") == "business_auth_failed" for p in packets))
        self.assertNotIn("他人的电影", json.dumps(packets, ensure_ascii=False))

    async def test_concurrent_graph_requests_keep_tool_observations_and_identity_separate(self) -> None:
        class OrderModel(ScriptedModel):
            async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
                if isinstance(messages[-1], ToolMessage):
                    return AIMessage(content="查询完成")
                content = json.loads(messages[1].content)
                return decision("query_order", {"order_no": content["validated_entities"]["order_no"]})

        self.assistant.model = OrderModel([])

        async def order_query(_, arguments, *, user_id):
            await asyncio.sleep(0)
            return {"order_no": arguments["order_no"], "user_id": user_id, "status": "ISSUED"}

        self.assistant.mcp.call_tool.side_effect = order_query
        responses = await asyncio.gather(
            *[
                self.assistant.chat(ChatRequest(user_id=user, session_id="same", question=f"{number} 的状态"))
                for user, number in ((2, "OTEST12"), (9, "OTEST13"))
            ]
        )
        self.assertEqual([response.data["user_id"] for response in responses], [2, 9])
        self.assertEqual([response.data["order_no"] for response in responses], ["OTEST12", "OTEST13"])

    async def test_model_decision_failure_downgrades_to_factual_single_query(self) -> None:
        model = ScriptedModel([])
        self.assistant.model = model
        self.assistant.mcp.call_tool.return_value = [{"id": 3, "title": "测试电影"}]
        packets = await self.packets("《测试电影》的导演是谁")
        self.assistant.mcp.call_tool.assert_awaited_once()
        self.assertIn("测试电影", "".join(p.get("text", "") for p in packets))
        self.assertEqual(packets[-1]["type"], "complete")

    async def test_closing_live_stream_cancels_an_inflight_query(self) -> None:
        self.assistant.model = ScriptedModel([decision("query_order", {"order_no": "OTEST12"})])
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked_query(*_, **__):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.assistant.mcp.call_tool.side_effect = blocked_query
        stream = self.assistant.live(LiveChatRequest(user_id=2, session_id="stop", question="OTEST12 的状态"))
        async with asyncio.timeout(5):
            while not started.is_set():
                await anext(stream)
            await stream.aclose()
            await cancelled.wait()

    async def test_memory_confirmation_path_does_not_enter_react(self) -> None:
        self.assistant.model = ScriptedModel([])
        packets = await self.packets("记住：我喜欢科幻电影")
        self.assertTrue(any(p["type"] == "memory_suggestion" for p in packets))
        self.assistant.memory.recall.assert_not_awaited()
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_tool_schema_hides_identity_and_keeps_explicit_scope_date(self) -> None:
        plan = await understand(None, "《测试电影》今天已排期的电影", [])
        state = {**plan, "messages": [{"role": "user", "content": "《测试电影》今天已排期的电影"}]}
        args = validate_arguments("search_movies", {}, state)
        self.assertEqual((args["movie_scope"], args["screening_date"]), ("scheduled", "2026-10-08"))
        for args in ({"movie_scope": "catalog"}, {"screening_date": "2026-10-09"}, {"userId": 9}):
            with self.assertRaises(CinemaQueryError):
                validate_arguments("search_movies", args, state)
        schema = next(spec for spec in TOOL_SPECS if spec["function"]["name"] == "recommend_movies")
        self.assertNotIn("user_id", schema["function"]["parameters"]["properties"])


if __name__ == "__main__":
    unittest.main()
