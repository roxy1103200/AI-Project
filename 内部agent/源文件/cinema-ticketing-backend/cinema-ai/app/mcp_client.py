"""Official MCP client used by the Agent's read-only ReAct workflow."""

# 导入当前步骤使用的模块或类型。
# isort: off
import asyncio
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
import httpx
# 导入当前步骤使用的模块或类型。
from mcp import ClientSession
# 导入当前步骤使用的模块或类型。
from mcp.client.streamable_http import streamable_http_client

# 导入当前步骤使用的模块或类型。
from app.failures import CinemaQueryError
# isort: on

# 为 `QUERY_TOOLS` 保存当前步骤所需的值。
QUERY_TOOLS = frozenset({"search_movies", "search_screenings", "query_seats", "query_order"})


# 声明当前处理单元及其入口。
class CinemaMcpClient:
    """Bind each MCP session to the authenticated caller, never model arguments."""

    # 声明当前处理单元及其入口。
    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        # 为 `self.url` 保存当前步骤所需的值。
        self.url = url or os.getenv("CINEMA_MCP_URL", "http://127.0.0.1:8020/mcp")
        # 为 `self.token` 保存当前步骤所需的值。
        self.token = token or os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")

    # 声明当前处理单元及其入口。
    async def call_tool(self, name: str, arguments: dict[str, Any], *, user_id: int) -> Any:
        """Initialize MCP, invoke an allowed tool, and unwrap its business data.

        每轮独立连接，避免并发请求共用可变身份头。用户 ID 只来自网关已校验的请求。
        不把 user_id 放入 MCP 工具参数；模型无法通过订单号或历史消息切换订单归属。
        """
        # 检查 `if name not in QUERY_TOOLS or user_id <= 0`，据此选择当前处理分支。
        if name not in QUERY_TOOLS or user_id <= 0:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("Invalid cinema tool or authenticated user")
        # 检查 `if "user_id" in arguments or "userId" in arguments`，据此选择当前处理分支。
        if "user_id" in arguments or "userId" in arguments:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise ValueError("Identity must not be supplied as a tool argument")
        # 进入对应的循环、异常处理或资源管理分支。
        async with asyncio.timeout(20):
            # 进入对应的循环、异常处理或资源管理分支。
            async with httpx.AsyncClient(
                # 为 `headers` 保存当前步骤所需的值。
                headers={"X-Internal-Token": self.token, "X-AI-User-ID": str(user_id)},
                # 为 `timeout` 保存当前步骤所需的值。
                timeout=15.0,
                # 为 `trust_env` 保存当前步骤所需的值。
                trust_env=False,
                # 为 `follow_redirects` 保存当前步骤所需的值。
                follow_redirects=False,
            # 继续构造当前业务表达式或数据结构。
            ) as http_client:
                # 进入对应的循环、异常处理或资源管理分支。
                async with streamable_http_client(self.url, http_client=http_client) as (reader, writer, _):
                    # 进入对应的循环、异常处理或资源管理分支。
                    async with ClientSession(reader, writer) as session:
                        # 执行当前异步调用或运行状态记录。
                        await session.initialize()
                        # 为 `result` 保存当前步骤所需的值。
                        result = await session.call_tool(name, arguments)
        # 为 `payload` 保存当前步骤所需的值。
        payload = result.structuredContent
        # 检查 `if not isinstance(payload, dict)`，据此选择当前处理分支。
        if not isinstance(payload, dict):
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("business_unavailable", "业务查询服务暂时不可用，请稍后重试。")
        # 为 `error` 保存当前步骤所需的值。
        error = payload.get("error")
        # 检查 `if error`，据此选择当前处理分支。
        if error:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError(error["code"], error["message"])
        # 检查 `if result.isError or "data" not in payload`，据此选择当前处理分支。
        if result.isError or "data" not in payload:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("business_unavailable", "业务查询服务暂时不可用，请稍后重试。")
        # 将当前计算结果返回给调用方。
        return payload["data"]
