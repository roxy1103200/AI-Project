"""Opt-in LangSmith tracing with a metadata-only upload boundary."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import requests
from langsmith import Client, trace, tracing_context
from langsmith.run_helpers import get_current_run_tree
from langsmith.run_trees import RunTree

LOGGER = logging.getLogger("uvicorn.error")
ROOT = Path(__file__).resolve().parents[1]
TRACE_ARCHIVE_ROOT = Path(__file__).resolve().parents[3] / "langsmith(tracing)"
CHINA_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
TRACE_ARCHIVE_LOCK = threading.Lock()
LOCAL_ENVIRONMENTS = frozenset({"local", "development", "dev", "test", "staging", "preprod"})
ERROR_CODES = frozenset(
    {
        "model_auth_failed",
        "model_access_denied",
        "model_rate_limited",
        "model_request_rejected",
        "model_unavailable",
        "query_timeout",
        "service_unreachable",
        "data_not_found",
        "business_auth_failed",
        "business_unavailable",
        "query_contract_mismatch",
        "agent_no_evidence",
        "invalid_tool_call",
        "agent_error",
        "interrupted",
        "stream_incomplete",
        "execution_failed",
    }
)
INTENTS = frozenset({"movies", "screenings", "seats", "order", "refund", "policy", "recommend", "chat", "fallback"})
TOOL_NAMES = frozenset(
    {
        "search_movies",
        "search_screenings",
        "query_seats",
        "query_order",
        "query_ticket_policy",
        "recommend_movies",
        "ask_user",
    }
)
COUNTERS = frozenset(
    {
        "tool_call_count",
        "invalid_call_count",
        "model_turn_count",
        "failure_count",
        "input_characters",
        "output_characters",
        "question_characters",
        "history_count",
        "message_count",
        "item_count",
        "row_count",
        "field_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
)
SAFE_METADATA = frozenset(
    {
        "service",
        "environment",
        "channel",
        "stage",
        "exception_type",
        "ls_provider",
        "ls_model_name",
        "ls_model_type",
        "langgraph_node",
    }
)
CURRENT_TURN: ContextVar[TraceTurn | None] = ContextVar("cinema_trace_turn", default=None)


class SdkLogFilter(logging.Filter):
    """Remove SDK transport details, which can include credential fragments or payloads."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        category = "sdk"
        if "401" in message or "403" in message or "unauthorized" in message:
            category = "authentication"
        elif "429" in message:
            category = "rate_limit"
        elif "connect" in message or "timeout" in message:
            category = "connection"
        record.msg, record.args = "LangSmith SDK event category=%s", (category,)
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        return True


def _filter_sdk_logs() -> None:
    for name in ("langsmith.client", "langsmith._internal._background_thread"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, SdkLogFilter) for item in logger.filters):
            logger.addFilter(SdkLogFilter())


def load_langsmith_key() -> str:
    """Read a server-only key, accepting one plain token or a named assignment."""
    key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if key:
        return key
    path = Path(os.getenv("LANGSMITH_API_KEY_FILE") or "../../API/langsmith.txt")
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return ""
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assignments = [
        match.group(1).strip().strip("\"'")
        for line in lines
        if (match := re.fullmatch(r"(?:export\s+)?LANGSMITH_API_KEY\s*=\s*(.+)", line, re.IGNORECASE))
    ]
    if len(assignments) == 1:
        return assignments[0]
    if len(lines) == 1:
        candidate = lines[0].strip("\"'")
        if re.fullmatch(r"[A-Za-z0-9_.+/=-]{16,256}", candidate):
            return candidate
    raise ValueError("LANGSMITH_API_KEY_FILE must contain one API key")


def _label(value: Any, default: str = "agent_step") -> str:
    """Keep only bounded operational labels, never arbitrary exception messages."""
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,99}", value) else default


def summarize_payload(payload: Any) -> dict[str, Any]:
    """Retain counts and validated workflow outcomes; omit conversation/business values."""
    if not isinstance(payload, dict):
        return {"item_count": len(payload)} if isinstance(payload, (list, tuple)) else {}
    summary: dict[str, Any] = {"field_count": len(payload)}
    for key in COUNTERS:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**9:
            summary[key] = value
    for key in ("question", "normalized_question", "answer", "text"):
        if isinstance(payload.get(key), str):
            summary["output_characters" if key in ("answer", "text") else "question_characters"] = len(payload[key])
    for key in ("messages", "agent_messages", "history"):
        if isinstance(payload.get(key), list):
            summary["history_count" if key == "history" else "message_count"] = len(payload[key])
    for key in ("data", "result", "observations"):
        if isinstance(payload.get(key), list):
            summary["row_count"] = len(payload[key])
    if isinstance(payload.get("intent"), str) and payload["intent"] in INTENTS:
        summary["intent"] = payload["intent"]
    if isinstance(payload.get("error_code"), str) and payload["error_code"] in ERROR_CODES:
        summary["error_code"] = payload["error_code"]
    if isinstance(payload.get("status"), str) and payload["status"] in {
        "completed",
        "failed",
        "interrupted",
        "running",
    }:
        summary["status"] = payload["status"]
    if isinstance(payload.get("finish_reason"), str) and payload["finish_reason"] in {
        "complete",
        "tool_limit",
        "retry_limit",
        "model_fallback",
    }:
        summary["finish_reason"] = payload["finish_reason"]
    if isinstance(payload.get("tool_calls"), list):
        summary["tool_calls"] = [name for name in payload["tool_calls"] if isinstance(name, str) and name in TOOL_NAMES]
    usage = payload.get("llm_output")
    if isinstance(usage, dict) and isinstance(usage.get("token_usage"), dict):
        summary.update(
            {key: value for key, value in usage["token_usage"].items() if key in COUNTERS and isinstance(value, int)}
        )
    return summary


def _metadata(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    result = {key: _label(value) for key, value in values.items() if key in SAFE_METADATA}
    for key in ("trace_id", "session_ref", "thread_id"):
        value = values.get(key)
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9-]{32,64}", value):
            result[key] = value
    for key in ("http_status", "failure_count", "langgraph_step"):
        if isinstance(values.get(key), int):
            result[key] = values[key]
    if isinstance(values.get("error_code"), str) and values["error_code"] in ERROR_CODES:
        result["error_code"] = values["error_code"]
    return result


def _run_fields(values: dict[str, Any]) -> dict[str, Any]:
    """Sanitize every public SDK write, including errors, events and serialized config."""
    safe = {
        key: value
        for key, value in values.items()
        if key in {"id", "start_time", "end_time", "parent_run_id", "trace_id", "dotted_order"}
    }
    if "name" in values:
        safe["name"] = _label(values["name"])
    for key in ("inputs", "outputs"):
        if values.get(key) is not None:
            safe[key] = summarize_payload(values[key])
    if values.get("error"):
        safe["error"] = (
            values["error"]
            if isinstance(values["error"], str) and values["error"] in ERROR_CODES
            else "execution_failed"
        )
    if "extra" in values:
        extra = values["extra"] if isinstance(values["extra"], dict) else {}
        safe["extra"] = {"metadata": _metadata(extra.get("metadata"))}
    if "events" in values:
        safe["events"] = [
            {"name": "agent_failure", "time": event["time"], "kwargs": _metadata(event.get("kwargs"))}
            for event in (values["events"] or [])
            if isinstance(event, dict) and event.get("name") == "agent_failure" and "time" in event
        ]
    # Prompt tokens, serialized model kwargs, attachments and arbitrary tags may contain secrets.
    return safe


def _archive_run(event: str, values: dict[str, Any], run_type: Any = "") -> None:
    """Append a sanitized span lifecycle event to today's local JSONL trace file."""
    try:
        trace_id = str(UUID(str(values.get("trace_id", ""))))
        run_id = str(UUID(str(values.get("id", ""))))
    except (ValueError, TypeError, AttributeError):
        return
    try:
        parent_run_id = str(UUID(str(values.get("parent_run_id", ""))))
    except (ValueError, TypeError, AttributeError):
        parent_run_id = None
    extra = values.get("extra", {})
    metadata = extra.get("metadata", {}) if isinstance(extra, dict) else {}
    archived = {
        "event": event,
        "recorded_at": datetime.now(CHINA_TIMEZONE).isoformat(),
        "trace_id": trace_id,
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "name": _label(values.get("name")),
        "run_type": _label(run_type, "chain"),
        "start_time": values.get("start_time"),
        "end_time": values.get("end_time"),
        "inputs": summarize_payload(values.get("inputs")),
        "outputs": summarize_payload(values.get("outputs")),
        "error_code": values.get("error")
        if isinstance(values.get("error"), str) and values["error"] in ERROR_CODES
        else None,
        "metadata": _metadata(metadata),
        "events": values.get("events", []),
    }
    day_directory = TRACE_ARCHIVE_ROOT / datetime.now(CHINA_TIMEZONE).strftime("%Y_%m_%d")
    try:
        with TRACE_ARCHIVE_LOCK:
            day_directory.mkdir(parents=True, exist_ok=True)
            with (day_directory / "traces.jsonl").open("a", encoding="utf-8") as archive:
                archive.write(json.dumps(archived, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        LOGGER.warning("Local trace archive unavailable type=%s", type(exc).__name__)


class MetadataOnlyClient(Client):
    """Prevent raw state, model prompts, results and exception bodies from leaving the process."""

    def create_run(self, name: str, inputs: dict[str, Any], run_type: Any, **kwargs: Any) -> None:
        """Sanitize creates before handing them to the SDK's background queue."""
        try:
            project = kwargs.get("project_name") or kwargs.get("session_name")
            fields = _run_fields(kwargs)
            safe_name = _label(name)
            fields["name"] = safe_name
            _archive_run("run_created", fields, run_type)
            fields.pop("name", None)
            super().create_run(
                name=safe_name,
                inputs=summarize_payload(inputs),
                run_type=run_type,
                project_name=project,
                **fields,
            )
        except Exception as exc:
            LOGGER.warning("LangSmith create unavailable type=%s", type(exc).__name__)

    def update_run(self, run_id: Any, **kwargs: Any) -> None:
        """Sanitize updates as well as starts; streamed model errors are also scrubbed."""
        try:
            fields = _run_fields(kwargs)
            fields["id"] = run_id
            _archive_run("run_updated", fields)
            fields.pop("id", None)
            super().update_run(run_id, **fields)
        except Exception as exc:
            LOGGER.warning("LangSmith update unavailable type=%s", type(exc).__name__)

    @staticmethod
    def _insert_runtime_env(runs: Any) -> None:
        """Keep the pinned SDK from appending process environment values after filtering."""
        for run in runs:
            extra = run.get("extra") or {}
            run["extra"] = {"metadata": _metadata(extra.get("metadata")), "runtime": {"sdk": "langsmith-py"}}


@dataclass
class TraceTurn:
    """A request-scoped outcome that survives caught exceptions and streamed error events."""

    trace_id: UUID
    run: RunTree | None = None
    status: str = "running"
    error_code: str = ""
    failure_count: int = 0
    tool_calls: list[str] = field(default_factory=list)
    intent: str = ""

    def observe(self, packet: dict[str, Any]) -> None:
        """Classify protocol events without retaining any answer text or user entities."""
        kind = packet.get("type")
        if kind == "error":
            self.status = "failed"
            code = packet.get("code")
            self.error_code = code if isinstance(code, str) and code in ERROR_CODES else "agent_error"
        elif kind == "complete" and self.status != "failed":
            self.status = "completed"
        elif kind == "context":
            summary = summarize_payload(packet)
            self.intent = summary.get("intent", self.intent)
            self.tool_calls = summary.get("tool_calls", self.tool_calls)

    def finish(self) -> None:
        """Mark missing completion explicitly and patch the root outcome."""
        if self.status == "running":
            self.status, self.error_code = "failed", "stream_incomplete"
        if self.run:
            self.run.end(
                outputs={
                    "status": self.status,
                    "error_code": self.error_code,
                    "intent": self.intent,
                    "failure_count": self.failure_count,
                    "tool_calls": self.tool_calls,
                },
                error=self.error_code or None,
            )
        LOGGER.info(
            "Agent turn trace_id=%s outcome=%s error_code=%s failures=%d",
            self.trace_id,
            self.status,
            self.error_code or "none",
            self.failure_count,
        )


class AgentTracing:
    """Enable tracing only with an explicit switch and a local/preproduction environment."""

    def __init__(self) -> None:
        self.environment = os.getenv("AI_ENVIRONMENT", "production").strip().lower()
        self.project = os.getenv("LANGSMITH_PROJECT", f"cinema-agent-{self.environment}").strip()
        self.client: MetadataOnlyClient | None = None
        requested = os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"
        if not requested:
            return
        if self.environment not in LOCAL_ENVIRONMENTS:
            LOGGER.warning("LangSmith disabled: tracing is restricted to local/preproduction environments")
            return
        _filter_sdk_logs()
        try:
            key = load_langsmith_key()
            if not key:
                LOGGER.warning("LangSmith disabled: server-only API key not configured")
                return
            session = requests.Session()
            workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID", "").strip()
            if workspace_id:
                # SDK 0.3.45 predates this environment setting; use its public session hook.
                session.headers["X-Tenant-Id"] = str(UUID(workspace_id))
            self.client = MetadataOnlyClient(
                api_key=key,
                api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/"),
                timeout_ms=3000,
                auto_batch_tracing=True,
                session=session,
            )
        except Exception as exc:
            LOGGER.warning("LangSmith disabled type=%s", type(exc).__name__)
        if self.client:
            LOGGER.info(
                "LangSmith enabled environment=%s project=%s content=metadata_only", self.environment, self.project
            )

    @contextmanager
    def turn(self, user_id: int, session_id: str, question: str, channel: str) -> Iterator[TraceTurn]:
        """Create one root span for both graph execution and streaming completion."""
        turn = TraceTurn(uuid4())
        token = CURRENT_TURN.set(turn)
        session_ref = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
        try:
            with tracing_context(
                enabled=self.client is not None,
                client=self.client,
                project_name=self.project,
                metadata={
                    "service": "cinema-agent",
                    "environment": self.environment,
                    "channel": channel,
                    "trace_id": str(turn.trace_id),
                    "session_ref": session_ref,
                    "thread_id": session_ref,
                },
            ):
                scope = (
                    trace(
                        f"cinema.agent.{channel}",
                        inputs={"question_characters": len(question)},
                        run_id=turn.trace_id,
                        client=self.client,
                        project_name=self.project,
                        exceptions_to_handle=(BaseException,),
                    )
                    if self.client is not None
                    else nullcontext(None)
                )
                with scope as run:
                    turn.run = run
                    try:
                        yield turn
                    except BaseException as exc:
                        if (
                            isinstance(exc, (GeneratorExit, KeyboardInterrupt))
                            or type(exc).__name__ == "CancelledError"
                        ):
                            turn.status, turn.error_code = "interrupted", "interrupted"
                        else:
                            turn.status = "failed"
                            turn.error_code = "query_timeout" if isinstance(exc, TimeoutError) else "agent_error"
                        raise
                    finally:
                        turn.finish()
        finally:
            CURRENT_TURN.reset(token)

    def status(self) -> dict[str, Any]:
        """Expose nonsecret effective configuration on the private health endpoint."""
        return {
            "enabled": self.client is not None,
            "environment": self.environment,
            "project": self.project,
            "content": "metadata_only",
        }

    def flush(self) -> None:
        """Drain pending writes during graceful service shutdown or a diagnostic run."""
        if self.client:
            try:
                self.client.flush()
            except Exception as exc:
                LOGGER.warning("LangSmith flush unavailable type=%s", type(exc).__name__)


def record_failure(stage: str, exception: Exception, code: str, status: int | None) -> None:
    """Attach a safe failure event even when business code catches the exception."""
    turn = CURRENT_TURN.get()
    if turn is None:
        return
    turn.failure_count += 1
    run = get_current_run_tree()
    if run:
        run.add_event(
            {
                "name": "agent_failure",
                "time": datetime.now(UTC).isoformat(),
                "kwargs": {
                    "stage": stage,
                    "exception_type": type(exception).__name__,
                    "error_code": code,
                    "http_status": status,
                },
            }
        )


def current_trace_id() -> str:
    """Return the correlation ID for safe application logs."""
    turn = CURRENT_TURN.get()
    return str(turn.trace_id) if turn else "none"


@contextmanager
def tool_span(name: str, arguments: dict[str, Any]) -> Iterator[RunTree | None]:
    """Trace MCP/local calls that execute outside native LangChain tool callbacks."""
    turn = CURRENT_TURN.get()
    scope = trace(f"tool.{name}", run_type="tool", inputs=arguments) if turn and turn.run else nullcontext(None)
    with scope as run:
        yield run
