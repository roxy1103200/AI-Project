"""Async public gateway: Dify FAQ traffic and model streams bypass Java."""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager, suppress
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.config import (
    AGENT_API_URL, DIFY_API_BASE_URL, DIFY_API_KEY, INTERNAL_TOKEN, JAVA_API_URL, MAX_STREAMS,
)
from app.protocol import event, read_events
from app.feedback import FeedbackInput, Snapshot, submit
from app.store import ConversationStore, Session

COOKIE_NAME = "cinema_ai_session"
MAX_ANSWER_SIZE = 40_000
LOGGER = logging.getLogger("uvicorn.error")

class ChatRequest(BaseModel):
    """Browser request without a user ID, Dify key, or Dify conversation ID."""

    sessionId: uuid.UUID
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["dify", "agent"] = "dify"
    credential: str = Field(default="", max_length=72)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Share bounded connection pools and close them at process shutdown."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90, connect=5),
        limits=httpx.Limits(max_connections=MAX_STREAMS + 8, max_keepalive_connections=16),
    ) as client, httpx.AsyncClient(
        timeout=httpx.Timeout(90, connect=5),
        limits=httpx.Limits(max_connections=MAX_STREAMS + 8, max_keepalive_connections=16),
        trust_env=False,
    ) as internal_client:
        store = ConversationStore()
        app.state.client = client
        # Java and the private Agent must not traverse environment or Windows system proxies.
        app.state.internal_client = internal_client
        app.state.store = store
        try:
            await store.redis.ping()
            await store.auth.ping()
            yield
        finally:
            await store.close()


app = FastAPI(title="Cinema AI Gateway", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RedisError)
async def storage_failure(request: Request, exception: RedisError) -> JSONResponse:
    """Fail closed when shared authorization or session storage is unavailable."""
    LOGGER.error("Shared AI storage unavailable: %s", type(exception).__name__)
    return JSONResponse(status_code=503, content={"detail": "聊天会话存储暂不可用，请稍后重试"})


def same_site(request: Request) -> None:
    """Reject cross-site requests carrying tab credentials."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "请从影院页面发起请求")


async def require_session(request: Request) -> Session:
    """Recheck the current tab's token, binding and expected conversation."""
    same_site(request)
    try:
        expected = str(uuid.UUID(request.headers.get("X-AI-Conversation", "")))
    except ValueError as exc:
        raise HTTPException(400, "缺少有效的当前对话标识，请重新连接") from exc
    tab_key = request.headers.get("X-AI-Session", "")
    if len(tab_key) > 64:
        raise HTTPException(400, "助手会话凭证格式错误")
    return await request.app.state.store.resolve(tab_key, request.headers.get("X-Auth-Token", ""), expected)


@app.get("/ai-gateway/session")
async def session_info(request: Request, response: Response) -> dict[str, object]:
    """Restore this tab or authenticated account without trusting a shared cookie."""
    same_site(request)
    store = request.app.state.store
    tab_key = request.headers.get("X-AI-Session", "")
    if len(tab_key) > 64:
        raise HTTPException(400, "助手会话凭证格式错误")
    session = await store.open(tab_key, request.headers.get("X-Auth-Token", ""))
    # Retire the legacy browser-wide credential; it is never read for authorization.
    response.delete_cookie(COOKIE_NAME, path="/ai-gateway")
    response.headers["Cache-Control"] = "no-store"
    return {"sessionId": session.chat_id, "bindingKey": session.browser_key, "difyReady": bool(DIFY_API_KEY), "agentReadOnly": True,
            "accountBound": bool(session.owner_id), "busy": await store.busy(session),
            "messages": await store.history(session)}


@app.post("/ai-gateway/reset")
async def reset_session(request: Request) -> dict[str, str]:
    """Begin a fresh shared account conversation after the active turn ends."""
    session = await require_session(request)
    current = await request.app.state.store.reset(session)
    return {"sessionId": current.chat_id}


async def stop_dify(client: httpx.AsyncClient, session: Session, store: ConversationStore) -> None:
    """Best-effort stop of cloud generation when the browser cancels its stream."""
    if session.task_id:
        task_id, session.task_id = session.task_id, ""
        await store.clear_task(session, task_id)
        try:
            await client.post(f"{DIFY_API_BASE_URL}/chat-messages/{task_id}/stop",
                              headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
                              json={"user": f"cinema-{session.chat_id}"}, timeout=5)
        except httpx.HTTPError:
            pass


@app.post("/ai-gateway/stop")
async def stop(request: Request) -> dict[str, bool]:
    """Cancel the current Dify task without exposing its ID to the browser."""
    session = await require_session(request)
    await request.app.state.store.cancel(session)
    await stop_dify(request.app.state.client, session, request.app.state.store)
    return {"stopped": True}


async def dify_events(client: httpx.AsyncClient, session: Session, question: str, record: Snapshot, store: ConversationStore) -> AsyncIterator[str]:
    """Translate Chatbot SSE deltas into the project's browser protocol."""
    payload = {"inputs": {}, "query": question, "response_mode": "streaming",
               "user": f"cinema-{session.chat_id}", "conversation_id": session.conversation_id}
    answer = ""
    finished = False
    try:
        async with client.stream("POST", f"{DIFY_API_BASE_URL}/chat-messages", json=payload,
                                 headers={"Authorization": f"Bearer {DIFY_API_KEY}"}) as upstream:
            upstream.raise_for_status()
            async for packet in read_events(upstream):
                message_id = packet.get("message_id")
                if not message_id and not record.provider_message_id and packet.get("event") == "message_end":
                    message_id = packet.get("id")
                if message_id:
                    record.provider_message_id = str(uuid.UUID(str(message_id)))
                previous = (session.task_id, session.conversation_id)
                session.task_id = packet.get("task_id") or session.task_id
                session.conversation_id = packet.get("conversation_id") or session.conversation_id
                if previous != (session.task_id, session.conversation_id):
                    await store.update(session)
                kind = packet.get("event")
                if kind in ("message", "agent_message"):
                    text = packet.get("answer", "")
                    answer += text
                    if len(answer) > MAX_ANSWER_SIZE:
                        raise ValueError("Answer exceeded size limit")
                    yield event("delta", text=text)
                elif kind == "message_replace":
                    answer = str(packet.get("answer", ""))[:MAX_ANSWER_SIZE]
                    yield event("replace", text=answer)
                elif kind == "error":
                    raise ValueError("Dify reported a generation error")
                elif kind == "message_end":
                    if not answer.strip():
                        raise ValueError("Dify returned an empty answer")
                    finished = True
                    task_id, session.task_id = session.task_id, ""
                    await store.clear_task(session, task_id)
                    # An optional project JSON contract can be implemented in the Dify prompt.
                    try:
                        structured = json.loads(answer)
                    except json.JSONDecodeError:
                        structured = None
                    if isinstance(structured, dict) and isinstance(structured.get("answer"), str):
                        yield event("replace", text=structured["answer"][:MAX_ANSWER_SIZE])
                        yield event("complete", handoffSuggested=structured.get("handoffSuggested") is True)
                    else:
                        yield event("complete", handoffSuggested=False)
                    return
        raise ValueError("Dify stream ended before completion")
    finally:
        if not finished:
            await stop_dify(client, session, store)


async def agent_events(client: httpx.AsyncClient, session: Session, body: ChatRequest, record: Snapshot, store: ConversationStore) -> AsyncIterator[str]:
    """Resolve the login-bound credential, then stream the private read-only Agent."""
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    resolved = await client.post(f"{JAVA_API_URL}/internal/ai/handoff/resolve", headers=headers,
                                 json={"credential": body.credential}, timeout=8)
    if resolved.status_code in (400, 401, 403):
        yield event("error", message="登录或转接已过期，请重新登录后转接", code="handoff_expired")
        return
    resolved.raise_for_status()
    identity = resolved.json()
    if identity.get("sessionId") != session.chat_id or identity.get("scope") != "cinema:read":
        yield event("error", message="转接凭证与当前对话不匹配，请重新转接", code="handoff_expired")
        return
    if not session.owner_id or identity["userId"] != session.owner_id:
        yield event("error", message="请登录当前账户后重新转接", code="handoff_expired")
        return
    history = await store.history(session)
    payload = {"user_id": identity["userId"], "session_id": session.chat_id, "question": body.question,
               "history": [{"role": item["role"], "content": item["content"][:2000]} for item in history if item.get("content") and not item.get("failed")][-10:]}
    record.user_id = identity["userId"]
    async with client.stream("POST", f"{AGENT_API_URL}/ai/live", headers=headers, json=payload) as upstream:
        upstream.raise_for_status()
        completed = False
        answer_size = 0
        async for packet in read_events(upstream):
            kind = packet.get("type")
            if kind == "delta":
                text = str(packet.get("text", ""))
                answer_size += len(text)
                if answer_size > MAX_ANSWER_SIZE:
                    raise ValueError("Agent answer exceeded size limit")
                yield event("delta", text=text)
            elif kind == "context":
                record.context = {key: packet.get(key) for key in ("intent", "normalized_question", "confidence", "intent_source", "entities", "tool_calls")}
                yield event("context", normalized_question=str(packet.get("normalized_question", ""))[:1000])
            elif kind == "status":
                yield event("status", message=str(packet.get("message", ""))[:200])
            elif kind == "error":
                # Only forward errors from the private Agent's explicit safe-code contract.
                safe_codes = {"model_auth_failed", "model_access_denied", "model_rate_limited", "model_request_rejected",
                              "model_unavailable", "query_timeout", "service_unreachable", "data_not_found",
                              "business_auth_failed", "business_unavailable", "agent_error"}
                code = packet.get("code", "agent_error")
                message = packet.get("message", "实时查询暂时失败，请稍后重试")
                yield event("error", code=code if code in safe_codes else "agent_error",
                            message=str(message)[:240] if code in safe_codes else "实时查询暂时失败，请稍后重试")
                return
            elif kind == "complete":
                completed = True
                yield event("complete", handoffSuggested=False)
        if not completed:
            raise ValueError("Agent stream ended before completion")


def describe_gateway_failure(exception: Exception, mode: str) -> tuple[str, str]:
    """Record a safe failure stage and return a useful message without private request data."""
    stage = "conversation" if isinstance(exception, RedisError) else "stream"
    status = None
    if isinstance(exception, httpx.HTTPError):
        # Only fixed route categories are logged, never raw URLs, headers or response bodies.
        try:
            path = exception.request.url.path
        except RuntimeError:
            path = ""
        stage = {
            "/internal/ai/handoff/resolve": "handoff_resolution",
            "/ai/live": "agent_stream",
        }.get(path, "dify_stream" if mode == "dify" else "agent_stream")
        if isinstance(exception, httpx.HTTPStatusError):
            status = exception.response.status_code
    LOGGER.warning("AI gateway failure provider=%s stage=%s type=%s status=%s",
                   mode, stage, type(exception).__name__, status)
    if isinstance(exception, RedisError):
        return "conversation_storage_failed", "聊天记录服务暂时不可用，请稍后恢复聊天。"
    if isinstance(exception, (httpx.TimeoutException, TimeoutError)):
        return "upstream_timeout", "实时 Agent 回答超时，请稍后重试。" if mode == "agent" else "智能助手回答超时，请稍后重试。"
    if mode == "agent":
        if stage == "handoff_resolution":
            return "handoff_service_unavailable", "实时 Agent 的转接服务暂时不可用，请稍后重新转接。"
        if isinstance(exception, httpx.HTTPError):
            return "agent_service_unavailable", "实时 Agent 暂时无法连接，请稍后重试。"
        return "agent_response_invalid", "实时 Agent 回答连接异常，请重试问题。"
    return "dify_service_unavailable", "智能助手暂时无法响应，请稍后重试或转接实时 Agent。"


@app.post("/ai-gateway/chat")
async def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream using Redis-wide identity, conversation leases and rate limits."""
    session = await require_session(request)
    store = request.app.state.store
    if str(body.sessionId) != session.chat_id:
        raise HTTPException(409, "聊天已在另一设备更新，请点击恢复聊天")
    if not body.question.strip():
        raise HTTPException(400, "请输入问题")
    if body.mode == "dify" and not DIFY_API_KEY:
        raise HTTPException(503, "Dify 尚未配置，可以登录后转接实时 Agent")
    if body.mode == "agent" and not body.credential:
        raise HTTPException(401, "请先登录并选择转接实时 Agent")
    await store.rate("chat:" + session.chat_id, 12)
    lease = await store.acquire(session)
    record = Snapshot(session_id=session.chat_id, provider=body.mode.upper(), question=body.question, user_id=session.owner_id or None)

    async def events() -> AsyncIterator[str]:
        completed = ""
        storage_error = False
        owner_task = asyncio.current_task()

        async def watch_stop() -> None:
            while True:
                await asyncio.sleep(.5)
                if await store.cancelled(session):
                    if owner_task:
                        owner_task.cancel()
                    return

        watcher = asyncio.create_task(watch_stop())
        try:
            yield event("message", messageId=record.message_id)
            yield event("status", message="正在查询实时业务数据…" if body.mode == "agent" else "智能助手正在回答…")
            # A crashed worker may have left a cloud task; stop it before starting this turn.
            if session.task_id:
                await stop_dify(request.app.state.client, session, store)
            upstream = (agent_events(request.app.state.internal_client, session, body, record, store) if body.mode == "agent"
                        else dify_events(request.app.state.client, session, body.question, record, store))
            async with asyncio.timeout(90), aclosing(upstream):
                async for packet in upstream:
                    record.observe(packet)
                    kind = json.loads(packet.removeprefix("data: ").strip()).get("type")
                    if kind == "complete":
                        completed = packet
                    else:
                        if kind == "error":
                            await store.save_snapshot(record)
                        yield packet
        except asyncio.CancelledError:
            record.error_code = record.error_code or "interrupted"
            record.ready = True
            if not record.answer:
                record.answer = "已停止回答。"
        except (httpx.HTTPError, ValueError, KeyError, TypeError, TimeoutError, RedisError) as exc:
            code, message = describe_gateway_failure(exc, body.mode)
            packet = event("error", message=message, code=code)
            record.observe(packet)
            with suppress(RedisError):
                await store.save_snapshot(record)
            yield packet
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError, RedisError):
                await watcher
            if not record.ready:
                record.error_code, record.ready = "interrupted", True
            async def finalize() -> None:
                try:
                    await store.finish(session, record)
                finally:
                    await store.release(session, lease)
            try:
                await asyncio.shield(finalize())
            except RedisError as exc:
                LOGGER.error("Conversation persistence failed: %s", type(exc).__name__)
                storage_error = True
        if storage_error:
            yield event("error", message="回答已生成，但聊天记录未能保存，请稍后恢复聊天", code="conversation_storage_failed")
        elif record.error_code == "interrupted":
            yield event("error", message="已停止回答，可重新输入问题", code="interrupted")
        elif completed:
            yield completed

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/ai-gateway/feedback")
async def feedback(request: Request, body: FeedbackInput) -> dict[str, object]:
    """Save trusted feedback on any worker with a shared serialization lease."""
    session = await require_session(request)
    store = request.app.state.store
    record = await store.snapshot(str(body.messageId))
    if record is None:
        raise HTTPException(410, "这条回答的反馈入口已过期，请重新提问")
    if record.session_id != session.chat_id:
        raise HTTPException(403, "无法评价其他对话的消息")
    if not record.ready:
        raise HTTPException(409, "请等待回答结束后再评价")
    await store.rate("feedback:" + session.chat_id, 20)
    lock = await store.feedback_lock(record)
    try:
        result = await submit(request.app.state.client, record, body)
        record.feedback = {"rating": body.rating, "reason": body.reason if body.rating == "dislike" else None,
                           "content": body.content.strip() if body.rating == "dislike" else ""}
        await store.save_snapshot(record)
        return result
    finally:
        await store.feedback_unlock(record, lock)
