"""Exercise the real Streamable HTTP MCP transport against a mocked Java API."""

import asyncio
import socket
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, patch

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.failures import CinemaQueryError, describe_failure
from app.intent import understand
from app.java_client import JavaApiClient
from app.mcp_client import QUERY_TOOLS, CinemaMcpClient
from app.mcp_server import create_app


class CinemaMcpTests(unittest.IsolatedAsyncioTestCase):
    """Verify protocol discovery, Java mapping, isolation, errors and Agent routing."""

    async def asyncSetUp(self) -> None:
        self.requests: list[httpx.Request] = []
        self.api = JavaApiClient()
        await self.api.aclose()
        self.api.client = httpx.AsyncClient(base_url="http://java.test", transport=httpx.MockTransport(self.upstream))
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.url = f"http://127.0.0.1:{self.listener.getsockname()[1]}/mcp"
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.api, "test-token"), log_level="critical"))
        self.task = asyncio.create_task(self.server.serve(sockets=[self.listener]))
        async with asyncio.timeout(5):
            while not self.server.started:
                if self.task.done():
                    await self.task
                await asyncio.sleep(0.01)
        self.client = CinemaMcpClient(self.url, "test-token")

    async def asyncTearDown(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.task, timeout=5)
        self.listener.close()

    async def upstream(self, request: httpx.Request) -> httpx.Response:
        """Simulate business data and ownership checks without live credentials."""
        self.requests.append(request)
        path = request.url.path
        if path == "/internal/movies/query":
            scope = request.url.params.get("movieScope", "catalog")
            day = request.url.params.get("screeningDate", "")
            item = {"id": 3, "title": "测试电影", "genre": "科幻", "duration": 120}
            if scope == "scheduled":
                item.update(
                    screening_count=1,
                    screenings=[
                        {
                            "id": 12,
                            "start_time": (day or "2026-10-08") + "T18:00:00",
                            "cinema_name": "测试影院",
                            "hall_name": "测试厅",
                            "price": 30,
                        }
                    ],
                    screenings_truncated=False,
                )
            return httpx.Response(
                200,
                json={
                    "movie_scope": scope,
                    "screening_date": day,
                    "from_date": day or "2026-10-08",
                    "time_zone": "Asia/Shanghai",
                    "items": [item],
                    "showing_only": request.url.params.get("showingOnly") == "true",
                    "total": 1,
                    "page": int(request.url.params.get("page", "1")),
                    "page_size": 20,
                    "has_more": False,
                },
            )
        if path == "/internal/movies":
            if request.url.params.get("query") == "timeout":
                raise httpx.ReadTimeout("SECRET upstream details", request=request)
            return httpx.Response(200, json=[{"id": 3, "title": "测试电影", "genre": "科幻"}])
        if path == "/internal/screenings":
            day = request.url.params.get("screeningDate", "2026-10-08")
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 12,
                        "title": "测试电影",
                        "start_time": day + "T18:00:00",
                        "cinema_name": "测试影院",
                        "hall_name": "测试厅",
                        "price": 30,
                    }
                ],
            )
        if path.startswith("/api/screenings/"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": [
                        {"id": 1, "seat_code": "1-1", "booking_status": "AVAILABLE"},
                        {"id": 2, "seat_code": "1-2", "booking_status": "LOCKED"},
                        {"id": 3, "seat_code": "1-3", "booking_status": "SOLD"},
                    ],
                },
            )
        if path.startswith("/internal/orders/"):
            await asyncio.sleep(0.01)
            if path.endswith("OOTHER1") and request.url.params.get("userId") != "9":
                return httpx.Response(404, json={"detail": "SECRET other user data"})
            return httpx.Response(
                200,
                json={
                    "order_no": path.rsplit("/", 1)[1],
                    "user_id": int(request.url.params["userId"]),
                    "status": "ISSUED",
                },
            )
        if path == "/internal/refund-policy":
            return httpx.Response(200, json={"version": "test", "policy": "开场前可退"})
        if path == "/internal/knowledge/search":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    @asynccontextmanager
    async def session(self, user: str | None = "2") -> AsyncIterator[ClientSession]:
        """Open a standard SDK session to test the exposed contract directly."""
        headers = {"X-Internal-Token": "test-token"}
        if user is not None:
            headers["X-AI-User-ID"] = user
        async with (
            httpx.AsyncClient(headers=headers, trust_env=False) as http_client,
            streamable_http_client(self.url, http_client=http_client) as (reader, writer, _),
            ClientSession(reader, writer) as session,
        ):
            await session.initialize()
            yield session

    async def test_discovery_has_only_four_read_only_tools(self) -> None:
        async with self.session() as session:
            tools = (await session.list_tools()).tools
        self.assertEqual({tool.name for tool in tools}, QUERY_TOOLS)
        for tool in tools:
            self.assertTrue(tool.annotations.readOnlyHint)
            self.assertFalse(tool.annotations.destructiveHint)
            self.assertIsNotNone(tool.outputSchema)
        order = next(tool for tool in tools if tool.name == "query_order")
        self.assertEqual(set(order.inputSchema["properties"]), {"order_no"})

    async def test_movies_and_screening_filters(self) -> None:
        movies = await self.client.call_tool("search_movies", {"query": "科幻"}, user_id=2)
        self.assertEqual(movies[0]["title"], "测试电影")
        await self.client.call_tool(
            "search_screenings",
            {
                "movie_id": 3,
                "cinema_id": 7,
                "movie_query": "测试",
                "cinema_query": "影院",
                "screening_date": "2026-10-02",
            },
            user_id=2,
        )
        self.assertEqual(
            dict(self.requests[-1].url.params),
            {
                "movieId": "3",
                "cinemaId": "7",
                "movieQuery": "测试",
                "cinemaQuery": "影院",
                "screeningDate": "2026-10-02",
            },
        )

    async def test_seats_unwrap_live_booking_status(self) -> None:
        seats = await self.client.call_tool("query_seats", {"screening_id": 12}, user_id=2)
        self.assertEqual([seat["booking_status"] for seat in seats], ["AVAILABLE", "LOCKED", "SOLD"])
        self.assertEqual(self.requests[-1].url.path, "/api/screenings/12/seats")

    async def test_movie_scopes_and_scheduled_details_cross_real_mcp_transport(self) -> None:
        result = await self.client.call_tool(
            "search_movies",
            {
                "movie_scope": "scheduled",
                "screening_date": "2026-10-08",
                "cinema_query": "测试影院",
                "showing_only": True,
                "page": 2,
            },
            user_id=2,
        )
        self.assertEqual(result["movie_scope"], "scheduled")
        self.assertEqual(result["page"], 2)
        params = self.requests[-1].url.params
        self.assertEqual(self.requests[-1].url.path, "/internal/movies/query")
        self.assertEqual(params["showingOnly"], "true")
        self.assertEqual(params["screeningDate"], "2026-10-08")
        await self.client.call_tool(
            "search_screenings", {"screening_date": "2026-10-08", "query_scope": "scheduled"}, user_id=2
        )
        self.assertEqual(self.requests[-1].url.params["queryScope"], "scheduled")
        count = len(self.requests)
        with self.assertRaises(CinemaQueryError):
            await self.client.call_tool("search_movies", {"movie_scope": "wrong"}, user_id=2)
        self.assertEqual(len(self.requests), count)

    async def test_agent_schedule_listing_keeps_date_and_does_not_recall_memory(self) -> None:
        with patch("app.model_config.create_model", return_value=None):
            from app.main import Assistant, LiveChatRequest
        with patch("app.main.create_model", return_value=None):
            assistant = Assistant()
        await assistant.client.aclose()
        assistant.client = self.api
        assistant.mcp = self.client

        assistant.memory.recall = AsyncMock(side_effect=AssertionError("Factual lists do not use memory retrieval"))
        with patch("app.intent.beijing_today", return_value=date(2026, 10, 8)):
            first = [
                packet
                async for packet in assistant.live(
                    LiveChatRequest(user_id=2, session_id="listing", question="今天在排期的电影有哪些")
                )
            ]
            second = [
                packet
                async for packet in assistant.live(
                    LiveChatRequest(user_id=2, session_id="listing", question="今天在排期的电影有哪些")
                )
            ]
        self.assertEqual(first, second)
        self.assertTrue(any("有效排期" in packet for packet in first))
        self.assertTrue(any('"search_movies"' in packet for packet in first))
        self.assertEqual(self.requests[-1].url.params["screeningDate"], "2026-10-08")
        assistant.memory.recall.assert_not_awaited()

    async def test_agent_screening_answers_preserve_schedule_and_booking_scopes(self) -> None:
        with patch("app.model_config.create_model", return_value=None):
            from app.main import Assistant, ChatRequest, LiveChatRequest
        with patch("app.main.create_model", return_value=None):
            assistant = Assistant()
        await assistant.client.aclose()
        assistant.client = self.api
        assistant.mcp = self.client
        assistant.memory.recall = AsyncMock(side_effect=AssertionError("No memory for screening facts"))
        with patch("app.intent.beijing_today", return_value=date(2026, 10, 8)):
            response = await assistant.chat(ChatRequest(user_id=2, session_id="screenings", question="今天有哪些场次"))
            self.assertIn("有效排期", response.answer)
            self.assertIn("2026-10-08T18:00:00", response.answer)
            self.assertEqual(self.requests[-1].url.params["queryScope"], "scheduled")
            packets = [
                packet
                async for packet in assistant.live(
                    LiveChatRequest(user_id=2, session_id="bookable", question="今天哪些场次可以买票")
                )
            ]
        self.assertTrue(any("当前可订购" in packet for packet in packets))
        self.assertTrue(any('"complete"' in packet for packet in packets))
        self.assertNotIn("queryScope", self.requests[-1].url.params)
        assistant.memory.recall.assert_not_awaited()

    async def test_agent_rejects_catalogue_rows_for_schedule_query(self) -> None:
        with patch("app.model_config.create_model", return_value=None):
            from app.main import Assistant, LiveChatRequest
        with patch("app.main.create_model", return_value=None):
            assistant = Assistant()
        await assistant.client.aclose()
        assistant.mcp = AsyncMock()
        assistant.mcp.call_tool.return_value = [{"id": 3, "title": "缺少排期依据"}]
        with patch("app.intent.beijing_today", return_value=date(2026, 10, 8)):
            packets = [
                packet
                async for packet in assistant.live(
                    LiveChatRequest(user_id=2, session_id="mismatch", question="今天在排期的电影有哪些")
                )
            ]
        self.assertTrue(any("query_contract_mismatch" in packet for packet in packets))
        self.assertFalse(any('"delta"' in packet for packet in packets))

    async def test_concurrent_order_identity_isolation(self) -> None:
        orders = await asyncio.gather(
            *(self.client.call_tool("query_order", {"order_no": "OTEST12"}, user_id=user) for user in (2, 9, 15))
        )
        self.assertEqual([order["user_id"] for order in orders], [2, 9, 15])

    async def test_order_denies_missing_identity_and_cross_user_access(self) -> None:
        async with self.session(None) as session:
            result = await session.call_tool("query_order", {"order_no": "OTEST12"})
        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["error"]["code"], "business_auth_failed")
        self.assertEqual(self.requests, [])
        with self.assertRaises(CinemaQueryError) as failure:
            await self.client.call_tool("query_order", {"order_no": "OOTHER1"}, user_id=2)
        self.assertEqual(failure.exception.code, "data_not_found")
        self.assertNotIn("SECRET", str(failure.exception))

    async def test_tool_arguments_cannot_override_identity(self) -> None:
        with self.assertRaises(ValueError):
            await self.client.call_tool("query_order", {"order_no": "OTEST12", "user_id": 9}, user_id=2)
        async with self.session("2") as session:
            # A third-party MCP client may send an unknown field; it cannot alter the trusted header.
            result = await session.call_tool("query_order", {"order_no": "OTEST12", "user_id": 9})
        self.assertEqual(result.structuredContent["data"]["user_id"], 2)

    async def test_invalid_parameters_never_reach_java(self) -> None:
        async with self.session() as session:
            for name, arguments in (
                ("query_seats", {"screening_id": -1}),
                ("query_seats", {"screening_id": "12"}),
                ("query_order", {"order_no": "../../secret"}),
                ("search_screenings", {"screening_date": "2026-02-30"}),
            ):
                result = await session.call_tool(name, arguments)
                self.assertTrue(result.isError)
        self.assertEqual(self.requests, [])

    async def test_auth_host_and_origin_validation(self) -> None:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(self.url, json={})
            self.assertEqual(response.status_code, 401)
            response = await client.post(self.url, headers={"X-Internal-Token": "wrong"}, json={})
            self.assertEqual(response.status_code, 401)
            headers = {"X-Internal-Token": "test-token", "Content-Type": "application/json"}
            response = await client.post(self.url, headers={**headers, "Host": "evil.test"}, json={})
            self.assertEqual(response.status_code, 421)
            response = await client.post(self.url, headers={**headers, "Origin": "https://evil.test"}, json={})
            self.assertEqual(response.status_code, 403)

    async def test_upstream_timeout_is_safe_mcp_error(self) -> None:
        async with self.session() as session:
            result = await session.call_tool("search_movies", {"query": "timeout"})
        self.assertTrue(result.isError)
        self.assertEqual(result.structuredContent["error"]["code"], "query_timeout")
        self.assertNotIn("SECRET", str(result))
        with self.assertRaises(CinemaQueryError) as failure:
            await self.client.call_tool("search_movies", {"query": "timeout"}, user_id=2)
        self.assertEqual(describe_failure(failure.exception, "test")[0], "query_timeout")

    async def test_seat_intent_requires_a_user_supplied_screening_id(self) -> None:
        plan = await understand(None, "查询场次 12 的座位", [])
        self.assertEqual(plan["intent"], "seats")
        self.assertEqual(plan["entities"]["screening_id"], 12)
        self.assertFalse(plan["clarification"])
        plan = await understand(None, "还有哪些空座？", [])
        self.assertTrue(plan["clarification"])
        plan = await understand(None, "场次12", [{"role": "user", "content": "还有哪些空座？"}])
        self.assertEqual(plan["intent"], "seats")
        self.assertEqual(plan["entities"]["screening_id"], 12)
        self.assertFalse(plan["clarification"])

    async def test_mcp_transport_auth_failure_keeps_error_category(self) -> None:
        bad_client = CinemaMcpClient(self.url, "wrong-token")
        with self.assertRaises(Exception) as failure:
            await bad_client.call_tool("search_movies", {}, user_id=2)
        self.assertEqual(describe_failure(failure.exception, "test")[0], "business_auth_failed")

    async def test_agent_chat_live_and_refund_use_mcp(self) -> None:
        # Patch before importing main: its module-level Assistant must not read real model keys.
        with patch("app.model_config.create_model", return_value=None):
            from app.main import Assistant, ChatRequest, LiveChatRequest, create_tools

        with patch("app.main.create_model", return_value=None):
            assistant = Assistant()
        await assistant.client.aclose()
        assistant.client = self.api
        assistant.mcp = self.client
        assistant.tools = create_tools(self.api, assistant.retriever)
        self.assertTrue(QUERY_TOOLS.isdisjoint(assistant.tools))
        response = await assistant.chat(ChatRequest(user_id=2, session_id="test", question="查询场次12的座位"))
        self.assertEqual(response.intent, "seats")
        self.assertEqual(response.tool_calls, ["query_seats"])
        self.assertIn("可选 1 个", response.answer)
        response = await assistant.chat(ChatRequest(user_id=2, session_id="test", question="OTEST12 能退票吗"))
        self.assertEqual(response.data["order"]["user_id"], 2)
        packets = [
            packet
            async for packet in assistant.live(LiveChatRequest(user_id=9, session_id="live", question="OTEST12 的状态"))
        ]
        self.assertTrue(any('"query_order"' in packet for packet in packets))
        self.assertTrue(any('"complete"' in packet for packet in packets))
        self.assertEqual(self.requests[-1].url.params["userId"], "9")


if __name__ == "__main__":
    unittest.main()
