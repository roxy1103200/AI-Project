"""Offline acceptance checks for routing, evidence reflection, and latched budgets."""

import asyncio
import json
import os
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent_budget import BudgetedModel, CircuitOpen, RequestBudget, configured_limit
from app.intent import SCREENING_PATTERN, QuestionPlan, understand
from app.query_answers import policy_answer
from app.react_agent import initial_state
from app.reflection import ReflectionResult, grounded_revision
from app.task_progress import build_tasks, progress, select_route
from tests.test_react_agent import ScriptedModel, decision


class WorkflowGuardTests(unittest.IsolatedAsyncioTestCase):
    """Run the actual graph with isolated tools and controlled provider responses."""

    async def asyncSetUp(self) -> None:
        from app.main import Assistant

        async def extract(_, question, history):
            return await understand(None, question, history)

        self.patches = [
            patch("app.react_agent.understand", side_effect=extract),
            patch("app.intent.beijing_today", return_value=date(2026, 10, 8)),
        ]
        for item in self.patches:
            item.start()
        with patch("app.main.create_model", return_value=None):
            self.assistant = Assistant()
        self.assistant.model = ScriptedModel([])
        self.assistant.memory.recall = AsyncMock(return_value=[])
        self.assistant.mcp.call_tool = AsyncMock(return_value={"status": "ISSUED"})

    async def asyncTearDown(self) -> None:
        await self.assistant.client.aclose()
        await self.assistant.reranker.aclose()
        for item in reversed(self.patches):
            item.stop()

    async def invoke(self, question: str) -> dict:
        return await self.assistant.graph.ainvoke(
            initial_state(2, "guards", question, []), config=self.assistant.workflow.config
        )

    async def test_simple_has_no_decision_call_and_only_one_reflection(self) -> None:
        result = await self.invoke("OTEST12 的状态")
        self.assertEqual((result["route"], result["step_count"], result["tool_call_count"]), ("simple", 1, 1))
        self.assertEqual(result["stop_reason"], "simple_verified")
        self.assertEqual(result["model_call_count"], 1)  # Extraction is patched in this case.
        self.assertEqual(result["reflection_call_count"], 1)

        self.assertEqual(self.assistant.model.requests, [])
        self.assertEqual(len(self.assistant.model.reflection_requests), 1)

    async def test_real_understanding_is_included_in_simple_two_call_budget(self) -> None:
        class UnderstandingModel(ScriptedModel):
            async def ainvoke(self, messages, **kwargs):
                if kwargs["config"]["metadata"]["agent_stage"] == "understanding":
                    return AIMessage(
                        content=QuestionPlan(
                            intent="order", normalized_question="查订单", confidence=0.95
                        ).model_dump_json(),
                        usage_metadata={"input_tokens": 200, "output_tokens": 50, "total_tokens": 250},
                    )
                return await super().ainvoke(messages, **kwargs)

        self.assistant.model = UnderstandingModel([])
        with patch("app.react_agent.understand", wraps=understand):
            result = await self.invoke("OTEST12 的状态")
        self.assertEqual(result["model_call_count"], 2)
        self.assertEqual(result["token_usage"]["total_tokens"], 370)
        self.assertEqual(result["reflection_call_count"], 1)

        self.assistant.workflow.max_simple_model_calls = 1
        self.assistant.model = UnderstandingModel([])
        with patch("app.react_agent.understand", wraps=understand):
            limited = await self.invoke("OTEST12 的状态")
        self.assertEqual(limited["stop_reason"], "model_budget")
        self.assertEqual(limited["model_call_count"], 1)
        self.assertEqual(limited["reflection_call_count"], 0)
        self.assertEqual(self.assistant.model.reflection_requests, [])

    async def test_fifth_step_ends_partial_task_without_reflection_or_sixth_call(self) -> None:
        self.assistant.workflow.max_tool_calls = 8
        numbers = [f"OTEST{number}" for number in range(12, 18)]
        self.assistant.model = ScriptedModel(
            [decision("query_order", {"order_no": number}, number) for number in numbers]
        )
        result = await self.invoke("分别查询 " + " ".join(numbers) + " 的订单状态")
        self.assertEqual(result["stop_reason"], "max_steps")
        self.assertEqual(result["step_count"], 5)
        self.assertEqual(self.assistant.mcp.call_tool.await_count, 5)
        self.assertEqual(len(self.assistant.model.requests), 5)
        self.assertEqual(result["reflection_call_count"], 0)
        self.assertEqual(len(self.assistant.model.reflection_requests), 0)
        self.assertTrue(result["circuit_open"])
        self.assertIn("OTEST17", result["answer"])
        self.assertIn("尚未完成", result["answer"])

    async def test_third_invalid_call_trips_before_fourth_decision(self) -> None:
        self.assistant.model = ScriptedModel([decision("refund_order", {}, str(i)) for i in range(4)])
        result = await self.invoke("查询 OTEST12 OTEST13 的订单状态")
        self.assertEqual(result["stop_reason"], "retry_limit")
        self.assertEqual(result["invalid_call_count"], 3)
        self.assertEqual(len(self.assistant.model.requests), 3)
        self.assertEqual(result["reflection_call_count"], 0)
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_duplicate_execution_is_blocked_and_partial_evidence_kept(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("query_order", {"order_no": "OTEST12"}),
                decision("query_order", {"order_no": "OTEST12"}, "again"),
            ]
        )
        result = await self.invoke("分别查询 OTEST12 OTEST13 的状态")
        self.assertEqual(result["stop_reason"], "duplicate_call")
        self.assistant.mcp.call_tool.assert_awaited_once()
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(result["reflection_call_count"], 0)
        self.assertIn("OTEST13", result["answer"])

    async def test_model_call_budget_includes_failed_attempt_and_prevents_next_tool(self) -> None:
        self.assistant.workflow.max_model_calls = 1
        self.assistant.model = ScriptedModel([decision("query_order", {"order_no": "OTEST12"})])
        result = await self.invoke("分别查询 OTEST12 OTEST13 的状态")
        self.assertEqual(result["stop_reason"], "model_budget")
        self.assertEqual(result["model_call_count"], 1)
        self.assistant.mcp.call_tool.assert_awaited_once()
        self.assertEqual(result["reflection_call_count"], 0)

    async def test_token_budget_is_checked_before_any_external_call(self) -> None:
        self.assistant.workflow.max_total_tokens = 100
        result = await self.invoke("分别查询 OTEST12 OTEST13 的状态")
        self.assertEqual(result["stop_reason"], "token_budget")
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(result["reflection_call_count"], 0)
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_reflection_cannot_publish_hallucinated_status(self) -> None:
        self.assistant.model.reflection_response = AIMessage(
            content=json.dumps(
                {
                    "verdict": "revise",
                    "revised_answer": "订单已退款，退款金额 99999 元。",
                },
                ensure_ascii=False,
            )
        )
        result = await self.invoke("OTEST12 的状态")
        self.assertEqual(result["reflection_status"], "rejected")
        self.assertEqual(result["stop_reason"], "reflection_fallback")
        self.assertNotIn("99999", result["answer"])
        self.assertIn("已出票", result["answer"])
        self.assertEqual(len(self.assistant.model.reflection_requests), 1)

    async def test_model_clarification_cannot_smuggle_unverified_business_facts(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("query_seats", {"screening_id": 999}),
                decision("ask_user", {"question": "订单已经退款99999元，请选择场次。"}, "ask"),
            ]
        )
        result = await self.invoke("《测试电影》今天的空座")
        self.assertEqual(result["stop_reason"], "needs_user")
        self.assertNotIn("99999", result["answer"])
        self.assertIn("请选择", result["answer"])
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_malformed_and_tool_call_reflections_fall_back_without_retry(self) -> None:
        for response in (AIMessage(content="not-json"), decision("query_order", {"order_no": "OTEST13"})):
            with self.subTest(response=response):
                self.assistant.model = ScriptedModel([])
                self.assistant.model.reflection_response = response
                result = await self.invoke("OTEST12 的状态")
                self.assertEqual(result["reflection_status"], "failed")
                self.assertEqual(result["model_call_count"], 1)
                self.assertEqual(result["reflection_call_count"], 1)
                self.assertIn("已出票", result["answer"])
        self.assertEqual(self.assistant.mcp.call_tool.await_count, 2)

    async def test_unplanned_requirement_flag_is_disclosed_without_new_tools(self) -> None:
        self.assistant.model.reflection_response = AIMessage(
            content=json.dumps(
                {
                    "verdict": "missing",
                    "missing_items": ["需进一步确认的要求"],
                    "recommended_action": "continue",
                },
                ensure_ascii=False,
            )
        )
        result = await self.invoke("OTEST12 的状态")
        self.assertEqual(result["stop_reason"], "verifier_incomplete")
        self.assistant.mcp.call_tool.assert_awaited_once()
        self.assertIn("尚未覆盖全部要求", result["answer"])

    async def test_reflection_continuation_uses_existing_todo_and_never_reflects_twice(self) -> None:
        first = await self.invoke("OTEST12 的状态")
        second_plan = await understand(None, "分别查询 OTEST12 OTEST13 的状态", [])
        state = {**first, **second_plan, "question": "分别查询 OTEST12 OTEST13 的状态", "route": "react"}
        state["tasks"] = build_tasks(state)
        state["messages"] = [{"role": "user", "content": state["question"]}]
        state["answer"] = ""
        state["verified_answer"] = ""
        state["reflection_call_count"] = 0
        state["budget"] = RequestBudget()
        state["stop_reason"] = ""
        self.assistant.model = ScriptedModel([decision("query_order", {"order_no": "OTEST13"}, "second")])
        with patch("app.react_agent.get_stream_writer", return_value=lambda _: None):
            reflected = await self.assistant.workflow.reflect(state)
            self.assertTrue(reflected["reflection_resume"])
            planned = await self.assistant.workflow.agent(reflected)
            queried = await self.assistant.workflow.tools(planned)
            drafted = await self.assistant.workflow.draft(queried)
            final = await self.assistant.workflow.reflect({**queried, **drafted})
        self.assertEqual(final["stop_reason"], "done_code_checked")
        self.assertEqual(len(self.assistant.model.reflection_requests), 1)

    async def test_stream_waits_for_reflection_before_sending_answer_text(self) -> None:
        from app.main import LiveChatRequest

        started, release = asyncio.Event(), asyncio.Event()

        class DelayedReflection(ScriptedModel):
            async def ainvoke(self, messages, **kwargs):
                started.set()
                await release.wait()
                return await super().ainvoke(messages, **kwargs)

        self.assistant.model = DelayedReflection([])
        packets = []

        async def consume():
            async for wire in self.assistant.live(
                LiveChatRequest(user_id=2, session_id="gate", question="OTEST12 状态")
            ):
                packets.append(json.loads(wire.removeprefix("data: ").strip()))

        task = asyncio.create_task(consume())
        try:
            async with asyncio.timeout(5):
                await started.wait()
                self.assertFalse(any(packet["type"] == "delta" for packet in packets))
                release.set()
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(sum(packet["type"] == "delta" for packet in packets), 1)
        self.assertEqual(packets[-1]["type"], "complete")

    async def test_concurrent_requests_have_separate_budget_instances(self) -> None:
        first, second = await asyncio.gather(self.invoke("OTEST12 的状态"), self.invoke("OTEST13 的状态"))
        self.assertIsNot(first["budget"], second["budget"])
        self.assertEqual([item["model_call_count"] for item in (first, second)], [1, 1])
        first["budget"].trip("token_budget")
        self.assertEqual(second["budget"].stop_reason, "")

    async def test_simple_recommendation_keeps_confirmed_memory_preference(self) -> None:
        self.assistant.memory.recall.return_value = [{"category": "GENRE", "content": "我喜欢科幻电影"}]
        recommendation = AsyncMock()
        recommendation.ainvoke.return_value = [{"title": "星际旅途", "genre": "科幻", "duration": 100}]
        self.assistant.tools["recommend_movies"] = recommendation
        result = await self.invoke("推荐几部电影")
        self.assertEqual(result["route"], "simple")
        recommendation.ainvoke.assert_awaited_once_with({"preference": "科幻", "user_id": 2})
        self.assertIn("星际旅途", result["answer"])

    async def test_oral_screening_id_routes_to_single_seat_query(self) -> None:
        self.assistant.mcp.call_tool.return_value = [{"seat_code": "1-1", "booking_status": "AVAILABLE"}]
        result = await self.invoke("38这场还有座没，帮我瞅瞅")
        self.assertEqual(result["route"], "simple")
        self.assistant.mcp.call_tool.assert_awaited_once_with("query_seats", {"screening_id": 38}, user_id=2)

    async def test_multiple_movie_queries_require_separate_evidence(self) -> None:
        question = "《电影甲》和《电影乙》的导演分别是谁"
        plan = await understand(None, question, [])
        state = {**initial_state(2, "films", question, []), **plan}
        state["tasks"] = build_tasks(state)
        self.assertEqual(select_route(state)[0], "react")
        state["observations"] = [
            {
                "name": "search_movies",
                "arguments": dict(state["tasks"][0]["arguments"]),
                "task_id": state["tasks"][0]["id"],
                "data": [{"title": "电影甲"}],
            }
        ]
        self.assertEqual([item["status"] for item in progress(state)], ["done", "pending"])


class BudgetBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """Test preflight accounting without graph extraction patches."""

    async def test_evaluation_observer_distinguishes_reflection_from_understanding(self) -> None:
        from evaluation.run import ACTIVE, ObservedModel

        row = {"model_calls": [], "proposals": []}
        token = ACTIVE.set(row)
        try:
            tracked = BudgetedModel(ObservedModel(ScriptedModel([])), RequestBudget(), "reflection", 1000)
            await tracked.bind(response_format={"type": "json_object"}).ainvoke([HumanMessage(content="check")])
        finally:
            ACTIVE.reset(token)
        self.assertEqual([call["stage"] for call in row["model_calls"]], ["reflection"])
        self.assertEqual(row["proposals"], [])

    async def test_usage_missing_keeps_reservation_and_latches_budget(self) -> None:
        model = AsyncMock()
        model.ainvoke.return_value = AIMessage(content="ok")
        budget = RequestBudget(max_calls=1)
        tracked = BudgetedModel(model, budget, "reflection", 20)
        await tracked.ainvoke([HumanMessage(content="check")])
        self.assertEqual(budget.snapshot()["token_usage"]["accounting"], "conservative_reservation")
        self.assertEqual(budget.missing_usage_calls, 1)
        with self.assertRaises(CircuitOpen):
            await tracked.ainvoke([HumanMessage(content="again")])
        model.ainvoke.assert_awaited_once()
        self.assertEqual(budget.stop_reason, "model_budget")

    async def test_failed_provider_attempt_is_counted_and_not_retried(self) -> None:
        model = AsyncMock()
        model.ainvoke.side_effect = RuntimeError("provider down")
        budget = RequestBudget()
        with self.assertRaises(RuntimeError):
            await BudgetedModel(model, budget, "decision", 20).ainvoke([HumanMessage(content="test")])
        self.assertEqual((budget.calls, budget.missing_usage_calls), (1, 1))
        model.ainvoke.assert_awaited_once()

    async def test_deadline_prevents_even_the_first_call(self) -> None:
        budget = RequestBudget(timeout_seconds=0)
        model = AsyncMock()
        with self.assertRaises(CircuitOpen):
            await BudgetedModel(model, budget, "decision").ainvoke([HumanMessage(content="test")])
        model.ainvoke.assert_not_awaited()
        self.assertEqual(budget.stop_reason, "timeout")

    async def test_outer_deadline_latches_the_budget_and_retains_unknown_usage(self) -> None:
        async def blocked(*_, **__):
            await asyncio.Event().wait()

        model = AsyncMock()
        model.ainvoke.side_effect = blocked
        budget = RequestBudget()
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.02):
                await BudgetedModel(model, budget, "understanding").ainvoke([HumanMessage(content="test")])
        self.assertEqual((budget.calls, budget.missing_usage_calls, budget.stop_reason), (1, 1, "timeout"))
        with self.assertRaises(CircuitOpen):
            budget.remaining_seconds()

    def test_environment_cannot_raise_code_hard_limits(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_STEPS": "999", "AGENT_MAX_INVALID_CALLS": "999"}):
            self.assertEqual(configured_limit("AGENT_MAX_STEPS", 5, 5), 5)
            self.assertEqual(configured_limit("AGENT_MAX_INVALID_CALLS", 3, 3), 3)

    def test_counts_prices_and_times_do_not_authorize_screening_ids(self) -> None:
        for text in ("今天3场还有空位吗", "票价38元", "18点那场", "前2场", "共有3场次"):
            with self.subTest(text=text):
                self.assertEqual(list(SCREENING_PATTERN.finditer(text)), [])

    def test_policy_preserves_purchase_evidence_without_stale_refund_passages(self) -> None:
        answer = policy_answer(
            {
                "policy": {"version": 2, "policy": "开场前30分钟截止退票", "cutoff_minutes": 30},
                "answer_context": ["旧退票政策：开场前60分钟截止退票", "儿童票以影院活动为准"],
            }
        )
        self.assertIn("30 分钟", answer)
        self.assertIn("儿童票以影院活动为准", answer)
        self.assertNotIn("60分钟", answer)

    def test_rewrite_cannot_mix_status_or_amount_between_record_blocks(self) -> None:
        blocks = ["订单 A：金额 20，已出票", "订单 B：金额 30，已退款"]
        self.assertIsNone(
            grounded_revision(
                ReflectionResult(
                    verdict="revise",
                    revised_answer="订单 A：金额 30，已退款\n订单 B：金额 20，已出票",
                ),
                blocks,
            )
        )
        self.assertEqual(
            grounded_revision(ReflectionResult(verdict="pass", evidence_order=[1, 0]), blocks),
            "\n\n".join(reversed(blocks)),
        )
        self.assertIsNone(grounded_revision(ReflectionResult(verdict="pass", evidence_order=[0, 0]), blocks))
