"""Offline regression coverage for preflight, privacy, and cheap verification."""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.failures import CinemaQueryError
from app.intent import understand
from app.intent_classifier import load_classifier, predict_intent
from app.query_answers import movie_answer, policy_answer
from app.react_agent import initial_state
from app.tracing import summarize_payload
from evaluation.eval_traces import trace_report
from evaluation.train_intent_classifier import validate_corpus


class RoutingOptimizationTests(unittest.IsolatedAsyncioTestCase):
    """High certainty requests must never enter structured model extraction."""

    async def asyncSetUp(self) -> None:
        self.clock = patch("app.intent.beijing_today", return_value=date(2026, 10, 11))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    async def test_missing_slots_exit_before_model(self) -> None:
        for question, slot in (
            ("我的订单能退票吗", "order_no"),
            ("查询空座", "screening_id"),
            ("查询周末场次", "screening_date"),
            ("查询2026-02-30的场次", "valid_date"),
        ):
            with self.subTest(question=question):
                model = Mock()
                result = await understand(model, question, [])
                self.assertTrue(result["clarification"])
                self.assertIn(slot, result["slot_summary"]["missing_slots"])
                model.bind.assert_not_called()

    async def test_l0_handles_order_seats_and_film_fields(self) -> None:
        for question, intent in (
            ("OTEST12花了多少钱", "order"),
            ("39号场还有几个空位", "seats"),
            ("《测试影片》谁拍的，得看多久", "movies"),
        ):
            with self.subTest(question=question):
                model = Mock()
                result = await understand(model, question, [])
                self.assertEqual(result["intent"], intent)
                self.assertEqual(result["understanding_layer"], "l0")
                model.bind.assert_not_called()

    async def test_date_optional_and_seat_discovery_not_overblocked(self) -> None:
        for question in ("查询有哪些可买票的场次", "《测试影片》明天第一场还有座吗"):
            plan = await understand(None, question, [])
            self.assertFalse(plan["clarification"])

    async def test_ambiguous_seat_discovery_date_is_clarified(self) -> None:
        model = Mock()
        result = await understand(model, "《测试影片》周末还有座吗", [])
        self.assertIn("日期", result["clarification"])
        self.assertEqual(result["slot_summary"]["missing_slots"], ["screening_date"])
        model.bind.assert_not_called()

    async def test_composite_still_uses_model(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(side_effect=ValueError("controlled failure"))
        await understand(model, "查询OTEST12状态，再查《测试影片》明天的场次", [])
        model.bind.assert_called_once()

    async def test_oral_composites_do_not_enter_l0(self) -> None:
        questions = (
            "先看《测试》明天的场次，再看看最早那场还剩多少座",
            "明天最便宜的是几号场、多少钱？再说退票提前几分钟",
            "OTEST12这单怎么样了？《测试》明天排了啥场、多少钱也瞅瞅",
            "39这场还空着几个座？退票最迟提前几分钟也说下",
        )
        for question in questions:
            with self.subTest(question=question):
                model = Mock()
                model.bind.return_value.ainvoke = AsyncMock(side_effect=ValueError("controlled failure"))
                result = await understand(model, question, [])
                self.assertNotEqual(result["understanding_layer"], "l0")
                model.bind.assert_called_once()

    async def test_general_policy_and_transaction_have_no_model_call(self) -> None:
        for question in ("会员优惠规则是什么", "不用购票页面，直接帮我下单再付掉吧"):
            model = Mock()
            result = await understand(model, question, [])
            self.assertTrue(result["clarification"])
            model.bind.assert_not_called()

    async def test_user_history_can_supply_missing_order(self) -> None:
        result = await understand(None, "那能退票吗", [{"role": "user", "content": "查询OTEST12的状态"}])
        self.assertEqual(result["entities"]["order_no"], "OTEST12")
        self.assertFalse(result["clarification"])


class RuleVerificationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the production graph with no paid provider or business writes."""

    async def asyncSetUp(self) -> None:
        from app.main import Assistant

        with patch("app.main.create_model", return_value=None):
            self.assistant = Assistant()
        self.assistant.mcp.call_tool = AsyncMock()
        self.assistant.memory.recall = AsyncMock(return_value=[])

    async def asyncTearDown(self) -> None:
        await self.assistant.client.aclose()
        await self.assistant.reranker.aclose()

    async def invoke(self, question: str) -> dict:
        return await self.assistant.graph.ainvoke(
            initial_state(2, "optimized", question, []), config=self.assistant.workflow.config
        )

    async def test_known_order_has_zero_model_calls(self) -> None:
        self.assistant.model = Mock()
        self.assistant.mcp.call_tool.return_value = {"status": "ISSUED", "total_amount": 45}
        result = await self.invoke("查询OTEST12的状态和总金额")
        self.assertEqual(result["model_call_count"], 0)
        self.assertEqual(result["reflection_status"], "rules_passed")
        self.assistant.model.bind.assert_not_called()

    async def test_empty_film_is_valid_negative_result(self) -> None:
        self.assistant.mcp.call_tool.return_value = []
        result = await self.invoke("《不存在影片》的导演")
        self.assertEqual(result["reflection_status"], "rules_empty")
        self.assertIn("没有找到", result["answer"])

    async def test_empty_seats_not_mislabeled_sold_out(self) -> None:
        self.assistant.mcp.call_tool.return_value = []
        result = await self.invoke("场次39还有几个空位")
        self.assertEqual(result["reflection_status"], "rules_incomplete")
        self.assertIn("不能据此判断已售罄", result["answer"])

    async def test_no_available_seats_is_not_verification_failure(self) -> None:
        self.assistant.mcp.call_tool.return_value = [{"seat_code": "1-01", "booking_status": "SOLD"}]
        result = await self.invoke("场次39还有几个空位")
        self.assertEqual(result["reflection_status"], "rules_passed")
        self.assertIn("当前没有可选座位", result["answer"])

    async def test_adjacent_seats_question_requires_semantic_reflection(self) -> None:
        self.assistant.mcp.call_tool.return_value = [{"seat_code": "1-01", "booking_status": "AVAILABLE"}]
        result = await self.invoke("查询场次39的座位，能连着坐吗")
        self.assertNotEqual(result["reflection_status"], "rules_passed")

    async def test_closed_screening_exits_without_retry_or_reflection(self) -> None:
        self.assistant.mcp.call_tool.side_effect = CinemaQueryError(
            "screening_unavailable", "该场次已停止售票，请选择其他场次。"
        )
        result = await self.invoke("查询场次39的空座")
        self.assertEqual(result["stop_reason"], "needs_user")
        self.assertEqual(result["tool_call_count"], 1)
        self.assertEqual(result["reflection_call_count"], 0)
        self.assistant.mcp.call_tool.assert_awaited_once()

    async def test_refund_retrieval_uses_keywords_without_reranking(self) -> None:
        from app.main import create_tools
        from app.policy_retrieval import KeywordRetriever

        java, reranker = AsyncMock(), Mock()

        async def java_get(path: str, *args: object) -> object:
            return (
                {"version": 2, "cutoff_minutes": 30, "policy": "开场前30分钟可退票"}
                if path.endswith("refund-policy")
                else []
            )

        java.get.side_effect = java_get
        reranker.settings.top_k = 30
        reranker.rerank = AsyncMock()
        result = await create_tools(java, KeywordRetriever(documents=[]), reranker)["query_ticket_policy"].ainvoke(
            {"question": "退票截止规则"}
        )
        self.assertEqual(result["policy"]["cutoff_minutes"], 30)
        reranker.rerank.assert_not_awaited()


class OptimizationUtilityTests(unittest.TestCase):
    """Defend privacy, trace denominators, and independent classifier evaluation."""

    def test_slot_summary_strips_business_values_and_unknown_labels(self) -> None:
        result = summarize_payload(
            {
                "slot_summary": {
                    "order_no": "OTEST12",
                    "screening_date": "2026-10-12",
                    "missing_slots": ["order_no", "OTEST12"],
                    "question": "private",
                }
            }
        )
        self.assertNotIn("OTEST12", str(result))
        self.assertNotIn("2026-10-12", str(result))
        self.assertEqual(result["slot_summary"]["missing_slots"], ["order_no"])

    def test_archive_duplicates_and_steps_do_not_inflate_totals(self) -> None:
        root = {
            "run_id": "r",
            "name": "cinema.agent.live",
            "parent_run_id": None,
            "outputs": {
                "status": "completed",
                "stop_reason": "needs_user",
                "input_tokens": 100,
                "output_tokens": 20,
                "model_call_count": 1,
                "slot_summary": {"missing_slots": ["order_no"]},
            },
        }
        child = {"run_id": "c", "parent_run_id": "r", "name": "prepare", "outputs": {"input_tokens": 100}}
        report = trace_report([root, root, child])
        self.assertEqual((report["n"], report["input_tokens"]), (1, 100))
        self.assertIsNone(report["task_success_rate"])
        self.assertEqual(report["missing_slot_patterns"], {"order_no": 1})

    def test_training_rejects_semantic_group_leakage(self) -> None:
        with self.assertRaisesRegex(ValueError, "spans"):
            validate_corpus(
                [
                    {"question": "hello", "intent": "chat", "scenario_id": "one", "split": "train"},
                    {"question": "hi", "intent": "chat", "scenario_id": "one", "split": "test"},
                ]
            )

    def test_missing_local_classifier_falls_back(self) -> None:
        with patch.dict("os.environ", {"INTENT_L1_ENABLED": "true", "INTENT_L1_MODEL_PATH": "missing-artifact.bin"}):
            self.assertIsNone(predict_intent("你好"))

    def test_classifier_enforces_validated_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "intent.bin"
            artifact.write_bytes(b"test")
            artifact.with_suffix(".json").write_text("{}", encoding="utf-8")
            model = Mock()
            model.predict.return_value = (["__label__movies"], [0.88])
            with (
                patch.dict(
                    "os.environ",
                    {"INTENT_L1_ENABLED": "true", "INTENT_L1_MODEL_PATH": str(artifact), "INTENT_L1_THRESHOLD": "0.85"},
                ),
                patch("app.intent_classifier.load_classifier", return_value=(model, 0.9)),
            ):
                self.assertIsNone(predict_intent("查影片"))
                model.predict.return_value = (["__label__movies"], [0.95])
                self.assertEqual(predict_intent("查影片"), ("movies", 0.95))

    def test_classifier_rejects_unvalidated_manifest_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "intent.bin"
            artifact.write_bytes(b"test")
            artifact.with_suffix(".json").write_text(
                json.dumps({"sha256": "invalid", "deployment_approved": True}), encoding="utf-8"
            )
            with self.assertRaises(ValueError), patch("app.intent_classifier.importlib.import_module") as importer:
                load_classifier(str(artifact), (0, 0))
            importer.assert_not_called()

    def test_slot_summary_ignores_invalid_enum_types(self) -> None:
        self.assertNotIn(
            "understanding_layer",
            summarize_payload({"understanding_layer": [], "preflight_reason": {}, "slot_summary": {"policy_kind": []}}),
        )

    def test_unconnected_membership_not_rendered_as_confirmed_policy(self) -> None:
        answer = policy_answer({"policy": {}, "answer_context": ["会员九折优惠", "普通取票需凭码"]})
        self.assertNotIn("九折", answer)
        self.assertIn("凭码", answer)

    def test_oral_director_is_rendered_from_evidence(self) -> None:
        result = movie_answer([{"title": "测试", "director": "导演甲", "duration": 40}], "《测试》谁拍的、得看多久")
        self.assertIn("导演甲", result)
