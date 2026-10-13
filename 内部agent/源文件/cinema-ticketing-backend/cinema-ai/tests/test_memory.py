"""Exercise real Chroma filters and SQL revalidation without external model calls."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import chromadb

from app.memory import MemoryIndex, UserMemory, memory_proposal
from app.memory_worker import process_job


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.client = chromadb.EphemeralClient()
        self.collection = self.client.create_collection("test_memory_" + uuid4().hex, embedding_function=None)
        self.index = MemoryIndex()
        self.index.collection = AsyncCollection(self.collection)
        self.index.encode = AsyncMock(return_value=[1.0, 0.0, 0.0])
        self.java = AsyncMock()
        self.recall = UserMemory(self.java, self.index)

    async def asyncTearDown(self) -> None:
        self.client.delete_collection(self.collection.name)

    async def write(self, user_id: int, version: int = 1) -> str:
        key = str(uuid4())
        await self.index.apply(
            key,
            {"user_id": user_id, "version": version, "content": "喜欢科幻", "category": "GENRE", "status": "ACTIVE"},
        )
        return key

    async def test_chroma_owner_filter_and_sql_version_revalidation(self) -> None:
        own = await self.write(1)
        await self.write(2)
        self.java.get.return_value = [{"id": own, "content": "SQL authoritative", "version": 1}]
        self.java.post.return_value = []  # Simulates a stale/deleted SQL row.
        self.java.get.side_effect = [self.java.get.return_value, []]
        self.assertEqual([], await self.recall.recall(1, "推荐电影"))
        payload = self.java.post.call_args.args[1]
        self.assertEqual(1, payload["userId"])
        self.assertEqual([{"id": own, "version": 1}], payload["candidates"])
        self.java.post.return_value = [{"id": own, "content": "SQL authoritative", "version": 1}]
        self.java.get.side_effect = None
        self.assertEqual("SQL authoritative", (await self.recall.recall(1, "推荐电影"))[0]["content"])

    async def test_projection_updates_idempotently_and_deletes(self) -> None:
        own = await self.write(1)
        row = {"user_id": 1, "version": 2, "content": "喜欢喜剧", "category": "GENRE", "status": "ACTIVE"}
        await self.index.apply(own, row)
        await self.index.apply(own, row)
        self.assertEqual(1, self.collection.count())
        result = self.collection.get(ids=[own])
        self.assertEqual(2, result["metadatas"][0]["version"])
        self.assertEqual("喜欢喜剧", result["documents"][0])
        await self.index.apply(own, {"status": "DELETED"})
        await self.index.apply(own, None)
        self.assertEqual(0, self.collection.count())

    async def test_failure_uses_fresh_sql_and_disabled_memory_is_empty(self) -> None:
        self.java.get.side_effect = [[{"content": "deleted while querying"}], []]
        self.index.encode.side_effect = RuntimeError("embedding down")
        self.assertEqual([], await self.recall.recall(1, "推荐电影"))
        self.assertEqual(2, self.java.get.await_count)
        with patch.dict("os.environ", {"MEMORY_ENABLED": "false"}):
            self.assertEqual([], await self.recall.recall(1, "推荐电影"))

    async def test_worker_skips_old_events_and_retries_failed_writes(self) -> None:
        index = AsyncMock()
        job = {
            "jobId": 1,
            "memoryId": str(uuid4()),
            "eventVersion": 1,
            "leaseToken": str(uuid4()),
            "memory": {"version": 2},
        }
        await process_job(self.java, index, job)
        index.apply.assert_not_awaited()
        self.assertTrue(self.java.post.call_args.args[1]["success"])
        job["eventVersion"] = 2
        index.apply.side_effect = RuntimeError("chroma down")
        await process_job(self.java, index, job)
        self.assertFalse(self.java.post.call_args.args[1]["success"])

    def test_only_explicit_requests_propose_and_do_not_write(self) -> None:
        self.assertIsNone(memory_proposal("我喜欢科幻电影"))
        self.assertEqual({"content": "我喜欢科幻电影", "category": "GENRE"}, memory_proposal("请记住：我喜欢科幻电影"))


class AsyncCollection:
    """Adapt real in-process Chroma to the Agent's async client contract."""

    def __init__(self, collection):
        self.collection = collection

    def __getattr__(self, name):
        async def invoke(**kwargs):
            return getattr(self.collection, name)(**kwargs)

        return invoke


if __name__ == "__main__":
    unittest.main()
