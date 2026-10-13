"""Collect deidentified clarification/answer pairs locally as weak slot labels."""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("uvicorn.error")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "agent-feedback" / "clarifications.sqlite3"
SLOTS = frozenset({"order_no", "screening_id", "screening_date", "valid_date"})


def deidentify(text: str) -> str:
    """Retain language and intent cues, replacing identifiers and common secrets."""
    text = re.sub(r"(?i)Bearer\s+\S+|sk-[A-Za-z0-9._~+/=-]+", "[密钥]", text)
    text = re.sub(r"(?i)(?:api[_ -]?key|密钥|密码|password)\s*[:：=]\s*\S+", "[凭证]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[手机号]", text)
    numbers: dict[str, str] = {}

    def order(match: re.Match[str]) -> str:
        return numbers.setdefault(match[0], f"OGOLD{len(numbers) + 1:06d}")

    return re.sub(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])", order, text)[:4000]


def filled_slots(question: str, missing: list[str]) -> list[str]:
    """A reply must itself provide the value, independently of model extraction."""
    from app.intent import ORDER_PATTERN, SCREENING_PATTERN, beijing_today, explicit_date

    found = []
    if "order_no" in missing and ORDER_PATTERN.search(question):
        found.append("order_no")
    if "screening_id" in missing and SCREENING_PATTERN.search(question):
        found.append("screening_id")
    if any(slot in missing for slot in ("screening_date", "valid_date")):
        value = explicit_date(question, beijing_today())
        try:
            date.fromisoformat(value or "")
            found.extend(slot for slot in missing if slot in ("screening_date", "valid_date"))
        except ValueError:
            pass
    return sorted(found)


class ClarificationFeedback:
    """Persist same-user/session pairs; never auto-promote them into held-out gold."""

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        """Open a small bounded local store without business or provider credentials."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=0.25)
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE IF NOT EXISTS pending(session_ref TEXT PRIMARY KEY, created REAL, payload TEXT)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY, created REAL, payload TEXT, occurrences INTEGER DEFAULT 1, review_status TEXT DEFAULT 'silver')"
        )
        return connection

    def record(self, state: dict[str, Any]) -> None:
        """Resolve pending slot requests only after a verified subsequent query."""
        if os.getenv("CLARIFICATION_FEEDBACK_ENABLED", "true").lower() != "true":
            return
        session = hashlib.sha256(f"{state['user_id']}:{state['session_id']}".encode()).hexdigest()
        now = time.time()
        with closing(self.connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM pending WHERE created < ?", (now - 1800,))
            pending = connection.execute("SELECT payload FROM pending WHERE session_ref=?", (session,)).fetchone()
            if pending:
                saved = json.loads(pending["payload"])
                supplied = filled_slots(state["question"], saved["missing_slots"])
                verified = state.get("reflection_status") in ("passed", "rules_passed", "rules_empty")
                compatible = state.get("intent") == saved["intent"] or {state.get("intent"), saved["intent"]} <= {
                    "order",
                    "refund",
                }
                linked = any(
                    message.get("role") == "user" and deidentify(message.get("content", "")) == saved["question"]
                    for message in state.get("messages", [])[:-1]
                )
                if (
                    compatible
                    and linked
                    and supplied == saved["missing_slots"]
                    and verified
                    and not state.get("error")
                    and state.get("stop_reason") in ("simple_verified", "done_verified", "done_code_checked")
                ):
                    combined = deidentify(saved["question"] + "\n[REPLY]\n" + state["question"])
                    question, reply = combined.split("\n[REPLY]\n", 1)
                    scenario = hashlib.sha256((question + ":" + saved["intent"]).encode()).hexdigest()
                    identity = hashlib.sha256((combined + ":" + saved["intent"]).encode()).hexdigest()
                    candidate = {
                        "id": identity,
                        "scenario_id": scenario,
                        "question": question,
                        "reply": reply,
                        "intent": saved["intent"],
                        "filled_slots": supplied,
                        "label_source": "user_supplied_slot",
                        "label_quality": "silver",
                        "requires_review": True,
                        "original_version": saved.get("runtime_version", {}),
                        "resolved_version": state.get("runtime_version", {}),
                    }
                    connection.execute(
                        "INSERT INTO candidates(id,created,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET occurrences=occurrences+1",
                        (identity, now, json.dumps(candidate, ensure_ascii=False)),
                    )
                    connection.execute("DELETE FROM pending WHERE session_ref=?", (session,))
                elif not compatible:
                    connection.execute("DELETE FROM pending WHERE session_ref=?", (session,))
            missing = sorted(set(state.get("slot_summary", {}).get("missing_slots", [])) & SLOTS)
            if (
                state.get("stop_reason") == "needs_user"
                and missing
                and state.get("intent") in ("order", "refund", "seats", "screenings", "movies")
            ):
                payload = {
                    "question": deidentify(state["question"]),
                    "intent": state["intent"],
                    "missing_slots": missing,
                    "runtime_version": state.get("runtime_version", {}),
                }
                connection.execute(
                    "INSERT OR IGNORE INTO pending VALUES(?,?,?)",
                    (session, now, json.dumps(payload, ensure_ascii=False)),
                )
            connection.execute(
                "DELETE FROM candidates WHERE id IN (SELECT id FROM candidates ORDER BY created DESC LIMIT -1 OFFSET 50000)"
            )
            connection.execute(
                "DELETE FROM pending WHERE session_ref IN (SELECT session_ref FROM pending ORDER BY created DESC LIMIT -1 OFFSET 10000)"
            )


def record_feedback(state: dict[str, Any]) -> None:
    """Feedback I/O must never turn a successful cinema query into an error."""
    try:
        path = Path(os.getenv("CLARIFICATION_FEEDBACK_DB") or str(DEFAULT_PATH))
        ClarificationFeedback(path).record(state)
    except (OSError, sqlite3.Error, ValueError, KeyError):
        LOGGER.warning("Clarification feedback storage unavailable; query response preserved")
