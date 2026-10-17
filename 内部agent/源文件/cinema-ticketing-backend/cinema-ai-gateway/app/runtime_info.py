"""Private, nonsecret gateway identity and a strict whitelist for Agent diagnostics."""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def source_digest(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.joinpath("app").rglob("*.py"), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


BUILD_ID = source_digest()
STARTED_AT = datetime.now(UTC).isoformat()


def runtime_info() -> dict[str, Any]:
    return {
        "component": "gateway",
        "build_id": BUILD_ID,
        "started_at": STARTED_AT,
        "contracts": {"order": "cinema-order-v2", "time": "cinema-time-v1", "sse": "cinema-sse-v1"},
        "workspace_changed": source_digest() != BUILD_ID,
    }


class TimeWindow(BaseModel):
    target: Literal["release", "screening", "unspecified"]
    status: Literal["resolved", "ambiguous", "invalid"]
    strength: Literal["hard", "soft"] = "hard"
    date_from: date | None = None
    date_to: date | None = None
    hour_from: int | None = Field(default=None, ge=0, le=23)
    hour_to: int | None = Field(default=None, ge=1, le=24)
    assumed_target: bool = False
    reason: Literal["none", "vague", "year_required", "invalid_date", "conflict", "target_required"] = "none"


class TemporalSummary(BaseModel):
    reference_date: date
    time_zone: Literal["Asia/Shanghai"]
    windows: list[TimeWindow] = Field(default_factory=list, max_length=12)


class RuntimeVersion(BaseModel):
    experiment_id: Literal["glm-l1-v1"]
    experiment_variant: Literal["A", "B"]
    prompt_version: str = Field(max_length=32, pattern=r"^[a-zA-Z0-9-]+$")
    rules_version: str = Field(max_length=32, pattern=r"^[a-zA-Z0-9-]+$")
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rules_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    configuration_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    l1_enabled: bool


def safe_diagnostics(packet: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, schema in (("temporal_summary", TemporalSummary), ("runtime_version", RuntimeVersion)):
        try:
            result[key] = schema.model_validate(packet.get(key)).model_dump(mode="json")
        except ValidationError:
            pass
    for key in ("tool_call_count", "step_count", "invalid_call_count", "model_call_count"):
        value = packet.get(key)
        if type(value) is int and 0 <= value <= 100:
            result[key] = value
    usage = packet.get("token_usage")
    if isinstance(usage, dict):
        result["token_usage"] = {
            key: value
            for key, value in usage.items()
            if key in {"input_tokens", "output_tokens", "total_tokens", "usage_missing_calls"}
            and type(value) is int
            and 0 <= value <= 1000000
        }
    return result
