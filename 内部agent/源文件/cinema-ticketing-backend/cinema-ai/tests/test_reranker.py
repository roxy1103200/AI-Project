"""Rerank contract, provenance and degradation checks without real credentials or paid calls."""

import asyncio
import json
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from langchain_core.documents import Document

from app.policy_retrieval import KeywordRetriever, policy_candidates, split_documents
from app.reranker import DEFAULT_API_URL, DashScopeReranker, RerankSettings


def documents() -> list[Document]:
    """Keep each candidate distinguishable in both text and provenance."""
    return [
        Document(page_content=f"规则内容{index}", metadata={"source": f"rules-{index}.md", "version": 3})
        for index in range(6)
    ]


def response_for(indices: list[int]) -> dict:
    """Model the provider's native response envelope, not its chat completion schema."""
    return {
        "output": {
            "results": [
                {"index": index, "relevance_score": 1 - position * 0.1} for position, index in enumerate(indices)
            ]
        },
        "usage": {"prompt_tokens": 80, "total_tokens": 80},
        "request_id": "request-1",
    }


class RerankerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.requests = []
        self.data = response_for([5, 1, 3, 0])
        self.status = 200

        async def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.data)

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        self.key_loader = Mock(return_value="sk-private-test-key")
        self.reranker = DashScopeReranker(RerankSettings(), client=self.client, key_loader=self.key_loader)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def test_native_contract_maps_indices_and_keeps_sources_without_mutating_candidates(self) -> None:
        candidates = documents()
        selected = await self.reranker.rerank("退票规则", candidates)
        self.assertEqual(
            [doc.page_content for doc in selected], [candidates[index].page_content for index in [5, 1, 3, 0]]
        )
        self.assertEqual(selected[0].metadata, {"source": "rules-5.md", "version": 3, "rerank_score": 1})
        self.assertNotIn("rerank_score", candidates[5].metadata)
        request = self.requests[0]
        self.assertEqual(str(request.url), DEFAULT_API_URL)
        self.assertEqual(request.headers["Authorization"], "Bearer sk-private-test-key")
        payload = json.loads(request.content)
        self.assertEqual(payload["model"], "qwen3.7-text-rerank")
        self.assertEqual(payload["input"]["query"], "退票规则")
        self.assertEqual(payload["input"]["documents"], [doc.page_content for doc in candidates])
        self.assertEqual(payload["parameters"]["top_n"], 4)
        self.assertNotIn("messages", payload)

    async def test_empty_single_disabled_and_missing_key_do_not_send_requests(self) -> None:
        self.assertEqual(await self.reranker.rerank("问题", []), [])
        single = documents()[:1]
        self.assertEqual(await self.reranker.rerank("问题", single), single)
        disabled = DashScopeReranker(
            replace(RerankSettings(), enabled=False), client=self.client, key_loader=self.key_loader
        )
        self.assertEqual(await disabled.rerank("问题", documents()), documents()[:4])
        self.key_loader.assert_not_called()
        self.key_loader.return_value = ""
        self.assertEqual(await self.reranker.rerank("问题", documents()), documents()[:4])
        self.assertEqual(self.requests, [])

    async def test_http_failures_revert_to_complete_keyword_order(self) -> None:
        for code in (400, 401, 403, 429, 500, 502):
            with self.subTest(status=code):
                self.status = code
                self.assertEqual(await self.reranker.rerank("问题", documents()), documents()[:4])

    async def test_malformed_partial_duplicate_and_out_of_range_results_fall_back(self) -> None:
        malformed = [
            {},
            {"results": []},
            response_for([]),
            response_for([0]),
            response_for([0, 0, 1, 2]),
            response_for([-1, 0, 1, 2]),
            response_for([7, 0, 1, 2]),
            {"output": {"results": [{"index": "0", "relevance_score": 1}]}},
            {"output": {"results": [{"index": 0, "relevance_score": 2}]}},
            {"output": {"results": [{"index": True, "relevance_score": 1}]}},
        ]
        for data in malformed:
            with self.subTest(data=data):
                self.data = data
                self.assertEqual(await self.reranker.rerank("问题", documents()), documents()[:4])

    async def test_transport_exception_is_safe_and_never_logged_with_body_or_credentials(self) -> None:
        async def fail(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("SECRET raw transport detail")

        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            reranker = DashScopeReranker(RerankSettings(), client=client, key_loader=self.key_loader)
            with self.assertLogs("uvicorn.error", level="WARNING") as output:
                selected = await reranker.rerank("PRIVATE USER QUESTION", documents())
        self.assertEqual(selected, documents()[:4])
        log = " ".join(output.output)
        for secret in ("SECRET", "PRIVATE", "sk-private-test-key", "规则内容"):
            self.assertNotIn(secret, log)
        self.assertIn("transport_error", log)

    async def test_request_deadline_cancels_request_and_external_cancellation_propagates(self) -> None:
        async def slow(_: httpx.Request) -> httpx.Response:
            await asyncio.sleep(1)
            return httpx.Response(200, json=self.data)

        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            reranker = DashScopeReranker(
                replace(RerankSettings(), timeout_seconds=0.02), client=client, key_loader=self.key_loader
            )
            self.assertEqual(await reranker.rerank("问题", documents()), documents()[:4])
            task = asyncio.create_task(reranker.rerank("问题", documents()))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_top_k_top_n_and_small_candidate_count_are_respected(self) -> None:
        self.data = response_for([2, 0])
        reranker = DashScopeReranker(RerankSettings(top_k=3, top_n=2), client=self.client, key_loader=self.key_loader)
        selected = await reranker.rerank("问题", documents())
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(json.loads(self.requests[-1].content)["input"]["documents"]), 3)
        self.data = response_for([1, 0])
        selected = await self.reranker.rerank("问题", documents()[:2])
        self.assertEqual(len(selected), 2)
        self.assertEqual(json.loads(self.requests[-1].content)["parameters"]["top_n"], 2)

    async def test_parallel_requests_share_a_bounded_provider_pool(self) -> None:
        active = peak = 0

        async def provider(_: httpx.Request) -> httpx.Response:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.02)
                return httpx.Response(200, json=self.data)
            finally:
                active -= 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            reranker = DashScopeReranker(RerankSettings(), client=client, key_loader=self.key_loader)
            results = await asyncio.gather(*(reranker.rerank("问题", documents()) for _ in range(8)))
        self.assertEqual(peak, 4)
        self.assertTrue(all(result[0].metadata["source"] == "rules-5.md" for result in results))

    async def test_success_logs_usage_and_pooled_client_is_owned_correctly(self) -> None:
        with self.assertLogs("uvicorn.error", level="INFO") as output:
            await self.reranker.rerank("PRIVATE QUESTION", documents())
        log = " ".join(output.output)
        self.assertIn("total_tokens=80", log)
        self.assertIn("request_id=request-1", log)
        self.assertNotIn("PRIVATE", log)
        await self.reranker.aclose()
        self.assertFalse(self.client.is_closed)
        owner = DashScopeReranker()
        owner.client = httpx.AsyncClient()
        await owner.aclose()
        self.assertTrue(owner.client.is_closed)

    async def test_public_knowledge_tool_reranks_both_sources_and_keeps_live_policy(self) -> None:
        with patch("app.model_config.create_model", return_value=None):
            from app.main import create_tools

        java = AsyncMock()
        policy = {"version": 9, "policy": "以当前规则为准"}

        async def java_get(path: str, *args) -> object:
            return (
                policy
                if path.endswith("refund-policy")
                else [{"id": 8, "title": "购票规则", "version": "v2", "content": "儿童票购票规则"}]
            )

        java.get.side_effect = java_get
        self.reranker = DashScopeReranker(RerankSettings(top_n=1), client=self.client, key_loader=self.key_loader)
        self.data = response_for([1])
        retriever = KeywordRetriever(
            documents=[Document(page_content="购票规则规则规则", metadata={"source": "local.md"})]
        )
        result = await create_tools(java, retriever, self.reranker)["query_ticket_policy"].ainvoke(
            {"question": "购票规则"}
        )
        payload = json.loads(self.requests[-1].content)
        self.assertEqual(len(payload["input"]["documents"]), 2)
        self.assertIs(result["policy"], policy)
        self.assertEqual(len(result["answer_context"]), 1)
        self.assertEqual(result["sources"][0]["source"], "knowledge_document")
        self.assertEqual(result["sources"][0]["version"], "v2")
        self.assertEqual(result["sources"][0]["id"], 8)
        self.assertNotIn(policy["policy"], payload["input"]["documents"])


class CandidateTests(unittest.TestCase):
    def test_database_chunks_are_bounded_with_stable_provenance_and_deduplication(self) -> None:
        row = {"id": 5, "title": "退票规则", "version": "v3", "content": "退票规则说明。" * 150}
        merged = policy_candidates("退票", [], [row, row], 30)
        self.assertTrue(merged)
        self.assertTrue(all(len(doc.page_content) <= 500 for doc in merged))
        self.assertTrue(all(doc.metadata["id"] == 5 and doc.metadata["version"] == "v3" for doc in merged))
        self.assertEqual(len(merged), len({doc.page_content for doc in merged}))
        self.assertEqual(merged, policy_candidates("退票", [], [row, row], 30))

    def test_keyword_fallback_merges_sources_and_candidate_limits(self) -> None:
        local = [Document(page_content="退票说明", metadata={"source": "local.md"})]
        business = [{"id": 1, "content": "退票规则", "title": "退票", "version": 2}]
        self.assertEqual(len(policy_candidates("退票规则", local, business, 1)), 1)
        self.assertEqual(policy_candidates("退票规则", local, business, 2)[0].metadata["source"], "knowledge_document")
        chunks = split_documents("退票。" * 400, {"source": "test.md", "version": 1})
        self.assertEqual(KeywordRetriever(documents=chunks).top_k, 20)

    def test_invalid_settings_do_not_accept_unbounded_limits_or_credential_redirects(self) -> None:
        for settings in (
            {"top_k": 51},
            {"top_n": 31},
            {"timeout_seconds": 0},
            {"api_url": "http://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"},
            {"api_url": "https://other.example/api/v1/services/rerank/text-rerank/text-rerank"},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                RerankSettings(**settings)


if __name__ == "__main__":
    unittest.main()
