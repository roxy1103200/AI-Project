"""Rebind held-out fixtures privately and force paired experiments in a local CLI."""

import copy
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def bind_cases(cases: list[dict[str, Any]], bindings: dict[str, str], metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace fixture identifiers recursively without serializing live bindings."""
    if set(bindings) != set(metadata["bindings_required_for_live"]):
        raise ValueError("Private bindings must cover exactly the frozen fixture identifiers")
    if any(
        not re.fullmatch(r"OGOLD\d{6}", key)
        or not isinstance(value, str)
        or not re.fullmatch(r"[Oo][A-Za-z0-9]{5,63}", value)
        for key, value in bindings.items()
    ):
        raise ValueError("Invalid fixture or development order identifier")
    if len(set(bindings.values())) != len(bindings):
        raise ValueError("Independent golden orders must not collapse into one binding")

    def replace(value: Any) -> Any:
        if isinstance(value, str):
            return re.sub(r"OGOLD\d{6}", lambda match: bindings.get(match[0], match[0]), value)
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return value

    return replace(copy.deepcopy(cases))


@contextmanager
def experiment_arm(arm: str) -> Iterator[None]:
    """Force only the sequential evaluator's server environment, then restore it."""
    if arm not in ("A", "B"):
        raise ValueError("Unknown experiment arm")
    previous = os.environ.get("AGENT_AB_FORCE_VARIANT")
    os.environ["AGENT_AB_FORCE_VARIANT"] = arm
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AGENT_AB_FORCE_VARIANT", None)
        else:
            os.environ["AGENT_AB_FORCE_VARIANT"] = previous
