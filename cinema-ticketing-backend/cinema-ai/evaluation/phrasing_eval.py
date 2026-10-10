"""Measure intent, facts, and tool traces on paired formal and colloquial questions."""

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evaluation.metrics import summarize
from evaluation.run import AI_ROOT, ACTIVE, instrument, services, trial


def grouped(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field, "unknown"))].append(row)
    result: dict[str, Any] = {}
    for name, selected in sorted(groups.items()):
        base = summarize(selected)
        base["intent_accuracy"] = sum(row.get("intent_correct", False) for row in selected) / len(selected)
        base["intent_correct"] = sum(row.get("intent_correct", False) for row in selected)
        base["fact_check_pass_rate"] = sum(
            row.get("score", {}).get("factual_checks_pass", False) for row in selected
        ) / len(selected)
        base["fact_accuracy"] = base["answer_correct_rate"]
        result[name] = base
    return result


def make_summary(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    overall = summarize(rows)
    if rows:
        overall["intent_accuracy"] = sum(row.get("intent_correct", False) for row in rows) / len(rows)
        overall["intent_correct"] = sum(row.get("intent_correct", False) for row in rows)
        overall["fact_check_pass_rate"] = sum(
            row.get("score", {}).get("factual_checks_pass", False) for row in rows
        ) / len(rows)
        overall["fact_accuracy"] = overall["answer_correct_rate"]
        overall["tool_chain_accuracy"] = overall["tool_correct_rate"]
    summary: dict[str, Any] = {
        "metadata": metadata,
        "overall": overall,
        "by_phrasing_style": grouped(rows, "phrasing_style"),
        "by_expected_intent": grouped(rows, "expected_intent"),
        "by_task_group": grouped(rows, "group"),
        "intent_confusion": {},
        "failures": [],
    }
    confusion: Counter[tuple[str, str]] = Counter(
        (row.get("expected_intent", "unknown"), row.get("detected_intent") or "not_detected") for row in rows
    )
    summary["intent_confusion"] = {
        f"{expected} -> {detected}": count for (expected, detected), count in sorted(confusion.items())
    }
    for row in rows:
        if not row.get("score", {}).get("task_success"):
            score = row.get("score", {})
            summary["failures"].append(
                {
                    "case_id": row["case_id"],
                    "style": row.get("phrasing_style"),
                    "expected_intent": row.get("expected_intent"),
                    "detected_intent": row.get("detected_intent"),
                    "intent_correct": row.get("intent_correct", False),
                    "tool_correct": score.get("tool_correct"),
                    "factual_checks_pass": score.get("factual_checks_pass"),
                    "completed": row.get("completed") and not row.get("errors"),
                    "missing_checks": score.get("missing_checks", []),
                    "extra_tool_calls": score.get("extra_tool_calls"),
                    "rejected_calls": score.get("rejected_calls"),
                    "tool_names": [call["name"] for call in row.get("tools", [])],
                    "error_codes": [error.get("code") for error in row.get("errors", [])],
                }
            )
    summary["failed_count"] = len(summary["failures"])
    return summary


async def run(manifest: Path, output: Path) -> None:
    load_dotenv(AI_ROOT / ".env")
    os.environ["MEMORY_ENABLED"] = "false"
    os.environ["AGENT_MAX_TOOL_CALLS"] = "4"
    os.environ["AGENT_MAX_INVALID_CALLS"] = "3"
    output.mkdir(parents=True, exist_ok=True)
    cases = json.loads(manifest.read_text(encoding="utf-8"))
    if len(cases) != 72 or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Expected 72 unique paired cases")
    if sum(case["phrasing_style"] == "标准" for case in cases) != 24:
        raise ValueError("Expected 24 standard control cases")
    if sum(case["phrasing_style"] == "口语" for case in cases) != 48:
        raise ValueError("Expected 48 colloquial cases")
    from app.model_config import create_model

    model = create_model()
    if model is None:
        raise RuntimeError("Real Qwen model configuration is required")
    snapshot_path = manifest.parent / "snapshot.json"
    metadata: dict[str, Any] = {
        "started_beijing": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "model": model.model_name,
        "case_count": len(cases),
        "repetitions_per_case": 1,
        "concurrency": 1,
        "memory_enabled": False,
        "tool_budget": 4,
        "invalid_retry_budget": 3,
        "data_mode": "real_java_mysql_redis",
        "phrasing_counts": {style: sum(case["phrasing_style"] == style for case in cases) for style in ("标准", "口语")},
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "snapshot_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "scoring": {
            "intent_accuracy": "initial Agent context intent equals independently assigned expected intent",
            "fact_accuracy": "all case-specific answer checks pass and the SSE completes without errors",
            "tool_chain_accuracy": "exact expected tool trace and argument subsets in order; no rejected proposals",
            "task_success": "intent-independent strict tool, fact, and completion checks all pass",
            "extra_calls": "executed calls beyond the shortest exact gold plan",
            "limitation": "answer correctness uses frozen checks, not human semantic adjudication",
        },
    }
    shutil.copyfile(manifest, output / "cases.json")
    shutil.copyfile(snapshot_path, output / "snapshot.json")
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    trace_path = output / "trials.jsonl"
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.exists() else []
    done = {row["case_id"] for row in rows}
    module = importlib.import_module("app.main")
    instrument(module.assistant)
    reranker = getattr(module.assistant, "reranker", None)
    settings = getattr(reranker, "settings", None)
    if settings is not None:
        metadata["reranker"] = {
            "enabled": getattr(settings, "enabled", None),
            "top_k": getattr(settings, "top_k", None),
            "top_n": getattr(settings, "top_n", None),
        }
    from app import react_agent

    original_validate = react_agent.validate_arguments

    def observe_validation(name: str, arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        observed = {"name": name, "arguments": arguments, "accepted": False}
        ACTIVE.get()["validation"].append(observed)
        try:
            result = original_validate(name, arguments, state)
        except Exception as exc:
            observed["error_code"] = getattr(exc, "code", type(exc).__name__)
            observed["reason"] = str(exc)
            raise
        observed["accepted"] = True
        return result

    react_agent.validate_arguments = observe_validation
    try:
        async with services(output):
            with trace_path.open("a", encoding="utf-8") as stream:
                for case in cases:
                    if case["id"] in done:
                        continue
                    row = await trial(module, case, "current", 1, model)
                    row["phrasing_style"] = case["phrasing_style"]
                    row["source_case_id"] = case["source_case_id"]
                    row["expected_intent"] = case["expected_intent"]
                    row["detected_intent"] = row.get("detected_intent")
                    row["intent_correct"] = row["detected_intent"] == case["expected_intent"]
                    stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
                    rows.append(row)
                    summary = make_summary(rows, metadata)
                    (output / "summary.json").write_text(
                        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(
                        json.dumps(
                            {
                                "done": len(rows),
                                "planned": len(cases),
                                "case": case["id"],
                                "style": case["phrasing_style"],
                                "intent_ok": row["intent_correct"],
                                "tools_ok": row["score"]["tool_correct"],
                                "facts_ok": row["score"]["factual_checks_pass"],
                                "success": row["score"]["task_success"],
                                "tool_names": [call["name"] for call in row["tools"]],
                                "seconds": round(row["total_ms"] / 1000, 2),
                            },
                            ensure_ascii=True,
                        ),
                        flush=True,
                    )
    finally:
        react_agent.validate_arguments = original_validate
        if hasattr(module.assistant, "reranker"):
            await module.assistant.reranker.aclose()
        await module.assistant.client.aclose()
        await model.root_async_client.close()
    metadata["finished_beijing"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = make_summary(rows, metadata)
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"finished": len(rows), "output": str(output)}, ensure_ascii=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    asyncio.run(run(options.manifest.resolve(), options.output.resolve()))


if __name__ == "__main__":
    main()
