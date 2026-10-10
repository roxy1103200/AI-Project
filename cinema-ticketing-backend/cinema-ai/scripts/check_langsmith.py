"""Upload synthetic success/failure traces and verify their cloud representation.

No Qwen, Java, MCP or database request is made. Local/cloud archives store metadata only.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=False)

from app.failures import CinemaQueryError, describe_failure  # noqa: E402
from app.tracing import CHINA_TIMEZONE, TRACE_ARCHIVE_ROOT, AgentTracing, tool_span  # noqa: E402

SENTINEL = "LANGSMITH-DIAGNOSTIC-PRIVATE-ORDER-13800138000"


class DiagnosticState(TypedDict, total=False):
    """Synthetic data used to exercise automatic instrumentation and error handling."""

    question: str
    answer: str
    intent: str
    error_code: str
    fail: bool


async def upload_case(tracing: AgentTracing, fail: bool) -> str:
    """Run four graph steps, one local fake model and one traced tool call."""
    model = FakeListChatModel(responses=[SENTINEL])

    async def agent(_: DiagnosticState) -> dict:
        reply = await model.ainvoke(SENTINEL)
        return {"answer": reply.content}

    def tools(state: DiagnosticState) -> dict:
        try:
            with tool_span("search_movies", {"query": SENTINEL}) as span:
                if state["fail"]:
                    raise CinemaQueryError("business_unavailable", SENTINEL)
                span.end(outputs={"data": [{"title": SENTINEL}]})
            return {}
        except CinemaQueryError as exc:
            code, _ = describe_failure(exc, "react_tool")
            return {"error_code": code}

    graph = StateGraph(DiagnosticState)
    graph.add_node("prepare", lambda state: {"intent": "movies"})
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("respond", lambda state: {})
    for source, destination in (
        (START, "prepare"),
        ("prepare", "agent"),
        ("agent", "tools"),
        ("tools", "respond"),
        ("respond", END),
    ):
        graph.add_edge(source, destination)
    channel = "verify_failure" if fail else "verify_success"
    with tracing.turn(1, "synthetic-langsmith-check", SENTINEL, channel) as turn:
        result = await graph.compile().ainvoke({"question": SENTINEL, "fail": fail})
        turn.observe({"type": "context", **result})
        turn.observe({"type": "error", "code": result["error_code"]} if fail else {"type": "complete"})
        return str(turn.trace_id)


def read_case(tracing: AgentTracing, run_id: str, fail: bool) -> dict:
    """Read stored spans and ensure the synthetic private text was never uploaded."""
    run = tracing.client.read_run(run_id, load_child_runs=True)
    spans = []
    pending = [run]
    while pending:
        span = pending.pop()
        spans.append(span)
        pending.extend(span.child_runs or [])
    names = {span.name for span in spans}
    required = {"prepare", "agent", "tools", "respond", "FakeListChatModel", "tool.search_movies"}
    if not required <= names:
        raise RuntimeError("Cloud trace is missing expected node/model/tool spans")
    if fail and run.error != "business_unavailable":
        raise RuntimeError("Failed answer is not marked with the expected error code")
    if not fail and run.error:
        raise RuntimeError("Successful answer is unexpectedly marked as failed")
    # langsmith 0.3.45 uses Pydantic v1 schemas alongside the app's Pydantic v2.
    encoded = json.dumps([span.dict() for span in spans], default=str)
    if SENTINEL in encoded:
        raise RuntimeError("Private diagnostic text reached LangSmith")
    return {
        "trace_id": run_id,
        "outcome": "failed" if fail else "completed",
        "error_code": run.error,
        "span_count": len(spans),
        "span_names": sorted(names),
        "private_text_uploaded": False,
        "timings_ms": [
            {
                "name": span.name,
                "duration": round((span.end_time - span.start_time).total_seconds() * 1000, 2)
                if span.end_time
                else None,
            }
            for span in spans
        ],
    }


def http_status(exception: Exception) -> int | None:
    """Extract a safe status from SDK errors without printing server bodies or keys."""
    current = exception
    seen = set()
    while current and id(current) not in seen:
        seen.add(id(current))
        response = getattr(current, "response", None)
        if response is not None:
            return response.status_code
        for code in (401, 403, 429):
            if str(code) in str(current):
                return code
        current = current.__cause__ or current.__context__
    return None


def save_report(tracing: AgentTracing, **details: object) -> None:
    """Save both successful and failed verification evidence without secrets."""
    report = {**tracing.status(), "checked_at": datetime.now(UTC).isoformat(), **details}
    day = datetime.now(CHINA_TIMEZONE).strftime("%Y_%m_%d")
    destination = TRACE_ARCHIVE_ROOT / day / "verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


async def main() -> int:
    """Validate upload, readback, native callbacks and sanitized errors end to end."""
    tracing = AgentTracing()
    if tracing.client is None:
        save_report(tracing, verified=False, stage="configuration")
        return 1
    try:
        await asyncio.to_thread(lambda: next(iter(tracing.client.list_projects(limit=1)), None))
    except Exception as exc:
        save_report(
            tracing,
            verified=False,
            stage="authentication",
            exception_type=type(exc).__name__,
            http_status=http_status(exc),
        )
        return 1
    cases = [(await upload_case(tracing, fail), fail) for fail in (False, True)]
    await asyncio.to_thread(wait_for_all_tracers)
    await asyncio.to_thread(tracing.flush)
    verified = []
    for run_id, fail in cases:
        for attempt in range(5):
            try:
                result = await asyncio.to_thread(read_case, tracing, run_id, fail)
                verified.append(result)
                break
            except Exception as exc:
                status = http_status(exc)
                if attempt == 4 or status in (401, 403):
                    save_report(
                        tracing,
                        verified=False,
                        stage="readback",
                        exception_type=type(exc).__name__,
                        http_status=status,
                        trace_ids=[item[0] for item in cases],
                        cases=verified,
                    )
                    return 1
                await asyncio.sleep(2)
    save_report(tracing, verified=True, cases=verified)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
