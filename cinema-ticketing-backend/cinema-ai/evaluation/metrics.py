"""Independent acceptance rules and descriptive statistics for Agent evaluation."""

import math
import re
from statistics import mean
from typing import Any

PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/qwen3-7-flash"


def percentile(values: list[float], fraction: float) -> float | None:
    """Use linear interpolation (Hyndman-Fan type 7), including small samples."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def priced_usage(usage: dict[str, Any]) -> float:
    """Estimate Beijing public list cost in CNY, with implicit cached input discounts."""
    inputs, outputs = usage["input_tokens"], usage["output_tokens"]
    cached = min(inputs, usage.get("input_token_details", {}).get("cache_read", 0))
    rate = 1 if inputs <= 32768 else 3 if inputs <= 262144 else 6
    return ((inputs - cached) * 0.2 + cached * 0.04 + outputs * 0.8) * rate / 1_000_000


def matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Match independently specified argument subsets and the trusted caller."""
    if actual["name"] != expected["name"] or actual["user_id"] != expected["user_id"]:
        return False
    arguments = actual["arguments"]
    defaults = {"movie_scope": "catalog", "query_scope": "bookable", "page": 1, "showing_only": False}
    return all(arguments.get(key, defaults.get(key)) == value for key, value in expected["arguments"].items())


def judge(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Require the full expected trace, validated arguments, facts, and completed SSE."""
    calls = result["tools"]
    trace_correct = any(
        len(calls) == len(plan) and all(matches(actual, expected) for actual, expected in zip(calls, plan, strict=True))
        for plan in case["plans"]
    )
    rejected = [call for call in result["validation"] if not call["accepted"]]
    tool_correct = trace_correct and not rejected
    missing = [pattern for pattern in case["answer_checks"] if not re.search(pattern, result["answer"], re.IGNORECASE)]
    forbidden = [
        pattern for pattern in case.get("answer_forbidden", []) if re.search(pattern, result["answer"], re.IGNORECASE)
    ]
    factual = not missing and not forbidden
    completed = result["completed"] and not result["errors"]
    return {
        "task_success": tool_correct and factual and completed,
        "tool_correct": tool_correct,
        "trace_correct": trace_correct,
        "factual_checks_pass": factual,
        "missing_checks": missing,
        "forbidden_matches": forbidden,
        "rejected_calls": len(rejected),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep failures in rate/cost denominators; report missing TTFT and usage explicitly."""
    if not rows:
        return {"n": 0}
    first = [row["ttft_ms"] for row in rows if row["ttft_ms"] is not None]
    total = [row["total_ms"] for row in rows]
    model_calls = [call for row in rows for call in row["model_calls"]]
    known = [call["usage"] for call in model_calls if call["usage"] is not None]
    success_rows = [row for row in rows if row["score"]["task_success"]]
    total_cost = sum(priced_usage(usage) for usage in known)
    return {
        "n": len(rows),
        "successes": len(success_rows),
        "task_success_rate": len(success_rows) / len(rows),
        "tool_correct_rate": sum(row["score"]["tool_correct"] for row in rows) / len(rows),
        "completed": sum(row["completed"] and not row["errors"] for row in rows),
        "ttft_n": len(first),
        "ttft_p50_ms": percentile(first, 0.5),
        "ttft_p95_ms": percentile(first, 0.95),
        "total_p50_ms": percentile(total, 0.5),
        "total_p95_ms": percentile(total, 0.95),
        "success_total_p50_ms": percentile([row["total_ms"] for row in success_rows], 0.5),
        "success_total_p95_ms": percentile([row["total_ms"] for row in success_rows], 0.95),
        "avg_model_calls": len(model_calls) / len(rows),
        "avg_business_tools": mean(len(row["tools"]) for row in rows),
        "avg_input_tokens": sum(usage["input_tokens"] for usage in known) / len(rows),
        "avg_output_tokens": sum(usage["output_tokens"] for usage in known) / len(rows),
        "avg_total_tokens": sum(usage["total_tokens"] for usage in known) / len(rows),
        "avg_cached_input_tokens": sum(usage.get("input_token_details", {}).get("cache_read", 0) for usage in known)
        / len(rows),
        "usage_missing_calls": len(model_calls) - len(known),
        "estimated_total_cny": total_cost,
        "estimated_avg_cny": total_cost / len(rows),
        "estimated_cny_per_success": total_cost / len(success_rows) if success_rows else None,
    }
