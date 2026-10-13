"""Offline acceptance for GLM gating, local weak labels and pinned experiments."""

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from openai import RateLimitError

from app import glm_router
from app.agent_budget import BudgetedModel, CircuitOpen, RequestBudget
from app.clarification_feedback import ClarificationFeedback, deidentify, filled_slots
from app.glm_router import GlmPrediction, apply_prediction, classify, create_glm_model, eligible, load_glm_key
from app.intent import QuestionPlan, rule_plan, understand
from app.react_agent import initial_state
from app.tracing import summarize_payload
from app.versions import ROOT, load_prompt, runtime_version
from evaluation.ab_report import report
from evaluation.golden_bindings import bind_cases, experiment_arm
from evaluation.metrics import summarize
from evaluation.run import ACTIVE, ObservedModel, instrument
from evaluation.train_intent_classifier import reject_held_out
from tests.test_react_agent import ScriptedModel


def prediction(**changes: object) -> GlmPrediction:
    """Represent a grounded classifier response independently of provider calls."""
    values = {
        "accept": True,
        "intent": "movies",
        "confidence": 0.95,
        "movie_query": "测试影片",
        "cinema_query": "",
        "preference": "",
        "movie_scope": "catalog",
        "screening_scope": "bookable",
        "showing_only": False,
        "multiple_tasks": False,
        "general_listing": False,
    }
    return GlmPrediction.model_validate({**values, **changes})


def fake_model(content: str | Exception) -> Mock:
    """Match the no-retry chat binding boundary and return reported usage."""
    model = Mock()
    model.bind.return_value = model
    message = (
        AIMessage(content=content, usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        if isinstance(content, str)
        else None
    )
    model.ainvoke = AsyncMock(return_value=message, side_effect=content if isinstance(content, Exception) else None)
    return model


class GlmRoutingTests(unittest.IsolatedAsyncioTestCase):
    """A high confidence score alone must never bypass deterministic constraints."""

    async def asyncSetUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "GLM_L1_THRESHOLD": "0.90",
                "GLM_L1_ENABLED": "true",
                "AGENT_L0_ENABLED": "true",
                "INTENT_L1_ENABLED": "false",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.clock = patch("app.intent.beijing_today", return_value=date(2026, 10, 11))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        glm_router._COOLDOWN_UNTIL = 0

    async def test_accepted_glm_skips_qwen_and_preserves_entities(self) -> None:
        primary = fake_model(ValueError("primary must not be called"))
        classifier = fake_model(prediction().model_dump_json())
        result = await understand(primary, "帮我看看测试影片是谁拍的", [], classifier_model=classifier)
        self.assertEqual(result["understanding_layer"], "l1")
        self.assertEqual(result["l1_status"], "accepted")
        self.assertEqual(result["entities"]["movie_query"], "测试影片")
        primary.bind.assert_not_called()
        classifier.ainvoke.assert_awaited_once()

    async def test_rejected_prediction_falls_back_once(self) -> None:
        for output in (
            prediction(confidence=0.5).model_dump_json(),
            prediction(movie_query="不存在的片名").model_dump_json(),
            "bad JSON",
        ):
            with self.subTest(output=output):
                primary = fake_model(
                    QuestionPlan(
                        intent="movies", normalized_question="查询影片资料", movie_query="测试影片", confidence=0.95
                    ).model_dump_json()
                )
                classifier = fake_model(output)
                result = await understand(primary, "测试影片的导演是谁", [], classifier_model=classifier)
                self.assertEqual(result["understanding_layer"], "llm")
                primary.ainvoke.assert_awaited_once()
                classifier.ainvoke.assert_awaited_once()

    async def test_preflight_l0_complex_and_context_skip_glm(self) -> None:
        for question, history in (
            ("我的订单能退吗", []),
            ("查询周末场次", []),
            ("39号场还有几个空位", []),
            ("《测试影片》谁拍的", []),
            ("查询OTEST12状态，再查《测试影片》明天的场次", []),
            ("它是谁拍的", [{"role": "user", "content": "测试影片"}]),
        ):
            with self.subTest(question=question):
                classifier = fake_model(prediction().model_dump_json())
                await understand(
                    fake_model(ValueError("controlled fallback")), question, history, classifier_model=classifier
                )
                classifier.ainvoke.assert_not_awaited()

    async def test_failed_glm_is_counted_in_shared_budget(self) -> None:
        budget = RequestBudget(max_calls=2)
        model = fake_model(ValueError("provider failure"))
        result = await classify(
            BudgetedModel(model, budget, "glm_l1", 320), "测试影片导演", rule_plan("测试影片导演", [])
        )
        self.assertEqual(result[1], "unavailable")
        self.assertEqual(budget.calls, 1)
        self.assertEqual(budget.missing_usage_calls, 1)
        await BudgetedModel(fake_model("ok"), budget, "understanding").ainvoke([HumanMessage(content="next")])
        with self.assertRaises(CircuitOpen):
            await BudgetedModel(fake_model("ok"), budget, "reflection").ainvoke([HumanMessage(content="blocked")])

    async def test_classifier_timeout_permits_qwen_but_not_request_deadline(self) -> None:
        budget = RequestBudget(max_calls=3)
        model = fake_model(TimeoutError())
        result = await classify(
            BudgetedModel(model, budget, "glm_l1", 320), "测试影片导演", rule_plan("测试影片导演", [])
        )
        self.assertEqual(result[1], "timeout")
        self.assertFalse(budget.stop_reason)
        await BudgetedModel(fake_model("ok"), budget, "understanding").ainvoke([HumanMessage(content="fallback")])
        budget.started -= 100
        with self.assertRaises(CircuitOpen):
            await BudgetedModel(fake_model("ok"), budget, "reflection").ainvoke([HumanMessage(content="expired")])
        self.assertEqual(budget.stop_reason, "timeout")

    async def test_outer_local_deadline_does_not_latch_global_timeout(self) -> None:
        budget = RequestBudget(max_calls=3)
        slow = fake_model("unused")

        async def wait_forever(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(5)

        slow.ainvoke.side_effect = wait_forever
        with patch("app.glm_router.timeout_seconds", return_value=0.01):
            result = await classify(
                BudgetedModel(slow, budget, "glm_l1", 320), "测试影片导演", rule_plan("测试影片导演", [])
            )
        self.assertEqual(result[1], "timeout")
        self.assertFalse(budget.stop_reason)
        self.assertEqual(budget.calls, 1)

    async def test_rate_limit_cooldown_avoids_second_external_call(self) -> None:
        error = RateLimitError(
            "overloaded",
            response=httpx.Response(429, request=httpx.Request("POST", "https://open.bigmodel.cn")),
            body={"error": {"code": "1305"}},
        )
        model = fake_model(error)
        rules = rule_plan("测试影片导演", [])
        self.assertEqual((await classify(model, "测试影片导演", rules))[1], "rate_limited")
        self.assertEqual((await classify(model, "测试影片导演", rules))[1], "cooldown")
        model.ainvoke.assert_awaited_once()

    async def test_busy_classifier_does_not_queue_or_spend_budget(self) -> None:
        semaphore = asyncio.Semaphore(0)
        glm_router._LIMITERS[asyncio.get_running_loop()] = semaphore
        model = fake_model(prediction().model_dump_json())
        result = await classify(model, "测试影片导演", rule_plan("测试影片导演", []))
        self.assertEqual(result[1], "busy")
        model.ainvoke.assert_not_awaited()

    async def test_tool_call_in_classifier_response_is_rejected(self) -> None:
        model = fake_model(prediction().model_dump_json())
        model.ainvoke.return_value = AIMessage(content="", tool_calls=[{"name": "query_order", "args": {}, "id": "x"}])
        self.assertEqual((await classify(model, "测试影片导演", rule_plan("测试影片导演", [])))[1], "unavailable")

    async def test_budget_open_refuses_provider(self) -> None:
        budget = RequestBudget(max_calls=1, calls=1)
        model = fake_model(prediction().model_dump_json())
        self.assertEqual(
            (await classify(BudgetedModel(model, budget, "glm_l1"), "测试影片导演", rule_plan("测试影片导演", [])))[1],
            "budget_open",
        )
        model.ainvoke.assert_not_awaited()

    async def test_order_slot_reply_keeps_refund_intent_without_llm(self) -> None:
        history = [{"role": "user", "content": "我的订单能退票吗"}, {"role": "assistant", "content": "请提供订单号。"}]
        for question in ("订单号是OTEST123", "给你单号：OTEST123", "就OTEST123这单"):
            primary, classifier = fake_model("unused"), fake_model("unused")
            result = await understand(primary, question, history, classifier_model=classifier)
            self.assertEqual(result["intent"], "refund")
            self.assertFalse(result["clarification"])
            primary.ainvoke.assert_not_awaited()
            classifier.ainvoke.assert_not_awaited()
        self.assertEqual((await understand(None, "查询OTEST123的状态", history))["intent"], "order")


class GlmGraphTests(unittest.IsolatedAsyncioTestCase):
    """Verify GLM and final reflection share the production graph budget."""

    async def asyncSetUp(self) -> None:
        from app.main import Assistant

        self.environment = patch.dict(
            os.environ,
            {
                "AGENT_AB_FORCE_VARIANT": "B",
                "GLM_L1_ENABLED": "true",
                "AGENT_RULE_VERIFIER_ENABLED": "false",
                "CLARIFICATION_FEEDBACK_ENABLED": "false",
            },
        )
        self.environment.start()
        with patch("app.main.create_model", return_value=None), patch("app.main.create_glm_model", return_value=None):
            self.assistant = Assistant()
        self.assistant.mcp.call_tool = AsyncMock(
            return_value=[{"id": 1, "title": "测试影片", "director": "导演甲", "duration": 100}]
        )
        self.assistant.memory.recall = AsyncMock(return_value=[])
        glm_router._COOLDOWN_UNTIL = 0

    async def asyncTearDown(self) -> None:
        await self.assistant.client.aclose()
        await self.assistant.reranker.aclose()
        self.environment.stop()

    async def invoke(self) -> dict:
        return await self.assistant.graph.ainvoke(
            initial_state(2, "glm-test", "测试影片的导演是谁", []), config=self.assistant.workflow.config
        )

    async def test_glm_accepted_then_one_reflection(self) -> None:
        self.assistant.model = ScriptedModel([])
        self.assistant.classifier_model = fake_model(prediction().model_dump_json())
        result = await self.invoke()
        self.assertEqual(result["l1_status"], "accepted")
        self.assertEqual(result["model_call_count"], 2)
        self.assertEqual(result["reflection_call_count"], 1)
        self.assertEqual(result["stop_reason"], "simple_verified")

    async def test_glm_rejected_qwen_then_reflection_and_hard_cap(self) -> None:
        response = AIMessage(
            content=QuestionPlan(
                intent="movies", normalized_question="查询影片资料", movie_query="测试影片", confidence=0.95
            ).model_dump_json()
        )
        self.assistant.model = ScriptedModel([response])
        self.assistant.classifier_model = fake_model(prediction(confidence=0.5).model_dump_json())
        result = await self.invoke()
        self.assertEqual(result["model_call_count"], 3)
        self.assertEqual(result["stop_reason"], "simple_verified")
        self.assistant.workflow.max_model_calls = 2
        self.assistant.model = ScriptedModel([response])
        limited = await self.invoke()
        self.assertEqual(limited["model_call_count"], 2)
        self.assertEqual(limited["reflection_call_count"], 0)
        self.assertEqual(limited["stop_reason"], "model_budget")

    async def test_arm_a_never_calls_glm(self) -> None:
        self.assistant.model = ScriptedModel(
            [
                AIMessage(
                    content=QuestionPlan(
                        intent="movies", normalized_question="查询影片资料", movie_query="测试影片", confidence=0.95
                    ).model_dump_json()
                )
            ]
        )
        self.assistant.classifier_model = fake_model(prediction().model_dump_json())
        with patch.dict(os.environ, {"AGENT_AB_FORCE_VARIANT": "A"}):
            result = await self.invoke()
        self.assertEqual(result["runtime_version"]["experiment_variant"], "A")
        self.assistant.classifier_model.ainvoke.assert_not_awaited()

    async def test_production_respond_hook_collects_clarification_reply(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "CLARIFICATION_FEEDBACK_ENABLED": "true",
                    "CLARIFICATION_FEEDBACK_DB": str(Path(directory) / "feedback.sqlite3"),
                    "AGENT_RULE_VERIFIER_ENABLED": "true",
                },
            ),
        ):
            self.assistant.model = None
            self.assistant.classifier_model = None
            self.assistant.mcp.call_tool.return_value = [{"seat_code": "1-01", "booking_status": "AVAILABLE"}]
            original = "查询空座"
            first = await self.assistant.graph.ainvoke(
                initial_state(2, "feedback-integration", original, []), config=self.assistant.workflow.config
            )
            self.assertEqual(first["stop_reason"], "needs_user")
            history = [{"role": "user", "content": original}, {"role": "assistant", "content": first["answer"]}]
            second = await self.assistant.graph.ainvoke(
                initial_state(2, "feedback-integration", "场次39的座位", history), config=self.assistant.workflow.config
            )
            self.assertEqual(second["reflection_status"], "rules_passed")
            with closing(ClarificationFeedback(Path(directory) / "feedback.sqlite3").connect()) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)


class FeedbackTests(unittest.TestCase):
    """User-supplied slots are weak labels, isolated by user and actual context."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = ClarificationFeedback(Path(self.directory.name) / "feedback.sqlite3")
        self.environment = patch.dict(os.environ, {"CLARIFICATION_FEEDBACK_ENABLED": "true"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.original = "我的订单能退吗"
        self.pending = {
            **initial_state(2, "session", self.original, []),
            "intent": "refund",
            "stop_reason": "needs_user",
            "slot_summary": {"missing_slots": ["order_no"]},
        }

    def resolved(self, **changes: object) -> dict:
        reply = "订单号是OTEST123456"
        return {
            **initial_state(
                2,
                "session",
                reply,
                [{"role": "user", "content": self.original}, {"role": "assistant", "content": "请提供订单号"}],
            ),
            "intent": "refund",
            "reflection_status": "rules_passed",
            "stop_reason": "simple_verified",
            **changes,
        }

    def rows(self) -> list:
        with closing(self.store.connect()) as connection:
            return connection.execute("SELECT * FROM candidates").fetchall()

    def test_verified_reply_creates_redacted_silver_and_deduplicates(self) -> None:
        for _ in range(2):
            self.store.record(self.pending)
            self.store.record(self.resolved())
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["occurrences"], 2)
        payload = json.loads(rows[0]["payload"])
        self.assertEqual(payload["label_quality"], "silver")
        self.assertTrue(payload["requires_review"])
        self.assertEqual(payload["filled_slots"], ["order_no"])
        self.assertNotIn("OTEST123456", rows[0]["payload"])

    def test_wrong_identity_topic_or_missing_history_cannot_label(self) -> None:
        self.store.record(self.pending)
        self.store.record(self.resolved(user_id=3))
        self.store.record(self.resolved(session_id="other"))
        self.store.record(self.resolved(messages=[]))
        self.assertEqual(self.rows(), [])
        self.store.record(self.resolved(intent="movies"))
        self.store.record(self.resolved())
        self.assertEqual(self.rows(), [])

    def test_unverified_or_missing_value_cannot_label(self) -> None:
        self.store.record(self.pending)
        self.store.record(self.resolved(reflection_status="rejected"))
        self.store.record(self.resolved(question="没找到单号"))
        self.store.record(self.resolved(error="unavailable"))
        self.assertEqual(self.rows(), [])

    def test_expired_pending_is_not_reused(self) -> None:
        self.store.record(self.pending)
        with closing(self.store.connect()) as connection, connection:
            connection.execute("UPDATE pending SET created=0")
        self.store.record(self.resolved())
        self.assertEqual(self.rows(), [])

    def test_valid_slot_rules_and_common_secrets(self) -> None:
        self.assertEqual(filled_slots("2026-02-30", ["valid_date"]), [])
        self.assertEqual(filled_slots("2026-10-12", ["valid_date"]), ["valid_date"])
        self.assertEqual(filled_slots("39号场", ["screening_id"]), ["screening_id"])
        self.assertEqual(filled_slots("没有订单号", ["order_no"]), [])
        masked = deidentify("OTEST123456 13812345678 a@b.com Bearer private-secret API_KEY=private-credential")
        for secret in ("OTEST123456", "13812345678", "a@b.com", "private-secret", "private-credential"):
            self.assertNotIn(secret, masked)


class VersionGoldenTests(unittest.TestCase):
    """Reject drift, denominator inflation, leakage and misleading A/B accuracy."""

    def test_stable_assignment_and_version_privacy(self) -> None:
        with patch.dict(
            os.environ, {"AGENT_AB_FORCE_VARIANT": "", "AGENT_AB_ENABLED": "true", "AGENT_AB_B_PERCENT": "50"}
        ):
            first = runtime_version(2, "private-session")
            self.assertEqual(first, runtime_version(2, "private-session"))
            variants = {runtime_version(2, str(index))["experiment_variant"] for index in range(100)}
            self.assertEqual(variants, {"A", "B"})
        summary = summarize_payload({"runtime_version": {**first, "user_id": 2, "session_id": "private-session"}})
        self.assertNotIn("private-session", str(summary))
        self.assertNotIn("user_id", summary["runtime_version"])
        self.assertEqual(len(first["prompt_hash"]), 64)

    def test_prompts_are_pinned_and_arbitrary_paths_rejected(self) -> None:
        self.assertIn("{{TODAY}}", load_prompt("understanding"))
        self.assertIn("{{SCHEMA}}", load_prompt("understanding"))
        with self.assertRaises(ValueError):
            load_prompt("../../api/glm")

    def test_key_loader_supports_labeled_file_without_exposing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key.txt"
            expected = "synthetic_credential_1234567890"
            path.write_text("密钥: " + expected, encoding="utf-8")
            with patch.dict(os.environ, {"GLM_API_KEY": "", "GLM_API_KEY_FILE": str(path)}):
                self.assertEqual(load_glm_key(), expected)
                with patch.dict(os.environ, {"GLM_L1_ENABLED": "true", "GLM_API_BASE_URL": "https://example.org/api"}):
                    self.assertIsNone(create_glm_model())

    def test_unsafe_or_changed_scope_predictions_are_rejected(self) -> None:
        for question, candidate in (
            ("测试影片导演", prediction(movie_query="别的电影")),
            ("查询全部影片", prediction(movie_query="", general_listing=False)),
            ("我的订单", prediction(intent="order", movie_query="")),
            ("查询空座", prediction(intent="seats", movie_query="")),
            ("测试影片导演", prediction(multiple_tasks=True)),
            ("测试影片导演", prediction(showing_only=True)),
            ("测试影片导演", prediction(movie_query="电影")),
        ):
            with self.subTest(question=question, candidate=candidate):
                self.assertIsNone(apply_prediction(candidate, rule_plan(question, []), question, 0.9))
        self.assertFalse(eligible("会员优惠是什么", [], rule_plan("会员优惠是什么", []), "llm_required"))

    def test_golden_hashes_size_and_complete_clarification_coverage(self) -> None:
        directory = ROOT / "evaluation/golden/v1"
        cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        events = json.loads((directory / "observed_clarifications.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 168)
        self.assertEqual(len({case["id"] for case in cases}), 168)
        self.assertEqual(len(events), 38)
        self.assertEqual(len({event["case_id"] for event in events}), 19)
        self.assertTrue({event["case_id"] for event in events} <= {case["id"] for case in cases})
        self.assertEqual(len([case for case in cases if case["id"].startswith("FOLLOW_")]), 24)
        self.assertEqual(len({case["expected_intent"] for case in cases}), 9)
        self.assertEqual(metadata["cases_sha256"], hashlib.sha256((directory / "cases.json").read_bytes()).hexdigest())

    def trace(self, identity: str, arm: str) -> dict:
        with patch.dict(os.environ, {"AGENT_AB_FORCE_VARIANT": arm}):
            version = runtime_version(2, "experiment")
        return {
            "run_id": identity,
            "name": "cinema.agent.live",
            "parent_run_id": None,
            "outputs": {
                "runtime_version": version,
                "status": "completed",
                "model_call_count": 1,
                "input_tokens": 100,
                "output_tokens": 20,
            },
        }

    def test_live_report_deduplicates_without_inventing_accuracy(self) -> None:
        row = self.trace("a", "A")
        result = report([row, row, self.trace("b", "B")])
        self.assertEqual(result["variants"]["A"]["n"], 1)
        self.assertIsNone(result["variants"]["B"]["task_success_rate"])

    def test_ab_refuses_mixed_deployment_fingerprints(self) -> None:
        row = self.trace("a", "A")
        other = self.trace("b", "A")
        other["outputs"]["runtime_version"]["rules_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "mixes"):
            report([row, other])
        other["outputs"]["runtime_version"]["experiment_variant"] = "B"
        with self.assertRaisesRegex(ValueError, "differ"):
            report([row, other])

    def test_report_filters_environment_before_grouping(self) -> None:
        local = {**self.trace("a", "A"), "metadata": {"environment": "local"}}
        prod = {**self.trace("b", "A"), "metadata": {"environment": "production"}}
        self.assertEqual(report([local, prod], "production")["variants"]["A"]["n"], 1)

    def test_glm_usage_does_not_use_qwen_rate_card(self) -> None:
        usage = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100}
        row = {
            "ttft_ms": 10,
            "total_ms": 20,
            "completed": True,
            "errors": [],
            "tools": [],
            "score": {"task_success": True, "tool_correct": True},
            "model_calls": [{"stage": "glm_l1", "usage": usage}],
        }
        result = summarize([row])
        self.assertEqual(result["estimated_total_cny"], 0)
        self.assertEqual(result["unpriced_model_calls"], 1)
        self.assertEqual(result["avg_total_tokens"], 1100)

    def test_live_bindings_are_private_complete_and_nonmutating(self) -> None:
        cases = [{"question": "查OGOLD000001", "plans": [[{"arguments": {"order_no": "OGOLD000001"}}]]}]
        metadata = {"bindings_required_for_live": ["OGOLD000001"]}
        actual = bind_cases(cases, {"OGOLD000001": "OTEST123"}, metadata)
        self.assertEqual(actual[0]["plans"][0][0]["arguments"]["order_no"], "OTEST123")
        self.assertEqual(cases[0]["question"], "查OGOLD000001")
        with self.assertRaises(ValueError):
            bind_cases(cases, {}, metadata)
        with self.assertRaises(ValueError):
            bind_cases(cases, {"OGOLD000001": "unexpected/path"}, metadata)

    def test_forced_evaluator_arm_is_restored_even_on_failure(self) -> None:
        with patch.dict(os.environ, {"AGENT_AB_FORCE_VARIANT": "A"}):
            with self.assertRaises(RuntimeError), experiment_arm("B"):
                self.assertEqual(os.environ["AGENT_AB_FORCE_VARIANT"], "B")
                raise RuntimeError("interrupted")
            self.assertEqual(os.environ["AGENT_AB_FORCE_VARIANT"], "A")

    def test_frozen_gold_and_unreviewed_feedback_are_excluded_from_training(self) -> None:
        golden = ROOT / "evaluation/golden/v1/cases.json"
        case = json.loads(golden.read_text(encoding="utf-8"))[0]
        with self.assertRaisesRegex(ValueError, "overlaps"):
            reject_held_out([{"question": case["question"], "scenario_id": "new-label"}], golden)
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            reject_held_out(
                [{"question": "independent synthetic text", "label_quality": "silver", "review_status": "silver"}],
                golden,
            )

    def test_scored_ab_pairs_same_questions_and_exposes_independent_scores(self) -> None:
        rows = []
        for arm in ("A", "B"):
            rows.append(
                {
                    "case_id": "CASE01",
                    "variant": arm,
                    "repetition": 1,
                    "runtime_version": self.trace(arm, arm)["outputs"]["runtime_version"],
                    "completed": True,
                    "errors": [],
                    "model_calls": [],
                    "score": {
                        "task_success": True,
                        "answer_correct": True,
                        "tool_correct": True,
                        "extra_tool_calls": 0,
                    },
                    "total_ms": 30,
                    "ttft_ms": 20,
                    "expected_intent": "movies",
                    "phrasing_style": "口语",
                }
            )
        result = report(rows)
        self.assertEqual(result["paired_case_rounds"], 1)
        self.assertTrue(result["same_case_rounds"])
        self.assertEqual(result["variants"]["B"]["by_style"]["口语"]["fact_check_rate"], 1)


class InstrumentationTests(unittest.IsolatedAsyncioTestCase):
    """Provider usage includes classifier calls, with the correct stage label."""

    async def test_classifier_observer_counts_provider_usage(self) -> None:
        assistant = Mock()
        assistant.mcp = Mock()
        assistant.tools = {}
        assistant.classifier_model = fake_model(prediction().model_dump_json())
        assistant.reranker = None
        with patch("evaluation.rerank_metrics.observe_reranker"):
            instrument(assistant)
        self.assertIsInstance(assistant.classifier_model, ObservedModel)
        token = ACTIVE.set({"model_calls": []})
        try:
            budget = RequestBudget()
            await (
                BudgetedModel(assistant.classifier_model, budget, "glm_l1", 320)
                .bind(response_format={"type": "json_object"})
                .ainvoke([HumanMessage(content="synthetic")])
            )
            calls = ACTIVE.get()["model_calls"]
            self.assertEqual(calls[0]["stage"], "glm_l1")
            self.assertEqual(calls[0]["usage"]["total_tokens"], 120)
        finally:
            ACTIVE.reset(token)


if __name__ == "__main__":
    unittest.main()
