"""Cinema read-only MCP Server, served over private Streamable HTTP at /mcp."""

# 导入当前步骤使用的模块或类型。
# isort: off
import hmac
# 导入当前步骤使用的模块或类型。
import json
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
from collections.abc import AsyncIterator
# 导入当前步骤使用的模块或类型。
from contextlib import asynccontextmanager
# 导入当前步骤使用的模块或类型。
from datetime import date
# 导入当前步骤使用的模块或类型。
from typing import Annotated, Any, Literal

# 导入当前步骤使用的模块或类型。
from mcp.server.fastmcp import Context, FastMCP
# 导入当前步骤使用的模块或类型。
from mcp.server.transport_security import TransportSecuritySettings
# 导入当前步骤使用的模块或类型。
from mcp.types import CallToolResult, TextContent, ToolAnnotations
# 导入当前步骤使用的模块或类型。
from pydantic import Field
# 导入当前步骤使用的模块或类型。
from starlette.applications import Starlette
# 导入当前步骤使用的模块或类型。
from starlette.requests import Request
# 导入当前步骤使用的模块或类型。
from starlette.responses import JSONResponse
# 导入当前步骤使用的模块或类型。
from starlette.routing import Mount, Route
# 导入当前步骤使用的模块或类型。
from starlette.types import ASGIApp, Receive, Scope, Send

# 导入当前步骤使用的模块或类型。
from app.failures import describe_failure
# 导入当前步骤使用的模块或类型。
from app.java_client import JavaApiClient
# isort: on

# 为 `PositiveId` 保存当前步骤所需的值。
PositiveId = Annotated[int, Field(gt=0, strict=True)]
# 为 `Keyword` 保存当前步骤所需的值。
Keyword = Annotated[str, Field(max_length=120)]
# 为 `OrderNumber` 保存当前步骤所需的值。
OrderNumber = Annotated[str, Field(pattern=r"^[Oo][A-Za-z0-9]{5,63}$")]
# 为 `QueryResult` 保存当前步骤所需的值。
QueryResult = Annotated[CallToolResult, dict[str, Any]]
# 为 `READ_ONLY` 保存当前步骤所需的值。
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


# 定义函数 `tool_result`：Provide both standard text and structured MCP output; failures set isError.
def tool_result(payload: dict[str, Any]) -> CallToolResult:
    """Provide both standard text and structured MCP output; failures set isError."""
    # 将当前计算结果返回给调用方。
    return CallToolResult(
        # 为 `isError` 保存当前步骤所需的值。
        isError="error" in payload,
        # 为 `content` 保存当前步骤所需的值。
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        # 为 `structuredContent` 保存当前步骤所需的值。
        structuredContent=payload,
    )


# 定义类 `InternalTokenMiddleware`：Authenticate every HTTP request before it enters the MCP protocol handler.
class InternalTokenMiddleware:
    """Authenticate every HTTP request before it enters the MCP protocol handler."""

    # 执行当前步骤中的业务处理表达式。
    def __init__(self, app: ASGIApp, token: str) -> None:
        # 为 `self.app` 保存当前步骤所需的值。
        self.app = app
        # 为 `self.token` 保存当前步骤所需的值。
        self.token = token

    # 执行当前步骤中的业务处理表达式。
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 检查 `if scope["type"] == "http"`，据此选择当前处理分支。
        if scope["type"] == "http":
            # 健康检查不返回业务数据；所有 MCP 方法（含 initialize/list_tools）均需凭证。
            # 为 `request` 保存当前步骤所需的值。
            request = Request(scope)
            # 检查 `if request.url.path != "/health" and not hmac.compare_digest(`，据此选择当前处理分支。
            if request.url.path != "/health" and not hmac.compare_digest(
                # 执行当前步骤中的业务处理表达式。
                request.headers.get("X-Internal-Token", ""), self.token
            # 执行当前步骤中的业务处理表达式。
            ):
                # 执行当前步骤中的业务处理表达式。
                await JSONResponse({"detail": "Invalid internal service token"}, status_code=401)(scope, receive, send)
                # 将当前计算结果返回给调用方。
                return
        # 执行当前步骤中的业务处理表达式。
        await self.app(scope, receive, send)


# 定义函数 `create_app`：Build a stateless MCP server with injectable upstream transport for tests.
def create_app(client: JavaApiClient | None = None, token: str | None = None) -> ASGIApp:
    """Build a stateless MCP server with injectable upstream transport for tests."""
    # 为 `api` 保存当前步骤所需的值。
    api = client or JavaApiClient()
    # 为 `service_token` 保存当前步骤所需的值。
    service_token = token or os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")
    # 为 `hosts` 保存当前步骤所需的值。
    hosts = os.getenv("CINEMA_MCP_ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,[::1]:*,cinema-mcp:*")
    # 为 `mcp` 保存当前步骤所需的值。
    mcp = FastMCP(
        # 补充当前表达式的 `"Cinema Query MCP"` 参数或元素。
        "Cinema Query MCP",
        # 为 `log_level` 保存当前步骤所需的值。
        log_level="WARNING",
        # 为 `instructions` 保存当前步骤所需的值。
        instructions="只读电影、场次、座位及本人订单查询；禁止下单、支付、锁座或退款。",
        # 为 `stateless_http` 保存当前步骤所需的值。
        stateless_http=True,
        # 为 `json_response` 保存当前步骤所需的值。
        json_response=True,
        # 为 `transport_security` 保存当前步骤所需的值。
        transport_security=TransportSecuritySettings(
            # 为 `enable_dns_rebinding_protection` 保存当前步骤所需的值。
            enable_dns_rebinding_protection=True,
            # 为 `allowed_hosts` 保存当前步骤所需的值。
            allowed_hosts=[host.strip() for host in hosts.split(",") if host.strip()],
            # 为 `allowed_origins` 保存当前步骤所需的值。
            allowed_origins=[],
        ),
    )

    # 定义异步函数 `fetch`：Return a stable envelope and keep upstream exceptions out of MCP output.
    async def fetch(path: str, params: dict[str, Any] | None = None, *, public: bool = False) -> CallToolResult:
        """Return a stable envelope and keep upstream exceptions out of MCP output."""
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `data` 保存当前步骤所需的值。
            data = await api.get(path, params)
            # 座位复用 Java 的实时座位服务，包含 Redis 锁定状态；公共接口带 ApiResponse 外壳。
            # 检查 `if public`，据此选择当前处理分支。
            if public:
                # 检查 `if data.get("code") != 0`，据此选择当前处理分支。
                if data.get("code") != 0:
                    # 将当前计算结果返回给调用方。
                    return tool_result({"error": {"code": "business_unavailable", "message": "座位查询暂时不可用。"}})
                # 为 `data` 保存当前步骤所需的值。
                data = data["data"]
            # 将当前计算结果返回给调用方。
            return tool_result({"data": data})
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exception:
            # 执行当前步骤中的业务处理表达式。
            code, message = describe_failure(exception, "mcp_java_query")
            # 将当前计算结果返回给调用方。
            return tool_result({"error": {"code": code, "message": message}})

    # 为紧随其后的函数或类设置装饰行为。
    @mcp.tool(annotations=READ_ONLY)
    # 定义异步函数 `search_movies`：查询影片资料 catalog、上映中 showing、真实已排期 scheduled。
    async def search_movies(
        # 设置当前结构中的 `query` 字段。
        query: Keyword = "",
        # 设置当前结构中的 `movie_scope` 字段。
        movie_scope: Literal["catalog", "showing", "scheduled"] = "catalog",
        # 设置当前结构中的 `screening_date` 字段。
        screening_date: date | None = None,
        # 设置当前结构中的 `cinema_query` 字段。
        cinema_query: Keyword = "",
        # 设置当前结构中的 `showing_only` 字段。
        showing_only: bool = False,
        # 设置当前结构中的 `page` 字段。
        page: Annotated[int, Field(ge=1, le=10000)] = 1,
        # 设置当前结构中的 `page_size` 字段。
        page_size: Annotated[int, Field(ge=1, le=50)] = 20,
    # 执行当前步骤中的业务处理表达式。
    ) -> QueryResult:
        """查询影片资料 catalog、上映中 showing、真实已排期 scheduled。

        上映不代表有场次。scheduled 按北京时间日期查询，日期留空表示今天及以后，
        包含已开场和未开售的有效排期；showing_only=true 额外要求影片已上映。
        排期结果按电影分页去重并包含实际场次摘要，不能用 catalog 代替排期。
        """
        # 检查 `if (`，据此选择当前处理分支。
        if (
            # 为 `movie_scope` 保存当前步骤所需的值。
            movie_scope == "catalog"
            # 执行当前步骤中的业务处理表达式。
            and not screening_date
            # 执行当前步骤中的业务处理表达式。
            and not cinema_query
            # 执行当前步骤中的业务处理表达式。
            and not showing_only
            # 执行当前步骤中的业务处理表达式。
            and page == 1
            # 执行当前步骤中的业务处理表达式。
            and page_size == 20
        # 执行当前步骤中的业务处理表达式。
        ):
            # 将当前计算结果返回给调用方。
            return await fetch("/internal/movies", {"query": query})
        # 为 `params` 保存当前步骤所需的值。
        params = {
            # 设置当前结构中的 `query` 字段。
            "query": query,
            # 设置当前结构中的 `movieScope` 字段。
            "movieScope": movie_scope,
            # 设置当前结构中的 `cinemaQuery` 字段。
            "cinemaQuery": cinema_query,
            # 设置当前结构中的 `showingOnly` 字段。
            "showingOnly": showing_only,
            # 设置当前结构中的 `page` 字段。
            "page": page,
            # 设置当前结构中的 `pageSize` 字段。
            "pageSize": page_size,
            # 设置当前结构中的 `screeningDate` 字段。
            "screeningDate": screening_date.isoformat() if screening_date else None,
        }
        # 将当前计算结果返回给调用方。
        return await fetch("/internal/movies/query", {key: value for key, value in params.items() if value is not None})

    # 为紧随其后的函数或类设置装饰行为。
    @mcp.tool(annotations=READ_ONLY)
    # 定义异步函数 `search_screenings`：查询场次明细：scheduled 为有效排期，bookable 为当前可订购。
    async def search_screenings(
        # 设置当前结构中的 `movie_id` 字段。
        movie_id: PositiveId | None = None,
        # 设置当前结构中的 `cinema_id` 字段。
        cinema_id: PositiveId | None = None,
        # 设置当前结构中的 `movie_query` 字段。
        movie_query: Keyword = "",
        # 设置当前结构中的 `cinema_query` 字段。
        cinema_query: Keyword = "",
        # 设置当前结构中的 `screening_date` 字段。
        screening_date: date | None = None,
        # 设置当前结构中的 `query_scope` 字段。
        query_scope: Literal["scheduled", "bookable"] = "bookable",
        # 设置当前结构中的 `showing_only` 字段。
        showing_only: bool = False,
    # 执行当前步骤中的业务处理表达式。
    ) -> QueryResult:
        """查询场次明细：scheduled 为有效排期，bookable 为当前可订购。

        日期按北京时间开场日筛选；未指定日期的 scheduled 返回今天及以后。
        仅 bookable 排除已开场与未开售场次，默认值兼容原调用。
        """
        # 为 `params` 保存当前步骤所需的值。
        params = {
            # 设置当前结构中的 `movieId` 字段。
            "movieId": movie_id,
            # 设置当前结构中的 `cinemaId` 字段。
            "cinemaId": cinema_id,
            # 设置当前结构中的 `movieQuery` 字段。
            "movieQuery": movie_query,
            # 设置当前结构中的 `cinemaQuery` 字段。
            "cinemaQuery": cinema_query,
            # 设置当前结构中的 `screeningDate` 字段。
            "screeningDate": screening_date.isoformat() if screening_date else None,
        }
        # 检查 `if query_scope != "bookable"`，据此选择当前处理分支。
        if query_scope != "bookable":
            # 执行当前步骤中的业务处理表达式。
            params["queryScope"] = query_scope
        # 检查 `if showing_only`，据此选择当前处理分支。
        if showing_only:
            # 执行当前步骤中的业务处理表达式。
            params["showingOnly"] = True
        # 将当前计算结果返回给调用方。
        return await fetch("/internal/screenings", {key: value for key, value in params.items() if value is not None})

    # 为紧随其后的函数或类设置装饰行为。
    @mcp.tool(annotations=READ_ONLY)
    # 定义异步函数 `query_seats`：查询指定场次的实时座位；booking_status 区分 AVAILABLE、LOCKED、SOLD 等状态。
    async def query_seats(screening_id: PositiveId) -> QueryResult:
        """查询指定场次的实时座位；booking_status 区分 AVAILABLE、LOCKED、SOLD 等状态。"""
        # 将当前计算结果返回给调用方。
        return await fetch(f"/api/screenings/{screening_id}/seats", public=True)

    # 为紧随其后的函数或类设置装饰行为。
    @mcp.tool(annotations=READ_ONLY)
    # 定义异步函数 `query_order`：查询已认证用户本人的订单和退票资格；用户身份由服务端请求头绑定。
    async def query_order(order_no: OrderNumber, ctx: Context) -> QueryResult:
        """查询已认证用户本人的订单和退票资格；用户身份由服务端请求头绑定。"""
        # Context 由 SDK 注入，不出现在 tools/list 的输入 schema 中。
        # 服务凭证代表可信内部调用者；最终订单归属仍由 Java 的 user_id 条件核验。
        # 为 `request` 保存当前步骤所需的值。
        request = ctx.request_context.request
        # 为 `user` 保存当前步骤所需的值。
        user = request.headers.get("X-AI-User-ID", "") if request else ""
        # 检查 `if not user.isascii() or not user.isdecimal() or len(user) > 19 or int(user) <= 0`，据此选择当前处理分支。
        if not user.isascii() or not user.isdecimal() or len(user) > 19 or int(user) <= 0:
            # 将当前计算结果返回给调用方。
            return tool_result({"error": {"code": "business_auth_failed", "message": "订单查询缺少有效的登录身份。"}})
        # 将当前计算结果返回给调用方。
        return await fetch(f"/internal/orders/{order_no}", {"userId": int(user)})

    # 为 `http_app` 保存当前步骤所需的值。
    http_app = mcp.streamable_http_app()

    # 为紧随其后的函数或类设置装饰行为。
    @asynccontextmanager
    # 执行当前步骤中的业务处理表达式。
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        # Mounted MCP apps require their session manager to run in the parent lifespan.
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 进入对应的循环、异常处理或资源管理分支。
            async with mcp.session_manager.run():
                # 向流式调用方交付当前事件或结果。
                yield
        # 进入对应的循环、异常处理或资源管理分支。
        finally:
            # 执行当前步骤中的业务处理表达式。
            await api.aclose()

    # 执行当前步骤中的业务处理表达式。
    async def health(_: Request) -> JSONResponse:
        # 将当前计算结果返回给调用方。
        return JSONResponse({"status": "UP", "service": "cinema-mcp"})

    # 为 `server` 保存当前步骤所需的值。
    server = Starlette(routes=[Route("/health", health), Mount("/", app=http_app)], lifespan=lifespan)
    # 将当前计算结果返回给调用方。
    return InternalTokenMiddleware(server, service_token)


# 为 `app` 保存当前步骤所需的值。
app = create_app()
