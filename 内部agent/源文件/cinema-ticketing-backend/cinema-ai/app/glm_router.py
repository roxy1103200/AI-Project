"""Bounded GLM-4.7-Flash intent extraction before the full Qwen understanding."""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import APITimeoutError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from app.agent_budget import CircuitOpen
from app.query_semantics import policy_kind, prose, query_domains
from app.versions import ROOT, load_prompt

LOGGER = logging.getLogger("uvicorn.error")
_LIMITERS: WeakKeyDictionary[Any, asyncio.Semaphore] = WeakKeyDictionary()
_COOLDOWN_UNTIL = 0.0


def timeout_seconds() -> float:
    """Use a bounded configurable deadline; never let L1 consume the whole task."""
    return max(1.0, min(8.0, float(os.getenv("GLM_L1_TIMEOUT_SECONDS", "6"))))


class GlmPrediction(BaseModel):
    """Do not let a classifier supply identity, business IDs, dates or tool calls."""

    model_config = ConfigDict(extra="forbid", strict=True)
    accept: bool
    intent: Literal["movies", "screenings", "seats", "order", "refund", "policy", "recommend", "chat", "unsupported"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    movie_query: str = Field(max_length=120)
    cinema_query: str = Field(max_length=120)
    preference: str = Field(max_length=120)
    movie_scope: Literal["catalog", "showing", "scheduled"]
    screening_scope: Literal["scheduled", "bookable"]
    showing_only: bool
    multiple_tasks: bool
    general_listing: bool


def load_glm_key() -> str:
    """Read a plain or labeled server-only credential without logging its contents."""
    key = os.getenv("GLM_API_KEY", "").strip()
    if key:
        return key
    path = Path(os.getenv("GLM_API_KEY_FILE", "../../api/glm.txt"))
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8-sig").strip()
    if re.fullmatch(r"[A-Za-z0-9._~+/=-]{20,512}", text):
        return text
    candidates = re.findall(r"(?:GLM_API_KEY|api_key|密钥)\s*[:：=]\s*[\"']?([A-Za-z0-9._~+/=-]{20,512})", text, re.I)
    if len(set(candidates)) != 1:
        raise ValueError("GLM_API_KEY_FILE must contain exactly one credential")
    return candidates[0]


def create_glm_model() -> ChatOpenAI | None:
    """Construct a no-retry client on the documented provider endpoint."""
    if os.getenv("GLM_L1_ENABLED", "true").lower() != "true":
        return None
    try:
        key = load_glm_key()
        if not key:
            return None
        base = os.getenv("GLM_API_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme != "https" or parsed.netloc != "open.bigmodel.cn" or parsed.path != "/api/paas/v4":
            raise ValueError("GLM credentials require the official API endpoint")
        return ChatOpenAI(
            model="glm-4.7-flash",
            api_key=key,
            base_url=base,
            temperature=0,
            timeout=timeout_seconds(),
            max_retries=0,
            max_tokens=320,
            extra_body={"thinking": {"type": "disabled"}},
            stream_usage=False,
        )
    except (OSError, ValueError):
        LOGGER.warning("GLM classifier configuration unavailable; preserving Qwen fallback")
        return None


def eligible(question: str, history: list[dict[str, str]], rules: Any, reason: str) -> bool:
    """Bypass L1 for compound work, context resolution and unsupported sources."""
    if reason in ("composite_requires_understanding", "context_requires_understanding"):
        return False
    if history or policy_kind(question) != "ticket_policy":
        return False
    if rules.intent in ("policy", "refund", "recommend", "chat"):
        return False
    return not re.search(
        r"再|顺便|同时|以及|并且|连.{0,3}座|连着|挨着|比较|排序|超过|小于|大于|筛选|最便宜|最早|直接.*(?:下单|支付)",
        prose(question),
    )


def apply_prediction(prediction: GlmPrediction, rules: Any, question: str, threshold: float) -> Any | None:
    """Accept only a grounded single task and preserve deterministic scope constraints."""
    if not prediction.accept or prediction.multiple_tasks or prediction.confidence < threshold:
        return None
    if prediction.intent not in ("movies", "screenings", "seats", "order"):
        return None
    if len(query_domains(question, bool(rules.order_no)) - {"general_policy"}) > 1:
        return None
    if any(
        value and (value not in question or value == question)
        for value in (prediction.movie_query, prediction.cinema_query, prediction.preference)
    ):
        return None
    if prediction.intent == "order" and not rules.order_no:
        return None
    if prediction.intent == "seats" and not rules.screening_id:
        return None
    if (
        prediction.intent == "movies"
        and not prediction.movie_query
        and not rules.movie_query
        and (not prediction.general_listing or not re.search(r"所有|全部|有哪些|几部|啥片|什么片|哪些", question))
    ):
        return None
    if rules.movie_query and prediction.movie_query not in ("", rules.movie_query):
        return None
    if (
        rules.intent in ("movies", "screenings")
        and rules.movie_scope != "catalog"
        and (prediction.intent != rules.intent or prediction.movie_scope != rules.movie_scope)
    ):
        return None
    if any(
        value in {"电影", "影片", "上映", "场次", "影院", "今天", "明天", "后天"}
        for value in (prediction.movie_query, prediction.cinema_query)
    ):
        return None
    if prediction.showing_only and not rules.showing_only:
        return None
    if rules.intent == "screenings" and prediction.intent != "screenings":
        return None
    if rules.intent == "screenings" and prediction.screening_scope != rules.screening_scope:
        return None
    if prediction.intent == "screenings" and not (
        rules.screening_date
        or prediction.movie_query
        or rules.movie_query
        or prediction.cinema_query
        or prediction.general_listing
    ):
        return None
    updates = prediction.model_dump(exclude={"accept", "multiple_tasks", "general_listing"})
    updates["movie_query"] = rules.movie_query or prediction.movie_query
    return rules.model_copy(update=updates)


async def classify(model: Any, question: str, rules: Any) -> tuple[Any | None, str, float]:
    """Attempt once; account the attempt upstream even when rejecting its output."""
    started = time.monotonic()
    global _COOLDOWN_UNTIL
    if started < _COOLDOWN_UNTIL:
        return None, "cooldown", 0.0
    semaphore = _LIMITERS.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(1))
    if semaphore.locked():
        return None, "busy", 0.0
    await semaphore.acquire()
    try:
        # The classifier does not need raw order numbers or authenticated identity.
        masked = re.sub(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])", "[订单号]", question)
        async with asyncio.timeout(timeout_seconds()):
            response = await model.bind(
                response_format={"type": "json_object"},
                max_tokens=320,
                extra_body={"thinking": {"type": "disabled"}},
                timeout=timeout_seconds(),
            ).ainvoke([SystemMessage(content=load_prompt("glm_router")), HumanMessage(content=masked)])
        if getattr(response, "tool_calls", None) or getattr(response, "invalid_tool_calls", None):
            raise ValueError("Classifier cannot call tools")
        prediction = GlmPrediction.model_validate_json(str(response.content))
        threshold = max(0.85, min(1.0, float(os.getenv("GLM_L1_THRESHOLD", "0.90"))))
        accepted = apply_prediction(prediction, rules, question, threshold)
        return accepted, "accepted" if accepted else "rejected", (time.monotonic() - started) * 1000
    except CircuitOpen:
        return None, "budget_open", (time.monotonic() - started) * 1000
    except RateLimitError as exc:
        _COOLDOWN_UNTIL = time.monotonic() + 30
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error", body)
        code = str(error.get("code", "")) if isinstance(error, dict) else ""
        LOGGER.warning(
            "GLM routing rate limited; cooldown=30s code=%s", code if re.fullmatch(r"\d{3,6}", code) else "unknown"
        )
        return None, "rate_limited", (time.monotonic() - started) * 1000
    except (TimeoutError, APITimeoutError):
        _COOLDOWN_UNTIL = time.monotonic() + 10
        return None, "timeout", (time.monotonic() - started) * 1000
    except Exception as exc:
        LOGGER.warning("GLM routing unavailable: %s", type(exc).__name__)
        return None, "unavailable", (time.monotonic() - started) * 1000
    finally:
        semaphore.release()
