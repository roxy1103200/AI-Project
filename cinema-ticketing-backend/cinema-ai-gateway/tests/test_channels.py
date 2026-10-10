"""Integration checks for provider isolation using real Redis and mocked upstreams."""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import redis

# Import with a fake key so test discovery never reads a real Dify credential file.
with patch.dict(os.environ, {"DIFY_API_KEY": "test-key"}):
    from app.feedback import Snapshot
    from app.main import app
    from app.store import ConversationStore


class ChannelIsolationTests(unittest.IsolatedAsyncioTestCase):
    """Exercise routes, persistent history, leases, resets, feedback and upstream input."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start an isolated Redis, or use an explicitly supplied test Redis URL."""
        cls.server = None
        cls.temp = None
        cls.redis_url = os.getenv("CINEMA_TEST_REDIS_URL", "")
        if cls.redis_url:
            return
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        executable = shutil.which("redis-server")
        if os.name == "nt" and not executable:
            # Reuse the pinned Redis binary from this project's Java test dependency.
            jar = Path.home() / ".m2/repository/com/github/codemonstur/embedded-redis/1.4.3/embedded-redis-1.4.3.jar"
            if not jar.is_file():
                raise unittest.SkipTest("Set CINEMA_TEST_REDIS_URL or install the project's embedded Redis dependency")
            cls.temp = tempfile.TemporaryDirectory(prefix="cinema-channel-tests-")
            name = "redis-server-5.0.14.1-windows-amd64.exe"
            executable = str(Path(cls.temp.name) / name)
            with zipfile.ZipFile(jar) as archive:
                Path(executable).write_bytes(archive.read(name))
        if not executable:
            raise unittest.SkipTest("Set CINEMA_TEST_REDIS_URL or install redis-server")
        cls.redis_url = f"redis://127.0.0.1:{port}/0"
        cls.server = subprocess.Popen(
            [executable, "--bind", "127.0.0.1", "--port", str(port), "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        client = redis.Redis.from_url(cls.redis_url)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    if client.ping():
                        return
                except redis.ConnectionError:
                    time.sleep(0.05)
            cls.tearDownClass()
            raise RuntimeError("Test Redis did not become ready")
        finally:
            client.close()

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop only this test's server and remove its verified temporary directory."""
        if cls.server:
            cls.server.terminate()
            cls.server.wait(timeout=5)
        if cls.temp:
            target = Path(cls.temp.name).resolve()
            assert target.parent == Path(tempfile.gettempdir()).resolve()
            assert target.name.startswith("cinema-channel-tests-")
            cls.temp.cleanup()

    async def asyncSetUp(self) -> None:
        self.token = str(uuid.uuid4())
        self.prefix = f"test:split:{uuid.uuid4()}:"
        self.account_active = True
        self.account_version = 0
        self.identity_failure = False
        self.upstream = httpx.AsyncClient(transport=httpx.MockTransport(self.mock_upstream))
        with (
            patch("app.store.REDIS_URL", self.redis_url),
            patch("app.store.REDIS_PREFIX", self.prefix),
        ):
            self.stores = {channel: ConversationStore(channel, self.upstream) for channel in ("dify", "agent")}
        self.upstream_requests: list[httpx.Request] = []
        self.agent_session_id = ""
        self.agent_memory_suggestion = False
        self.agent_trace_id = ""
        self.revoke_during_stream = False
        app.state.stores = self.stores
        app.state.client = app.state.internal_client = self.upstream
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        await self.stores["dify"].redis.hset(
            "auth:session:" + self.token, mapping={"userId": "2", "role": "USER", "sessionVersion": "0"}
        )
        self.info = {}
        for channel in ("dify", "agent"):
            response = await self.client.get(f"/ai-gateway/{channel}/session", headers={"X-Auth-Token": self.token})
            self.assertEqual(response.status_code, 200)
            self.info[channel] = response.json()
        self.agent_session_id = self.info["agent"]["sessionId"]

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.upstream.aclose()
        store = self.stores["dify"]
        keys = [key async for key in store.redis.scan_iter(self.prefix + "*")]
        if keys:
            await store.redis.delete(*keys)
        await store.redis.delete("auth:session:" + self.token)
        for store in self.stores.values():
            await store.close()

    async def mock_upstream(self, request: httpx.Request) -> httpx.Response:
        """Return deterministic SSE and resolved identities, never contact cloud/Java."""
        if request.url.path.endswith("/auth/resolve"):
            if self.identity_failure:
                return httpx.Response(503, json={"message": "fixture unavailable"})
            token = json.loads(request.content)["token"]
            values = await self.stores["dify"].redis.hgetall("auth:session:" + token)
            if not self.account_active or values.get("sessionVersion") != str(self.account_version):
                return httpx.Response(401, json={"message": "fixture revoked"})
            return httpx.Response(200, json={"userId": 2, "role": "USER", "expiresInSeconds": 60})
        self.upstream_requests.append(request)
        if request.url.path.endswith("/handoff/resolve"):
            return httpx.Response(200, json={"userId": 2, "sessionId": self.agent_session_id, "scope": "cinema:read"})
        if request.url.path == "/ai/live":
            if self.revoke_during_stream:
                owner = self

                class RevokedStream(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield b'data: {"type":"delta","text":"before revocation"}\n\n'
                        owner.account_version += 1
                        await asyncio.sleep(10)
                        yield b'data: {"type":"complete"}\n\n'

                return httpx.Response(200, stream=RevokedStream(), headers={"Content-Type": "text/event-stream"})
            content = 'data: {"type":"delta","text":"AGENT ONLY"}\n\ndata: {"type":"complete"}\n\n'
            if self.agent_trace_id:
                content = (
                    'data: {"type":"trace","trace_id":"invalid"}\n\n'
                    + 'data: ' + json.dumps({"type": "trace", "trace_id": self.agent_trace_id}) + '\n\n'
                    + 'data: {"type":"context","intent":"movies","normalized_question":"电影"}\n\n'
                    + content
                )
            if self.agent_memory_suggestion:
                content = (
                    'data: {"type":"memory_suggestion","content":"喜欢科幻","category":"GENRE","userId":999}\n\n'
                    + content
                )
            return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})
        if request.url.path.endswith("/chat-messages"):
            content = (
                "data: "
                + json.dumps(
                    {
                        "event": "message",
                        "answer": "DIFY ONLY",
                        "conversation_id": "cloud-conversation",
                        "message_id": str(uuid.uuid4()),
                    }
                )
                + '\n\ndata: {"event":"message_end"}\n\n'
            )
            return httpx.Response(200, text=content, headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={"data": {}})

    def headers(self, channel: str) -> dict[str, str]:
        return {
            "X-Auth-Token": self.token,
            "X-AI-Session": self.info[channel]["bindingKey"],
            "X-AI-Conversation": self.info[channel]["sessionId"],
        }

    async def turn(self, channel: str, question: str) -> httpx.Response:
        response = await self.client.post(
            f"/ai-gateway/{channel}/chat",
            headers=self.headers(channel),
            json={
                "sessionId": self.info[channel]["sessionId"],
                "question": question,
                **({"credential": "test-agent-credential"} if channel == "agent" else {}),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "complete"', response.text)
        return response

    async def test_same_account_has_independent_history_and_cloud_context(self) -> None:
        self.assertNotEqual(self.info["dify"]["sessionId"], self.info["agent"]["sessionId"])
        self.assertNotEqual(self.info["dify"]["bindingKey"], self.info["agent"]["bindingKey"])
        await self.turn("dify", "DIFY QUESTION")
        await self.turn("agent", "AGENT QUESTION")
        await self.turn("agent", "AGENT FOLLOWUP")
        for channel in ("dify", "agent"):
            restored = (await self.client.get(f"/ai-gateway/{channel}/session", headers=self.headers(channel))).json()
            self.assertTrue(all(item["mode"] == channel for item in restored["messages"]))
            text = json.dumps(restored["messages"])
            self.assertNotIn("AGENT" if channel == "dify" else "DIFY", text)
        agent_calls = [request for request in self.upstream_requests if request.url.path == "/ai/live"]
        payload = json.loads(agent_calls[-1].content)
        self.assertEqual([item["content"] for item in payload["history"]], ["AGENT QUESTION", "AGENT ONLY"])
        self.assertNotIn("DIFY", str(payload))
        dify_call = next(request for request in self.upstream_requests if request.url.path.endswith("/chat-messages"))
        self.assertEqual(json.loads(dify_call.content)["conversation_id"], "")
        session = await self.stores["agent"].load(self.info["agent"]["sessionId"])
        self.assertEqual(session.conversation_id, "")

    async def test_trace_id_is_persisted_and_not_forwarded_to_browser(self) -> None:
        self.agent_trace_id = str(uuid.uuid4())
        response = await self.turn("agent", "电影")
        self.assertNotIn(self.agent_trace_id, response.text)
        self.assertNotIn('"type": "trace"', response.text)
        session = await self.stores["agent"].load(self.info["agent"]["sessionId"])
        messages = await self.stores["agent"].history(session)
        message = next(item for item in messages if item["role"] == "assistant")
        record = await self.stores["agent"].snapshot(message["id"])
        self.assertEqual(record.context["trace_id"], self.agent_trace_id)
        self.assertEqual(record.context["intent"], "movies")

    async def test_memory_suggestion_is_agent_only_and_has_no_owner_override(self) -> None:
        self.agent_memory_suggestion = True
        response = await self.turn("agent", "请记住科幻偏好")
        self.assertIn('"type": "memory_suggestion"', response.text)
        self.assertNotIn('"userId": 999', response.text)
        response = await self.turn("dify", "购票须知")
        self.assertNotIn("memory_suggestion", response.text)

    async def test_binding_and_feedback_cannot_cross_channels(self) -> None:
        for channel, other in (("dify", "agent"), ("agent", "dify")):
            response = await self.client.post(f"/ai-gateway/{channel}/reset", headers=self.headers(other))
            self.assertEqual(response.status_code, 401)
        await self.turn("dify", "DIFY QUESTION")
        restored = (await self.client.get("/ai-gateway/dify/session", headers=self.headers("dify"))).json()
        message_id = restored["messages"][-1]["messageId"]
        response = await self.client.post(
            "/ai-gateway/agent/feedback",
            headers=self.headers("agent"),
            json={"messageId": message_id, "rating": "like"},
        )
        self.assertEqual(response.status_code, 410)
        self.assertFalse(any(request.url.path.endswith("/feedbacks") for request in self.upstream_requests))

    async def test_reset_one_channel_preserves_the_other(self) -> None:
        await self.turn("dify", "KEEP THIS")
        await self.turn("agent", "RESET THIS")
        result = await self.client.post("/ai-gateway/agent/reset", headers=self.headers("agent"))
        self.assertEqual(result.status_code, 200)
        self.assertNotEqual(result.json()["sessionId"], self.info["agent"]["sessionId"])
        dify = (await self.client.get("/ai-gateway/dify/session", headers=self.headers("dify"))).json()
        self.assertEqual(dify["sessionId"], self.info["dify"]["sessionId"])
        self.assertEqual(dify["messages"][0]["content"], "KEEP THIS")
        agent = (await self.client.get("/ai-gateway/agent/session", headers={"X-Auth-Token": self.token})).json()
        self.assertEqual(agent["messages"], [])

    async def test_parallel_leases_and_stop_are_independent(self) -> None:
        sessions = {
            channel: await store.load(self.info[channel]["sessionId"]) for channel, store in self.stores.items()
        }
        leases = await asyncio.gather(*(store.acquire(sessions[channel]) for channel, store in self.stores.items()))
        response = await self.client.post("/ai-gateway/agent/stop", headers=self.headers("agent"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(await self.stores["agent"].cancelled(sessions["agent"]))
        self.assertFalse(await self.stores["dify"].cancelled(sessions["dify"]))
        self.assertTrue(await self.stores["dify"].busy(sessions["dify"]))
        self.assertEqual(self.upstream_requests, [])
        for (channel, store), lease in zip(self.stores.items(), leases, strict=True):
            await store.release(sessions[channel], lease)

    async def test_dify_and_agent_feedback_use_their_own_provider(self) -> None:
        for channel in ("dify", "agent"):
            await self.turn(channel, channel + " question")
            restored = (await self.client.get(f"/ai-gateway/{channel}/session", headers=self.headers(channel))).json()
            response = await self.client.post(
                f"/ai-gateway/{channel}/feedback",
                headers=self.headers(channel),
                json={"messageId": restored["messages"][-1]["messageId"], "rating": "like"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["providerSync"], "SYNCED" if channel == "dify" else "NOT_APPLICABLE")
        cloud_feedback = [request for request in self.upstream_requests if request.url.path.endswith("/feedbacks")]
        self.assertEqual(len(cloud_feedback), 1)
        self.assertEqual(json.loads(cloud_feedback[0].content)["user"], "cinema-" + self.info["dify"]["sessionId"])

    async def test_provider_is_selected_by_route_and_agent_requires_login(self) -> None:
        response = await self.client.get("/ai-gateway/agent/session")
        self.assertEqual(response.status_code, 401)
        response = await self.client.get("/ai-gateway/dify/session")
        self.assertEqual(response.status_code, 200)
        response = await self.client.post(
            "/ai-gateway/dify/chat",
            headers=self.headers("dify"),
            json={"sessionId": self.info["dify"]["sessionId"], "question": "test", "credential": "agent-secret"},
        )
        self.assertEqual(response.status_code, 400)
        response = await self.client.post(
            "/ai-gateway/agent/chat",
            headers=self.headers("agent"),
            json={"sessionId": self.info["agent"]["sessionId"], "question": "test", "mode": "dify"},
        )
        self.assertEqual(response.status_code, 401)
        response = await self.client.get("/ai-gateway/session", headers={"X-Auth-Token": self.token})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.upstream_requests, [])

    async def test_old_mixed_history_is_not_imported(self) -> None:
        redis_client = self.stores["dify"].redis
        legacy_chat = str(uuid.uuid4())
        await redis_client.set(self.prefix + "user:2:active", legacy_chat)
        await redis_client.hset(
            self.prefix + "session:" + legacy_chat, mapping={"chat_id": legacy_chat, "owner_id": "2"}
        )
        await redis_client.rpush(self.prefix + "history:" + legacy_chat, '{"content":"OLD MIXED HISTORY"}')
        for channel in ("dify", "agent"):
            restored = (await self.client.get(f"/ai-gateway/{channel}/session", headers=self.headers(channel))).json()
            self.assertEqual(restored["messages"], [])
            self.assertNotEqual(restored["sessionId"], legacy_chat)

    async def test_revoked_tokens_cannot_read_reset_chat_or_submit_feedback(self) -> None:
        """Leftover Redis hashes grant no access after authoritative revocation."""
        self.account_version += 1
        self.assertTrue(await self.stores["dify"].redis.exists("auth:session:" + self.token))
        for channel in ("dify", "agent"):
            requests = [
                self.client.get(f"/ai-gateway/{channel}/session", headers=self.headers(channel)),
                self.client.post(f"/ai-gateway/{channel}/reset", headers=self.headers(channel)),
                self.client.post(
                    f"/ai-gateway/{channel}/chat",
                    headers=self.headers(channel),
                    json={
                        "sessionId": self.info[channel]["sessionId"],
                        "question": "private query",
                        "credential": "old-credential",
                    },
                ),
                self.client.post(
                    f"/ai-gateway/{channel}/feedback",
                    headers=self.headers(channel),
                    json={"messageId": str(uuid.uuid4()), "rating": "like"},
                ),
            ]
            for response in await asyncio.gather(*requests):
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers.get("X-Auth-Expired"), "1")
        self.assertEqual(self.upstream_requests, [])

    async def test_account_revocation_interrupts_an_active_answer(self) -> None:
        self.revoke_during_stream = True
        response = await self.client.post(
            "/ai-gateway/agent/chat",
            headers=self.headers("agent"),
            json={
                "sessionId": self.info["agent"]["sessionId"],
                "question": "slow query",
                "credential": "old-credential",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"code": "auth_expired"', response.text)
        self.assertNotIn('"type": "complete"', response.text)
        session = await self.stores["agent"].load(self.info["agent"]["sessionId"])
        self.assertFalse(await self.stores["agent"].busy(session))

    async def test_disabled_accounts_are_rejected_and_java_failure_never_falls_back(self) -> None:
        self.account_active = False
        response = await self.client.get("/ai-gateway/agent/session", headers=self.headers("agent"))
        self.assertEqual(response.status_code, 401)
        self.account_active = True
        self.identity_failure = True
        for channel in ("dify", "agent"):
            response = await self.client.get(f"/ai-gateway/{channel}/session", headers=self.headers(channel))
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("X-Auth-Expired", response.headers)
        self.assertEqual(self.upstream_requests, [])

    async def test_store_rejects_accidental_cross_provider_write(self) -> None:
        record = Snapshot(session_id=self.info["agent"]["sessionId"], provider="AGENT", question="private")
        with self.assertRaises(ValueError):
            await self.stores["dify"].save_snapshot(record)


if __name__ == "__main__":
    unittest.main()
