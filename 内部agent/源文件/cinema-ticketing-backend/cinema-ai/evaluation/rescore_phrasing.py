"""Apply transparent scoring corrections to an already completed phrasing run."""

import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from evaluation.metrics import judge, summarize


def corrected_case(case: dict[str, Any]) -> dict[str, Any]:
    """Correct fixture labels that do not depend on another model call."""
    updated = deepcopy(case)
    if updated.get("source_case_id") in ("S06", "S07"):
        updated["numeric_only"] = True
    if updated.get("source_case_id") == "G02":
        updated["expected_intent"] = "unsupported"
    return updated


def add_rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = summarize(rows)
    if not rows:
        return result
    result["intent_correct"] = sum(row.get("intent_correct", False) for row in rows)
    result["intent_accuracy"] = result["intent_correct"] / len(rows)
    result["fact_check_passes"] = sum(row["score"]["factual_checks_pass"] for row in rows)
    result["fact_check_pass_rate"] = result["fact_check_passes"] / len(rows)
    result["fact_accuracy"] = result["answer_correct_rate"]
    result["tool_chain_accuracy"] = result["tool_correct_rate"]
    return result


def summarize_groups(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    names = sorted({str(row.get(key, "unknown")) for row in rows})
    return {
        name: add_rates([row for row in rows if str(row.get(key, "unknown")) == name])
        for name in names
    }


def rescore(directory: Path) -> dict[str, Any]:
    cases = {
        case["id"]: case
        for case in json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    }
    raw_rows = [
        json.loads(line)
        for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        case = corrected_case(cases[raw["case_id"]])
        row = deepcopy(raw)
        row["score"] = judge(case, row)
        row["expected_intent"] = case["expected_intent"]
        row["intent_correct"] = row.get("detected_intent") == case["expected_intent"]
        if row["case_id"] == "Q2_S02":
            # This variant explicitly asks what is still showing; the answer used the full catalog scope.
            row["score"]["factual_checks_pass"] = False
            row["score"]["answer_correct"] = False
            row["score"]["missing_checks"].append("manual: current-showing scope; catalog answer was overbroad")
            row["score"]["task_success"] = False
        row["primary_included"] = row["case_id"] != "Q2_S05"
        row["audit_note"] = None
        if row["case_id"] == "Q2_S05":
            row["audit_note"] = "Excluded: uses 'this movie' without a title or antecedent in conversation history."
        elif row["case_id"] == "Q2_S02":
            row["audit_note"] = "Manual fact correction: current-showing request received the full-catalog result."
        elif row["case_id"] == "F_S07":
            row["audit_note"] = "Numeric-only answer accepted; the prompt explicitly requests an Arabic numeral."
        elif row["case_id"] == "Q1_M06":
            row["audit_note"] = "Markdown-normalized seat fact check recognizes the returned 'bookable seats' count."
        elif row["source_case_id"] == "G02":
            row["audit_note"] = "Expected intent label corrected from chat to unsupported action."
        rows.append(row)

    included = [row for row in rows if row["primary_included"]]
    summary = {
        "method": "Post-run scoring only; no additional model or business-tool calls.",
        "n_evaluated": len(rows),
        "n_primary": len(included),
        "excluded_cases": [
            {
                "case_id": "Q2_S05",
                "reason": "The colloquial query says 'this movie' but includes no movie title or prior conversational antecedent.",
            }
        ],
        "manual_scoring_corrections": [
            "Accept the single numeric seat count for prompts that explicitly request an Arabic numeral.",
            "Normalize Markdown markers and recognize '订购座位' as seat-count context in fact checks.",
            "Mark Q2_S02 factually incorrect: it asks for currently showing movies but the Agent used catalog scope and returned non-current titles.",
            "Label direct purchase/payment requests as unsupported intent rather than chat.",
        ],
        "overall": add_rates(included),
        "by_phrasing_style": summarize_groups(included, "phrasing_style"),
        "by_expected_intent": summarize_groups(included, "expected_intent"),
        "by_task_group": summarize_groups(included, "group"),
        "tool_usage": {},
        "intent_confusion": {},
        "failures": [],
    }
    tool_names = Counter(call["name"] for row in included for call in row["tools"])
    duplicate_executions = 0
    for row in included:
        signatures = [
            (call["name"], json.dumps(call["arguments"], sort_keys=True, ensure_ascii=False))
            for call in row["tools"]
        ]
        duplicate_executions += len(signatures) - len(set(signatures))
    validation = [item for row in included for item in row["validation"]]
    model_calls = [call for row in included for call in row["model_calls"]]
    decisions = [call for call in model_calls if call["stage"] == "decision"]
    summary["tool_usage"] = {
        "executed_business_calls": sum(tool_names.values()),
        "by_tool": dict(tool_names),
        "exact_duplicate_executions": duplicate_executions,
        "rejected_tool_proposals": sum(not item["accepted"] for item in validation),
        "tool_proposals": sum(len(row["proposals"]) for row in included),
        "avg_decision_model_turns_per_case": len(decisions) / len(included),
        "max_executed_business_calls_in_one_case": max(len(row["tools"]) for row in included),
        "all_streams_completed": all(row["completed"] and not row["errors"] for row in included),
    }
    confusion = Counter(
        (row["expected_intent"], row.get("detected_intent") or "not_detected") for row in included
    )
    summary["intent_confusion"] = {
        f"{expected} -> {actual}": count for (expected, actual), count in sorted(confusion.items())
    }
    summary["failures"] = [
        {
            "case_id": row["case_id"],
            "style": row["phrasing_style"],
            "expected_intent": row["expected_intent"],
            "detected_intent": row.get("detected_intent"),
            "intent_correct": row["intent_correct"],
            "tool_correct": row["score"]["tool_correct"],
            "facts_correct": row["score"]["factual_checks_pass"],
            "missing_checks": row["score"]["missing_checks"],
            "executed_tools": [call["name"] for call in row["tools"]],
            "audit_note": row["audit_note"],
        }
        for row in included
        if not row["score"]["task_success"]
    ]
    (directory / "rescored_trials.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows), encoding="utf-8"
    )
    (directory / "adjudicated_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(rescore(options.run_dir.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
