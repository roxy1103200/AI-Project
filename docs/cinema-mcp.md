# 影院查询 MCP Server

电影、场次、座位、订单四类查询已从内部 Agent 的 LangChain `@tool` 中迁出，由独立 MCP Server 提供。Agent 使用官方 MCP SDK 完成 `initialize`、`tools/call`；其他 MCP 客户端可以通过 `tools/list` 发现工具及 JSON Schema。

```text
前端 → AI 网关（校验登录/转接凭证）→ 内部 Agent
                                      ↓ MCP Streamable HTTP
                                  cinema-mcp:8020/mcp
                                      ↓ 固定 HTTP 接口
                                  Java 业务服务 → MySQL / Redis
```

## 工具及边界

- `search_movies(query="")`：查询影片，关键词支持片名、类型、演员。
- `search_screenings(movie_id=null, cinema_id=null, movie_query="", cinema_query="", screening_date=null)`：查询场次；日期为北京时间 `YYYY-MM-DD`，返回的 `id` 是场次编号。
- `query_seats(screening_id)`：正整数场次编号；复用 Java `/api/screenings/{id}/seats`，返回实时 `booking_status`，包含 `AVAILABLE`、`LOCKED`、`SOLD` 等状态。查询不会锁座。
- `query_order(order_no)`：查询本人订单、出票信息及当前退票资格。订单号格式与现有 Agent 一致：O/o 开头，后接 5～63 个英文字母或数字。

工具都声明 `readOnlyHint=true`。成功结果同时提供文本 `content` 和 `structuredContent={"data": ...}`；上游失败设置 MCP `isError=true`，结构化错误为 `{"error":{"code":"...","message":"..."}}`。Agent 解包后沿用原聊天/SSE 返回格式。参数验证失败由 SDK 返回 MCP 工具错误，不调用 Java。

通用规则 RAG 与电影推荐继续使用现有工具。退票资格复合查询中的订单部分也通过 MCP 查询。

## 身份与配置

复制 `cinema-ticketing-backend/cinema-ai/.env.example` 为同目录 `.env`，配置：

```dotenv
JAVA_API_URL=http://127.0.0.1:8080
AI_INTERNAL_TOKEN=与Java和网关一致的服务凭证
CINEMA_MCP_URL=http://127.0.0.1:8020/mcp
CINEMA_MCP_ALLOWED_HOSTS=127.0.0.1:*,localhost:*,[::1]:*,cinema-mcp:*
```

MCP 的所有协议请求需携带 `X-Internal-Token`。订单查询另外读取 `X-AI-User-ID`，该值由 Agent 从网关已认证的 `user_id` 设置；它不属于工具参数，模型和历史消息不能覆盖。Java 继续以订单号和用户 ID 同时查询，拒绝读取他人订单。Agent 每轮建立独立 MCP 会话，避免并发用户共享身份头。

这是**内部服务信任边界**：持有服务凭证的调用者必须先认证真实用户，再设置身份头，不能把凭证发给浏览器。MCP 没有对公网提供终端用户 OAuth。Docker 不发布 8020，也不从 Nginx 转发 `/mcp`。`CINEMA_MCP_ALLOWED_HOSTS` 控制 Host 白名单；浏览器 Origin 均不接受。

SDK 固定 `mcp==1.28.0`，使用维护中的 v1 API；同时固定 `sse-starlette==2.2.1` 兼容项目现有 FastAPI/Starlette，避免隐式升级到 SDK v2 或不兼容的传输依赖。依赖来源：[官方 Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)。

## 本地启动

在项目根目录安装依赖：

```powershell
.\cinema-ticketing-backend\cinema-ai\.venv\Scripts\python.exe -m pip install -r .\cinema-ticketing-backend\cinema-ai\requirements.txt
```

如果虚拟环境由 uv 创建、不带 pip，可使用 `uv pip install --python .\cinema-ticketing-backend\cinema-ai\.venv\Scripts\python.exe -r .\cinema-ticketing-backend\cinema-ai\requirements.txt`。

先启动 Java，再在后端目录运行：

```powershell
cd .\cinema-ticketing-backend
.\start-ai-local.ps1 -Service all
# 单独启动或重启 MCP（Agent-only 启动不会自动启动 MCP）
.\stop-ai-local.ps1 -Service mcp
.\start-ai-local.ps1 -Service mcp
```

MCP 协议地址：`http://127.0.0.1:8020/mcp`；健康检查：`http://127.0.0.1:8020/health`。Agent 8000、网关 8010。日志为 `target/ai-mcp-{stdout,stderr}.log`。MCP 不是 Swagger REST 接口，浏览器直接 GET `/mcp` 不能用于调用工具。

Linux/macOS 可以从 `cinema-ai` 目录运行（先导出相同环境变量）：

```bash
python -m uvicorn app.mcp_server:app --host 127.0.0.1 --port 8020 --env-file .env
```

Docker 在后端目录运行 `docker compose --profile app up -d --build cinema-mcp cinema-ai cinema-ai-gateway`。Agent 通过 `http://cinema-mcp:8020/mcp` 连接，等待 MCP 健康后启动。部署已有服务器时，需要保留原服务器的 env、卷与 Compose 覆盖文件。

## 标准 MCP 客户端示例

在已安装依赖的环境中运行；凭证和用户 ID 应由可信调用端从环境或登录结果提供：

```python
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    headers = {"X-Internal-Token": os.environ["AI_INTERNAL_TOKEN"],
               "X-AI-User-ID": os.environ["AUTHENTICATED_USER_ID"]}
    async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
        async with streamable_http_client("http://127.0.0.1:8020/mcp", http_client=http) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                print((await session.list_tools()).model_dump())
                print((await session.call_tool("search_movies", {"query": "科幻"})).structuredContent)


asyncio.run(main())
```

聊天示例：`查科幻电影`、`《测试电影》明天的场次`、`查询场次 12 的座位`、`查询订单 O...`。座位查询缺少场次编号时先澄清，不猜测数据库 ID。

## 验证

从 `cinema-ai` 目录运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用实际 SDK 客户端和本地 HTTP 服务，Java 接口使用 MockTransport，不读取线上数据库或调用收费模型。覆盖四类工具发现、查询映射、座位状态、并发订单身份隔离、缺少身份、跨用户拒绝、参数校验、服务凭证/Host/Origin 校验、上游超时和 Agent 普通/流式/退票调用链。

`内部agent/源文件` 是 2026-09-28 的历史备份快照，不随此次迁移覆盖；当前可运行实现位于 `cinema-ticketing-backend/cinema-ai/app/`。
