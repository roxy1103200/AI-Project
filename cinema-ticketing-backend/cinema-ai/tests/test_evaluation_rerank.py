"""Check native rerank accounting and independent passage-ranking judgments."""

import contextvars
import unittest

import httpx
from langchain_core.documents import Document

from app.reranker import DashScopeReranker, RerankSettings
from evaluation.rerank_focus import ranking_score, summarize_focus
from evaluation.rerank_metrics import observe_reranker, rerank_summary


class RerankEvaluationTests(unittest.IsolatedAsyncioTestCase):
    """Use local contract fixtures; no paid requests are made by these tests."""

    async def test_success_records_native_usage_without_changing_selected_evidence(self) -> None:
        data = {
            "output": {"results": [{"index": 1, "relevance_score": 0.9}]},
            "usage": {"total_tokens": 100},
            "request_id": "test-request",
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
            ranker = DashScopeReranker(RerankSettings(top_n=1), client=client, key_loader=lambda: "local-test-key")
            active = contextvars.ContextVar("test_active")
            row = {"rerank_calls": []}
            active.set(row)
            observe_reranker(ranker, active)
            selected = await ranker.rerank("规则", [Document(page_content="一"), Document(page_content="二")])
        self.assertEqual(selected[0].page_content, "二")
        summary = rerank_summary([row])
        self.assertEqual(summary["provider_successes"], 1)
        self.assertEqual(summary["total_tokens"], 100)
        self.assertEqual(summary["usage_missing_requests"], 0)
        self.assertAlmostEqual(summary["estimated_total_cny"], 0.00005)

    async def test_http_fallback_is_not_success_or_zero_token_measurement(self) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429))) as client:
            ranker = DashScopeReranker(RerankSettings(top_n=1), client=client, key_loader=lambda: "local-test-key")
            active = contextvars.ContextVar("test_active")
            row = {"rerank_calls": []}
            active.set(row)
            observe_reranker(ranker, active)
            selected = await ranker.rerank("规则", [Document(page_content="一"), Document(page_content="二")])
        self.assertEqual(selected[0].page_content, "一")
        summary = rerank_summary([row])
        self.assertEqual(summary["provider_attempts"], 1)
        self.assertEqual(summary["provider_successes"], 0)
        self.assertEqual(summary["fallbacks"], 1)
        self.assertEqual(summary["usage_missing_requests"], 1)

    async def test_disabled_ranking_does_not_count_as_provider_call(self) -> None:
        ranker = DashScopeReranker(RerankSettings(enabled=False))
        active = contextvars.ContextVar("test_active")
        row = {"rerank_calls": []}
        active.set(row)
        observe_reranker(ranker, active)
        await ranker.rerank("规则", [Document(page_content="一"), Document(page_content="二")])
        summary = rerank_summary([row])
        self.assertEqual(summary["provider_attempts"], 0)
        self.assertEqual(summary["disabled"], 1)

    def test_negative_queries_are_excluded_from_positive_ranking_denominators(self) -> None:
        document = Document(page_content="规则", metadata={"chunk_id": "a", "source": "rules.md"})
        case = {
            "answerable": True,
            "relevant_candidate_ids": ["a"],
            "candidates": [{"text": document.page_content, "metadata": document.metadata}],
        }
        positive = ranking_score(case, [document])
        negative = ranking_score({**case, "answerable": False, "relevant_candidate_ids": []}, [document])
        rows = [
            {"variant": variant, "answerable": answerable, "score": score, "rerank_calls": []}
            for variant in ("baseline", "react")
            for answerable, score in ((True, positive), (False, negative))
        ]
        summary = summarize_focus(rows)["react"]
        self.assertEqual(summary["top1_hit"], 1)
        self.assertEqual(summary["positive_n"], 1)
        self.assertEqual(summary["negative_n"], 1)
        self.assertEqual(summary["negative_returned_evidence_count"], 1)
        altered = Document(page_content="篡改内容", metadata=document.metadata)
        self.assertFalse(ranking_score(case, [altered])["provenance_correct"])
