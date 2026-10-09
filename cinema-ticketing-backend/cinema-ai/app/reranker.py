"""Bounded DashScope reranking for policy passages, with deterministic local fallback."""

import asyncio
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.model_config import load_qwen_key

LOGGER = logging.getLogger("uvicorn.error")
DEFAULT_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


@dataclass(frozen=True)
class RerankSettings:
    """Keep reranking configuration independent of the chat completion endpoint."""

    enabled: bool = True
    model: str = "qwen3.7-text-rerank"
    api_url: str = DEFAULT_API_URL
    top_k: int = 30
    top_n: int = 4
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Reject invalid limits before accepting requests."""
        if not 1 <= self.top_n <= self.top_k <= 50:
            raise ValueError("RERANK limits must satisfy 1 <= TOP_N <= TOP_K <= 50")
        if not 0 < self.timeout_seconds <= 15:
            raise ValueError("RERANK_TIMEOUT_SECONDS must be in (0, 15]")
        url = httpx.URL(self.api_url)
        host = url.host
        # Service credentials may only be sent to Alibaba's published model endpoints.
        allowed = host in {
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
            "cn-hongkong.dashscope.aliyuncs.com",
        } or host.endswith(".maas.aliyuncs.com")
        if url.scheme != "https" or not allowed or url.userinfo or url.query or url.fragment:
            raise ValueError("RERANK_API_URL must be an HTTPS Alibaba model endpoint")
        if url.path != "/api/v1/services/rerank/text-rerank/text-rerank":
            raise ValueError("RERANK_API_URL must use the native text-rerank path")
        if not self.model.strip():
            raise ValueError("RERANK_MODEL must not be empty")

    @classmethod
    def from_env(cls) -> "RerankSettings":
        """Load server-only settings; the existing Qwen key loader supplies credentials."""
        return cls(
            enabled=os.getenv("RERANK_ENABLED", "true").strip().lower() == "true",
            model=os.getenv("RERANK_MODEL", "qwen3.7-text-rerank").strip(),
            api_url=(os.getenv("RERANK_API_URL") or DEFAULT_API_URL).strip(),
            top_k=int(os.getenv("RERANK_TOP_K", "30")),
            top_n=int(os.getenv("RERANK_TOP_N", "4")),
            timeout_seconds=float(os.getenv("RERANK_TIMEOUT_SECONDS", "5")),
        )


class _Rank(BaseModel):
    index: int = Field(strict=True, ge=0)
    relevance_score: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


class _Output(BaseModel):
    results: list[_Rank]


class _Response(BaseModel):
    output: _Output
    usage: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(default="", max_length=128)


class DashScopeReranker:
    """Rerank only supplied public policy passages, never memory or business tool rows."""

    def __init__(
        self,
        settings: RerankSettings | None = None,
        client: httpx.AsyncClient | None = None,
        key_loader: Callable[[], str] = load_qwen_key,
    ) -> None:
        self.settings = settings or RerankSettings.from_env()
        self.client = client
        self.key_loader = key_loader
        self._owns_client = client is None
        self._slots = asyncio.Semaphore(4)

    async def rerank(self, question: str, candidates: list[Document]) -> list[Document]:
        """Preserve provenance and fall back atomically if the provider result is unusable."""
        documents = candidates[: self.settings.top_k]
        fallback = documents[: self.settings.top_n]
        if not self.settings.enabled or len(documents) <= 1:
            return fallback
        started = perf_counter()
        try:
            key = self.key_loader()
            if not key:
                self._log_fallback("missing_key", len(documents), started)
                return fallback
            # The deadline includes waiting for a free slot, so bursts cannot queue indefinitely.
            async with asyncio.timeout(self.settings.timeout_seconds), self._slots:
                result = await self._request(question, documents, key)
            selected = self._select(result, documents)
        except (TimeoutError, httpx.TimeoutException):
            self._log_fallback("timeout", len(documents), started)
            return fallback
        except httpx.HTTPStatusError as exc:
            self._log_fallback(f"http_{exc.response.status_code}", len(documents), started)
            return fallback
        except httpx.HTTPError:
            self._log_fallback("transport_error", len(documents), started)
            return fallback
        except (ValueError, OSError):
            self._log_fallback("invalid_key_or_response", len(documents), started)
            return fallback
        self._log_success(result, len(documents), len(selected), started)
        return selected

    async def _request(self, question: str, documents: list[Document], key: str) -> _Response:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.settings.timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            )
        response = await self.client.post(
            self.settings.api_url,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": self.settings.model,
                "input": {"query": question, "documents": [document.page_content for document in documents]},
                "parameters": {
                    "top_n": min(self.settings.top_n, len(documents)),
                    "instruct": "Retrieve policy passages that directly answer the question.",
                },
            },
        )
        response.raise_for_status()
        return _Response.model_validate(response.json())

    def _select(self, result: _Response, documents: list[Document]) -> list[Document]:
        ranks = result.output.results
        indices = [rank.index for rank in ranks]
        if len(ranks) != min(self.settings.top_n, len(documents)) or len(set(indices)) != len(indices):
            raise ValueError("Incomplete or duplicate rerank results")
        if any(index >= len(documents) for index in indices):
            raise ValueError("Rerank index outside candidate list")
        return [
            Document(
                page_content=documents[rank.index].page_content,
                metadata={**documents[rank.index].metadata, "rerank_score": rank.relevance_score},
            )
            for rank in sorted(ranks, key=lambda rank: rank.relevance_score, reverse=True)
        ]

    def _log_fallback(self, reason: str, count: int, started: float) -> None:
        # Never include exception text, response bodies, questions, passages or credentials.
        LOGGER.warning(
            "Rerank status=fallback reason=%s candidates=%d elapsed_ms=%.0f",
            reason,
            count,
            (perf_counter() - started) * 1000,
        )

    def _log_success(self, result: _Response, count: int, selected: int, started: float) -> None:
        tokens = result.usage.get("total_tokens", 0)
        request_id = result.request_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result.request_id) else "unavailable"
        LOGGER.info(
            "Rerank status=success model=%s candidates=%d selected=%d elapsed_ms=%.0f total_tokens=%d request_id=%s",
            self.settings.model,
            count,
            selected,
            (perf_counter() - started) * 1000,
            tokens if type(tokens) is int else 0,
            request_id,
        )

    async def aclose(self) -> None:
        """Close the pool owned by this component when the Agent stops."""
        if self.client is not None and self._owns_client:
            await self.client.aclose()
