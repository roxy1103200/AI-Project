"""Cinema assistant with a shared read-only ReAct graph and policy RAG."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.failures import describe_failure
from app.java_client import JavaApiClient
from app.mcp_client import QUERY_TOOLS, CinemaMcpClient
from app.model_config import create_model
from app.policy_retrieval import KeywordRetriever, load_retriever, policy_candidates
from app.query_answers import movie_answer, screening_answer
from app.react_agent import AgentState, CinemaReAct, initial_state
from app.reranker import DashScopeReranker

INTERNAL_API_TOKEN = os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")


def create_tools(
    client: JavaApiClient,
    retriever: KeywordRetriever,
    reranker: DashScopeReranker | None = None,
) -> dict[str, BaseTool]:
    """Build policy RAG and recommendation tools; business queries use MCP."""

    @tool
    async def query_ticket_policy(question: str) -> dict[str, Any]:
        """Retrieve ticket policy passages with source and version metadata."""
        local_documents, policy, business_documents = await asyncio.gather(
            retriever.ainvoke(question),
            client.get("/internal/refund-policy"),
            client.get("/internal/knowledge/search", {"query": question}),
        )
        candidates = policy_candidates(
            question,
            local_documents,
            business_documents,
            reranker.settings.top_k if reranker else 30,
        )
        documents = await reranker.rerank(question, candidates) if reranker else candidates[:4]
        return {
            "answer_context": [document.page_content for document in documents],
            "sources": [document.metadata for document in documents],
            "policy": policy,
        }

    @tool
    async def recommend_movies(user_id: int, preference: str = "") -> Any:
        """Recommend movies using the Java recommendation endpoint."""
        return await client.post("/internal/recommendations", {"userId": user_id, "preference": preference})

    return {
        tool.name: tool
        for tool in (
            query_ticket_policy,
            recommend_movies,
        )
    }


class ChatRequest(BaseModel):
    """Request accepted by the assistant endpoints."""

    user_id: int = Field(gt=0)
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)


class HistoryMessage(BaseModel):
    """Untrusted context accompanying an explicit handoff."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class LiveChatRequest(ChatRequest):
    """Read-only gateway request with bounded conversation context."""

    history: list[HistoryMessage] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    """Structured assistant response."""

    answer: str
    intent: str
    data: Any = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)


class Assistant:
    """Serve chat and SSE using the same authenticated read-only ReAct graph."""

    def __init__(self) -> None:
        self.client = JavaApiClient()
        from app.memory import UserMemory

        self.memory = UserMemory(self.client)
        self.mcp = CinemaMcpClient()
        self.retriever = load_retriever()
        self.reranker = DashScopeReranker()
        self.tools = create_tools(self.client, self.retriever, self.reranker)
        self.sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.model = create_model()
        self.workflow = CinemaReAct(
            model_provider=lambda: self.model,
            execute_tool=self._call_tool,
            recall_memory=lambda user_id, question: self.memory.recall(user_id, question),
            format_facts=lambda state: _business_answer(state),
        )
        self.graph = self.workflow.graph

    async def _call_tool(self, name: str, arguments: dict[str, Any], user_id: int) -> Any:
        """Use existing MCP/local tools with a server-supplied identity."""
        if name in QUERY_TOOLS:
            return await self.mcp.call_tool(name, arguments, user_id=user_id)
        if name == "recommend_movies":
            arguments = {**arguments, "user_id": user_id}
        return await self.tools[name].ainvoke(arguments)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run a normal request through the same graph used by live streaming."""
        session_key = f"{request.user_id}:{request.session_id}"
        state = initial_state(request.user_id, request.session_id, request.question, self.sessions[session_key])
        async with asyncio.timeout(80):
            result = await self.graph.ainvoke(state, config=self.workflow.config)
        answer = result.get("answer", "暂时无法处理这个问题，请稍后重试。")
        self.sessions[session_key] += [
            {"role": "user", "content": request.question},
            {"role": "assistant", "content": answer},
        ]
        self.sessions[session_key] = self.sessions[session_key][-10:]
        return ChatResponse(
            answer=answer,
            intent=result.get("intent", "fallback"),
            data=result.get("result"),
            sources=result.get("retrieved_docs", []),
            tool_calls=result.get("tool_calls", []),
        )

    async def live(self, request: LiveChatRequest) -> AsyncIterator[str]:
        """Translate shared graph events to the existing gateway SSE protocol."""
        from app.memory import memory_proposal

        proposal = memory_proposal(request.question)
        if proposal:
            yield _live_event(
                "delta",
                text="请点击下方‘保存记忆’确认。这条信息将用于以后与智能 Agent 的对话，你可以在‘我的记忆’中修改或删除。",
            )
            yield _live_event("memory_suggestion", **proposal)
            yield _live_event("complete")
            return
        if any(phrase in request.question for phrase in ("记得我", "我的偏好", "我的记忆")):
            memories = await self.memory.recall(request.user_id, request.question)
            yield _live_event(
                "delta",
                text=("目前记得：\n" + "\n".join("• " + item["content"] for item in memories))
                if memories
                else "还没有保存的相关记忆。你可以在‘我的记忆’中添加，或对我说‘记住：……’。",
            )
            yield _live_event("complete")
            return
        state = initial_state(
            request.user_id,
            request.session_id,
            request.question,
            [message.model_dump() for message in request.history],
        )
        failed = False
        async with aclosing(self.graph.astream(state, config=self.workflow.config, stream_mode="custom")) as events:
            async for packet in events:
                failed = failed or packet["type"] == "error"
                yield _live_event(packet["type"], **{key: value for key, value in packet.items() if key != "type"})
        if not failed:
            yield _live_event("complete")


assistant = Assistant()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Close the Java and DashScope HTTP pools on shutdown."""
    try:
        yield
    finally:
        await assistant.reranker.aclose()
        await assistant.client.aclose()


app = FastAPI(title="Cinema AI Assistant", version="0.2.0", lifespan=lifespan)


def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    """Require the shared service token for AI business endpoints."""
    if not hmac.compare_digest(x_internal_token, INTERNAL_API_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid internal service token")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return AI service health status."""
    return {"status": "UP"}


@app.post("/ai/chat", response_model=ChatResponse, dependencies=[Depends(verify_internal_token)])
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a normal structured assistant request."""
    return await assistant.chat(request)


@app.post("/ai/stream", dependencies=[Depends(verify_internal_token)])
async def stream(request: ChatRequest) -> StreamingResponse:
    """Return the assistant answer as a single server-sent event."""
    result = await assistant.chat(request)

    async def events():
        yield f"data: {result.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


def _live_event(kind: str, **payload: Any) -> str:
    return "data: " + json.dumps({"type": kind, **payload}, ensure_ascii=False, default=str) + "\n\n"


def _business_answer(state: AgentState) -> str:
    """Render actual business rows when no internal model key is configured."""
    data, intent = state.get("result"), state["intent"]
    if intent == "chat":
        return "你好，我是影院实时助手，可以查询影片场次、你的订单和当前退票资格。你想查询什么？"
    if intent == "policy":
        policy = data.get("policy", {})
        return f"当前退票规则（版本 {policy.get('version', '未知')}）：\n{policy.get('policy', '')}"
    if intent == "seats":
        return _seat_answer(data)
    if intent in ("order", "refund"):
        order = data.get("order", {}) if intent == "refund" else data
        status = {"UNPAID": "待支付", "PAID": "已支付", "ISSUED": "已出票", "CANCELLED": "已取消", "REFUNDED": "已退款"}
        return (
            f"订单：{order.get('order_no', '')}\n影片：{order.get('movie_title', '')}\n"
            f"状态：{status.get(order.get('status'), order.get('status', '未知'))}\n"
            f"开场：{order.get('start_time', '')}（北京时间）\n金额：¥{order.get('total_amount', '')}\n"
            f"座位：{'、'.join(item.get('seat_code', '') for item in order.get('items', []))}\n"
            f"退票：{order.get('refund_reason', '请在订单页面查看当前可退状态')}\n"
            "如需操作，请前往我的订单。"
        )
    if intent == "movies":
        return movie_answer(data, state.get("question", ""))
    if intent == "screenings":
        return screening_answer(data, state.get("entities", {}))
    if isinstance(data, list) and not data:
        return "没有找到符合条件的结果，可补充影片名称或在两周观影日程中查看排期。"
    return "影片查询结果：\n" + "\n".join(
        f"• {row.get('title')}｜{row.get('genre', '')}｜{row.get('duration', '未知')} 分钟" for row in data[:12]
    )


def _seat_answer(seats: list[dict[str, Any]]) -> str:
    """Show current availability without promising a reservation."""
    available = [seat for seat in seats if seat.get("booking_status") == "AVAILABLE"]
    locked = sum(seat.get("booking_status") == "LOCKED" for seat in seats)
    sold = sum(seat.get("booking_status") == "SOLD" for seat in seats)
    codes = "、".join(str(seat.get("seat_code", "")) for seat in available[:30])
    return (
        f"该场次共 {len(seats)} 个座位，可选 {len(available)} 个、锁定 {locked} 个、已售 {sold} 个。"
        + (f"\n可选座位：{codes}" if available else "")
        + "\n状态为查询时快照，请在选座页面确认并购票。"
    )


@app.post("/ai/live", dependencies=[Depends(verify_internal_token)])
async def live(request: LiveChatRequest) -> StreamingResponse:
    """Private live endpoint used only after gateway credential validation."""

    async def events() -> AsyncIterator[str]:
        try:
            async with asyncio.timeout(80):
                async for packet in assistant.live(request):
                    yield packet
        except Exception as exception:
            code, message = describe_failure(exception, "live_generation")
            yield _live_event("error", message=message, code=code)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@app.exception_handler(httpx.HTTPError)
async def handle_http_error(_, exception: httpx.HTTPError) -> JSONResponse:
    """Convert Java service failures into a stable AI error response."""
    return JSONResponse(status_code=502, content={"detail": f"Java API unavailable: {exception}"})
