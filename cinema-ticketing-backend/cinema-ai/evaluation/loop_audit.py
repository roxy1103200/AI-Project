"""Audit finite ReAct execution from recorded proposals and upstream business calls."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def repeated(calls: list[dict[str, Any]], argument_key: str) -> int:
    """Count exact repeated tool/argument pairs within one request, ignoring call IDs."""
    signatures = Counter(
        json.dumps([call["name"], call.get(argument_key, {}), call.get("user_id")], sort_keys=True, ensure_ascii=False)
        for call in calls
    )
    return sum(count - 1 for count in signatures.values())


def audit(directory: Path) -> dict[str, Any]:
    """Keep errors, repeated proposals and executed duplicates separate in the result."""
    rows = [json.loads(line) for line in (directory / "trials.jsonl").read_text(encoding="utf-8").splitlines()]
    meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "definition": "Exact tool name + argument JSON within one request; business signatures include caller identity.",
        "business_call_budget": meta["tool_budget"],
        "invalid_call_budget": meta["invalid_retry_budget"],
        "decision_turn_budget": meta["tool_budget"] + meta["invalid_retry_budget"] + 1,
        "variants": {},
    }
    for variant in ("baseline", "react"):
        chosen = [row for row in rows if row["variant"] == variant]
        if not chosen:
            continue
        decisions = [sum(call["stage"] == "decision" for call in row["model_calls"]) for row in chosen]
        duplicate_rows = [row for row in chosen if repeated(row["tools"], "arguments")]
        proposal_rows = [row for row in chosen if repeated(row["proposals"], "args")]
        result["variants"][variant] = {
            "n": len(chosen),
            "normal_completion": sum(row["completed"] and not row["errors"] for row in chosen),
            "error_tasks": sum(bool(row["errors"]) for row in chosen),
            "timeout_tasks": sum(
                any("timeout" in event.get("code", "").lower() for event in row["errors"]) for row in chosen
            ),
            "duplicate_execution_tasks": len(duplicate_rows),
            "duplicate_executions": sum(repeated(row["tools"], "arguments") for row in chosen),
            "repeated_proposal_tasks": len(proposal_rows),
            "repeated_proposals": sum(repeated(row["proposals"], "args") for row in chosen),
            "max_business_calls": max(len(row["tools"]) for row in chosen),
            "max_invalid_calls": max(row.get("invalid_call_count", 0) for row in chosen),
            "max_decision_turns": max(decisions),
            "max_elapsed_ms": max(row["total_ms"] for row in chosen),
            "business_budget_breaches": sum(len(row["tools"]) > meta["tool_budget"] for row in chosen),
            "invalid_budget_breaches": sum(
                row.get("invalid_call_count", 0) > meta["invalid_retry_budget"] for row in chosen
            ),
            "decision_budget_breaches": sum(count > result["decision_turn_budget"] for count in decisions),
            "repeated_proposal_cases": [
                {"case_id": row["case_id"], "repetition": row["repetition"]} for row in proposal_rows
            ],
        }
    (directory / "loop-audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    """Inspect saved measurements without calling a model or any business service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args()
    print(json.dumps(audit(options.directory), ensure_ascii=True))


if __name__ == "__main__":
    main()
