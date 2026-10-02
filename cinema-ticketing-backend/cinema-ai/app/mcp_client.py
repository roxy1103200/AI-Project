"""Official MCP client used by the Agent's fixed read-only query workflow."""

import asyncio
import os
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.failures import CinemaQueryError

QUERY_TOOLS = frozenset({"search_movies", "search_screenings", "query_seats", "query_order"})


class CinemaMcpClient:
    """Bind each MCP session to the authenticated caller, never model arguments."""

    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = url or os.getenv("CINEMA_MCP_URL", "http://127.0.0.1:8020/mcp")
        self.token = token or os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")

    async def call_tool(self, name: str, arguments: dict[str, Any], *, user_id: int) -> Any:
        """Initialize MCP, invoke an allowed tool, and unwrap its business data.

        每轮独立连接，避免并发请求共用可变身份头。用户 ID 只来自网关已校验的请求。
        不把 user_id 放入 MCP 工具参数；模型无法通过订单号或历史消息切换订单归属。
        """
        if name not in QUERY_TOOLS or user_id <= 0:
            raise ValueError("Invalid cinema tool or authenticated user")
        if "user_id" in arguments or "userId" in arguments:
            raise ValueError("Identity must not be supplied as a tool argument")
        async with asyncio.timeout(20):
            async with httpx.AsyncClient(
                headers={"X-Internal-Token": self.token, "X-AI-User-ID": str(user_id)},
                timeout=15.0,
                trust_env=False,
                follow_redirects=False,
            ) as http_client:
                async with streamable_http_client(self.url, http_client=http_client) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        result = await session.call_tool(name, arguments)
        payload = result.structuredContent
        if not isinstance(payload, dict):
            raise CinemaQueryError("business_unavailable", "业务查询服务暂时不可用，请稍后重试。")
        error = payload.get("error")
        if error:
            raise CinemaQueryError(error["code"], error["message"])
        if result.isError or "data" not in payload:
            raise CinemaQueryError("business_unavailable", "业务查询服务暂时不可用，请稍后重试。")
        return payload["data"]
