"""Structured reflection with an extractive, code-checked answer boundary."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.versions import load_prompt

REFLECTION_PROMPT = load_prompt("reflection")


class ReflectionResult(BaseModel):
    """One verifier result; absent or malformed fields never imply success."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["complete", "missing", "unsupported", "pass", "revise", "uncertain"]
    missing_tasks: list[str] = Field(default_factory=list, max_length=30)
    missing_items: list[str] = Field(default_factory=list, max_length=30)
    unsupported_claims: list[str] = Field(default_factory=list, max_length=30)
    recommended_action: Literal["finish", "continue", "ask_user"] = "finish"
    revised_answer: str = Field(default="", max_length=48000)
    evidence_order: list[int] = Field(default_factory=list, max_length=30)


def grounded_revision(result: ReflectionResult, blocks: list[str]) -> str | None:
    """Only admit intact evidence blocks, preserving facts and record associations."""
    order = result.evidence_order or list(range(len(blocks)))
    if any(type(index) is not int for index in order) or sorted(order) != list(range(len(blocks))):
        return None
    answer = "\n\n".join(blocks[index] for index in order)

    def normalize(value: str) -> str:
        return re.sub(r"\s+", "", value)

    if result.revised_answer and normalize(result.revised_answer) != normalize(answer):
        return None
    return answer
