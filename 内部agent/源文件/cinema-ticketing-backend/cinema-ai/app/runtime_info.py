"""Nonsecret process identity and bounded private evidence for website regression."""

import hashlib
import json
import os
import time
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID: ContextVar[str] = ContextVar("website_request_id", default="")
CONTRACTS = {"order": "cinema-order-v2", "time": "cinema-time-v1", "sse": "cinema-sse-v1"}


def source_digest(root: Path = ROOT) -> str:
    """Hash executable source and public prompt/config artifacts, never local secrets."""
    paths = [*root.joinpath("app").rglob("*.py"), *root.joinpath("prompts").rglob("*.txt")]
    profile = root / "config/agent_versions.json"
    if profile.exists():
        paths.append(profile)
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


BUILD_ID = source_digest()
STARTED_AT = datetime.now(UTC).isoformat()
_EVIDENCE: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
_LOCK = Lock()


def runtime_info(component: str = "agent") -> dict[str, Any]:
    return {
        "component": component,
        "build_id": BUILD_ID,
        "started_at": STARTED_AT,
        "contracts": CONTRACTS.copy(),
        "time_zone": "Asia/Shanghai",
        "reference_date": datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
        "workspace_changed": source_digest() != BUILD_ID,
        "model": os.getenv("QWEN_MODEL", "qwen3.7-flash"),
    }


def observe(kind: str, **facts: Any) -> None:
    """Keep twenty bounded observations per authenticated service request for twenty minutes."""
    request_id = REQUEST_ID.get()
    if not request_id:
        return
    with _LOCK:
        now = time.monotonic()
        while _EVIDENCE and (len(_EVIDENCE) >= 1500 or next(iter(_EVIDENCE.values()))[0] < now - 1200):
            _EVIDENCE.popitem(last=False)
        _, rows = _EVIDENCE.setdefault(request_id, (now, []))
        if len(rows) < 20:
            encoded = json.dumps({"kind": kind, **facts}, ensure_ascii=False, default=str)
            if len(encoded) <= 12000:
                rows.append(json.loads(encoded))


def evidence(request_id: str, component: str = "agent") -> dict[str, Any]:
    with _LOCK:
        created, rows = _EVIDENCE.get(request_id, (0, []))
        selected = list(rows) if created >= time.monotonic() - 1200 else []
    return {"request_id": request_id, "runtime": runtime_info(component), "observations": selected}


class RequestContextMiddleware:
    """Propagate a server correlation ID across streaming tasks without mutable global headers."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw = dict(scope.get("headers", [])).get(b"x-trace-id", b"").decode("ascii", errors="ignore")
        try:
            request_id = uuid.UUID(raw).hex
        except ValueError:
            request_id = uuid.uuid4().hex
        marker = REQUEST_ID.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST_ID.reset(marker)
