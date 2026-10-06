"""Agent-only long-term memory; MySQL is authoritative, Chroma is a projection."""

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.java_client import JavaApiClient

logger = logging.getLogger(__name__)
COLLECTION = "agent_user_memory_v1"
MODEL = "BAAI/bge-small-zh-v1.5"
MODEL_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class MemoryIndex:
    """Use the same normalized BGE vectors for writes and queries."""

    def __init__(self) -> None:
        self.model: Any = None
        self.collection: Any = None
        self.lock = asyncio.Lock()
        # Timeouts may cancel awaiting a thread. A single executor keeps CPU inference serialized.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-embedding")

    async def connect(self) -> Any:
        """Connect lazily so memory outages do not prevent business service startup."""
        if self.collection is None:
            async with self.lock:
                if self.collection is None:
                    import chromadb

                    client = await chromadb.AsyncHttpClient(
                        host=os.getenv("CHROMA_HOST", "127.0.0.1"),
                        port=int(os.getenv("CHROMA_PORT", "8030")),
                        ssl=os.getenv("CHROMA_SSL", "false").lower() == "true",
                    )
                    self.collection = await client.get_or_create_collection(
                        COLLECTION,
                        embedding_function=None,
                        metadata={"hnsw:space": "cosine", "embedding_model": MODEL},
                    )
        return self.collection

    def _encode(self, text: str) -> list[float]:
        if self.model is None:
            from sentence_transformers import SentenceTransformer

            # Provision the model once, outside request processing. No implicit downloads.
            self.model = SentenceTransformer(
                os.getenv("MEMORY_MODEL_PATH", MODEL),
                device="cpu",
                local_files_only=True,
            )
        return self.model.encode(text, normalize_embeddings=True).tolist()

    async def encode(self, text: str, *, query: bool = False) -> list[float]:
        """Run CPU work in a thread and serialize model initialization/encoding."""
        async with self.lock:
            return await asyncio.get_running_loop().run_in_executor(
                self.executor,
                self._encode,
                (QUERY_PREFIX if query else "") + text,
            )

    async def apply(self, memory_id: str, memory: dict[str, Any] | None) -> None:
        """Idempotently project the latest row, including deletion tombstones."""
        collection = await self.connect()
        if not memory or memory["status"] != "ACTIVE":
            await collection.delete(ids=[memory_id])
            return
        vector = await self.encode(memory["content"])
        await collection.upsert(
            ids=[memory_id],
            embeddings=[vector],
            documents=[memory["content"]],
            metadatas=[
                {
                    "user_id": str(memory["user_id"]),
                    "channel": "AGENT",
                    "version": memory["version"],
                    "category": memory["category"],
                }
            ],
        )


class UserMemory:
    """Recall only rows still owned by this authenticated user at the stored version."""

    def __init__(self, java: JavaApiClient, index: MemoryIndex | None = None) -> None:
        self.java = java
        self.index = index or MemoryIndex()

    async def recall(self, user_id: int, question: str) -> list[dict[str, Any]]:
        """Fail open for ordinary queries; use current SQL preferences if indexing is down."""
        if os.getenv("MEMORY_ENABLED", "true").lower() != "true":
            return []
        try:
            active = await self.java.get("/internal/ai/memories", {"userId": user_id})
            if not active:
                return []
            try:
                async with asyncio.timeout(4):
                    collection = await self.index.connect()
                    vector = await self.index.encode(question, query=True)
                    results = await collection.query(
                        query_embeddings=[vector],
                        n_results=5,
                        where={"$and": [{"user_id": str(user_id)}, {"channel": "AGENT"}]},
                        include=["metadatas"],
                    )
                candidates = [
                    {"id": key, "version": meta["version"]}
                    for key, meta in zip(results["ids"][0], results["metadatas"][0], strict=True)
                ]
                if candidates:
                    # Never trust Chroma text/ownership, even after metadata filtering.
                    verified = await self.java.post(
                        "/internal/ai/memories/verify",
                        {"userId": user_id, "candidates": candidates},
                    )
                    if verified:
                        return verified[:5]
            except Exception as exc:
                logger.warning("Memory vector recall unavailable (%s); using SQL", type(exc).__name__)
            # Re-read SQL: an earlier snapshot may have been deleted while encoding.
            return (await self.java.get("/internal/ai/memories", {"userId": user_id}))[:5]
        except Exception as exc:
            logger.warning("Memory recall unavailable (%s)", type(exc).__name__)
            return []


def memory_proposal(question: str) -> dict[str, str] | None:
    """Offer explicit 'remember' requests for confirmation; never write from model output."""
    match = re.match(r"^(?:请)?(?:帮我)?记住[：:,，\s]*(.+)$", question.strip())
    if not match:
        return None
    content = match.group(1).strip(" ：:,，")[:500]
    if not content:
        return None
    category = "GENERAL"
    for value, words in (
        ("SEAT", ("座位", "过道", "排")),
        ("CINEMA", ("影院",)),
        ("GENRE", ("科幻", "喜剧", "恐怖", "动作", "爱情")),
    ):
        if any(word in content for word in words):
            category = value
            break
    return {"content": content, "category": category}
