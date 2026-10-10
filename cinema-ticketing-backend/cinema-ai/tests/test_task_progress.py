"""Regression coverage for explicit subtask completion and independent retry limits."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import AIMessage

from app.failures import CinemaQueryError
from app.intent import QuestionPlan, understand
from app.react_agent import initial_state
from app.react_tools import validate_arguments
from app.task_progress import build_tasks, progress
from evaluation.metrics import judge
from tests.test_react_agent import ScriptedModel, decision, screening


class TaskProgressTests(unittest.IsolatedAsyncioTestCase):
    """Use local scripted models only; no provider or development database calls."""

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
        self.assistant.memory.recall = AsyncMock(return_value=[])
        self.assistant.mcp.call_tool = AsyncMock()

    async def asyncTearDown(self) -> None:
        await self.assistant.client.aclose()
        await self.assistant.reranker.aclose()
        for item in self.patches:
            item.stop()

    async def invoke(self, question: str) -> dict:
        return await self.assistant.graph.ainvoke(
            initial_state(2, "tasks", question, []), config=self.assistant.workflow.config
        )

    async def test_model_missing_identifiers_cannot_erase_two_user_orders(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(
            return_value=SimpleNamespace(
                content=QuestionPlan(intent="order", normalized_question="查订单", confidence=0.9).model_dump_json()
            )
        )
        plan = await understand(model, "查询 OTEST12 和 OTEST13 两个订单的状态", [])
        self.assertEqual(plan["entities"]["order_nos"], ["OTEST12", "OTEST13"])
        self.assertEqual(plan["clarification"], "")

    async def test_refund_followup_keeps_qualification_and_all_identifiers(self) -> None:
        history = [{"role": "user", "content": "我的票能退钱吗？"}]
        plan = await understand(None, "OTEST12", history)
        self.assertEqual(plan["intent"], "refund")
        self.assertEqual(plan["entities"]["order_nos"], ["OTEST12"])
        policy = await understand(None, "退票需要满足什么条件？", [])
        self.assertEqual(policy["intent"], "policy")
        self.assertFalse(policy["clarification"])

    async def test_null_date_text_is_normalized_without_relaxing_explicit_dates(self) -> None:
        question = "查询《评测专用不存在影片X9F7》的导演和片长。"
        plan = await understand(None, question, [])
        state = {**initial_state(2, "null-date", question, []), **plan}
        state["tasks"] = build_tasks(state)
        for value in ("None", "null", "", " NULL "):
            with self.subTest(value=value):
                arguments = validate_arguments("search_movies", {"screening_date": value}, state)
                self.assertIsNone(arguments["screening_date"])
        with self.assertRaisesRegex(CinemaQueryError, "screening_date"):
            validate_arguments("search_movies", {"screening_date": "2026-10-08"}, state)
        dated_question = "2026-10-08有哪些实际场次？"
        dated_plan = await understand(None, dated_question, [])
        dated_state = {**initial_state(2, "dated", dated_question, []), **dated_plan}
        dated_state["tasks"] = build_tasks(dated_state)
        with self.assertRaisesRegex(CinemaQueryError, "screening_date"):
            validate_arguments("search_screenings", {"screening_date": "None"}, dated_state)

    async def test_invalid_date_has_specific_clarification(self) -> None:
        result = await self.invoke("2026-02-30有哪些实际场次？")
        self.assertIn("2026-02-30", result["answer"])
        self.assertIn("不存在", result["answer"])
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_two_orders_finish_without_third_decision(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("query_order", {"order_no": "OTEST12"}),
                decision("query_order", {"order_no": "OTEST13"}, "second"),
            ]
        )
        self.assistant.mcp.call_tool.side_effect = [
            {"order_no": "OTEST12", "status": "ISSUED"},
            {"order_no": "OTEST13", "status": "REFUNDED"},
        ]
        result = await self.invoke("分别查询 OTEST12 和 OTEST13 两个订单的状态")
        self.assertEqual(result["tool_calls"], ["query_order", "query_order"])
        self.assertEqual(result["finish_reason"], "complete")
        self.assertEqual(len(self.assistant.model.requests), 2)

    async def test_catalogue_scope_does_not_inherit_screening_date_or_showing(self) -> None:
        question = "查《测试电影》的导演和片长，再查今天实际场次及第一场座位"
        plan = await understand(None, question, [])
        plan["entities"]["movie_scope"] = "showing"  # Wrong initial model inference.
        state = {**initial_state(2, "scope", question, []), **plan}
        state["tasks"] = build_tasks(state)
        args = validate_arguments("search_movies", {"movie_scope": "catalog"}, state)
        self.assertEqual(args["movie_scope"], "catalog")
        self.assertIsNone(args["screening_date"])
        args = validate_arguments("search_screenings", {}, state)
        self.assertEqual((args["screening_date"], args["query_scope"]), ("2026-10-08", "scheduled"))

    async def test_invalid_call_does_not_consume_successful_query_budget(self) -> None:
        self.assistant.workflow.max_tool_calls = 2
        self.assistant.model = ScriptedModel(
            [
                decision("query_seats", {"screening_id": 999}),
                decision("search_screenings", {}, "discover"),
                decision("query_seats", {"screening_id": 12}, "seat"),
            ]
        )
        self.assistant.mcp.call_tool.side_effect = [
            [screening(12)],
            [{"seat_code": "1-1", "booking_status": "AVAILABLE"}],
        ]
        result = await self.invoke("查询《测试电影》今天实际场次和第一场座位")
        self.assertEqual(result["tool_call_count"], 2)
        self.assertEqual(result["invalid_call_count"], 1)
        self.assertEqual(result["finish_reason"], "complete")

    async def test_repeated_invalid_calls_are_bounded_without_upstream_queries(self) -> None:
        self.assistant.workflow.max_invalid_calls = 2
        self.assistant.model = ScriptedModel(
            [decision("query_seats", {"screening_id": 999}), decision("query_seats", {"screening_id": 998}, "retry")]
        )
        result = await self.invoke("查询《测试电影》今天场次和第一场座位")
        self.assertEqual(result["invalid_call_count"], 2)
        self.assertEqual(result["tool_call_count"], 0)
        self.assistant.mcp.call_tool.assert_not_awaited()

    async def test_early_model_finish_recovers_missing_second_order(self) -> None:
        self.assistant.model = ScriptedModel(
            [decision("query_order", {"order_no": "OTEST12"}), AIMessage(content="完成")]
        )
        self.assistant.mcp.call_tool.side_effect = [{"status": "ISSUED"}, {"status": "REFUNDED"}]
        result = await self.invoke("查询 OTEST12 和 OTEST13 两个订单")
        self.assertEqual(result["tool_calls"], ["query_order", "query_order"])

    async def test_four_completed_queries_do_not_report_budget_exhaustion(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("query_order", {"order_no": number}, number)
                for number in ("OTEST12", "OTEST13", "OTEST14", "OTEST15")
            ]
        )
        self.assistant.mcp.call_tool.return_value = {"status": "ISSUED"}
        result = await self.invoke("查询 OTEST12 OTEST13 OTEST14 OTEST15 四个订单")
        self.assertEqual(result["finish_reason"], "complete")
        self.assertNotIn("查询上限", result["answer"])

    async def test_multiple_unselected_screenings_require_user_choice(self) -> None:
        self.assistant.model = ScriptedModel([decision("search_screenings", {}), AIMessage(content="完成")])
        self.assistant.mcp.call_tool.return_value = [screening(12), screening(13)]
        result = await self.invoke("查《测试电影》今天的空座")
        self.assertIn("多个场次", result["answer"])
        self.assistant.mcp.call_tool.assert_awaited_once()

    async def test_empty_screenings_finish_without_inventing_seat_ids(self) -> None:
        self.assistant.model = ScriptedModel([decision("search_screenings", {})])
        self.assistant.mcp.call_tool.return_value = []
        result = await self.invoke("查《测试电影》今天的第一场座位")
        self.assertEqual(result["finish_reason"], "complete")
        self.assertEqual([item["status"] for item in progress(result)], ["done", "empty"])

    async def test_first_screening_cannot_be_replaced_by_another_valid_id(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                decision("search_screenings", {}),
                decision("query_seats", {"screening_id": 13}, "wrong"),
                decision("query_seats", {"screening_id": 12}, "first"),
            ]
        )
        self.assistant.mcp.call_tool.side_effect = [
            [screening(12), screening(13)],
            [{"seat_code": "1-1", "booking_status": "AVAILABLE"}],
        ]
        result = await self.invoke("查《测试电影》今天第一场的座位")
        self.assertEqual(result["invalid_call_count"], 1)
        self.assertEqual(result["observations"][-1]["arguments"]["screening_id"], 12)

    def test_answer_toolchain_and_extra_calls_are_independent_metrics(self) -> None:
        expected = {"name": "query_order", "arguments": {"order_no": "OTEST12"}, "user_id": 2}
        case = {"id": "unit", "plans": [[expected]], "answer_checks": ["已出票"]}
        result = {"tools": [expected, expected], "validation": [], "answer": "已出票", "completed": True, "errors": []}
        score = judge(case, result)
        self.assertTrue(score["answer_correct"])
        self.assertFalse(score["task_success"])
        self.assertEqual(score["extra_tool_calls"], 1)

    def test_correct_numeric_only_seat_answer_is_accepted_symmetrically(self) -> None:
        case = {"id": "S07", "plans": [[]], "answer_checks": [r"可选.*(?<!\d)48(?!\d)"]}
        row = {"tools": [], "validation": [], "answer": "48", "completed": True, "errors": []}
        self.assertTrue(judge(case, row)["answer_correct"])
        row["answer"] = "47"
        self.assertFalse(judge(case, row)["answer_correct"])

    async def test_wrong_initial_intent_does_not_skip_explicit_seat_request(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(
            return_value=SimpleNamespace(
                content=QuestionPlan(
                    intent="unsupported", normalized_question="不清楚", confidence=0.2
                ).model_dump_json()
            )
        )
        plan = await understand(model, "查询《测试电影》今天实际场次和第一场座位", [])
        self.assertEqual(plan["intent"], "seats")
        self.assertGreaterEqual(plan["confidence"], 0.65)

    def test_missing_query_is_not_mislabeled_as_extra_and_rejected_duplicates_still_fail(self) -> None:
        one = {"name": "query_order", "arguments": {"order_no": "OTEST12"}, "user_id": 2}
        two = {"name": "query_order", "arguments": {"order_no": "OTEST13"}, "user_id": 2}
        case = {"id": "unit", "plans": [[one, two], [two, one]], "answer_checks": ["已出票"]}
        row = {"tools": [one], "validation": [], "answer": "已出票", "completed": True, "errors": []}
        self.assertEqual(judge(case, row)["extra_tool_calls"], 0)
        row["tools"] = [two, one]
        self.assertTrue(judge(case, row)["tool_correct"])
        case["plans"] = [[one, two]]
        self.assertFalse(judge(case, row)["tool_correct"])
        self.assertEqual(judge(case, row)["extra_tool_calls"], 0)
        case["plans"] = [[two, one]]
        row["invalid_call_count"] = 1  # Rejected duplicate after argument validation.
        self.assertFalse(judge(case, row)["tool_correct"])
