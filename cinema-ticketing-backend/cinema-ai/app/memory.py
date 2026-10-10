"""Agent-only long-term memory; MySQL is authoritative, Chroma is a projection."""

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
from concurrent.futures import ThreadPoolExecutor
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
from app.java_client import JavaApiClient
# isort: on

# 为 `logger` 保存当前步骤所需的值。
logger = logging.getLogger(__name__)
# 为 `COLLECTION` 保存当前步骤所需的值。
COLLECTION = "agent_user_memory_v1"
# 为 `MODEL` 保存当前步骤所需的值。
MODEL = "BAAI/bge-small-zh-v1.5"
# 为 `MODEL_REVISION` 保存当前步骤所需的值。
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
# 为 `QUERY_PREFIX` 保存当前步骤所需的值。
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


# 声明当前处理单元及其入口。
class MemoryIndex:
    """Use the same normalized BGE vectors for writes and queries."""

    # 声明当前处理单元及其入口。
    def __init__(self) -> None:
        # 设置当前结构中的 `self.model` 字段。
        self.model: Any = None
        # 设置当前结构中的 `self.collection` 字段。
        self.collection: Any = None
        # 为 `self.lock` 保存当前步骤所需的值。
        self.lock = asyncio.Lock()
        # Timeouts may cancel awaiting a thread. A single executor keeps CPU inference serialized.
        # 为 `self.executor` 保存当前步骤所需的值。
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-embedding")

    # 声明当前处理单元及其入口。
    async def connect(self) -> Any:
        """Connect lazily so memory outages do not prevent business service startup."""
        # 检查 `if self.collection is None`，据此选择当前处理分支。
        if self.collection is None:
            # 进入对应的循环、异常处理或资源管理分支。
            async with self.lock:
                # 检查 `if self.collection is None`，据此选择当前处理分支。
                if self.collection is None:
                    # 导入当前步骤使用的模块或类型。
                    import chromadb

                    # 为 `client` 保存当前步骤所需的值。
                    client = await chromadb.AsyncHttpClient(
                        # 为 `host` 保存当前步骤所需的值。
                        host=os.getenv("CHROMA_HOST", "127.0.0.1"),
                        # 为 `port` 保存当前步骤所需的值。
                        port=int(os.getenv("CHROMA_PORT", "8030")),
                        # 为 `ssl` 保存当前步骤所需的值。
                        ssl=os.getenv("CHROMA_SSL", "false").lower() == "true",
                    )
                    # 为 `self.collection` 保存当前步骤所需的值。
                    self.collection = await client.get_or_create_collection(
                        # 补充当前表达式的 `COLLECTION` 参数或元素。
                        COLLECTION,
                        # 为 `embedding_function` 保存当前步骤所需的值。
                        embedding_function=None,
                        # 为 `metadata` 保存当前步骤所需的值。
                        metadata={"hnsw:space": "cosine", "embedding_model": MODEL},
                    )
        # 将当前计算结果返回给调用方。
        return self.collection

    # 声明当前处理单元及其入口。
    def _encode(self, text: str) -> list[float]:
        # 检查 `if self.model is None`，据此选择当前处理分支。
        if self.model is None:
            # 导入当前步骤使用的模块或类型。
            from sentence_transformers import SentenceTransformer

            # Provision the model once, outside request processing. No implicit downloads.
            # 为 `self.model` 保存当前步骤所需的值。
            self.model = SentenceTransformer(
                # 补充当前表达式的 `os.getenv("MEMORY_MODEL_PATH", MODEL)` 参数或元素。
                os.getenv("MEMORY_MODEL_PATH", MODEL),
                # 为 `device` 保存当前步骤所需的值。
                device="cpu",
                # 为 `local_files_only` 保存当前步骤所需的值。
                local_files_only=True,
            )
        # 将当前计算结果返回给调用方。
        return self.model.encode(text, normalize_embeddings=True).tolist()

    # 声明当前处理单元及其入口。
    async def encode(self, text: str, *, query: bool = False) -> list[float]:
        """Run CPU work in a thread and serialize model initialization/encoding."""
        # 进入对应的循环、异常处理或资源管理分支。
        async with self.lock:
            # 将当前计算结果返回给调用方。
            return await asyncio.get_running_loop().run_in_executor(
                # 补充当前表达式的 `self.executor` 参数或元素。
                self.executor,
                # 补充当前表达式的 `self._encode` 参数或元素。
                self._encode,
                # 补充当前表达式的 `(QUERY_PREFIX if query else "") + text` 参数或元素。
                (QUERY_PREFIX if query else "") + text,
            )

    # 声明当前处理单元及其入口。
    async def apply(self, memory_id: str, memory: dict[str, Any] | None) -> None:
        """Idempotently project the latest row, including deletion tombstones."""
        # 为 `collection` 保存当前步骤所需的值。
        collection = await self.connect()
        # 检查 `if not memory or memory["status"] != "ACTIVE"`，据此选择当前处理分支。
        if not memory or memory["status"] != "ACTIVE":
            # 执行当前异步调用或运行状态记录。
            await collection.delete(ids=[memory_id])
            # 将当前计算结果返回给调用方。
            return
        # 为 `vector` 保存当前步骤所需的值。
        vector = await self.encode(memory["content"])
        # 执行当前异步调用或运行状态记录。
        await collection.upsert(
            # 为 `ids` 保存当前步骤所需的值。
            ids=[memory_id],
            # 为 `embeddings` 保存当前步骤所需的值。
            embeddings=[vector],
            # 为 `documents` 保存当前步骤所需的值。
            documents=[memory["content"]],
            # 为 `metadatas` 保存当前步骤所需的值。
            metadatas=[
                # 继续构造当前业务表达式或数据结构。
                {
                    # 设置当前结构中的 `user_id` 字段。
                    "user_id": str(memory["user_id"]),
                    # 设置当前结构中的 `channel` 字段。
                    "channel": "AGENT",
                    # 设置当前结构中的 `version` 字段。
                    "version": memory["version"],
                    # 设置当前结构中的 `category` 字段。
                    "category": memory["category"],
                }
            ],
        )


# 声明当前处理单元及其入口。
class UserMemory:
    """Recall only rows still owned by this authenticated user at the stored version."""

    # 声明当前处理单元及其入口。
    def __init__(self, java: JavaApiClient, index: MemoryIndex | None = None) -> None:
        # 为 `self.java` 保存当前步骤所需的值。
        self.java = java
        # 为 `self.index` 保存当前步骤所需的值。
        self.index = index or MemoryIndex()

    # 声明当前处理单元及其入口。
    async def recall(self, user_id: int, question: str) -> list[dict[str, Any]]:
        """Fail open for ordinary queries; use current SQL preferences if indexing is down."""
        # 检查 `if os.getenv("MEMORY_ENABLED", "true").lower() != "true"`，据此选择当前处理分支。
        if os.getenv("MEMORY_ENABLED", "true").lower() != "true":
            # 将当前计算结果返回给调用方。
            return []
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `active` 保存当前步骤所需的值。
            active = await self.java.get("/internal/ai/memories", {"userId": user_id})
            # 检查 `if not active`，据此选择当前处理分支。
            if not active:
                # 将当前计算结果返回给调用方。
                return []
            # 进入对应的循环、异常处理或资源管理分支。
            try:
                # 进入对应的循环、异常处理或资源管理分支。
                async with asyncio.timeout(4):
                    # 为 `collection` 保存当前步骤所需的值。
                    collection = await self.index.connect()
                    # 为 `vector` 保存当前步骤所需的值。
                    vector = await self.index.encode(question, query=True)
                    # 为 `results` 保存当前步骤所需的值。
                    results = await collection.query(
                        # 为 `query_embeddings` 保存当前步骤所需的值。
                        query_embeddings=[vector],
                        # 为 `n_results` 保存当前步骤所需的值。
                        n_results=5,
                        # 为 `where` 保存当前步骤所需的值。
                        where={"$and": [{"user_id": str(user_id)}, {"channel": "AGENT"}]},
                        # 为 `include` 保存当前步骤所需的值。
                        include=["metadatas"],
                    )
                # 为 `candidates` 保存当前步骤所需的值。
                candidates = [
                    {"id": key, "version": meta["version"]}
                    # 进入对应的循环、异常处理或资源管理分支。
                    for key, meta in zip(results["ids"][0], results["metadatas"][0], strict=True)
                ]
                # 检查 `if candidates`，据此选择当前处理分支。
                if candidates:
                    # Never trust Chroma text/ownership, even after metadata filtering.
                    # 为 `verified` 保存当前步骤所需的值。
                    verified = await self.java.post(
                        # 补充当前表达式的 `"/internal/ai/memories/verify"` 参数或元素。
                        "/internal/ai/memories/verify",
                        # 补充当前表达式的 `{"userId": user_id, "candidates": candidates` 参数或元素。
                        {"userId": user_id, "candidates": candidates},
                    )
                    # 检查 `if verified`，据此选择当前处理分支。
                    if verified:
                        # 将当前计算结果返回给调用方。
                        return verified[:5]
            # 进入对应的循环、异常处理或资源管理分支。
            except Exception as exc:
                # 执行当前异步调用或运行状态记录。
                logger.warning("Memory vector recall unavailable (%s); using SQL", type(exc).__name__)
            # Re-read SQL: an earlier snapshot may have been deleted while encoding.
            # 将当前计算结果返回给调用方。
            return (await self.java.get("/internal/ai/memories", {"userId": user_id}))[:5]
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exc:
            # 执行当前异步调用或运行状态记录。
            logger.warning("Memory recall unavailable (%s)", type(exc).__name__)
            # 将当前计算结果返回给调用方。
            return []


# 声明当前处理单元及其入口。
def memory_proposal(question: str) -> dict[str, str] | None:
    """Offer explicit 'remember' requests for confirmation; never write from model output."""
    # 为 `match` 保存当前步骤所需的值。
    match = re.match(r"^(?:请)?(?:帮我)?记住[：:,，\s]*(.+)$", question.strip())
    # 检查 `if not match`，据此选择当前处理分支。
    if not match:
        # 将当前计算结果返回给调用方。
        return None
    # 为 `content` 保存当前步骤所需的值。
    content = match.group(1).strip(" ：:,，")[:500]
    # 检查 `if not content`，据此选择当前处理分支。
    if not content:
        # 将当前计算结果返回给调用方。
        return None
    # 为 `category` 保存当前步骤所需的值。
    category = "GENERAL"
    # 进入对应的循环、异常处理或资源管理分支。
    for value, words in (
        # 补充当前表达式的 `("SEAT", ("座位", "过道", "排"))` 参数或元素。
        ("SEAT", ("座位", "过道", "排")),
        # 补充当前表达式的 `("CINEMA", ("影院",))` 参数或元素。
        ("CINEMA", ("影院",)),
        # 补充当前表达式的 `("GENRE", ("科幻", "喜剧", "恐怖", "动作", "爱情"))` 参数或元素。
        ("GENRE", ("科幻", "喜剧", "恐怖", "动作", "爱情")),
    # 继续构造当前业务表达式或数据结构。
    ):
        # 检查 `if any(word in content for word in words)`，据此选择当前处理分支。
        if any(word in content for word in words):
            # 为 `category` 保存当前步骤所需的值。
            category = value
            # 结束当前循环。
            break
    # 将当前计算结果返回给调用方。
    return {"content": content, "category": category}
