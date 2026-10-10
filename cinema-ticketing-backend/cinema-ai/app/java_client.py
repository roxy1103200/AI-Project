"""Shared Java API transport for the Agent and the cinema MCP server."""

# 导入当前步骤使用的模块或类型。
# isort: off
import os
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
import httpx
# isort: on


# 声明当前处理单元及其入口。
class JavaApiClient:
    """Call fixed business endpoints with the private service credential."""

    # 声明当前处理单元及其入口。
    def __init__(self) -> None:
        # 为 `self.client` 保存当前步骤所需的值。
        self.client = httpx.AsyncClient(
            # 为 `base_url` 保存当前步骤所需的值。
            base_url=os.getenv("JAVA_API_URL", "http://localhost:8080").rstrip("/"),
            # 为 `headers` 保存当前步骤所需的值。
            headers={"X-Internal-Token": os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")},
            # 为 `timeout` 保存当前步骤所需的值。
            timeout=8.0,
            # 为 `trust_env` 保存当前步骤所需的值。
            trust_env=False,
        )

    # 声明当前处理单元及其入口。
    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return decoded JSON after checking the upstream HTTP status."""
        # 为 `response` 保存当前步骤所需的值。
        response = await self.client.get(path, params=params)
        # 继续构造当前业务表达式或数据结构。
        response.raise_for_status()
        # 将当前计算结果返回给调用方。
        return response.json()

    # 声明当前处理单元及其入口。
    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        """Call the recommendation endpoint and return decoded JSON."""
        # 为 `response` 保存当前步骤所需的值。
        response = await self.client.post(path, json=payload)
        # 继续构造当前业务表达式或数据结构。
        response.raise_for_status()
        # 将当前计算结果返回给调用方。
        return response.json()

    # 声明当前处理单元及其入口。
    async def aclose(self) -> None:
        """Release pooled HTTP connections when the service stops."""
        # 执行当前异步调用或运行状态记录。
        await self.client.aclose()
