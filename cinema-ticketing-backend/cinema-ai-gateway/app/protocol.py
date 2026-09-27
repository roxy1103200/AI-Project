"""Small SSE transport shared by Dify and the internal Agent adapters."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


def event(kind: str, **payload: Any) -> str:
    """Encode one normalized browser event."""
    return "data: " + json.dumps({"type": kind, **payload}, ensure_ascii=False) + "\n\n"


async def read_events(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Read complete SSE frames across network chunks, skipping heartbeat events."""
    data: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            value = line[5:].lstrip(" ")
            size += len(value)
            if size > 256_000:
                raise ValueError("Upstream event exceeded size limit")
            data.append(value)
        elif not line:
            if data:
                raw = "\n".join(data)
                data.clear()
                size = 0
                if raw == "[DONE]":
                    return
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    yield decoded
    if data:
        raw = "\n".join(data)
        if raw != "[DONE]":
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                yield decoded
