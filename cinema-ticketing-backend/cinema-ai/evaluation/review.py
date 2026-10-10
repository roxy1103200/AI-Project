"""Apply explicit human adjudications while retaining all original automatic scores."""

import json
from pathlib import Path
from typing import Any

from evaluation.metrics import judge


def reviewed_rows(directory: Path) -> list[dict[str, Any]]:
    """Require a reason and unique exact trial key for every published correction."""
    rows = [json.loads(line) for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    path = directory / "review.json"
    review = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"corrections": []}
    changes = {}
    for correction in review["corrections"]:
        key = (correction["case_id"], correction["variant"], correction["repetition"])
        if key in changes or not correction.get("reason"):
            raise ValueError("Every review correction needs a unique trial key and written reason")
        if set(correction["score"]) - {"task_success", "tool_correct", "factual_checks_pass"}:
            raise ValueError("Unsupported review score field")
        changes[key] = correction
    found = set()
    for row in rows:
        key = (row["case_id"], row["variant"], row["repetition"])
        if key in changes:
            found.add(key)
            row["automated_score"] = dict(row["score"])
            row["score"].update(changes[key]["score"])
            row["review_reason"] = changes[key]["reason"]
            row["score"]["review_reason"] = row["review_reason"]
            row["score"]["original_automated_score"] = row["automated_score"]
    if found != set(changes):
        raise ValueError("Review refers to a trial that was not run")
    cases_path = directory / "cases.json"
    if cases_path.exists():
        cases = {case["id"]: case for case in json.loads(cases_path.read_text(encoding="utf-8"))}
        for row in rows:
            dimensions = judge(cases[row["case_id"]], row)
            for field in ("extra_tool_calls", "has_extra_tool_calls"):
                row["score"][field] = dimensions[field]
            row["score"]["answer_correct"] = (
                row["score"]["factual_checks_pass"] and row["completed"] and not row["errors"]
            )
    return rows
