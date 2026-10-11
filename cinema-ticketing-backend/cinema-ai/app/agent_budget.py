"""Request-local limits for all model calls, including understanding and reflection."""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any


def configured_limit(name: str, default: int, maximum: int) -> int:
    """Read a positive limit while retaining a code-enforced upper bound."""
    return max(1, min(maximum, int(os.getenv(name, str(default)))))


class CircuitOpen(RuntimeError):
    """An operation was refused before it could exceed a request limit."""


@dataclass
class RequestBudget:
    """Mutable accounting owned by one graph invocation, never by the shared model."""

    max_calls: int = 8
    max_tokens: int = 32768
    timeout_seconds: float = 65
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    missing_usage_calls: int = 0
    stop_reason: str = ""
    started: float = field(default_factory=time.monotonic)

    def trip(self, reason: str) -> None:
        """Latch the first circuit reason; later operations cannot reopen it."""
        if not self.stop_reason:
            self.stop_reason = reason

    def remaining_seconds(self) -> float:
        """Check the request deadline independently of graph recursion limits."""
        remaining = self.timeout_seconds - (time.monotonic() - self.started)
        if remaining <= 0:
            self.trip("timeout")
            raise CircuitOpen(self.stop_reason)
        if self.stop_reason:
            raise CircuitOpen(self.stop_reason)
        return remaining

    def reserve(self, input_bound: int, output_limit: int) -> None:
        """Reserve an entire call before sending it, including its maximum output."""
        self.remaining_seconds()
        if self.calls >= self.max_calls:
            self.trip("model_budget")
        elif self.input_tokens + self.output_tokens + input_bound + output_limit > self.max_tokens:
            self.trip("token_budget")
        if self.stop_reason:
            raise CircuitOpen(self.stop_reason)
        self.calls += 1
        self.input_tokens += input_bound
        self.output_tokens += output_limit

    def reconcile(self, response: Any, input_bound: int, output_limit: int) -> None:
        """Use provider usage when available; retain the reservation on unknown usage."""
        usage = getattr(response, "usage_metadata", None) or {}
        incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
        if type(incoming) is int and incoming >= 0 and type(outgoing) is int and outgoing >= 0:
            self.input_tokens += incoming - input_bound
            self.output_tokens += outgoing - output_limit
        else:
            self.missing_usage_calls += 1
        if self.input_tokens + self.output_tokens >= self.max_tokens:
            self.trip("token_budget")

    def snapshot(self) -> dict[str, Any]:
        """Expose bounded counters without credentials or business result bodies."""
        return {
            "model_call_count": self.calls,
            "token_usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.input_tokens + self.output_tokens,
                "usage_missing_calls": self.missing_usage_calls,
                "accounting": "conservative_reservation" if self.missing_usage_calls else "provider",
            },
        }


class BudgetedModel:
    """Wrap the existing model without losing bind/bind_tools or request isolation."""

    def __init__(
        self,
        inner: Any,
        budget: RequestBudget,
        stage: str,
        output_limit: int = 512,
        schema_bytes: int = 0,
    ) -> None:
        self.inner = inner
        self.budget = budget
        self.stage = stage
        self.output_limit = output_limit
        self.schema_bytes = schema_bytes

    def bind(self, **kwargs: Any) -> "BudgetedModel":
        """Retain call-specific output caps used by intent extraction and reflection."""
        output_limit = min(self.output_limit, int(kwargs.get("max_tokens", self.output_limit)))
        kwargs["max_tokens"] = output_limit
        return BudgetedModel(self.inner.bind(**kwargs), self.budget, self.stage, output_limit, self.schema_bytes)

    def bind_tools(self, schemas: list[dict[str, Any]], **kwargs: Any) -> "BudgetedModel":
        """Account for the schema context as well as the visible message content."""
        schema_bytes = len(json.dumps(schemas, ensure_ascii=False).encode("utf-8")) + 256
        inner = self.inner.bind_tools(schemas, **kwargs)
        return BudgetedModel(inner, self.budget, self.stage, self.output_limit, schema_bytes)

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> Any:
        """Count attempted calls and refuse new work once any circuit is open."""
        # UTF-8 bytes plus message/schema framing conservatively reserve token usage.
        input_bound = (
            self.schema_bytes
            + 256
            + sum(
                len(json.dumps(message.model_dump(), ensure_ascii=False, default=str).encode("utf-8")) + 64
                for message in messages
            )
        )
        self.budget.reserve(input_bound, self.output_limit)
        config = dict(kwargs.pop("config", {}) or {})
        config["metadata"] = {**config.get("metadata", {}), "agent_stage": self.stage}
        try:
            async with asyncio.timeout(min(20, self.budget.remaining_seconds())):
                response = await self.inner.ainvoke(messages, config=config, **kwargs)
        except asyncio.CancelledError:
            # Covers upstream extraction deadlines as well as a disconnected client.
            self.budget.missing_usage_calls += 1
            self.budget.trip("timeout")
            raise
        except TimeoutError:
            self.budget.missing_usage_calls += 1
            self.budget.trip("timeout")
            raise
        except Exception:
            self.budget.missing_usage_calls += 1
            raise
        self.budget.reconcile(response, input_bound, self.output_limit)
        return response
