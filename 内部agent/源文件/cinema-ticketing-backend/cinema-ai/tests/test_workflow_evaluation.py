"""Validate frozen expanded coverage and independent fact association checks."""

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from evaluation.workflow_cases import build
from evaluation.workflow_eval import audit, score_associations


class WorkflowEvaluationTests(unittest.TestCase):
    """Protect evaluation integrity without any paid model calls."""

    def test_corpus_pairing_and_dependency(self):
        prepared = Path(__file__).parents[2] / "target/agent-evaluation/reflection-base-prepared-20261011"
        if not prepared.exists():
            self.skipTest("Frozen development snapshot is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            cases = build(prepared, Path(directory))
            self.assertEqual(len(cases), 144)
            self.assertEqual(set(Counter(case["source_case_id"] for case in cases).values()), {2})
            self.assertEqual(sorted(Counter(case["phrasing_style"] for case in cases).values()), [72, 72])
            for case in cases:
                if case["source_case_id"] == "X18":
                    for plan in case["plans"]:
                        names = [call["name"] for call in plan]
                        self.assertLess(names.index("search_screenings"), names.index("query_seats"))
            loaded = json.loads((Path(directory) / "cases.json").read_text(encoding="utf-8"))
            self.assertEqual(cases, loaded)

    def test_swapped_record_facts_are_rejected(self):
        case = {"expected_intent": "movies", "accepted_intents": ["movies"], "answer_associations": [
            {"anchor": "Film A", "checks": ["Alice", "100"]},
            {"anchor": "Film B", "checks": ["Bob", "90"]},
        ]}
        row = {"answer": "Film A: Bob, 90. Film B: Alice, 100.", "detected_intent": "movies",
               "score": dict.fromkeys(("task_success", "answer_correct", "factual_checks_pass"), True)}
        score_associations(case, row)
        self.assertFalse(row["score"]["answer_correct"])
        self.assertEqual(len(row["score"]["association_failures"]), 2)

    def test_matching_record_facts_pass(self):
        case = {"expected_intent": "movies", "accepted_intents": ["movies"],
                "answer_associations": [{"anchor": "Film A", "checks": ["Alice", "100"]}]}
        row = {"answer": "Film A: Alice, 100.", "detected_intent": "movies", "score": {"answer_correct": True}}
        score_associations(case, row)
        self.assertTrue(row["score"]["answer_correct"])

    def test_audit_detects_simple_route_limit(self):
        row = {"case_id": "test", "repetition": 1, "route": "simple", "step_count": 2,
               "tools": [], "model_calls": [], "completed": True, "total_ms": 100}
        self.assertEqual(len(audit([row])["limit_violations"]), 1)
