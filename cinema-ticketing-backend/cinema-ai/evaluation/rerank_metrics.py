"""Observe real reranking decisions, provider usage and fallback without changing ranking."""

import time
from typing import Any

from evaluation.metrics import percentile

RERANK_PRICE_SOURCE = "https://help.aliyun.com/zh/model-studio/qwen3-7-text-rerank"
RERANK_CNY_PER_MILLION = 0.5


def observe_reranker(reranker: Any, active: Any) -> None:
    """Attach observers to the instance already captured by the policy tool closure."""
    original_rank = reranker.rerank
    original_request = reranker._request
    original_fallback = reranker._log_fallback

    async def request(question: str, documents: list, key: str) -> Any:
        event = active.get()["rerank_calls"][-1]
        event["provider_attempted"] = True
        result = await original_request(question, documents, key)
        event["usage"] = result.usage
        event["request_id"] = result.request_id
        event["status"] = "success"
        return result

    def fallback(reason: str, count: int, started: float) -> None:
        event = active.get()["rerank_calls"][-1]
        event.update(status="fallback", reason=reason)
        original_fallback(reason, count, started)

    async def rank(question: str, candidates: list) -> list:
        settings = reranker.settings
        documents = candidates[: settings.top_k]
        event = {
            "question": question,
            "enabled": settings.enabled,
            "model": settings.model,
            "status": "disabled" if not settings.enabled else "skipped_single_candidate",
            "provider_attempted": False,
            "usage": None,
            "candidates": [{"text": doc.page_content, "metadata": doc.metadata} for doc in documents],
        }
        active.get().setdefault("rerank_calls", []).append(event)
        started = time.perf_counter()
        try:
            selected = await original_rank(question, candidates)
            event["selected"] = [{"text": doc.page_content, "metadata": doc.metadata} for doc in selected]
            return selected
        finally:
            event["duration_ms"] = (time.perf_counter() - started) * 1000

    reranker._request = request
    reranker._log_fallback = fallback
    reranker.rerank = rank


def rerank_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep provider requests distinct from disabled, skipped and failed requests."""
    events = [event for row in rows for event in row.get("rerank_calls", [])]
    attempted = [event for event in events if event["provider_attempted"]]
    successes = [event for event in attempted if event["status"] == "success"]
    known = [
        event["usage"]["total_tokens"]
        for event in attempted
        if isinstance(event.get("usage"), dict) and type(event["usage"].get("total_tokens")) is int
    ]
    tokens = sum(known)
    return {
        "policy_retrieval_calls": len(events),
        "provider_attempts": len(attempted),
        "provider_successes": len(successes),
        "fallbacks": sum(event["status"] == "fallback" for event in events),
        "disabled": sum(event["status"] == "disabled" for event in events),
        "skipped": sum(event["status"] == "skipped_single_candidate" for event in events),
        "provider_success_rate": len(successes) / len(attempted) if attempted else None,
        "usage_missing_requests": len(attempted) - len(known),
        "total_tokens": tokens,
        "avg_tokens_per_task": tokens / len(rows) if rows else None,
        "avg_provider_calls_per_task": len(attempted) / len(rows) if rows else None,
        "p50_ms": percentile([event["duration_ms"] for event in events], 0.5),
        "p95_ms": percentile([event["duration_ms"] for event in events], 0.95),
        "estimated_total_cny": tokens * RERANK_CNY_PER_MILLION / 1_000_000,
        "estimated_avg_cny": tokens * RERANK_CNY_PER_MILLION / 1_000_000 / len(rows) if rows else None,
        "price_source": RERANK_PRICE_SOURCE,
        "price_asof": "2026-10-09",
    }


def augment_summary(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    """Include native rerank requests in total cost/call accounting while retaining chat-only fields."""
    ranking = rerank_summary(rows)
    if not rows:
        return summary
    return {
        **summary,
        "rerank": ranking,
        "avg_all_model_calls": summary["avg_model_calls"] + ranking["avg_provider_calls_per_task"],
        "avg_all_tokens": summary["avg_total_tokens"] + ranking["avg_tokens_per_task"],
        "estimated_avg_task_cny": summary["estimated_avg_cny"] + ranking["estimated_avg_cny"],
        "estimated_total_task_cny": summary["estimated_total_cny"] + ranking["estimated_total_cny"],
    }
