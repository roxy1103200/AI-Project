"""Run 144 frozen real questions twice against the current workflow."""

import argparse
import asyncio
import hashlib
import importlib
import json
import logging
import os
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evaluation.metrics import summarize
from evaluation.rerank_metrics import augment_summary
from evaluation.run import ACTIVE, AI_ROOT, BACKEND_ROOT, REPO_ROOT, instrument, services, trial
from evaluation.verify_snapshot import verify


def score_associations(case: dict[str, Any], row: dict[str, Any]) -> None:
    """Check record-specific facts without accepting facts from another record."""
    answer = row["answer"].replace("*", "")
    positions = [(item, answer.find(item["anchor"])) for item in case.get("answer_associations", [])]
    missing = []
    for item, start in positions:
        end = min((position for _, position in positions if position > start), default=len(answer))
        section = answer[start:end] if start >= 0 else ""
        if start < 0 or any(not re.search(pattern, section, re.IGNORECASE) for pattern in item["checks"]):
            missing.append(item["anchor"])
    row["score"]["association_failures"] = missing
    if missing:
        for key in ("task_success", "answer_correct", "factual_checks_pass"):
            row["score"][key] = False
    row["strict_primary_intent_correct"] = row.get("detected_intent") == case["expected_intent"]
    row["intent_correct"] = row.get("detected_intent") in case["accepted_intents"]


def statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Include failed attempts and native rerank cost in denominators."""
    result = augment_summary(rows, summarize(rows))
    if rows:
        result["intent_accuracy"] = sum(row["intent_correct"] for row in rows) / len(rows)
        result["strict_primary_intent_accuracy"] = sum(row["strict_primary_intent_correct"] for row in rows) / len(rows)
    return result


def grouped(rows: list[dict[str, Any]], *fields: str) -> dict[str, Any]:
    """Expose phrasing performance within each task group and route."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[" / ".join(str(row.get(field, "unknown")) for field in fields)].append(row)
    return {key: statistics(selected) for key, selected in sorted(groups.items())}


def audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Check observed hard limits and identical repeated business calls."""
    violations, duplicates = [], []
    for row in rows:
        simple = row.get("route") == "simple"
        counts = {
            "steps": (row.get("step_count", 0), 1 if simple else 5),
            "tools": (len(row["tools"]), 1 if simple else 4),
            "models": (len(row["model_calls"]), 2 if simple else 8),
            "reflections": (sum(call["stage"] == "reflection" for call in row["model_calls"]), 1),
            "invalid": (row.get("invalid_call_count", 0), 3),
        }
        excess = {key: value for key, value in counts.items() if value[0] > value[1]}
        if excess:
            violations.append({"case_id": row["case_id"], "repetition": row["repetition"], "excess": excess})
        signatures = Counter(json.dumps({k: v for k, v in call.items() if k != "result"}, sort_keys=True) for call in row["tools"])
        if any(count > 1 for count in signatures.values()):
            duplicates.append({"case_id": row["case_id"], "repetition": row["repetition"]})
    return {"limit_violations": violations, "duplicate_call_tasks": duplicates,
            "all_completed": all(row["completed"] for row in rows),
            "max_total_ms": max((row["total_ms"] for row in rows), default=0)}


def summary(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> dict[str, Any]:
    """Provide checkpoints after every paid task."""
    return {"metadata": metadata, "overall": statistics(rows),
            "by_style": grouped(rows, "phrasing_style"), "by_group": grouped(rows, "group"),
            "by_group_style": grouped(rows, "group", "phrasing_style"), "by_route": grouped(rows, "route"),
            "by_repetition": grouped(rows, "repetition"), "loop_audit": audit(rows)}


def source_hashes() -> dict[str, str]:
    """Fingerprint executable code, knowledge, scoring code, and Java artifact."""
    paths = [*(AI_ROOT / "app").rglob("*.py"), *(AI_ROOT / "knowledge").glob("*.md"),
             *(AI_ROOT / "evaluation").glob("*.py"),
             BACKEND_ROOT / "target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar"]
    return {str(path.relative_to(REPO_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


async def run(manifest: Path, output: Path) -> None:
    """Own isolated services and resume only with unchanged cases and source."""
    load_dotenv(AI_ROOT / ".env")
    os.environ.update(MEMORY_ENABLED="false", AGENT_MAX_TOOL_CALLS="4", AGENT_MAX_INVALID_CALLS="3")
    cases = json.loads(manifest.read_text(encoding="utf-8"))
    if len(cases) != 144 or len({case["id"] for case in cases}) != 144:
        raise ValueError("Exactly 144 unique questions are authorized")
    output.mkdir(parents=True, exist_ok=True)
    from app.model_config import create_model

    model = create_model()
    if model is None:
        raise RuntimeError("A real Qwen model is required")
    frozen = source_hashes()
    metadata_path = output / "metadata.json"
    manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["source_sha256"] != frozen or metadata["manifest_sha256"] != manifest_hash:
            raise RuntimeError("Resume refused: source or questions changed")
    else:
        metadata = {"started_utc": datetime.now(UTC).isoformat(), "model": model.model_name,
                    "questions": 144, "scenarios": 72, "repetitions": 2, "planned_tasks": 288,
                    "concurrency": 1, "source_sha256": frozen, "manifest_sha256": manifest_hash,
                    "snapshot_sha256": hashlib.sha256((manifest.parent / "snapshot.json").read_bytes()).hexdigest(),
                    "price_basis": "retained 2026-10-09 public-price estimate; not an invoice",
                    "scoring": "frozen regex facts and record associations; exact tool trace and arguments; accepted intent and strict primary both reported"}
        shutil.copyfile(manifest, output / "cases.json")
        shutil.copyfile(manifest.parent / "snapshot.json", output / "snapshot.json")
        for relative in frozen:
            if relative.endswith(".jar"):
                continue
            saved = output / "measured-source" / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, saved)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    trace = output / "trials.jsonl"
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
    done = {(row["case_id"], row["repetition"]) for row in rows}
    if len(done) != len(rows):
        raise RuntimeError("Duplicate trial identities")
    async with services(output):
        module = importlib.import_module("app.main")
        instrument(module.assistant)
        from app import react_agent

        original_validate = react_agent.validate_arguments

        def observe_validation(name: str, arguments: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
            entry = {"name": name, "arguments": arguments, "accepted": False}
            ACTIVE.get()["validation"].append(entry)
            try:
                result = original_validate(name, arguments, state)
            except Exception as exc:
                entry["error_code"] = getattr(exc, "code", type(exc).__name__)
                raise
            entry["accepted"] = True
            return result

        react_agent.validate_arguments = observe_validation
        try:
            with trace.open("a", encoding="utf-8") as stream:
                for repetition in (1, 2):
                    ordered = list(cases)
                    random.Random(20261011 + repetition).shuffle(ordered)
                    for case in ordered:
                        if (case["id"], repetition) in done:
                            continue
                        row = await trial(module, case, "current", repetition, model)
                        for field in ("phrasing_style", "source_case_id", "expected_intent"):
                            row[field] = case[field]
                        score_associations(case, row)
                        stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                        stream.flush()
                        rows.append(row)
                        (output / "summary.json").write_text(json.dumps(summary(rows, metadata), ensure_ascii=False, indent=2), encoding="utf-8")
                        print(json.dumps({"done": len(rows), "planned": 288, "case": case["id"], "repeat": repetition,
                                          "success": row["score"]["task_success"], "route": row.get("route"),
                                          "seconds": round(row["total_ms"] / 1000, 2)}, ensure_ascii=True), flush=True)
            stability = await verify(output)
            metadata.update(finished_utc=datetime.now(UTC).isoformat(), source_unchanged=source_hashes() == frozen,
                            data_unchanged=stability["all_unchanged"])
            metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            (output / "summary.json").write_text(json.dumps(summary(rows, metadata), ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            react_agent.validate_arguments = original_validate
            await module.assistant.reranker.aclose()
            await module.assistant.client.aclose()
            await model.root_async_client.close()


def main() -> None:
    """Parse paths without serializing credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run(options.manifest.resolve(), options.output.resolve()))


if __name__ == "__main__":
    main()
