"""Cinema read-only MCP Server, served over private Streamable HTTP at /mcp."""

import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.failures import describe_failure
from app.java_client import JavaApiClient

PositiveId = Annotated[int, Field(gt=0, strict=True)]
Keyword = Annotated[str, Field(max_length=120)]
OrderNumber = Annotated[str, Field(pattern=r"^[Oo][A-Za-z0-9]{5,63}$")]
QueryResult = Annotated[CallToolResult, dict[str, Any]]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def tool_result(payload: dict[str, Any]) -> CallToolResult:
    """Provide both standard text and structured MCP output; failures set isError."""
    return CallToolResult(
        isError="error" in payload,
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structuredContent=payload,
    )


class InternalTokenMiddleware:
    """Authenticate every HTTP request before it enters the MCP protocol handler."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            # 健康检查不返回业务数据；所有 MCP 方法（含 initialize/list_tools）均需凭证。
            request = Request(scope)
            if request.url.path != "/health" and not hmac.compare_digest(
                request.headers.get("X-Internal-Token", ""), self.token
            ):
                await JSONResponse({"detail": "Invalid internal service token"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(client: JavaApiClient | None = None, token: str | None = None) -> ASGIApp:
    """Build a stateless MCP server with injectable upstream transport for tests."""
    api = client or JavaApiClient()
    service_token = token or os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")
    hosts = os.getenv("CINEMA_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,[::1]:*,cinema-mcp:*")
    mcp = FastMCP(
        "Cinema Query MCP",
        log_level="WARNING",
        instructions="只读电影、场次、座位及本人订单查询；禁止下单、支付、锁座或退款。",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host.strip() for host in hosts.split(",") if host.strip()],
            allowed_origins=[],
        ),
    )

    async def fetch(path: str, params: dict[str, Any] | None = None, *, public: bool = False) -> CallToolResult:
        """Return a stable envelope and keep upstream exceptions out of MCP output."""
        try:
            data = await api.get(path, params)
            # 座位复用 Java 的实时座位服务，包含 Redis 锁定状态；公共接口带 ApiResponse 外壳。
            if public:
                if data.get("code") != 0:
                    return tool_result({"error": {"code": "business_unavailable", "message": "座位查询暂时不可用。"}})
                data = data["data"]
            return tool_result({"data": data})
        except Exception as exception:
            code, message = describe_failure(exception, "mcp_java_query")
            return tool_result({"error": {"code": code, "message": message}})

    @mcp.tool(annotations=READ_ONLY)
    async def search_movies(query: Keyword = "") -> QueryResult:
        """查询可用电影，query 可填写片名、类型、演员或关键词；留空返回可用影片。"""
        return await fetch("/internal/movies", {"query": query})

    @mcp.tool(annotations=READ_ONLY)
    async def search_screenings(
        movie_id: PositiveId | None = None,
        cinema_id: PositiveId | None = None,
        movie_query: Keyword = "",
        cinema_query: Keyword = "",
        screening_date: date | None = None,
    ) -> QueryResult:
        """按电影/影院 ID 或关键词、北京时间日期 YYYY-MM-DD 查询可订购场次。"""
        params = {
            "movieId": movie_id,
            "cinemaId": cinema_id,
            "movieQuery": movie_query,
            "cinemaQuery": cinema_query,
            "screeningDate": screening_date.isoformat() if screening_date else None,
        }
        return await fetch("/internal/screenings", {key: value for key, value in params.items() if value is not None})

    @mcp.tool(annotations=READ_ONLY)
    async def query_seats(screening_id: PositiveId) -> QueryResult:
        """查询指定场次的实时座位；booking_status 区分 AVAILABLE、LOCKED、SOLD 等状态。"""
        return await fetch(f"/api/screenings/{screening_id}/seats", public=True)

    @mcp.tool(annotations=READ_ONLY)
    async def query_order(order_no: OrderNumber, ctx: Context) -> QueryResult:
        """查询已认证用户本人的订单和退票资格；用户身份由服务端请求头绑定。"""
        # Context 由 SDK 注入，不出现在 tools/list 的输入 schema 中。
        # 服务凭证代表可信内部调用者；最终订单归属仍由 Java 的 user_id 条件核验。
        request = ctx.request_context.request
        user = request.headers.get("X-AI-User-ID", "") if request else ""
        if not user.isascii() or not user.isdecimal() or len(user) > 19 or int(user) <= 0:
            return tool_result({"error": {"code": "business_auth_failed", "message": "订单查询缺少有效的登录身份。"}})
        return await fetch(f"/internal/orders/{order_no}", {"userId": int(user)})

    http_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        # Mounted MCP apps require their session manager to run in the parent lifespan.
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await api.aclose()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "UP", "service": "cinema-mcp"})

    server = Starlette(routes=[Route("/health", health), Mount("/", app=http_app)], lifespan=lifespan)
    return InternalTokenMiddleware(server, service_token)


app = create_app()
