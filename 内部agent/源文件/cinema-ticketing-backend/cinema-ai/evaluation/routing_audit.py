"""Audit cheap routing against frozen gold plans without querying any provider."""

import argparse
import asyncio
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.intent import understand
from app.react_agent import initial_state
from app.task_progress import build_tasks
from evaluation.metrics import matches


async def audit(cases: list[dict[str, Any]], frozen_date: date) -> dict[str, Any]:
    """Check plan names/argument subsets only; this cannot measure answer accuracy."""
    rows = []
    with (
        patch("app.intent.beijing_today", return_value=frozen_date),
        patch.dict("os.environ", {"INTENT_L1_ENABLED": "false", "AGENT_L0_ENABLED": "true"}),
    ):
        for case in cases:
            prepared = await understand(None, case["question"], case.get("history", []))
            state = {
                **initial_state(case["user_id"], "offline-audit", case["question"], case.get("history", [])),
                **prepared,
            }
            tasks = [] if prepared["clarification"] or prepared["intent"] == "chat" else build_tasks(state)
            calls = [
                {"name": task["name"], "arguments": task["arguments"], "user_id": case["user_id"]} for task in tasks
            ]
            cheap = prepared["understanding_layer"] in ("l0", "preflight")
            correct = any(
                len(calls) == len(plan)
                and all(matches(call, expected) for call, expected in zip(calls, plan, strict=True))
                for plan in case["plans"]
            )
            rows.append(
                {
                    "case_id": case["id"],
                    "style": case.get("phrasing_style", "unknown"),
                    "layer": prepared["understanding_layer"],
                    "reason": prepared["preflight_reason"],
                    "cheap": cheap,
                    "gold_plan_match": correct if cheap else None,
                    "intent_match": prepared["intent"] in case["accepted_intents"] if cheap else None,
                    "predicted_tools": [task["name"] for task in tasks] if cheap else [],
                    "slot_summary": prepared["slot_summary"],
                }
            )
    selected = [row for row in rows if row["cheap"]]
    return {
        "scope": "offline routing and gold plan comparison only; no model, tool, answer or latency evaluation",
        "n": len(rows),
        "cheap_tasks": len(selected),
        "layers": dict(Counter(row["layer"] for row in rows)),
        "cheap_plan_matches": sum(row["gold_plan_match"] for row in selected),
        "cheap_intent_matches": sum(row["intent_match"] for row in selected),
        "by_style": {
            style: {"cheap": len(group), "plan_matches": sum(row["gold_plan_match"] for row in group)}
            for style in sorted({row["style"] for row in rows})
            if (group := [row for row in selected if row["style"] == style])
        },
        "cases": rows,
    }


def main() -> None:
    """Write sanitized routing statistics and optional historical usage estimates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--historical-trials", type=Path)
    options = parser.parse_args()
    report = asyncio.run(audit(json.loads(options.cases.read_text(encoding="utf-8")), options.date))
    if options.historical_trials:
        trials = [
            json.loads(line)
            for line in options.historical_trials.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cheap = {row["case_id"] for row in report["cases"] if row["cheap"]}
        all_calls = [
            call for trial in trials for call in trial.get("model_calls", []) if call.get("stage") == "understanding"
        ]
        avoided = [
            call
            for trial in trials
            if trial["case_id"] in cheap
            for call in trial.get("model_calls", [])
            if call.get("stage") == "understanding"
        ]
        report["historical_projection"] = {
            "scope": "same frozen questions, understanding only; potential avoided historical usage, not a new measured run",
            "historical_understanding_calls": len(all_calls),
            "potential_avoided_calls": len(avoided),
            "potential_remaining_calls": len(all_calls) - len(avoided),
            "potential_avoided_input_tokens": sum((call.get("usage") or {}).get("input_tokens", 0) for call in avoided),
            "potential_avoided_output_tokens": sum(
                (call.get("usage") or {}).get("output_tokens", 0) for call in avoided
            ),
            "usage_missing_calls": sum(call.get("usage") is None for call in avoided),
        }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
