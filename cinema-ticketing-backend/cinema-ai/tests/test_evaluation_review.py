"""Ensure manual adjudication never silently replaces the measured evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.review import reviewed_rows


def check_review_preserves_raw_score_and_reason(tmp_path):
    row = {
        "case_id": "S06",
        "variant": "baseline",
        "repetition": 1,
        "score": {"task_success": False, "tool_correct": True, "factual_checks_pass": False},
    }
    source = json.dumps(row) + "\n"
    (tmp_path / "trials.jsonl").write_text(source, encoding="utf-8")
    review = {
        "corrections": [
            {
                "case_id": "S06",
                "variant": "baseline",
                "repetition": 1,
                "score": {"task_success": True, "factual_checks_pass": True},
                "reason": "A correct numeric-only answer satisfies this quantity question.",
            }
        ]
    }
    (tmp_path / "review.json").write_text(json.dumps(review), encoding="utf-8")
    result = reviewed_rows(tmp_path)[0]
    assert result["score"]["task_success"]
    assert not result["automated_score"]["task_success"]
    assert result["review_reason"]
    assert (tmp_path / "trials.jsonl").read_text(encoding="utf-8") == source


def check_review_rejects_unknown_trial(tmp_path):
    (tmp_path / "trials.jsonl").write_text("", encoding="utf-8")
    review = {
        "corrections": [
            {
                "case_id": "missing",
                "variant": "react",
                "repetition": 1,
                "score": {"task_success": True},
                "reason": "This trial does not exist.",
            }
        ]
    }
    (tmp_path / "review.json").write_text(json.dumps(review), encoding="utf-8")
    reviewed_rows(tmp_path)


class EvaluationReviewTests(unittest.TestCase):
    """Run review checks using the project's existing standard-library test runner."""

    def test_review_preserves_raw_score_and_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            check_review_preserves_raw_score_and_reason(Path(directory))

    def test_review_rejects_unknown_trial(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "not run"):
            check_review_rejects_unknown_trial(Path(directory))
