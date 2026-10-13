"""Bounded DashScope reranking for policy passages, with deterministic local fallback."""

# 导入当前步骤使用的模块或类型。
# isort: off
import asyncio
# 导入当前步骤使用的模块或类型。
import logging
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
import re
# 导入当前步骤使用的模块或类型。
from collections.abc import Callable
# 导入当前步骤使用的模块或类型。
from dataclasses import dataclass
# 导入当前步骤使用的模块或类型。
from time import perf_counter
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
import httpx
# 导入当前步骤使用的模块或类型。
from langchain_core.documents import Document
# 导入当前步骤使用的模块或类型。
from pydantic import BaseModel, Field

# 导入当前步骤使用的模块或类型。
from app.model_config import load_qwen_key
# isort: on

# 为 `LOGGER` 保存当前步骤所需的值。
LOGGER = logging.getLogger("uvicorn.error")
# 为 `DEFAULT_API_URL` 保存当前步骤所需的值。
DEFAULT_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


# 为紧随其后的函数或类设置装饰行为。
@dataclass(frozen=True)
# 声明当前处理单元及其入口。
class RerankSettings:
    """Keep reranking configuration independent of the chat completion endpoint."""

    # 设置当前结构中的 `enabled` 字段。
    enabled: bool = True
    # 设置当前结构中的 `model` 字段。
    model: str = "qwen3.7-text-rerank"
    # 设置当前结构中的 `api_url` 字段。
    api_url: str = DEFAULT_API_URL
    # 设置当前结构中的 `top_k` 字段。
    top_k: int = 30
    # 设置当前结构中的 `top_n` 字段。
    top_n: int = 4
    # 设置当前结构中的 `timeout_seconds` 字段。
    timeout_seconds: float = 5.0

    # 声明当前处理单元及其入口。
    def __post_init__(self) -> None:
        """Reject invalid limits before accepting requests."""
        # 检查 `if not 1 <= self.top_n <= self.top_k <= 50`，据此选择当前处理分支。
        if not 1 <= self.top_n <= self.top_k <= 50:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("RERANK limits must satisfy 1 <= TOP_N <= TOP_K <= 50")
        # 检查 `if not 0 < self.timeout_seconds <= 15`，据此选择当前处理分支。
        if not 0 < self.timeout_seconds <= 15:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("RERANK_TIMEOUT_SECONDS must be in (0, 15]")
        # 为 `url` 保存当前步骤所需的值。
        url = httpx.URL(self.api_url)
        # 为 `host` 保存当前步骤所需的值。
        host = url.host
        # Service credentials may only be sent to Alibaba's published model endpoints.
        # 为 `allowed` 保存当前步骤所需的值。
        allowed = host in {
            # 补充当前表达式的 `"dashscope.aliyuncs.com"` 参数或元素。
            "dashscope.aliyuncs.com",
            # 补充当前表达式的 `"dashscope-intl.aliyuncs.com"` 参数或元素。
            "dashscope-intl.aliyuncs.com",
            # 补充当前表达式的 `"dashscope-us.aliyuncs.com"` 参数或元素。
            "dashscope-us.aliyuncs.com",
            # 补充当前表达式的 `"cn-hongkong.dashscope.aliyuncs.com"` 参数或元素。
            "cn-hongkong.dashscope.aliyuncs.com",
        } or host.endswith(".maas.aliyuncs.com")
        # 检查 `if url.scheme != "https" or not allowed or url.userinfo or url.query or url.fragment`，据此选择当前处理分支。
        if url.scheme != "https" or not allowed or url.userinfo or url.query or url.fragment:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("RERANK_API_URL must be an HTTPS Alibaba model endpoint")
        # 检查 `if url.path != "/api/v1/services/rerank/text-rerank/text-rerank"`，据此选择当前处理分支。
        if url.path != "/api/v1/services/rerank/text-rerank/text-rerank":
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("RERANK_API_URL must use the native text-rerank path")
        # 检查 `if not self.model.strip()`，据此选择当前处理分支。
        if not self.model.strip():
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("RERANK_MODEL must not be empty")

    # 为紧随其后的函数或类设置装饰行为。
    @classmethod
    # 声明当前处理单元及其入口。
    def from_env(cls) -> "RerankSettings":
        """Load server-only settings; the existing Qwen key loader supplies credentials."""
        # 将当前计算结果返回给调用方。
        return cls(
            # 为 `enabled` 保存当前步骤所需的值。
            enabled=os.getenv("RERANK_ENABLED", "true").strip().lower() == "true",
            # 为 `model` 保存当前步骤所需的值。
            model=os.getenv("RERANK_MODEL", "qwen3.7-text-rerank").strip(),
            # 为 `api_url` 保存当前步骤所需的值。
            api_url=(os.getenv("RERANK_API_URL") or DEFAULT_API_URL).strip(),
            # 为 `top_k` 保存当前步骤所需的值。
            top_k=int(os.getenv("RERANK_TOP_K", "30")),
            # 为 `top_n` 保存当前步骤所需的值。
            top_n=int(os.getenv("RERANK_TOP_N", "4")),
            # 为 `timeout_seconds` 保存当前步骤所需的值。
            timeout_seconds=float(os.getenv("RERANK_TIMEOUT_SECONDS", "5")),
        )


# 声明当前处理单元及其入口。
class _Rank(BaseModel):
    # 设置当前结构中的 `index` 字段。
    index: int = Field(strict=True, ge=0)
    # 设置当前结构中的 `relevance_score` 字段。
    relevance_score: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)


# 声明当前处理单元及其入口。
class _Output(BaseModel):
    # 设置当前结构中的 `results` 字段。
    results: list[_Rank]


# 声明当前处理单元及其入口。
class _Response(BaseModel):
    # 设置当前结构中的 `output` 字段。
    output: _Output
    # 设置当前结构中的 `usage` 字段。
    usage: dict[str, Any] = Field(default_factory=dict)
    # 设置当前结构中的 `request_id` 字段。
    request_id: str = Field(default="", max_length=128)


# 声明当前处理单元及其入口。
class DashScopeReranker:
    """Rerank only supplied public policy passages, never memory or business tool rows."""

    # 声明当前处理单元及其入口。
    def __init__(
        # 补充当前表达式的 `self` 参数或元素。
        self,
        # 设置当前结构中的 `settings` 字段。
        settings: RerankSettings | None = None,
        # 设置当前结构中的 `client` 字段。
        client: httpx.AsyncClient | None = None,
        # 设置当前结构中的 `key_loader` 字段。
        key_loader: Callable[[], str] = load_qwen_key,
    # 继续构造当前业务表达式或数据结构。
    ) -> None:
        # 为 `self.settings` 保存当前步骤所需的值。
        self.settings = settings or RerankSettings.from_env()
        # 为 `self.client` 保存当前步骤所需的值。
        self.client = client
        # 为 `self.key_loader` 保存当前步骤所需的值。
        self.key_loader = key_loader
        # 为 `self._owns_client` 保存当前步骤所需的值。
        self._owns_client = client is None
        # 为 `self._slots` 保存当前步骤所需的值。
        self._slots = asyncio.Semaphore(4)

    # 声明当前处理单元及其入口。
    async def rerank(self, question: str, candidates: list[Document]) -> list[Document]:
        """Preserve provenance and fall back atomically if the provider result is unusable."""
        # 为 `documents` 保存当前步骤所需的值。
        documents = candidates[: self.settings.top_k]
        # 为 `fallback` 保存当前步骤所需的值。
        fallback = documents[: self.settings.top_n]
        # 检查 `if not self.settings.enabled or len(documents) <= 1`，据此选择当前处理分支。
        if not self.settings.enabled or len(documents) <= 1:
            # 将当前计算结果返回给调用方。
            return fallback
        # 为 `started` 保存当前步骤所需的值。
        started = perf_counter()
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `key` 保存当前步骤所需的值。
            key = self.key_loader()
            # 检查 `if not key`，据此选择当前处理分支。
            if not key:
                self._log_fallback("missing_key", len(documents), started)
                # 将当前计算结果返回给调用方。
                return fallback
            # The deadline includes waiting for a free slot, so bursts cannot queue indefinitely.
            # 进入对应的循环、异常处理或资源管理分支。
            async with asyncio.timeout(self.settings.timeout_seconds), self._slots:
                # 为 `result` 保存当前步骤所需的值。
                result = await self._request(question, documents, key)
            # 为 `selected` 保存当前步骤所需的值。
            selected = self._select(result, documents)
        # 进入对应的循环、异常处理或资源管理分支。
        except (TimeoutError, httpx.TimeoutException):
            self._log_fallback("timeout", len(documents), started)
            # 将当前计算结果返回给调用方。
            return fallback
        # 进入对应的循环、异常处理或资源管理分支。
        except httpx.HTTPStatusError as exc:
            # 继续构造当前业务表达式或数据结构。
            self._log_fallback(f"http_{exc.response.status_code}", len(documents), started)
            # 将当前计算结果返回给调用方。
            return fallback
        # 进入对应的循环、异常处理或资源管理分支。
        except httpx.HTTPError:
            self._log_fallback("transport_error", len(documents), started)
            # 将当前计算结果返回给调用方。
            return fallback
        # 进入对应的循环、异常处理或资源管理分支。
        except (ValueError, OSError):
            self._log_fallback("invalid_key_or_response", len(documents), started)
            # 将当前计算结果返回给调用方。
            return fallback
        # 继续构造当前业务表达式或数据结构。
        self._log_success(result, len(documents), len(selected), started)
        # 将当前计算结果返回给调用方。
        return selected

    # 声明当前处理单元及其入口。
    async def _request(self, question: str, documents: list[Document], key: str) -> _Response:
        # 检查 `if self.client is None`，据此选择当前处理分支。
        if self.client is None:
            # 为 `self.client` 保存当前步骤所需的值。
            self.client = httpx.AsyncClient(
                # 为 `timeout` 保存当前步骤所需的值。
                timeout=self.settings.timeout_seconds,
                # 为 `trust_env` 保存当前步骤所需的值。
                trust_env=False,
                # 为 `follow_redirects` 保存当前步骤所需的值。
                follow_redirects=False,
                # 为 `limits` 保存当前步骤所需的值。
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            )
        # 为 `response` 保存当前步骤所需的值。
        response = await self.client.post(
            # 补充当前表达式的 `self.settings.api_url` 参数或元素。
            self.settings.api_url,
            # 为 `headers` 保存当前步骤所需的值。
            headers={"Authorization": f"Bearer {key}"},
            # 为 `json` 保存当前步骤所需的值。
            json={
                # 设置当前结构中的 `model` 字段。
                "model": self.settings.model,
                # 设置当前结构中的 `input` 字段。
                "input": {"query": question, "documents": [document.page_content for document in documents]},
                # 设置当前结构中的 `parameters` 字段。
                "parameters": {
                    # 设置当前结构中的 `top_n` 字段。
                    "top_n": min(self.settings.top_n, len(documents)),
                    # 设置当前结构中的 `instruct` 字段。
                    "instruct": "Retrieve policy passages that directly answer the question.",
                },
            },
        )
        # 继续构造当前业务表达式或数据结构。
        response.raise_for_status()
        # 将当前计算结果返回给调用方。
        return _Response.model_validate(response.json())

    # 声明当前处理单元及其入口。
    def _select(self, result: _Response, documents: list[Document]) -> list[Document]:
        # 为 `ranks` 保存当前步骤所需的值。
        ranks = result.output.results
        # 为 `indices` 保存当前步骤所需的值。
        indices = [rank.index for rank in ranks]
        # 检查 `if len(ranks) != min(self.settings.top_n, len(documents)) or len(set(indices)) != len(indices)`，据此选择当前处理分支。
        if len(ranks) != min(self.settings.top_n, len(documents)) or len(set(indices)) != len(indices):
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("Incomplete or duplicate rerank results")
        # 检查 `if any(index >= len(documents) for index in indices)`，据此选择当前处理分支。
        if any(index >= len(documents) for index in indices):
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("Rerank index outside candidate list")
        # 将当前计算结果返回给调用方。
        return [
            # 调用 `Document` 执行当前业务操作。
            Document(
                # 为 `page_content` 保存当前步骤所需的值。
                page_content=documents[rank.index].page_content,
                # 为 `metadata` 保存当前步骤所需的值。
                metadata={**documents[rank.index].metadata, "rerank_score": rank.relevance_score},
            )
            # 进入对应的循环、异常处理或资源管理分支。
            for rank in sorted(ranks, key=lambda rank: rank.relevance_score, reverse=True)
        ]

    # 声明当前处理单元及其入口。
    def _log_fallback(self, reason: str, count: int, started: float) -> None:
        # Never include exception text, response bodies, questions, passages or credentials.
        # 执行当前异步调用或运行状态记录。
        LOGGER.warning(
            # 补充当前表达式的 `"Rerank status=fallback reason=%s candidates` 参数或元素。
            "Rerank status=fallback reason=%s candidates=%d elapsed_ms=%.0f",
            # 补充当前表达式的 `reason` 参数或元素。
            reason,
            # 补充当前表达式的 `count` 参数或元素。
            count,
            # 补充当前表达式的 `(perf_counter() - started) * 1000` 参数或元素。
            (perf_counter() - started) * 1000,
        )

    # 声明当前处理单元及其入口。
    def _log_success(self, result: _Response, count: int, selected: int, started: float) -> None:
        # 为 `tokens` 保存当前步骤所需的值。
        tokens = result.usage.get("total_tokens", 0)
        # 为 `request_id` 保存当前步骤所需的值。
        request_id = result.request_id if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", result.request_id) else "unavailable"
        # 执行当前异步调用或运行状态记录。
        LOGGER.info(
            # 补充当前表达式的 `"Rerank status=success model=%s candidates=%` 参数或元素。
            "Rerank status=success model=%s candidates=%d selected=%d elapsed_ms=%.0f total_tokens=%d request_id=%s",
            # 补充当前表达式的 `self.settings.model` 参数或元素。
            self.settings.model,
            # 补充当前表达式的 `count` 参数或元素。
            count,
            # 补充当前表达式的 `selected` 参数或元素。
            selected,
            # 补充当前表达式的 `(perf_counter() - started) * 1000` 参数或元素。
            (perf_counter() - started) * 1000,
            # 补充当前表达式的 `tokens if type(tokens) is int else 0` 参数或元素。
            tokens if type(tokens) is int else 0,
            # 补充当前表达式的 `request_id` 参数或元素。
            request_id,
        )

    # 声明当前处理单元及其入口。
    async def aclose(self) -> None:
        """Close the pool owned by this component when the Agent stops."""
        # 检查 `if self.client is not None and self._owns_client`，据此选择当前处理分支。
        if self.client is not None and self._owns_client:
            # 执行当前异步调用或运行状态记录。
            await self.client.aclose()
