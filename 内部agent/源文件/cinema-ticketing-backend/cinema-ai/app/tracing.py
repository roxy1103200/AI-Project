"""Opt-in LangSmith tracing with a metadata-only upload boundary."""

# 导入当前步骤使用的模块或类型。
# isort: off
from __future__ import annotations

# 导入当前步骤使用的模块或类型。
import hashlib
# 导入当前步骤使用的模块或类型。
import json
# 导入当前步骤使用的模块或类型。
import logging
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
import re
# SQLite 仅保存本地会话与目录的对应关系，支持服务重启及多个进程同时归档。
import sqlite3
# 导入当前步骤使用的模块或类型。
import threading
# 导入当前步骤使用的模块或类型。
from collections.abc import Iterator
# 导入当前步骤使用的模块或类型。
from contextlib import contextmanager, nullcontext
# 导入当前步骤使用的模块或类型。
from contextvars import ContextVar
# 导入当前步骤使用的模块或类型。
from dataclasses import dataclass, field
# 导入当前步骤使用的模块或类型。
from datetime import UTC, datetime, timedelta, timezone
# 导入当前步骤使用的模块或类型。
from pathlib import Path
# 导入当前步骤使用的模块或类型。
from typing import Any
# 导入当前步骤使用的模块或类型。
from uuid import UUID, uuid4

# 导入当前步骤使用的模块或类型。
import requests
# 导入当前步骤使用的模块或类型。
from langsmith import Client, trace, tracing_context
# 导入当前步骤使用的模块或类型。
from langsmith.run_helpers import get_current_run_tree
# 导入当前步骤使用的模块或类型。
from langsmith.run_trees import RunTree
# isort: on

# 为 `LOGGER` 保存当前步骤所需的值。
LOGGER = logging.getLogger("uvicorn.error")
# 为 `ROOT` 保存当前步骤所需的值。
ROOT = Path(__file__).resolve().parents[1]
# 为 `TRACE_ARCHIVE_ROOT` 保存当前步骤所需的值。
TRACE_ARCHIVE_ROOT = Path(__file__).resolve().parents[3] / "langsmith(tracing)"
# 为 `CHINA_TIMEZONE` 保存当前步骤所需的值。
CHINA_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
# 为 `TRACE_ARCHIVE_LOCK` 保存当前步骤所需的值。
TRACE_ARCHIVE_LOCK = threading.Lock()
# 为 `LOCAL_ENVIRONMENTS` 保存当前步骤所需的值。
LOCAL_ENVIRONMENTS = frozenset({"local", "development", "dev", "test", "staging", "preprod"})
# 为 `ERROR_CODES` 保存当前步骤所需的值。
ERROR_CODES = frozenset(
    # 继续构造当前业务表达式或数据结构。
    {
        # 补充当前表达式的 `"model_auth_failed"` 参数或元素。
        "model_auth_failed",
        # 补充当前表达式的 `"model_access_denied"` 参数或元素。
        "model_access_denied",
        # 补充当前表达式的 `"model_rate_limited"` 参数或元素。
        "model_rate_limited",
        # 补充当前表达式的 `"model_request_rejected"` 参数或元素。
        "model_request_rejected",
        # 补充当前表达式的 `"model_unavailable"` 参数或元素。
        "model_unavailable",
        # 补充当前表达式的 `"query_timeout"` 参数或元素。
        "query_timeout",
        # 补充当前表达式的 `"service_unreachable"` 参数或元素。
        "service_unreachable",
        # 补充当前表达式的 `"data_not_found"` 参数或元素。
        "data_not_found",
        # 补充当前表达式的 `"business_auth_failed"` 参数或元素。
        "business_auth_failed",
        # 补充当前表达式的 `"business_unavailable"` 参数或元素。
        "business_unavailable",
        "screening_unavailable",
        # 补充当前表达式的 `"query_contract_mismatch"` 参数或元素。
        "query_contract_mismatch",
        # 补充当前表达式的 `"agent_no_evidence"` 参数或元素。
        "agent_no_evidence",
        # 补充当前表达式的 `"invalid_tool_call"` 参数或元素。
        "invalid_tool_call",
        # 补充当前表达式的 `"agent_error"` 参数或元素。
        "agent_error",
        # 补充当前表达式的 `"interrupted"` 参数或元素。
        "interrupted",
        # 补充当前表达式的 `"stream_incomplete"` 参数或元素。
        "stream_incomplete",
        # 补充当前表达式的 `"execution_failed"` 参数或元素。
        "execution_failed",
    }
)
# 为 `INTENTS` 保存当前步骤所需的值。
INTENTS = frozenset({"movies", "screenings", "seats", "order", "refund", "policy", "recommend", "chat", "fallback", "unsupported"})
# 为 `TOOL_NAMES` 保存当前步骤所需的值。
TOOL_NAMES = frozenset(
    # 继续构造当前业务表达式或数据结构。
    {
        # 补充当前表达式的 `"search_movies"` 参数或元素。
        "search_movies",
        # 补充当前表达式的 `"search_screenings"` 参数或元素。
        "search_screenings",
        # 补充当前表达式的 `"query_seats"` 参数或元素。
        "query_seats",
        # 补充当前表达式的 `"query_order"` 参数或元素。
        "query_order",
        # 补充当前表达式的 `"query_ticket_policy"` 参数或元素。
        "query_ticket_policy",
        # 补充当前表达式的 `"recommend_movies"` 参数或元素。
        "recommend_movies",
        # 补充当前表达式的 `"ask_user"` 参数或元素。
        "ask_user",
    }
)
# 为 `COUNTERS` 保存当前步骤所需的值。
COUNTERS = frozenset(
    # 继续构造当前业务表达式或数据结构。
    {
        # 补充当前表达式的 `"tool_call_count"` 参数或元素。
        "tool_call_count",
        # 补充当前表达式的 `"invalid_call_count"` 参数或元素。
        "invalid_call_count",
        # 补充当前表达式的 `"model_turn_count"` 参数或元素。
        "model_turn_count",
        "model_call_count",
        "reflection_call_count",
        "step_count",
        "l1_duration_ms",
        "input_tokens",
        "output_tokens",
        "usage_missing_calls",
        # 补充当前表达式的 `"failure_count"` 参数或元素。
        "failure_count",
        # 补充当前表达式的 `"input_characters"` 参数或元素。
        "input_characters",
        # 补充当前表达式的 `"output_characters"` 参数或元素。
        "output_characters",
        # 补充当前表达式的 `"question_characters"` 参数或元素。
        "question_characters",
        # 补充当前表达式的 `"history_count"` 参数或元素。
        "history_count",
        # 补充当前表达式的 `"message_count"` 参数或元素。
        "message_count",
        # 补充当前表达式的 `"item_count"` 参数或元素。
        "item_count",
        # 补充当前表达式的 `"row_count"` 参数或元素。
        "row_count",
        # 补充当前表达式的 `"field_count"` 参数或元素。
        "field_count",
        # 补充当前表达式的 `"prompt_tokens"` 参数或元素。
        "prompt_tokens",
        # 补充当前表达式的 `"completion_tokens"` 参数或元素。
        "completion_tokens",
        # 补充当前表达式的 `"total_tokens"` 参数或元素。
        "total_tokens",
    }
)
# 为 `SAFE_METADATA` 保存当前步骤所需的值。
SAFE_METADATA = frozenset(
    # 继续构造当前业务表达式或数据结构。
    {
        # 补充当前表达式的 `"service"` 参数或元素。
        "service",
        # 补充当前表达式的 `"environment"` 参数或元素。
        "environment",
        # 补充当前表达式的 `"channel"` 参数或元素。
        "channel",
        # 补充当前表达式的 `"stage"` 参数或元素。
        "stage",
        "agent_stage",
        # 补充当前表达式的 `"exception_type"` 参数或元素。
        "exception_type",
        # 补充当前表达式的 `"ls_provider"` 参数或元素。
        "ls_provider",
        # 补充当前表达式的 `"ls_model_name"` 参数或元素。
        "ls_model_name",
        # 补充当前表达式的 `"ls_model_type"` 参数或元素。
        "ls_model_type",
        # 补充当前表达式的 `"langgraph_node"` 参数或元素。
        "langgraph_node",
    }
)
# 设置当前结构中的 `CURRENT_TURN` 字段。
CURRENT_TURN: ContextVar[TraceTurn | None] = ContextVar("cinema_trace_turn", default=None)


# 声明当前处理单元及其入口。
class SdkLogFilter(logging.Filter):
    """Remove SDK transport details, which can include credential fragments or payloads."""

    # 声明当前处理单元及其入口。
    def filter(self, record: logging.LogRecord) -> bool:
        # 为 `message` 保存当前步骤所需的值。
        message = record.getMessage().lower()
        # 为 `category` 保存当前步骤所需的值。
        category = "sdk"
        # 检查 `if "401" in message or "403" in message or "unauthorized" in message`，据此选择当前处理分支。
        if "401" in message or "403" in message or "unauthorized" in message:
            # 为 `category` 保存当前步骤所需的值。
            category = "authentication"
        # 检查 `elif "429" in message`，据此选择当前处理分支。
        elif "429" in message:
            # 为 `category` 保存当前步骤所需的值。
            category = "rate_limit"
        # 检查 `elif "connect" in message or "timeout" in message`，据此选择当前处理分支。
        elif "connect" in message or "timeout" in message:
            # 为 `category` 保存当前步骤所需的值。
            category = "connection"
        record.msg, record.args = "LangSmith SDK event category=%s", (category,)
        # 继续构造当前业务表达式或数据结构。
        record.exc_info, record.exc_text, record.stack_info = None, None, None
        # 将当前计算结果返回给调用方。
        return True


# 声明当前处理单元及其入口。
def _filter_sdk_logs() -> None:
    # 进入对应的循环、异常处理或资源管理分支。
    for name in ("langsmith.client", "langsmith._internal._background_thread"):
        # 为 `logger` 保存当前步骤所需的值。
        logger = logging.getLogger(name)
        # 检查 `if not any(isinstance(item, SdkLogFilter) for item in logger.filters)`，据此选择当前处理分支。
        if not any(isinstance(item, SdkLogFilter) for item in logger.filters):
            # 执行当前异步调用或运行状态记录。
            logger.addFilter(SdkLogFilter())


# 声明当前处理单元及其入口。
def load_langsmith_key() -> str:
    """Read a server-only key, accepting one plain token or a named assignment."""
    # 为 `key` 保存当前步骤所需的值。
    key = os.getenv("LANGSMITH_API_KEY", "").strip()
    # 检查 `if key`，据此选择当前处理分支。
    if key:
        # 将当前计算结果返回给调用方。
        return key
    # 为 `path` 保存当前步骤所需的值。
    path = Path(os.getenv("LANGSMITH_API_KEY_FILE") or "../../API/langsmith.txt")
    # 检查 `if not path.is_absolute()`，据此选择当前处理分支。
    if not path.is_absolute():
        # 为 `path` 保存当前步骤所需的值。
        path = ROOT / path
    # 检查 `if not path.is_file()`，据此选择当前处理分支。
    if not path.is_file():
        # 将当前计算结果返回给调用方。
        return ""
    # 为 `lines` 保存当前步骤所需的值。
    lines = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    # 为 `assignments` 保存当前步骤所需的值。
    assignments = [
        match.group(1).strip().strip("\"'")
        # 进入对应的循环、异常处理或资源管理分支。
        for line in lines
        # 检查 `if (match `，据此选择当前处理分支。
        if (match := re.fullmatch(r"(?:export\s+)?LANGSMITH_API_KEY\s*=\s*(.+)", line, re.IGNORECASE))
    ]
    # 检查 `if len(assignments) == 1`，据此选择当前处理分支。
    if len(assignments) == 1:
        # 将当前计算结果返回给调用方。
        return assignments[0]
    # 检查 `if len(lines) == 1`，据此选择当前处理分支。
    if len(lines) == 1:
        # 为 `candidate` 保存当前步骤所需的值。
        candidate = lines[0].strip("\"'")
        # 检查 `if re.fullmatch(r"[A-Za-z0-9_.+/=-]{16,256}", candidate)`，据此选择当前处理分支。
        if re.fullmatch(r"[A-Za-z0-9_.+/=-]{16,256}", candidate):
            # 将当前计算结果返回给调用方。
            return candidate
    # 抛出当前异常，交由上层错误处理流程处理。
    raise ValueError("LANGSMITH_API_KEY_FILE must contain one API key")


# 声明当前处理单元及其入口。
def _label(value: Any, default: str = "agent_step") -> str:
    """Keep only bounded operational labels, never arbitrary exception messages."""
    # 将当前计算结果返回给调用方。
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,99}", value) else default


# 声明当前处理单元及其入口。
def summarize_payload(payload: Any) -> dict[str, Any]:
    """Retain counts and validated workflow outcomes; omit conversation/business values."""
    # 检查 `if not isinstance(payload, dict)`，据此选择当前处理分支。
    if not isinstance(payload, dict):
        # 将当前计算结果返回给调用方。
        return {"item_count": len(payload)} if isinstance(payload, (list, tuple)) else {}
    # 设置当前结构中的 `summary` 字段。
    summary: dict[str, Any] = {"field_count": len(payload)}
    # 进入对应的循环、异常处理或资源管理分支。
    for key in COUNTERS:
        # 为 `value` 保存当前步骤所需的值。
        value = payload.get(key)
        # 检查 `if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**9`，据此选择当前处理分支。
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**9:
            # 继续构造当前业务表达式或数据结构。
            summary[key] = value
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("question", "normalized_question", "answer", "text"):
        # 检查 `if isinstance(payload.get(key), str)`，据此选择当前处理分支。
        if isinstance(payload.get(key), str):
            summary["output_characters" if key in ("answer", "text") else "question_characters"] = len(payload[key])
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("messages", "agent_messages", "history"):
        # 检查 `if isinstance(payload.get(key), list)`，据此选择当前处理分支。
        if isinstance(payload.get(key), list):
            summary["history_count" if key == "history" else "message_count"] = len(payload[key])
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("data", "result", "observations"):
        # 检查 `if isinstance(payload.get(key), list)`，据此选择当前处理分支。
        if isinstance(payload.get(key), list):
            summary["row_count"] = len(payload[key])
    # 检查 `if isinstance(payload.get("intent"), str) and payload["intent"] in INTENTS`，据此选择当前处理分支。
    if isinstance(payload.get("intent"), str) and payload["intent"] in INTENTS:
        summary["intent"] = payload["intent"]
    # 检查 `if isinstance(payload.get("error_code"), str) and payload["error_code"] in ERROR_CODES`，据此选择当前处理分支。
    if isinstance(payload.get("error_code"), str) and payload["error_code"] in ERROR_CODES:
        summary["error_code"] = payload["error_code"]
    # 检查 `if isinstance(payload.get("status"), str) and payload["status"] in {`，据此选择当前处理分支。
    if isinstance(payload.get("status"), str) and payload["status"] in {
        # 补充当前表达式的 `"completed"` 参数或元素。
        "completed",
        # 补充当前表达式的 `"failed"` 参数或元素。
        "failed",
        # 补充当前表达式的 `"interrupted"` 参数或元素。
        "interrupted",
        # 补充当前表达式的 `"running"` 参数或元素。
        "running",
    # 继续构造当前业务表达式或数据结构。
    }:
        summary["status"] = payload["status"]
    # 检查 `if isinstance(payload.get("finish_reason"), str) and payload["finish_reason"] in {`，据此选择当前处理分支。
    if isinstance(payload.get("finish_reason"), str) and payload["finish_reason"] in {
        # 补充当前表达式的 `"complete"` 参数或元素。
        "complete",
        # 补充当前表达式的 `"tool_limit"` 参数或元素。
        "tool_limit",
        # 补充当前表达式的 `"retry_limit"` 参数或元素。
        "retry_limit",
        # 补充当前表达式的 `"model_fallback"` 参数或元素。
        "model_fallback",
    # 继续构造当前业务表达式或数据结构。
    }:
        summary["finish_reason"] = payload["finish_reason"]
    for key in ("finish_reason", "stop_reason"):
        value = payload.get(key)
        if isinstance(value, str) and value in {
            "complete", "tool_limit", "retry_limit", "model_fallback", "simple_verified",
            "done_verified", "done_code_checked", "max_steps", "model_budget", "token_budget",
            "timeout", "duplicate_call", "stalled", "verifier_incomplete", "reflection_fallback",
            "direct", "needs_user", "no_evidence", "simple_failed", "query_contract_mismatch",
            "business_auth_failed",
        }:
            summary[key] = value
    for key, allowed in (
        ("route", {"simple", "react", "direct"}),
        ("reflection_status", {
            "not_run", "no_evidence", "unavailable", "incomplete", "needs_work", "rejected", "passed", "failed",
            "rules_passed", "rules_empty", "rules_incomplete",
        }),
    ):
        if isinstance(payload.get(key), str) and payload[key] in allowed:
            summary[key] = payload[key]
    if type(payload.get("circuit_open")) is bool:
        summary["circuit_open"] = payload["circuit_open"]
    if isinstance(payload.get("understanding_layer"), str) and payload["understanding_layer"] in {"l0", "l1", "preflight", "llm", "fallback"}:
        summary["understanding_layer"] = payload["understanding_layer"]
    if isinstance(payload.get("preflight_reason"), str) and payload["preflight_reason"] in {
        "invalid_date", "greeting", "unsupported_transaction", "policy_source_unavailable",
        "missing_order_no", "missing_screening_id", "missing_date", "explicit_order",
        "explicit_screening", "explicit_movie_fields", "ticket_policy", "explicit_screening_date",
        "validated_local_classifier", "glm_high_confidence", "none",
    }:
        summary["preflight_reason"] = payload["preflight_reason"]
    if type(payload.get("l1_attempted")) is bool:
        summary["l1_attempted"] = payload["l1_attempted"]
    if isinstance(payload.get("l1_status"), str) and payload["l1_status"] in {"not_attempted", "accepted", "rejected", "unavailable", "budget_open", "cooldown", "busy", "rate_limited", "timeout"}:
        summary["l1_status"] = payload["l1_status"]
    version = payload.get("runtime_version")
    if isinstance(version, dict):
        safe_version = {}
        for key, allowed in (("experiment_id", {"glm-l1-v1"}), ("experiment_variant", {"A", "B"}), ("prompt_version", {"cinema-p1"}), ("rules_version", {"cost-r1"})):
            if isinstance(version.get(key), str) and version[key] in allowed:
                safe_version[key] = version[key]
        for key in ("prompt_hash", "rules_hash", "configuration_hash"):
            if isinstance(version.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", version[key]):
                safe_version[key] = version[key]
        if type(version.get("l1_enabled")) is bool:
            safe_version["l1_enabled"] = version["l1_enabled"]
        summary["runtime_version"] = safe_version
    slots = payload.get("slot_summary")
    if isinstance(slots, dict):
        safe = {key: slots[key] for key in ("order_no", "screening_id", "movie_query", "cinema_query") if type(slots.get(key)) is bool}
        if slots.get("screening_date") is None or type(slots.get("screening_date")) is bool:
            safe["screening_date"] = slots.get("screening_date")
        allowed_slots = {"order_no", "screening_date", "screening_id", "valid_date", "policy_source"}
        values = slots.get("missing_slots")
        if isinstance(values, list):
            safe["missing_slots"] = sorted({value for value in values if isinstance(value, str) and value in allowed_slots})
        if isinstance(slots.get("policy_kind"), str) and slots["policy_kind"] in {"none", "ticket_policy", "general_policy", "mixed"}:
            safe["policy_kind"] = slots["policy_kind"]
        summary["slot_summary"] = safe
    if isinstance(payload.get("token_usage"), dict):
        accounting = payload["token_usage"].get("accounting")
        if isinstance(accounting, str) and accounting in {"provider", "conservative_reservation"}:
            summary["token_accounting"] = accounting
        summary.update({
            key: value for key, value in payload["token_usage"].items()
            if key in COUNTERS and type(value) is int and 0 <= value <= 10**9
        })
    # 检查 `if isinstance(payload.get("tool_calls"), list)`，据此选择当前处理分支。
    if isinstance(payload.get("tool_calls"), list):
        summary["tool_calls"] = [name for name in payload["tool_calls"] if isinstance(name, str) and name in TOOL_NAMES]
    # 为 `usage` 保存当前步骤所需的值。
    usage = payload.get("llm_output")
    # 检查 `if isinstance(usage, dict) and isinstance(usage.get("token_usage"), dict)`，据此选择当前处理分支。
    if isinstance(usage, dict) and isinstance(usage.get("token_usage"), dict):
        # 继续构造当前业务表达式或数据结构。
        summary.update(
            {key: value for key, value in usage["token_usage"].items() if key in COUNTERS and isinstance(value, int)}
        )
    # 将当前计算结果返回给调用方。
    return summary


# 声明当前处理单元及其入口。
def _metadata(values: Any) -> dict[str, Any]:
    # 检查 `if not isinstance(values, dict)`，据此选择当前处理分支。
    if not isinstance(values, dict):
        # 将当前计算结果返回给调用方。
        return {}
    # 为 `result` 保存当前步骤所需的值。
    result = {key: _label(value) for key, value in values.items() if key in SAFE_METADATA}
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("trace_id", "session_ref", "thread_id"):
        # 为 `value` 保存当前步骤所需的值。
        value = values.get(key)
        # 检查 `if isinstance(value, str) and re.fullmatch(r"[a-f0-9-]{32,64}", value)`，据此选择当前处理分支。
        if isinstance(value, str) and re.fullmatch(r"[a-f0-9-]{32,64}", value):
            # 继续构造当前业务表达式或数据结构。
            result[key] = value
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("http_status", "failure_count", "langgraph_step"):
        # 检查 `if isinstance(values.get(key), int)`，据此选择当前处理分支。
        if isinstance(values.get(key), int):
            # 继续构造当前业务表达式或数据结构。
            result[key] = values[key]
    # 检查 `if isinstance(values.get("error_code"), str) and values["error_code"] in ERROR_CODES`，据此选择当前处理分支。
    if isinstance(values.get("error_code"), str) and values["error_code"] in ERROR_CODES:
        result["error_code"] = values["error_code"]
    # 将当前计算结果返回给调用方。
    return result


# 声明当前处理单元及其入口。
def _run_fields(values: dict[str, Any]) -> dict[str, Any]:
    """Sanitize every public SDK write, including errors, events and serialized config."""
    # 为 `safe` 保存当前步骤所需的值。
    safe = {
        # 设置当前结构中的 `key` 字段。
        key: value
        # 进入对应的循环、异常处理或资源管理分支。
        for key, value in values.items()
        # 检查 `if key in {"id", "start_time", "end_time", "parent_run_id", "trace_id", "dotted_order"}`，据此选择当前处理分支。
        if key in {"id", "start_time", "end_time", "parent_run_id", "trace_id", "dotted_order"}
    }
    # 检查 `if "name" in values`，据此选择当前处理分支。
    if "name" in values:
        safe["name"] = _label(values["name"])
    # 进入对应的循环、异常处理或资源管理分支。
    for key in ("inputs", "outputs"):
        # 检查 `if values.get(key) is not None`，据此选择当前处理分支。
        if values.get(key) is not None:
            # 继续构造当前业务表达式或数据结构。
            safe[key] = summarize_payload(values[key])
    # 检查 `if values.get("error")`，据此选择当前处理分支。
    if values.get("error"):
        safe["error"] = (
            values["error"]
            # 检查 `if isinstance(values["error"], str) and values["error"] in ERROR_CODES`，据此选择当前处理分支。
            if isinstance(values["error"], str) and values["error"] in ERROR_CODES
            else "execution_failed"
        )
    # 检查 `if "extra" in values`，据此选择当前处理分支。
    if "extra" in values:
        # 为 `extra` 保存当前步骤所需的值。
        extra = values["extra"] if isinstance(values["extra"], dict) else {}
        safe["extra"] = {"metadata": _metadata(extra.get("metadata"))}
    # 检查 `if "events" in values`，据此选择当前处理分支。
    if "events" in values:
        safe["events"] = [
            {"name": "agent_failure", "time": event["time"], "kwargs": _metadata(event.get("kwargs"))}
            # 进入对应的循环、异常处理或资源管理分支。
            for event in (values["events"] or [])
            # 检查 `if isinstance(event, dict) and event.get("name") == "agent_failure" and "time" in event`，据此选择当前处理分支。
            if isinstance(event, dict) and event.get("name") == "agent_failure" and "time" in event
        ]
    # Prompt tokens, serialized model kwargs, attachments and arbitrary tags may contain secrets.
    # 将当前计算结果返回给调用方。
    return safe


# 声明当前处理单元及其入口。
# 在持有进程内锁和 SQLite 写锁期间，统一管理会话索引与日志追加。
@contextmanager
def _archive_index() -> Iterator[sqlite3.Connection]:
    """Serialize local archive writes across threads and Agent processes."""
    # 只在实际启用追踪时建立归档根目录。
    TRACE_ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    # 同一进程的线程先排队，避免重复争抢数据库写锁。
    with TRACE_ARCHIVE_LOCK:
        # 写锁等待最多四分之一秒，归档故障不应长时间阻塞问答。
        connection = sqlite3.connect(TRACE_ARCHIVE_ROOT / ".archive-index.sqlite3", timeout=0.25)
        # 无论归档成功还是失败都关闭连接，释放文件与数据库锁。
        try:
            # 提前取得写锁，让多个进程的目录注册和文件追加也按顺序执行。
            connection.execute("BEGIN IMMEDIATE")
            # 会话散列唯一，目录记录第一次追踪时间，后续轮次沿用该目录。
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(session_ref TEXT PRIMARY KEY, directory TEXT NOT NULL UNIQUE, started_at TEXT NOT NULL)"
            )
            # 每轮追踪保存根 UUID，延迟到达的节点事件据此找到所属会话。
            connection.execute(
                "CREATE TABLE IF NOT EXISTS traces (trace_id TEXT PRIMARY KEY, session_ref TEXT NOT NULL)"
            )
            # 将持有写锁的连接交给目录注册或日志追加逻辑。
            yield connection
            # 完整完成本次操作后才提交索引。
            connection.commit()
        # 连接关闭会自动回滚尚未提交的索引变更。
        finally:
            # 即使磁盘或序列化操作失败，也释放数据库锁。
            connection.close()


# 在根 span 创建之前注册本轮所属的用户会话，避免异步回调丢失归属。
def _register_archive_session(user_id: int, session_ref: str, trace_id: UUID) -> None:
    """Persist a session's first trace directory and register this turn's root UUID."""
    # 使用北京时间记录会话首次在内部 Agent 产生追踪的时刻。
    started = datetime.now(CHINA_TIMEZONE)
    # 下划线替代 Windows 禁止的冒号，短散列区分同一分钟内的不同会话。
    relative_directory = (
        f"{started:%Y_%m_%d}/{user_id}_{started:%Y_%m_%d_%H_%M}_{session_ref[:12]}"
    )
    # 归档故障只记录类型，不影响正常问答或云端追踪。
    try:
        # 数据库锁保证同时到达的同一会话只采用一个首次时间。
        with _archive_index() as connection:
            # 已存在的会话保持原目录，跨日期及服务重启也能继续追加。
            connection.execute(
                "INSERT INTO sessions(session_ref, directory, started_at) VALUES (?, ?, ?) "
                "ON CONFLICT(session_ref) DO NOTHING",
                (session_ref, relative_directory, started.isoformat()),
            )
            # 为本轮 UUID 绑定会话，所有子节点共享这个根 UUID。
            connection.execute(
                "INSERT INTO traces(trace_id, session_ref) VALUES (?, ?)", (str(trace_id), session_ref)
            )
            # 获取索引中实际采用的首次目录和首次时间。
            row = connection.execute(
                "SELECT directory, started_at FROM sessions WHERE session_ref = ?", (session_ref,)
            ).fetchone()
            # 拼接完全由本模块生成的相对目录。
            directory = TRACE_ARCHIVE_ROOT / row[0]
            # 在写入会话说明或生命周期事件前创建用户会话目录。
            directory.mkdir(parents=True, exist_ok=True)
            # 会话说明仅保存在本地，用户 ID 不加入 LangSmith 上传元数据。
            manifest = directory / "session.json"
            # 已有会话的首次时间保持不变。
            if not manifest.exists():
                # 保存可用于定位会话的身份与时间摘要，不保存原始会话 ID 或对话。
                manifest.write_text(
                    json.dumps(
                        {"user_id": user_id, "session_ref": session_ref, "started_at": row[1]},
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
        # 日志同时给出本轮 UUID 与归档位置，便于与网关错误日志对照。
        LOGGER.info("Local trace archive trace_id=%s directory=%s", trace_id, directory)
    # 文件系统或索引不可用时仍继续模型与工具执行。
    except (OSError, sqlite3.Error) as exc:
        # 避免将异常正文中的路径、参数或业务信息扩散到日志。
        LOGGER.warning("Local trace session unavailable type=%s", type(exc).__name__)


# 将节点、模型和工具的生命周期事件追加到根追踪所属的会话目录。
def _archive_run(event: str, values: dict[str, Any], run_type: Any = "") -> None:
    """Append a sanitized span event to its registered user session's JSONL file."""
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        # 为 `trace_id` 保存当前步骤所需的值。
        trace_id = str(UUID(str(values.get("trace_id", ""))))
        # 为 `run_id` 保存当前步骤所需的值。
        run_id = str(UUID(str(values.get("id", ""))))
    # 进入对应的循环、异常处理或资源管理分支。
    except (ValueError, TypeError, AttributeError):
        # 将当前计算结果返回给调用方。
        return
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        # 为 `parent_run_id` 保存当前步骤所需的值。
        parent_run_id = str(UUID(str(values.get("parent_run_id", ""))))
    # 进入对应的循环、异常处理或资源管理分支。
    except (ValueError, TypeError, AttributeError):
        # 为 `parent_run_id` 保存当前步骤所需的值。
        parent_run_id = None
    # 为 `extra` 保存当前步骤所需的值。
    extra = values.get("extra", {})
    # 为 `metadata` 保存当前步骤所需的值。
    metadata = extra.get("metadata", {}) if isinstance(extra, dict) else {}
    # 为 `archived` 保存当前步骤所需的值。
    archived = {
        # 设置当前结构中的 `event` 字段。
        "event": event,
        # 设置当前结构中的 `recorded_at` 字段。
        "recorded_at": datetime.now(CHINA_TIMEZONE).isoformat(),
        # 设置当前结构中的 `trace_id` 字段。
        "trace_id": trace_id,
        # 设置当前结构中的 `run_id` 字段。
        "run_id": run_id,
        # 设置当前结构中的 `parent_run_id` 字段。
        "parent_run_id": parent_run_id,
        # 设置当前结构中的 `name` 字段。
        "name": _label(values.get("name")),
        # 设置当前结构中的 `run_type` 字段。
        "run_type": _label(run_type, "chain"),
        # 设置当前结构中的 `start_time` 字段。
        "start_time": values.get("start_time"),
        # 设置当前结构中的 `end_time` 字段。
        "end_time": values.get("end_time"),
        # 设置当前结构中的 `inputs` 字段。
        "inputs": summarize_payload(values.get("inputs")),
        # 设置当前结构中的 `outputs` 字段。
        "outputs": summarize_payload(values.get("outputs")),
        # 设置当前结构中的 `error_code` 字段。
        "error_code": values.get("error")
        # 检查 `if isinstance(values.get("error"), str) and values["error"] in ERROR_CODES`，据此选择当前处理分支。
        if isinstance(values.get("error"), str) and values["error"] in ERROR_CODES
        # 补充当前表达式的 `else None` 参数或元素。
        else None,
        # 设置当前结构中的 `metadata` 字段。
        "metadata": _metadata(metadata),
        # 设置当前结构中的 `events` 字段。
        "events": values.get("events", []),
    }
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        # 查询持久化索引，后台回调无需依赖当前请求的 ContextVar。
        with _archive_index() as connection:
            # 根 UUID 能把延迟结束及跨午夜的子节点事件送回原会话目录。
            row = connection.execute(
                "SELECT sessions.directory FROM traces JOIN sessions USING(session_ref) WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            # 没有业务会话的直接 SDK 调用单独按根 UUID 归档。
            relative_directory = row[0] if row else (
                f"{datetime.now(CHINA_TIMEZONE):%Y_%m_%d}/_unassigned_{trace_id}"
            )
            # 每个会话拥有独立的日志文件，多轮回答通过 trace_id 区分。
            directory = TRACE_ARCHIVE_ROOT / relative_directory
            # 允许异常诊断产生的无会话追踪也创建独立目录。
            directory.mkdir(parents=True, exist_ok=True)
            # 在同一写锁内追加完整一行，避免不同进程混写 JSON。
            with (directory / "traces.jsonl").open("a", encoding="utf-8") as archive:
                archive.write(json.dumps(archived, ensure_ascii=False, default=str) + "\n")
    # 进入对应的循环、异常处理或资源管理分支。
    except (OSError, sqlite3.Error) as exc:
        # 执行当前异步调用或运行状态记录。
        LOGGER.warning("Local trace archive unavailable type=%s", type(exc).__name__)


# 声明当前处理单元及其入口。
class MetadataOnlyClient(Client):
    """Prevent raw state, model prompts, results and exception bodies from leaving the process."""

    # 声明当前处理单元及其入口。
    def create_run(self, name: str, inputs: dict[str, Any], run_type: Any, **kwargs: Any) -> None:
        """Sanitize creates before handing them to the SDK's background queue."""
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `project` 保存当前步骤所需的值。
            project = kwargs.get("project_name") or kwargs.get("session_name")
            # 为 `fields` 保存当前步骤所需的值。
            fields = _run_fields(kwargs)
            # 为 `safe_name` 保存当前步骤所需的值。
            safe_name = _label(name)
            fields["name"] = safe_name
            # 调用 `_archive_run` 执行当前业务操作。
            _archive_run("run_created", fields, run_type)
            fields.pop("name", None)
            # 调用 `super` 执行当前业务操作。
            super().create_run(
                # 为 `name` 保存当前步骤所需的值。
                name=safe_name,
                # 为 `inputs` 保存当前步骤所需的值。
                inputs=summarize_payload(inputs),
                # 为 `run_type` 保存当前步骤所需的值。
                run_type=run_type,
                # 为 `project_name` 保存当前步骤所需的值。
                project_name=project,
                # 补充当前表达式的 `**fields` 参数或元素。
                **fields,
            )
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exc:
            # 执行当前异步调用或运行状态记录。
            LOGGER.warning("LangSmith create unavailable type=%s", type(exc).__name__)

    # 声明当前处理单元及其入口。
    def update_run(self, run_id: Any, **kwargs: Any) -> None:
        """Sanitize updates as well as starts; streamed model errors are also scrubbed."""
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `fields` 保存当前步骤所需的值。
            fields = _run_fields(kwargs)
            fields["id"] = run_id
            # 调用 `_archive_run` 执行当前业务操作。
            _archive_run("run_updated", fields)
            fields.pop("id", None)
            # 调用 `super` 执行当前业务操作。
            super().update_run(run_id, **fields)
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exc:
            # 执行当前异步调用或运行状态记录。
            LOGGER.warning("LangSmith update unavailable type=%s", type(exc).__name__)

    # 为紧随其后的函数或类设置装饰行为。
    @staticmethod
    # 声明当前处理单元及其入口。
    def _insert_runtime_env(runs: Any) -> None:
        """Keep the pinned SDK from appending process environment values after filtering."""
        # 进入对应的循环、异常处理或资源管理分支。
        for run in runs:
            # 为 `extra` 保存当前步骤所需的值。
            extra = run.get("extra") or {}
            run["extra"] = {"metadata": _metadata(extra.get("metadata")), "runtime": {"sdk": "langsmith-py"}}


# 为紧随其后的函数或类设置装饰行为。
@dataclass
# 声明当前处理单元及其入口。
class TraceTurn:
    """A request-scoped outcome that survives caught exceptions and streamed error events."""

    # 设置当前结构中的 `trace_id` 字段。
    trace_id: UUID
    # 设置当前结构中的 `run` 字段。
    run: RunTree | None = None
    # 设置当前结构中的 `status` 字段。
    status: str = "running"
    # 设置当前结构中的 `error_code` 字段。
    error_code: str = ""
    # 设置当前结构中的 `failure_count` 字段。
    failure_count: int = 0
    # 设置当前结构中的 `tool_calls` 字段。
    tool_calls: list[str] = field(default_factory=list)
    # 设置当前结构中的 `intent` 字段。
    intent: str = ""
    workflow: dict[str, Any] = field(default_factory=dict)

    # 声明当前处理单元及其入口。
    def observe(self, packet: dict[str, Any]) -> None:
        """Classify protocol events without retaining any answer text or user entities."""
        # 为 `kind` 保存当前步骤所需的值。
        kind = packet.get("type")
        # 检查 `if kind == "error"`，据此选择当前处理分支。
        if kind == "error":
            # 为 `self.status` 保存当前步骤所需的值。
            self.status = "failed"
            # 为 `code` 保存当前步骤所需的值。
            code = packet.get("code")
            # 为 `self.error_code` 保存当前步骤所需的值。
            self.error_code = code if isinstance(code, str) and code in ERROR_CODES else "agent_error"
        # 检查 `elif kind == "complete" and self.status != "failed"`，据此选择当前处理分支。
        elif kind == "complete" and self.status != "failed":
            # 为 `self.status` 保存当前步骤所需的值。
            self.status = "completed"
        # 检查 `elif kind == "context"`，据此选择当前处理分支。
        elif kind == "context":
            # 为 `summary` 保存当前步骤所需的值。
            summary = summarize_payload(packet)
            # 为 `self.intent` 保存当前步骤所需的值。
            self.intent = summary.get("intent", self.intent)
            # 为 `self.tool_calls` 保存当前步骤所需的值。
            self.tool_calls = summary.get("tool_calls", self.tool_calls)
            self.workflow.update({
                key: value for key, value in summary.items() if key not in {"field_count", "intent", "tool_calls"}
            })

    # 声明当前处理单元及其入口。
    def finish(self) -> None:
        """Mark missing completion explicitly and patch the root outcome."""
        # 检查 `if self.status == "running"`，据此选择当前处理分支。
        if self.status == "running":
            self.status, self.error_code = "failed", "stream_incomplete"
        # 检查 `if self.run`，据此选择当前处理分支。
        if self.run:
            # 继续构造当前业务表达式或数据结构。
            self.run.end(
                # 为 `outputs` 保存当前步骤所需的值。
                outputs={
                    # 设置当前结构中的 `status` 字段。
                    "status": self.status,
                    # 设置当前结构中的 `error_code` 字段。
                    "error_code": self.error_code,
                    # 设置当前结构中的 `intent` 字段。
                    "intent": self.intent,
                    # 设置当前结构中的 `failure_count` 字段。
                    "failure_count": self.failure_count,
                    # 设置当前结构中的 `tool_calls` 字段。
                    "tool_calls": self.tool_calls,
                    **self.workflow,
                },
                # 为 `error` 保存当前步骤所需的值。
                error=self.error_code or None,
            )
        # 执行当前异步调用或运行状态记录。
        LOGGER.info(
            # 补充当前表达式的 `"Agent turn trace_id=%s outcome=%s error_cod` 参数或元素。
            "Agent turn trace_id=%s outcome=%s error_code=%s failures=%d",
            # 补充当前表达式的 `self.trace_id` 参数或元素。
            self.trace_id,
            # 补充当前表达式的 `self.status` 参数或元素。
            self.status,
            # 补充当前表达式的 `self.error_code or "none"` 参数或元素。
            self.error_code or "none",
            # 补充当前表达式的 `self.failure_count` 参数或元素。
            self.failure_count,
        )


# 声明当前处理单元及其入口。
class AgentTracing:
    """Enable tracing only with an explicit switch and a local/preproduction environment."""

    # 声明当前处理单元及其入口。
    def __init__(self) -> None:
        # 为 `self.environment` 保存当前步骤所需的值。
        self.environment = os.getenv("AI_ENVIRONMENT", "production").strip().lower()
        # 为 `self.project` 保存当前步骤所需的值。
        self.project = os.getenv("LANGSMITH_PROJECT", f"cinema-agent-{self.environment}").strip()
        # 设置当前结构中的 `self.client` 字段。
        self.client: MetadataOnlyClient | None = None
        # 为 `requested` 保存当前步骤所需的值。
        requested = os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"
        # 检查 `if not requested`，据此选择当前处理分支。
        if not requested:
            # 将当前计算结果返回给调用方。
            return
        # 检查 `if self.environment not in LOCAL_ENVIRONMENTS`，据此选择当前处理分支。
        if self.environment not in LOCAL_ENVIRONMENTS:
            # 执行当前异步调用或运行状态记录。
            LOGGER.warning("LangSmith disabled: tracing is restricted to local/preproduction environments")
            # 将当前计算结果返回给调用方。
            return
        # 调用 `_filter_sdk_logs` 执行当前业务操作。
        _filter_sdk_logs()
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `key` 保存当前步骤所需的值。
            key = load_langsmith_key()
            # 检查 `if not key`，据此选择当前处理分支。
            if not key:
                # 执行当前异步调用或运行状态记录。
                LOGGER.warning("LangSmith disabled: server-only API key not configured")
                # 将当前计算结果返回给调用方。
                return
            # 为 `session` 保存当前步骤所需的值。
            session = requests.Session()
            # 为 `workspace_id` 保存当前步骤所需的值。
            workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID", "").strip()
            # 检查 `if workspace_id`，据此选择当前处理分支。
            if workspace_id:
                # SDK 0.3.45 predates this environment setting; use its public session hook.
                session.headers["X-Tenant-Id"] = str(UUID(workspace_id))
            # 为 `self.client` 保存当前步骤所需的值。
            self.client = MetadataOnlyClient(
                # 为 `api_key` 保存当前步骤所需的值。
                api_key=key,
                # 为 `api_url` 保存当前步骤所需的值。
                api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/"),
                # 为 `timeout_ms` 保存当前步骤所需的值。
                timeout_ms=3000,
                # 为 `auto_batch_tracing` 保存当前步骤所需的值。
                auto_batch_tracing=True,
                # 为 `session` 保存当前步骤所需的值。
                session=session,
            )
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exc:
            # 执行当前异步调用或运行状态记录。
            LOGGER.warning("LangSmith disabled type=%s", type(exc).__name__)
        # 检查 `if self.client`，据此选择当前处理分支。
        if self.client:
            # 执行当前异步调用或运行状态记录。
            LOGGER.info(
                "LangSmith enabled environment=%s project=%s content=metadata_only", self.environment, self.project
            )

    # 为紧随其后的函数或类设置装饰行为。
    @contextmanager
    # 声明当前处理单元及其入口。
    def turn(self, user_id: int, session_id: str, question: str, channel: str) -> Iterator[TraceTurn]:
        """Create one root span for both graph execution and streaming completion."""
        # 为 `turn` 保存当前步骤所需的值。
        turn = TraceTurn(uuid4())
        # 为 `token` 保存当前步骤所需的值。
        token = CURRENT_TURN.set(turn)
        # 为 `session_ref` 保存当前步骤所需的值。
        session_ref = hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()
        # 关闭追踪时不建立目录；启用时在创建根 span 前持久化用户会话归属。
        if self.client is not None:
            # 本地用户 ID 只用于目录和说明文件，上传仍使用会话散列。
            _register_archive_session(user_id, session_ref, turn.trace_id)
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 进入对应的循环、异常处理或资源管理分支。
            with tracing_context(
                # 为 `enabled` 保存当前步骤所需的值。
                enabled=self.client is not None,
                # 为 `client` 保存当前步骤所需的值。
                client=self.client,
                # 为 `project_name` 保存当前步骤所需的值。
                project_name=self.project,
                # 为 `metadata` 保存当前步骤所需的值。
                metadata={
                    # 设置当前结构中的 `service` 字段。
                    "service": "cinema-agent",
                    # 设置当前结构中的 `environment` 字段。
                    "environment": self.environment,
                    # 设置当前结构中的 `channel` 字段。
                    "channel": channel,
                    # 设置当前结构中的 `trace_id` 字段。
                    "trace_id": str(turn.trace_id),
                    # 设置当前结构中的 `session_ref` 字段。
                    "session_ref": session_ref,
                    # 设置当前结构中的 `thread_id` 字段。
                    "thread_id": session_ref,
                },
            # 继续构造当前业务表达式或数据结构。
            ):
                # 为 `scope` 保存当前步骤所需的值。
                scope = (
                    # 调用 `trace` 执行当前业务操作。
                    trace(
                        # 补充当前表达式的 `f"cinema.agent.{channel}"` 参数或元素。
                        f"cinema.agent.{channel}",
                        # 为 `inputs` 保存当前步骤所需的值。
                        inputs={"question_characters": len(question)},
                        # 为 `run_id` 保存当前步骤所需的值。
                        run_id=turn.trace_id,
                        # 为 `client` 保存当前步骤所需的值。
                        client=self.client,
                        # 为 `project_name` 保存当前步骤所需的值。
                        project_name=self.project,
                        # 为 `exceptions_to_handle` 保存当前步骤所需的值。
                        exceptions_to_handle=(BaseException,),
                    )
                    # 检查 `if self.client is not None`，据此选择当前处理分支。
                    if self.client is not None
                    # 继续构造当前业务表达式或数据结构。
                    else nullcontext(None)
                )
                # 进入对应的循环、异常处理或资源管理分支。
                with scope as run:
                    # 为 `turn.run` 保存当前步骤所需的值。
                    turn.run = run
                    # 进入对应的循环、异常处理或资源管理分支。
                    try:
                        # 向流式调用方交付当前事件或结果。
                        yield turn
                    # 进入对应的循环、异常处理或资源管理分支。
                    except BaseException as exc:
                        # 检查 `if (`，据此选择当前处理分支。
                        if (
                            # 调用 `isinstance` 执行当前业务操作。
                            isinstance(exc, (GeneratorExit, KeyboardInterrupt))
                            or type(exc).__name__ == "CancelledError"
                        # 继续构造当前业务表达式或数据结构。
                        ):
                            turn.status, turn.error_code = "interrupted", "interrupted"
                        # 进入对应的循环、异常处理或资源管理分支。
                        else:
                            # 为 `turn.status` 保存当前步骤所需的值。
                            turn.status = "failed"
                            # 为 `turn.error_code` 保存当前步骤所需的值。
                            turn.error_code = "query_timeout" if isinstance(exc, TimeoutError) else "agent_error"
                        # 继续构造当前业务表达式或数据结构。
                        raise
                    # 进入对应的循环、异常处理或资源管理分支。
                    finally:
                        # 继续构造当前业务表达式或数据结构。
                        turn.finish()
        # 进入对应的循环、异常处理或资源管理分支。
        finally:
            # 继续构造当前业务表达式或数据结构。
            CURRENT_TURN.reset(token)

    # 声明当前处理单元及其入口。
    def status(self) -> dict[str, Any]:
        """Expose nonsecret effective configuration on the private health endpoint."""
        # 将当前计算结果返回给调用方。
        return {
            # 设置当前结构中的 `enabled` 字段。
            "enabled": self.client is not None,
            # 设置当前结构中的 `environment` 字段。
            "environment": self.environment,
            # 设置当前结构中的 `project` 字段。
            "project": self.project,
            # 设置当前结构中的 `content` 字段。
            "content": "metadata_only",
        }

    # 声明当前处理单元及其入口。
    def flush(self) -> None:
        """Drain pending writes during graceful service shutdown or a diagnostic run."""
        # 检查 `if self.client`，据此选择当前处理分支。
        if self.client:
            # 进入对应的循环、异常处理或资源管理分支。
            try:
                # 继续构造当前业务表达式或数据结构。
                self.client.flush()
            # 进入对应的循环、异常处理或资源管理分支。
            except Exception as exc:
                # 执行当前异步调用或运行状态记录。
                LOGGER.warning("LangSmith flush unavailable type=%s", type(exc).__name__)


# 声明当前处理单元及其入口。
def record_failure(stage: str, exception: Exception, code: str, status: int | None) -> None:
    """Attach a safe failure event even when business code catches the exception."""
    # 为 `turn` 保存当前步骤所需的值。
    turn = CURRENT_TURN.get()
    # 检查 `if turn is None`，据此选择当前处理分支。
    if turn is None:
        # 将当前计算结果返回给调用方。
        return
    # 继续构造当前业务表达式或数据结构。
    turn.failure_count += 1
    # 为 `run` 保存当前步骤所需的值。
    run = get_current_run_tree()
    # 检查 `if run`，据此选择当前处理分支。
    if run:
        # 继续构造当前业务表达式或数据结构。
        run.add_event(
            # 继续构造当前业务表达式或数据结构。
            {
                # 设置当前结构中的 `name` 字段。
                "name": "agent_failure",
                # 设置当前结构中的 `time` 字段。
                "time": datetime.now(UTC).isoformat(),
                # 设置当前结构中的 `kwargs` 字段。
                "kwargs": {
                    # 设置当前结构中的 `stage` 字段。
                    "stage": stage,
                    # 设置当前结构中的 `exception_type` 字段。
                    "exception_type": type(exception).__name__,
                    # 设置当前结构中的 `error_code` 字段。
                    "error_code": code,
                    # 设置当前结构中的 `http_status` 字段。
                    "http_status": status,
                },
            }
        )


# 声明当前处理单元及其入口。
def current_trace_id() -> str:
    """Return the correlation ID for safe application logs."""
    # 为 `turn` 保存当前步骤所需的值。
    turn = CURRENT_TURN.get()
    # 将当前计算结果返回给调用方。
    return str(turn.trace_id) if turn else "none"


# 为紧随其后的函数或类设置装饰行为。
@contextmanager
# 声明当前处理单元及其入口。
def tool_span(name: str, arguments: dict[str, Any]) -> Iterator[RunTree | None]:
    """Trace MCP/local calls that execute outside native LangChain tool callbacks."""
    # 为 `turn` 保存当前步骤所需的值。
    turn = CURRENT_TURN.get()
    # 为 `scope` 保存当前步骤所需的值。
    scope = trace(f"tool.{name}", run_type="tool", inputs=arguments) if turn and turn.run else nullcontext(None)
    # 进入对应的循环、异常处理或资源管理分支。
    with scope as run:
        # 向流式调用方交付当前事件或结果。
        yield run
