"""Prevent optimistic scoring and incorrect percentile/cache accounting."""

import unittest

from evaluation.metrics import judge, percentile, priced_usage, summarize


class EvaluationMetricsTests(unittest.TestCase):
    """Check the evaluation oracle using outcomes independent of application code."""

    def setUp(self) -> None:
        self.case = {
            "plans": [[{"name": "query_seats", "arguments": {"screening_id": 12}, "user_id": 2}]],
            "answer_checks": ["可选3"],
        }
        self.row = {
            "tools": [{"name": "query_seats", "arguments": {"screening_id": 12}, "user_id": 2}],
            "validation": [],
            "answer": "可选3",
            "completed": True,
            "errors": [],
            "ttft_ms": 100,
            "total_ms": 200,
            "model_calls": [],
        }

    def test_correct_words_do_not_hide_wrong_identity_id_or_extra_calls(self) -> None:
        self.assertTrue(judge(self.case, self.row)["task_success"])
        for key, value in (("user_id", 9), ("arguments", {"screening_id": 99})):
            row = {**self.row, "tools": [{**self.row["tools"][0], key: value}]}
            self.assertFalse(judge(self.case, row)["task_success"])
        self.assertFalse(judge(self.case, {**self.row, "tools": self.row["tools"] * 2})["task_success"])

    def test_rejected_proposals_and_missing_completion_are_failures(self) -> None:
        for changes in (
            {"validation": [{"accepted": False}]},
            {"completed": False},
            {"errors": [{"code": "timeout"}]},
            {"answer": "可选4"},
        ):
            self.assertFalse(judge(self.case, {**self.row, **changes})["task_success"])

    def test_empty_expected_trace_can_only_accept_no_business_calls(self) -> None:
        case = {"plans": [[]], "answer_checks": ["订单号"]}
        row = {**self.row, "tools": [], "answer": "请提供订单号"}
        self.assertTrue(judge(case, row)["task_success"])
        self.assertFalse(judge(case, {**row, "tools": self.row["tools"]})["task_success"])

    def test_percentile_interpolation_and_missing_ttft_denominators(self) -> None:
        self.assertEqual(percentile([10, 20, 30, 40], 0.5), 25)
        self.assertEqual(percentile([10, 20, 30, 40], 0.95), 38.5)
        self.assertIsNone(percentile([], 0.95))
        rows = [
            {**self.row, "score": {"task_success": True, "tool_correct": True}},
            {**self.row, "ttft_ms": None, "score": {"task_success": False, "tool_correct": False}},
        ]
        summary = summarize(rows)
        self.assertEqual((summary["n"], summary["ttft_n"], summary["task_success_rate"]), (2, 1, 0.5))

    def test_cache_cost_and_unknown_usage_are_not_zero_token_measurements(self) -> None:
        usage = {
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "input_token_details": {"cache_read": 500},
        }
        self.assertAlmostEqual(priced_usage(usage), 0.0002)
        row = {
            **self.row,
            "model_calls": [{"usage": usage}, {"usage": None}],
            "score": {"task_success": True, "tool_correct": True},
        }
        summary = summarize([row])
        self.assertEqual(summary["usage_missing_calls"], 1)
        self.assertEqual(summary["avg_model_calls"], 2)
        self.assertEqual(summary["avg_total_tokens"], 1100)
