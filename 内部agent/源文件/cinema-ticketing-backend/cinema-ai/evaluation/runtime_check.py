"""Inspect termination of the already running Agent using frozen real query cases."""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from evaluation.run import AI_ROOT


async def check(options: argparse.Namespace) -> None:
    """Save the SSE events and report observed completion without restarting services."""
    load_dotenv(AI_ROOT / ".env")
    cases = json.loads(options.manifest.read_text(encoding="utf-8"))
    wanted = set(options.case_ids.split(","))
    selected = [case for case in cases if case["id"] in wanted]
    if wanted != {case["id"] for case in selected}:
        raise ValueError("Unknown case identifier")
    options.output.mkdir(parents=True, exist_ok=True)
    rows = []
    async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(95, connect=5)) as client:
        for case in selected:
            events = []
            started = time.perf_counter()
            error = None
            stream_ended = False
            try:
                async with (
                    asyncio.timeout(95),
                    client.stream(
                        "POST",
                        options.agent_url.rstrip("/") + "/ai/live",
                        headers={"X-Internal-Token": os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")},
                        json={
                            "user_id": case["user_id"],
                            "session_id": f"runtime-check-{time.time_ns()}",
                            "question": case["question"],
                            "history": case.get("history", []),
                        },
                    ) as response,
                ):
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            packet = json.loads(line[5:].strip())
                            events.append({"elapsed_ms": round((time.perf_counter() - started) * 1000), **packet})
                stream_ended = True
            except (httpx.HTTPError, TimeoutError, ValueError) as exc:
                error = type(exc).__name__
            contexts = [event for event in events if event.get("type") == "context"]
            last = contexts[-1] if contexts else {}
            row = {
                "case_id": case["id"],
                "question": case["question"],
                "total_ms": round((time.perf_counter() - started) * 1000),
                "complete": any(event.get("type") == "complete" for event in events),
                "errors": [event for event in events if event.get("type") == "error"],
                "client_error": error,
                "stream_ended": stream_ended,
                "tool_calls": last.get("tool_calls", []),
                "tool_call_count": last.get("tool_call_count"),
                "invalid_call_count": last.get("invalid_call_count"),
                "task_progress": last.get("task_progress", []),
                "answer": "".join(event.get("text", "") for event in events if event.get("type") == "delta"),
                "events": events,
            }
            rows.append(row)
            (options.output / "trials.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        key: row[key]
                        for key in (
                            "case_id",
                            "total_ms",
                            "complete",
                            "client_error",
                            "tool_calls",
                            "invalid_call_count",
                        )
                    }
                ),
                flush=True,
            )
    summary = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "agent_url": options.agent_url,
        "count": len(rows),
        "completed": sum(row["complete"] for row in rows),
        "streams_ended": sum(row["stream_ended"] for row in rows),
        "terminal_events": sum(row["complete"] or bool(row["errors"]) for row in rows),
        "client_timeouts": sum(row["client_error"] == "TimeoutError" for row in rows),
        "max_elapsed_ms": max(row["total_ms"] for row in rows),
        "max_business_calls": max((row["tool_call_count"] or 0) for row in rows),
        "max_invalid_calls": max((row["invalid_call_count"] or 0) for row in rows),
        "limits": "SSE exposes counts and task progress; exact argument duplicates require instrumented benchmark traces.",
    }
    (options.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


def main() -> None:
    """Parse a serial diagnostic invocation against an existing local Agent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-url", default="http://127.0.0.1:8000")
    parser.add_argument("--case-ids", default="S04,S10,S11,S12,M02,M04,M06,C03")
    asyncio.run(check(parser.parse_args()))


if __name__ == "__main__":
    main()
