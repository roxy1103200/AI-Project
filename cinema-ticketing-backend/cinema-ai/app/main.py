"""Cinema assistant with a shared read-only ReAct graph and policy RAG."""

# 导入当前步骤使用的模块或类型。
# isort: off
from __future__ import annotations

# 导入当前步骤使用的模块或类型。
import asyncio
# 导入当前步骤使用的模块或类型。
import hmac
# 导入当前步骤使用的模块或类型。
import json
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
from collections import defaultdict
# 导入当前步骤使用的模块或类型。
from collections.abc import AsyncIterator
# 导入当前步骤使用的模块或类型。
from contextlib import aclosing, asynccontextmanager
# 导入当前步骤使用的模块或类型。
from typing import Any, Literal

# 导入当前步骤使用的模块或类型。
import httpx
# 导入当前步骤使用的模块或类型。
from fastapi import Depends, FastAPI, Header, HTTPException
# 导入当前步骤使用的模块或类型。
from fastapi.responses import JSONResponse, StreamingResponse
# 导入当前步骤使用的模块或类型。
from langchain_core.tools import BaseTool, tool
# 导入当前步骤使用的模块或类型。
from pydantic import BaseModel, Field

# 导入当前步骤使用的模块或类型。
from app.failures import describe_failure
# 导入当前步骤使用的模块或类型。
from app.java_client import JavaApiClient
# 导入当前步骤使用的模块或类型。
from app.mcp_client import QUERY_TOOLS, CinemaMcpClient
# 导入当前步骤使用的模块或类型。
from app.model_config import create_model
# 导入当前步骤使用的模块或类型。
from app.policy_retrieval import KeywordRetriever, load_retriever, policy_candidates
# 导入当前步骤使用的模块或类型。
from app.query_answers import movie_answer, screening_answer
# 导入当前步骤使用的模块或类型。
from app.react_agent import AgentState, CinemaReAct, initial_state
# 导入当前步骤使用的模块或类型。
from app.reranker import DashScopeReranker
# 导入当前步骤使用的模块或类型。
from app.tracing import AgentTracing
# isort: on

# 为 `INTERNAL_API_TOKEN` 保存当前步骤所需的值。
INTERNAL_API_TOKEN = os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")


# 声明当前处理单元及其入口。
def create_tools(
    # 设置当前结构中的 `client` 字段。
    client: JavaApiClient,
    # 设置当前结构中的 `retriever` 字段。
    retriever: KeywordRetriever,
    # 设置当前结构中的 `reranker` 字段。
    reranker: DashScopeReranker | None = None,
# 继续构造当前业务表达式或数据结构。
) -> dict[str, BaseTool]:
    """Build policy RAG and recommendation tools; business queries use MCP."""

    # 为紧随其后的函数或类设置装饰行为。
    @tool
    # 声明当前处理单元及其入口。
    async def query_ticket_policy(question: str) -> dict[str, Any]:
        """Retrieve ticket policy passages with source and version metadata."""
        # 继续构造当前业务表达式或数据结构。
        local_documents, policy, business_documents = await asyncio.gather(
            # 补充当前表达式的 `retriever.ainvoke(question)` 参数或元素。
            retriever.ainvoke(question),
            # 补充当前表达式的 `client.get("/internal/refund-policy")` 参数或元素。
            client.get("/internal/refund-policy"),
            # 补充当前表达式的 `client.get("/internal/knowledge/search", {"q` 参数或元素。
            client.get("/internal/knowledge/search", {"query": question}),
        )
        # 为 `candidates` 保存当前步骤所需的值。
        candidates = policy_candidates(
            # 补充当前表达式的 `question` 参数或元素。
            question,
            # 补充当前表达式的 `local_documents` 参数或元素。
            local_documents,
            # 补充当前表达式的 `business_documents` 参数或元素。
            business_documents,
            # 补充当前表达式的 `reranker.settings.top_k if reranker else 30` 参数或元素。
            reranker.settings.top_k if reranker else 30,
        )
        # 为 `documents` 保存当前步骤所需的值。
        documents = await reranker.rerank(question, candidates) if reranker else candidates[:4]
        # 将当前计算结果返回给调用方。
        return {
            # 设置当前结构中的 `answer_context` 字段。
            "answer_context": [document.page_content for document in documents],
            # 设置当前结构中的 `sources` 字段。
            "sources": [document.metadata for document in documents],
            # 设置当前结构中的 `policy` 字段。
            "policy": policy,
        }

    # 为紧随其后的函数或类设置装饰行为。
    @tool
    # 声明当前处理单元及其入口。
    async def recommend_movies(user_id: int, preference: str = "") -> Any:
        """Recommend movies using the Java recommendation endpoint."""
        # 将当前计算结果返回给调用方。
        return await client.post("/internal/recommendations", {"userId": user_id, "preference": preference})

    # 将当前计算结果返回给调用方。
    return {
        # 设置当前结构中的 `tool.name` 字段。
        tool.name: tool
        # 进入对应的循环、异常处理或资源管理分支。
        for tool in (
            # 补充当前表达式的 `query_ticket_policy` 参数或元素。
            query_ticket_policy,
            # 补充当前表达式的 `recommend_movies` 参数或元素。
            recommend_movies,
        )
    }


# 声明当前处理单元及其入口。
class ChatRequest(BaseModel):
    """Request accepted by the assistant endpoints."""

    # 设置当前结构中的 `user_id` 字段。
    user_id: int = Field(gt=0)
    # 设置当前结构中的 `session_id` 字段。
    session_id: str = Field(min_length=1, max_length=128)
    # 设置当前结构中的 `question` 字段。
    question: str = Field(min_length=1, max_length=2000)


# 声明当前处理单元及其入口。
class HistoryMessage(BaseModel):
    """Untrusted context accompanying an explicit handoff."""

    # 设置当前结构中的 `role` 字段。
    role: Literal["user", "assistant"]
    # 设置当前结构中的 `content` 字段。
    content: str = Field(max_length=2000)


# 声明当前处理单元及其入口。
class LiveChatRequest(ChatRequest):
    """Read-only gateway request with bounded conversation context."""

    # 设置当前结构中的 `history` 字段。
    history: list[HistoryMessage] = Field(default_factory=list, max_length=10)


# 声明当前处理单元及其入口。
class ChatResponse(BaseModel):
    """Structured assistant response."""

    # 设置当前结构中的 `answer` 字段。
    answer: str
    # 设置当前结构中的 `intent` 字段。
    intent: str
    # 设置当前结构中的 `data` 字段。
    data: Any = None
    # 设置当前结构中的 `sources` 字段。
    sources: list[dict[str, Any]] = Field(default_factory=list)
    # 设置当前结构中的 `tool_calls` 字段。
    tool_calls: list[str] = Field(default_factory=list)


# 声明当前处理单元及其入口。
class Assistant:
    """Serve chat and SSE using the same authenticated read-only ReAct graph."""

    # 声明当前处理单元及其入口。
    def __init__(self) -> None:
        # 为 `self.tracing` 保存当前步骤所需的值。
        self.tracing = AgentTracing()
        # 为 `self.client` 保存当前步骤所需的值。
        self.client = JavaApiClient()
        # 导入当前步骤使用的模块或类型。
        from app.memory import UserMemory

        # 为 `self.memory` 保存当前步骤所需的值。
        self.memory = UserMemory(self.client)
        # 为 `self.mcp` 保存当前步骤所需的值。
        self.mcp = CinemaMcpClient()
        # 为 `self.retriever` 保存当前步骤所需的值。
        self.retriever = load_retriever()
        # 为 `self.reranker` 保存当前步骤所需的值。
        self.reranker = DashScopeReranker()
        # 为 `self.tools` 保存当前步骤所需的值。
        self.tools = create_tools(self.client, self.retriever, self.reranker)
        # 设置当前结构中的 `self.sessions` 字段。
        self.sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        # 为 `self.model` 保存当前步骤所需的值。
        self.model = create_model()
        # 为 `self.workflow` 保存当前步骤所需的值。
        self.workflow = CinemaReAct(
            # 为 `model_provider` 保存当前步骤所需的值。
            model_provider=lambda: self.model,
            # 为 `execute_tool` 保存当前步骤所需的值。
            execute_tool=self._call_tool,
            # 为 `recall_memory` 保存当前步骤所需的值。
            recall_memory=lambda user_id, question: self.memory.recall(user_id, question),
            # 为 `format_facts` 保存当前步骤所需的值。
            format_facts=lambda state: _business_answer(state),
        )
        # 为 `self.graph` 保存当前步骤所需的值。
        self.graph = self.workflow.graph

    # 声明当前处理单元及其入口。
    async def _call_tool(self, name: str, arguments: dict[str, Any], user_id: int) -> Any:
        """Use existing MCP/local tools with a server-supplied identity."""
        # 检查 `if name in QUERY_TOOLS`，据此选择当前处理分支。
        if name in QUERY_TOOLS:
            # 将当前计算结果返回给调用方。
            return await self.mcp.call_tool(name, arguments, user_id=user_id)
        # 检查 `if name == "recommend_movies"`，据此选择当前处理分支。
        if name == "recommend_movies":
            # 为 `arguments` 保存当前步骤所需的值。
            arguments = {**arguments, "user_id": user_id}
        # 将当前计算结果返回给调用方。
        return await self.tools[name].ainvoke(arguments)

    # 声明当前处理单元及其入口。
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run a normal request through the same graph used by live streaming."""
        # 进入对应的循环、异常处理或资源管理分支。
        with self.tracing.turn(request.user_id, request.session_id, request.question, "chat") as turn:
            # 继续构造当前业务表达式或数据结构。
            response, error_code = await self._chat(request)
            turn.observe({"type": "context", "intent": response.intent, "tool_calls": response.tool_calls})
            # The structured graph can return a business error without raising an exception.
            turn.observe({"type": "error", "code": error_code} if error_code else {"type": "complete"})
            # 将当前计算结果返回给调用方。
            return response

    # 声明当前处理单元及其入口。
    async def _chat(self, request: ChatRequest) -> tuple[ChatResponse, str]:
        """Execute the structured request inside its tracing scope."""
        # 为 `session_key` 保存当前步骤所需的值。
        session_key = f"{request.user_id}:{request.session_id}"
        # 为 `state` 保存当前步骤所需的值。
        state = initial_state(request.user_id, request.session_id, request.question, self.sessions[session_key])
        # 进入对应的循环、异常处理或资源管理分支。
        async with asyncio.timeout(80):
            # 为 `result` 保存当前步骤所需的值。
            result = await self.graph.ainvoke(state, config=self.workflow.config)
        # 为 `answer` 保存当前步骤所需的值。
        answer = result.get("answer", "暂时无法处理这个问题，请稍后重试。")
        # 继续构造当前业务表达式或数据结构。
        self.sessions[session_key] += [
            # 补充当前表达式的 `{"role": "user", "content": request.question` 参数或元素。
            {"role": "user", "content": request.question},
            # 补充当前表达式的 `{"role": "assistant", "content": answer}` 参数或元素。
            {"role": "assistant", "content": answer},
        ]
        # 继续构造当前业务表达式或数据结构。
        self.sessions[session_key] = self.sessions[session_key][-10:]
        # 为 `response` 保存当前步骤所需的值。
        response = ChatResponse(
            # 为 `answer` 保存当前步骤所需的值。
            answer=answer,
            # 为 `intent` 保存当前步骤所需的值。
            intent=result.get("intent", "fallback"),
            # 为 `data` 保存当前步骤所需的值。
            data=result.get("result"),
            # 为 `sources` 保存当前步骤所需的值。
            sources=result.get("retrieved_docs", []),
            # 为 `tool_calls` 保存当前步骤所需的值。
            tool_calls=result.get("tool_calls", []),
        )
        # 将当前计算结果返回给调用方。
        return response, result.get("error_code", "agent_error") if result.get("error") else ""

    # 声明当前处理单元及其入口。
    async def live(self, request: LiveChatRequest) -> AsyncIterator[str]:
        """Keep tracing open until SSE completion, failure, timeout or cancellation."""
        # 进入对应的循环、异常处理或资源管理分支。
        with self.tracing.turn(request.user_id, request.session_id, request.question, "live") as turn:
            # 检查 `if turn.run`，据此选择当前处理分支。
            if turn.run:
                # 向流式调用方交付当前事件或结果。
                yield _live_event("trace", trace_id=str(turn.trace_id))
            # 进入对应的循环、异常处理或资源管理分支。
            async with asyncio.timeout(80), aclosing(self._live(request)) as packets:
                # 进入对应的循环、异常处理或资源管理分支。
                async for packet in packets:
                    turn.observe(json.loads(packet.removeprefix("data: ").strip()))
                    # 向流式调用方交付当前事件或结果。
                    yield packet

    # 声明当前处理单元及其入口。
    async def _live(self, request: LiveChatRequest) -> AsyncIterator[str]:
        """Translate shared graph events to the existing gateway SSE protocol."""
        # 导入当前步骤使用的模块或类型。
        from app.memory import memory_proposal

        # 为 `proposal` 保存当前步骤所需的值。
        proposal = memory_proposal(request.question)
        # 检查 `if proposal`，据此选择当前处理分支。
        if proposal:
            # 向流式调用方交付当前事件或结果。
            yield _live_event(
                # 补充当前表达式的 `"delta"` 参数或元素。
                "delta",
                # 为 `text` 保存当前步骤所需的值。
                text="请点击下方‘保存记忆’确认。这条信息将用于以后与智能 Agent 的对话，你可以在‘我的记忆’中修改或删除。",
            )
            # 向流式调用方交付当前事件或结果。
            yield _live_event("memory_suggestion", **proposal)
            # 向流式调用方交付当前事件或结果。
            yield _live_event("complete")
            # 将当前计算结果返回给调用方。
            return
        # 检查 `if any(phrase in request.question for phrase in ("记得我", "我的偏好", "我的记忆"))`，据此选择当前处理分支。
        if any(phrase in request.question for phrase in ("记得我", "我的偏好", "我的记忆")):
            # 为 `memories` 保存当前步骤所需的值。
            memories = await self.memory.recall(request.user_id, request.question)
            # 向流式调用方交付当前事件或结果。
            yield _live_event(
                # 补充当前表达式的 `"delta"` 参数或元素。
                "delta",
                # 为 `text` 保存当前步骤所需的值。
                text=("目前记得：\n" + "\n".join("• " + item["content"] for item in memories))
                # 检查 `if memories`，据此选择当前处理分支。
                if memories
                # 补充当前表达式的 `else "还没有保存的相关记忆。你可以在‘我的记忆’中添加，或对我说‘记住：……’。"` 参数或元素。
                else "还没有保存的相关记忆。你可以在‘我的记忆’中添加，或对我说‘记住：……’。",
            )
            # 向流式调用方交付当前事件或结果。
            yield _live_event("complete")
            # 将当前计算结果返回给调用方。
            return
        # 为 `state` 保存当前步骤所需的值。
        state = initial_state(
            # 补充当前表达式的 `request.user_id` 参数或元素。
            request.user_id,
            # 补充当前表达式的 `request.session_id` 参数或元素。
            request.session_id,
            # 补充当前表达式的 `request.question` 参数或元素。
            request.question,
            # 补充当前表达式的 `[message.model_dump() for message in request` 参数或元素。
            [message.model_dump() for message in request.history],
        )
        # 为 `failed` 保存当前步骤所需的值。
        failed = False
        # 进入对应的循环、异常处理或资源管理分支。
        async with aclosing(self.graph.astream(state, config=self.workflow.config, stream_mode="custom")) as events:
            # 进入对应的循环、异常处理或资源管理分支。
            async for packet in events:
                # 为 `failed` 保存当前步骤所需的值。
                failed = failed or packet["type"] == "error"
                # 向流式调用方交付当前事件或结果。
                yield _live_event(packet["type"], **{key: value for key, value in packet.items() if key != "type"})
        # 检查 `if not failed`，据此选择当前处理分支。
        if not failed:
            # 向流式调用方交付当前事件或结果。
            yield _live_event("complete")


# 为 `assistant` 保存当前步骤所需的值。
assistant = Assistant()


# 为紧随其后的函数或类设置装饰行为。
@asynccontextmanager
# 声明当前处理单元及其入口。
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the Java and DashScope HTTP pools on shutdown."""
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        # 向流式调用方交付当前事件或结果。
        yield
    # 进入对应的循环、异常处理或资源管理分支。
    finally:
        # 执行当前异步调用或运行状态记录。
        await assistant.reranker.aclose()
        # 执行当前异步调用或运行状态记录。
        await assistant.client.aclose()
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 进入对应的循环、异常处理或资源管理分支。
            async with asyncio.timeout(5):
                # 执行当前异步调用或运行状态记录。
                await asyncio.to_thread(assistant.tracing.flush)
        # 进入对应的循环、异常处理或资源管理分支。
        except TimeoutError:
            # 此分支不执行额外操作。
            pass


# 为 `app` 保存当前步骤所需的值。
app = FastAPI(title="Cinema AI Assistant", version="0.2.0", lifespan=lifespan)


# 声明当前处理单元及其入口。
def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    """Require the shared service token for AI business endpoints."""
    # 检查 `if not hmac.compare_digest(x_internal_token, INTERNAL_API_TOKEN)`，据此选择当前处理分支。
    if not hmac.compare_digest(x_internal_token, INTERNAL_API_TOKEN):
        # 抛出当前异常，交由上层错误处理流程处理。
        raise HTTPException(status_code=401, detail="Invalid internal service token")


# 为紧随其后的函数或类设置装饰行为。
@app.get("/health")
# 声明当前处理单元及其入口。
async def health() -> dict[str, Any]:
    """Return AI service health status."""
    # 将当前计算结果返回给调用方。
    return {"status": "UP", "tracing": assistant.tracing.status()}


# 为紧随其后的函数或类设置装饰行为。
@app.post("/ai/chat", response_model=ChatResponse, dependencies=[Depends(verify_internal_token)])
# 声明当前处理单元及其入口。
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a normal structured assistant request."""
    # 将当前计算结果返回给调用方。
    return await assistant.chat(request)


# 为紧随其后的函数或类设置装饰行为。
@app.post("/ai/stream", dependencies=[Depends(verify_internal_token)])
# 声明当前处理单元及其入口。
async def stream(request: ChatRequest) -> StreamingResponse:
    """Return the assistant answer as a single server-sent event."""
    # 为 `result` 保存当前步骤所需的值。
    result = await assistant.chat(request)

    # 声明当前处理单元及其入口。
    async def events():
        # 向流式调用方交付当前事件或结果。
        yield f"data: {result.model_dump_json()}\n\n"
        # 向流式调用方交付当前事件或结果。
        yield "data: [DONE]\n\n"

    # 将当前计算结果返回给调用方。
    return StreamingResponse(events(), media_type="text/event-stream")


# 声明当前处理单元及其入口。
def _live_event(kind: str, **payload: Any) -> str:
    # 将当前计算结果返回给调用方。
    return "data: " + json.dumps({"type": kind, **payload}, ensure_ascii=False, default=str) + "\n\n"


# 声明当前处理单元及其入口。
def _business_answer(state: AgentState) -> str:
    """Render actual business rows when no internal model key is configured."""
    data, intent = state.get("result"), state["intent"]
    # 检查 `if intent == "chat"`，据此选择当前处理分支。
    if intent == "chat":
        # 将当前计算结果返回给调用方。
        return "你好，我是影院实时助手，可以查询影片场次、你的订单和当前退票资格。你想查询什么？"
    # 检查 `if intent == "policy"`，据此选择当前处理分支。
    if intent == "policy":
        # 为 `policy` 保存当前步骤所需的值。
        policy = data.get("policy", {})
        # 将当前计算结果返回给调用方。
        return f"当前退票规则（版本 {policy.get('version', '未知')}）：\n{policy.get('policy', '')}"
    # 检查 `if intent == "seats"`，据此选择当前处理分支。
    if intent == "seats":
        # 将当前计算结果返回给调用方。
        return _seat_answer(data)
    # 检查 `if intent in ("order", "refund")`，据此选择当前处理分支。
    if intent in ("order", "refund"):
        # 为 `order` 保存当前步骤所需的值。
        order = data.get("order", {}) if intent == "refund" else data
        # 为 `status` 保存当前步骤所需的值。
        status = {"UNPAID": "待支付", "PAID": "已支付", "ISSUED": "已出票", "CANCELLED": "已取消", "REFUNDED": "已退款"}
        # 将当前计算结果返回给调用方。
        return (
            f"订单：{order.get('order_no', '')}\n影片：{order.get('movie_title', '')}\n"
            f"状态：{status.get(order.get('status'), order.get('status', '未知'))}\n"
            f"开场：{order.get('start_time', '')}（北京时间）\n金额：¥{order.get('total_amount', '')}\n"
            f"座位：{'、'.join(item.get('seat_code', '') for item in order.get('items', []))}\n"
            f"退票：{order.get('refund_reason', '请在订单页面查看当前可退状态')}\n"
            "如需操作，请前往我的订单。"
        )
    # 检查 `if intent == "movies"`，据此选择当前处理分支。
    if intent == "movies":
        # 将当前计算结果返回给调用方。
        return movie_answer(data, state.get("question", ""))
    # 检查 `if intent == "screenings"`，据此选择当前处理分支。
    if intent == "screenings":
        # 将当前计算结果返回给调用方。
        return screening_answer(data, state.get("entities", {}))
    # 检查 `if isinstance(data, list) and not data`，据此选择当前处理分支。
    if isinstance(data, list) and not data:
        # 将当前计算结果返回给调用方。
        return "没有找到符合条件的结果，可补充影片名称或在两周观影日程中查看排期。"
    # 将当前计算结果返回给调用方。
    return "影片查询结果：\n" + "\n".join(
        f"• {row.get('title')}｜{row.get('genre', '')}｜{row.get('duration', '未知')} 分钟" for row in data[:12]
    )


# 声明当前处理单元及其入口。
def _seat_answer(seats: list[dict[str, Any]]) -> str:
    """Show current availability without promising a reservation."""
    # 为 `available` 保存当前步骤所需的值。
    available = [seat for seat in seats if seat.get("booking_status") == "AVAILABLE"]
    # 为 `locked` 保存当前步骤所需的值。
    locked = sum(seat.get("booking_status") == "LOCKED" for seat in seats)
    # 为 `sold` 保存当前步骤所需的值。
    sold = sum(seat.get("booking_status") == "SOLD" for seat in seats)
    # 为 `codes` 保存当前步骤所需的值。
    codes = "、".join(str(seat.get("seat_code", "")) for seat in available[:30])
    # 将当前计算结果返回给调用方。
    return (
        # 继续构造当前业务表达式或数据结构。
        f"该场次共 {len(seats)} 个座位，可选 {len(available)} 个、锁定 {locked} 个、已售 {sold} 个。"
        + (f"\n可选座位：{codes}" if available else "")
        + "\n状态为查询时快照，请在选座页面确认并购票。"
    )


# 为紧随其后的函数或类设置装饰行为。
@app.post("/ai/live", dependencies=[Depends(verify_internal_token)])
# 声明当前处理单元及其入口。
async def live(request: LiveChatRequest) -> StreamingResponse:
    """Private live endpoint used only after gateway credential validation."""

    # 声明当前处理单元及其入口。
    async def events() -> AsyncIterator[str]:
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 进入对应的循环、异常处理或资源管理分支。
            async with aclosing(assistant.live(request)) as packets:
                # 进入对应的循环、异常处理或资源管理分支。
                async for packet in packets:
                    # 向流式调用方交付当前事件或结果。
                    yield packet
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exception:
            code, message = describe_failure(exception, "live_generation")
            # 向流式调用方交付当前事件或结果。
            yield _live_event("error", message=message, code=code)

    # 将当前计算结果返回给调用方。
    return StreamingResponse(
        # 调用 `events` 执行当前业务操作。
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


# 为紧随其后的函数或类设置装饰行为。
@app.exception_handler(httpx.HTTPError)
# 声明当前处理单元及其入口。
async def handle_http_error(_, exception: httpx.HTTPError) -> JSONResponse:
    """Convert Java service failures into a stable AI error response."""
    # 将当前计算结果返回给调用方。
    return JSONResponse(status_code=502, content={"detail": f"Java API unavailable: {exception}"})
