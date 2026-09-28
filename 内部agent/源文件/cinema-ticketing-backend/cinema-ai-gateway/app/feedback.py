"""Session-owned feedback snapshots; Java receives only explicitly rated messages."""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.config import DIFY_API_BASE_URL, DIFY_API_KEY, INTERNAL_TOKEN, JAVA_API_URL

SNAPSHOT_TTL = 7200
MAX_SNAPSHOTS = 1000
REASONS = {"misunderstood": "理解错误", "irrelevant": "答非所问", "inaccurate": "信息不准确",
           "outdated": "信息过时", "unresolved": "未解决问题", "error": "服务异常", "other": "其他"}


class FeedbackInput(BaseModel):
    """Accept a vote, never browser-supplied answer or user identity."""

    messageId: uuid.UUID
    rating: Literal["like", "dislike"] | None = None
    reason: Literal["misunderstood", "irrelevant", "inaccurate", "outdated", "unresolved", "error", "other"] | None = None
    content: str = Field(default="", max_length=500)


@dataclass
class Snapshot:
    """Bounded trusted answer context with an independent feedback mutation lock."""

    session_id: str
    provider: str
    question: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: float = field(default_factory=time.time)
    answer: str = ""
    provider_message_id: str = ""
    user_id: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    ready: bool = False
    truncated: bool = False
    feedback: dict[str, Any] = field(default_factory=dict)

    def observe(self, frame: str) -> None:
        """Retain only bounded normalized SSE payloads, excluding private tool results."""
        packet = json.loads(frame.removeprefix("data: ").strip())
        kind = packet.get("type")
        if kind == "delta":
            text = str(packet.get("text", ""))
            self.truncated = self.truncated or len(self.answer) + len(text) > 8000
            self.answer = (self.answer + text)[:8000]
        elif kind == "replace":
            text = str(packet.get("text", ""))
            self.truncated = len(text) > 8000
            self.answer = text[:8000]
        elif kind == "context":
            self.context.update({key: packet[key] for key in ("intent", "normalized_question", "confidence", "intent_source", "entities", "tool_calls") if key in packet})
        elif kind == "error":
            self.error_code = str(packet.get("code", "service_error"))[:64]
            if not self.answer:
                self.answer = str(packet.get("message", "回答未完成"))[:8000]
            self.ready = True
        elif kind == "complete":
            self.ready = True


async def submit(client: httpx.AsyncClient, record: Snapshot, body: FeedbackInput) -> dict[str, object]:
    """Save local feedback first, then report the actual Dify synchronization result."""
    rating = body.rating
    reason = body.reason if rating == "dislike" else None
    content = body.content.strip() if rating == "dislike" else ""
    context = record.context
    sync = "NOT_APPLICABLE" if record.provider == "AGENT" else "PENDING" if record.provider_message_id else "UNAVAILABLE"
    payload = {"messageId": record.message_id, "sessionId": record.session_id, "provider": record.provider,
               "providerMessageId": record.provider_message_id, "userId": record.user_id,
               "question": record.question, "answer": record.answer, "rating": rating, "reason": reason,
               "content": content, "syncStatus": sync, "errorCode": record.error_code,
               "normalizedQuestion": str(context.get("normalized_question", ""))[:1000],
               "intent": str(context.get("intent", ""))[:48], "confidence": context.get("confidence"),
               "intentSource": str(context.get("intent_source", ""))[:48],
               "entitiesJson": json.dumps(context.get("entities", {}), ensure_ascii=False)[:4000],
               "toolCallsJson": json.dumps(context.get("tool_calls", []), ensure_ascii=False)[:2000]}
    headers = {"X-Internal-Token": INTERNAL_TOKEN}
    try:
        saved = await client.post(f"{JAVA_API_URL}/internal/ai/feedback", headers=headers, json=payload, timeout=8)
        saved.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "反馈未保存，请稍后重试") from exc
    if sync == "PENDING":
        try:
            result = await client.post(f"{DIFY_API_BASE_URL}/messages/{record.provider_message_id}/feedbacks",
                                      headers={"Authorization": f"Bearer {DIFY_API_KEY}"},
                                      json={"rating": rating, "user": f"cinema-{record.session_id}",
                                            "content": "；".join(filter(None, (REASONS.get(reason, ""), content)))}, timeout=5)
            result.raise_for_status()
            sync = "SYNCED"
        except httpx.HTTPError:
            sync = "FAILED"
        try:
            updated = await client.post(f"{JAVA_API_URL}/internal/ai/feedback/{record.message_id}/sync",
                                        headers=headers, json={"status": sync}, timeout=8)
            updated.raise_for_status()
        except httpx.HTTPError:
            # The persistent PENDING state remains actionable in the admin page.
            return {"saved": True, "providerSync": sync, "syncRecorded": False}
    return {"saved": True, "providerSync": sync, "syncRecorded": True}
