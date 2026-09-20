"""LangChain-based cinema assistant with Java HTTP tools and local RAG."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, TypedDict

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.retrievers import BaseRetriever
from langchain_core.tools import BaseTool, tool
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

JAVA_API_URL = os.getenv("JAVA_API_URL", "http://localhost:8080").rstrip("/")
INTERNAL_API_TOKEN = os.getenv("AI_INTERNAL_TOKEN", "local-internal-token")
KNOWLEDGE_PATH = Path(__file__).resolve().parent.parent / "knowledge"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _terms(text: str) -> set[str]:
    """Create keyword terms that work for both Chinese and Latin text."""
    words = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower()))
    return {word for word in words if word.strip()}


class KeywordRetriever(BaseRetriever):
    """Small deterministic retriever for the local policy knowledge base."""

    documents: list[Document] = Field(default_factory=list)
    top_k: int = 4

    def _get_relevant_documents(self, query: str, *, run_manager: Any) -> list[Document]:
        """Return documents ordered by keyword overlap with the question."""
        query_terms = _terms(query)
        ranked = []
        for document in self.documents:
            score = len(query_terms & _terms(document.page_content))
            if score:
                ranked.append((score, document))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [document for _, document in ranked[: self.top_k]]


def load_retriever() -> KeywordRetriever:
    """Load and split markdown knowledge documents into searchable chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n\n", "\n", "。", "，", " ", ""],
    )
    documents: list[Document] = []
    for source in sorted(KNOWLEDGE_PATH.glob("*.md")):
        text = source.read_text(encoding="utf-8")
        documents.extend(
            splitter.create_documents([text], metadatas=[{"source": source.name, "version": "2026.01"}])
        )
    return KeywordRetriever(documents=documents)


class JavaApiClient:
    """HTTP client for the Java business API used by AI tools."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            base_url=JAVA_API_URL,
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
            timeout=8.0,
        )

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Call a Java internal endpoint and return decoded JSON."""
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, payload: dict[str, Any]) -> Any:
        """Call a Java internal POST endpoint and return decoded JSON."""
        response = await self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


def create_tools(client: JavaApiClient, retriever: KeywordRetriever) -> dict[str, BaseTool]:
    """Build the assistant's LangChain business and RAG tools."""

    @tool
    async def search_movies(query: str = "") -> Any:
        """Search currently available movies by title, genre, actor, or keyword."""
        return await client.get("/internal/movies", {"query": query})

    @tool
    async def search_screenings(movie_id: int | None = None, cinema_id: int | None = None) -> Any:
        """Search scheduled screenings by movie or cinema."""
        params = {key: value for key, value in {"movieId": movie_id, "cinemaId": cinema_id}.items() if value}
        return await client.get("/internal/screenings", params)

    @tool
    async def query_order(order_no: str, user_id: int) -> Any:
        """Query one order belonging to the authenticated user."""
        return await client.get(f"/internal/orders/{order_no}", {"userId": user_id})

    @tool
    async def query_ticket_policy(question: str) -> dict[str, Any]:
        """Retrieve ticket policy passages with source and version metadata."""
        documents = await retriever.ainvoke(question)
        policy = await client.get("/internal/refund-policy")
        return {
            "answer_context": [document.page_content for document in documents],
            "sources": [document.metadata for document in documents],
            "policy": policy,
        }

    @tool
    async def recommend_movies(user_id: int, preference: str = "") -> Any:
        """Recommend movies using the Java recommendation endpoint."""
        return await client.post("/internal/recommendations", {"userId": user_id, "preference": preference})

    @tool
    async def check_refund_eligibility(order_no: str, user_id: int) -> dict[str, Any]:
        """Check order status and return the policy context for a refund decision."""
        order = await query_order.ainvoke({"order_no": order_no, "user_id": user_id})
        policy = await query_ticket_policy.ainvoke("退票规则和开场时间")
        return {"order": order, "policy": policy}

    return {
        tool.name: tool
        for tool in (
            search_movies,
            search_screenings,
            query_order,
            query_ticket_policy,
            recommend_movies,
            check_refund_eligibility,
        )
    }


class ChatRequest(BaseModel):
    """Request accepted by the assistant endpoints."""

    user_id: int
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    """Structured assistant response."""

    answer: str
    intent: str
    data: Any = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)


class AgentState(TypedDict, total=False):
    """State carried through the LangGraph assistant workflow."""

    session_id: str
    user_id: int
    question: str
    intent: str
    slots: dict[str, Any]
    messages: list[dict[str, str]]
    tool_calls: list[str]
    retrieved_docs: list[dict[str, Any]]
    auth_scope: dict[str, Any]
    result: Any
    answer: str
    error: str | None
    needs_clarification: bool


class Assistant:
    """Route questions to tools, RAG, optional model generation, and session memory."""

    def __init__(self) -> None:
        self.client = JavaApiClient()
        self.retriever = load_retriever()
        self.tools = create_tools(self.client, self.retriever)
        self.sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.model = None
        if OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI

            self.model = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=OPENAI_API_KEY)
        self.graph = self._build_graph()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run one request through the LangGraph state machine."""
        history = self.sessions[request.session_id]
        state: AgentState = {
            "session_id": request.session_id,
            "user_id": request.user_id,
            "question": request.question,
            "messages": history + [{"role": "user", "content": request.question}],
            "auth_scope": {"user_id": request.user_id, "session_id": request.session_id},
            "error": None,
        }
        result = await self.graph.ainvoke(state)
        answer = result.get("answer", "暂时无法处理这个问题，请稍后重试。")
        self.sessions[request.session_id].append({"role": "user", "content": request.question})
        self.sessions[request.session_id].append({"role": "assistant", "content": answer})
        self.sessions[request.session_id] = self.sessions[request.session_id][-10:]
        return ChatResponse(
            answer=answer,
            intent=result.get("intent", "fallback"),
            data=result.get("result"),
            sources=result.get("retrieved_docs", []),
            tool_calls=result.get("tool_calls", []),
        )

    def _build_graph(self):
        """Build the route, clarify, execute, validate, and response graph."""
        graph = StateGraph(AgentState)
        graph.add_node("intent", self._intent_node)
        graph.add_node("clarify", self._clarify_node)
        graph.add_node("execute", self._execute_node)
        graph.add_node("validate", self._validate_node)
        graph.add_node("respond", self._respond_node)
        graph.add_edge(START, "intent")
        graph.add_conditional_edges("intent", self._route_next, {"clarify": "clarify", "execute": "execute"})
        graph.add_edge("clarify", "respond")
        graph.add_edge("execute", "validate")
        graph.add_edge("validate", "respond")
        graph.add_edge("respond", END)
        return graph.compile()

    async def _intent_node(self, state: AgentState) -> AgentState:
        question = state["question"]
        history = state.get("messages", [])
        previous_message = history[-2] if len(history) >= 2 else {}
        if "订单号" in previous_message.get("content", "") and re.search(r"[Oo][A-Za-z0-9]{5,}", question):
            question = f"订单 {question}"
        intent, arguments = self._route(question, state["user_id"])
        tool_name = arguments.pop("_tool", "")
        return {
            "intent": intent,
            "slots": arguments,
            "tool_calls": [tool_name] if tool_name else [],
            "needs_clarification": intent == "clarify",
        }

    def _route_next(self, state: AgentState) -> str:
        return "clarify" if state.get("needs_clarification") else "execute"

    async def _clarify_node(self, state: AgentState) -> AgentState:
        missing = state.get("slots", {}).get("missing", "必要参数")
        return {"answer": f"为了继续查询，请提供{missing}。"}

    async def _execute_node(self, state: AgentState) -> AgentState:
        try:
            tool_name = state["tool_calls"][0]
            result = await self.tools[tool_name].ainvoke(state.get("slots", {}))
            sources = result.get("sources", []) if isinstance(result, dict) else []
            return {"result": result, "retrieved_docs": sources}
        except Exception as exception:
            return {"error": "工具调用失败，请稍后重试。", "result": {"detail": str(exception)}}

    async def _validate_node(self, state: AgentState) -> AgentState:
        if state.get("error"):
            return state
        result = state.get("result")
        if result is None:
            return {"error": "工具没有返回有效结果。"}
        return state

    async def _respond_node(self, state: AgentState) -> AgentState:
        if state.get("answer"):
            return state
        if state.get("error"):
            return {"answer": state["error"], "intent": "fallback"}
        answer = await self._answer(state["question"], state["intent"], state.get("result"))
        return {"answer": answer}

    async def _answer(self, question: str, intent: str, data: Any) -> str:
        if self.model:
            response = await self.model.ainvoke([
                SystemMessage(content="你是影院助手，只能根据工具结果回答，不得编造票务规则。"),
                HumanMessage(content=f"问题：{question}\n意图：{intent}\n工具结果：{data}"),
            ])
            if response.content:
                return str(response.content)
        if intent == "policy":
            contexts = data.get("answer_context", [])
            return "\n".join(contexts) if contexts else "未检索到匹配的规则，请以页面展示的最新规则为准。"
        if intent == "refund":
            status = data.get("order", {}).get("status", "未知") if isinstance(data, dict) else "未知"
            return f"订单当前状态为 {status}。退票资格请以返回的规则版本和开场时间校验结果为准。"
        if intent == "order":
            status = data.get("status", "未知") if isinstance(data, dict) else "未知"
            return f"已查询到订单，当前状态：{status}。"
        if intent == "recommend":
            return f"根据你的偏好，为你找到 {len(data)} 部候选影片。"
        if intent == "screenings":
            return f"已找到 {len(data)} 个可用场次。"
        return f"已找到 {len(data)} 部相关影片。"

    def _route(self, question: str, user_id: int) -> tuple[str, dict[str, Any]]:
        order_match = re.search(r"[Oo][A-Za-z0-9]{5,}", question)
        if any(word in question for word in ("退票", "退款", "退改")) and order_match:
            return "refund", {"_tool": "check_refund_eligibility", "order_no": order_match.group(), "user_id": user_id}
        if any(word in question for word in ("订单", "订单状态")) and not order_match:
            return "clarify", {"missing": "订单号"}
        if any(word in question for word in ("规则", "须知", "优惠", "会员", "退票")):
            return "policy", {"_tool": "query_ticket_policy", "question": question}
        if any(word in question for word in ("订单", "订单状态")) and order_match:
            return "order", {"_tool": "query_order", "order_no": order_match.group(), "user_id": user_id}
        if any(word in question for word in ("推荐", "喜欢", "适合")):
            return "recommend", {"_tool": "recommend_movies", "user_id": user_id, "preference": question}
        if any(word in question for word in ("场次", "排片", "几点", "影院")):
            return "screenings", {"_tool": "search_screenings"}
        return "movies", {"_tool": "search_movies", "query": question}


app = FastAPI(title="Cinema AI Assistant", version="0.1.0")
assistant = Assistant()


def verify_internal_token(x_internal_token: str = Header(default="")) -> None:
    """Require the shared service token for AI business endpoints."""
    if x_internal_token != INTERNAL_API_TOKEN:
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


@app.exception_handler(httpx.HTTPError)
async def handle_http_error(_, exception: httpx.HTTPError) -> JSONResponse:
    """Convert Java service failures into a stable AI error response."""
    return JSONResponse(status_code=502, content={"detail": f"Java API unavailable: {exception}"})
