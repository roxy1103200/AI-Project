"""Pin prompts and fingerprint rules, with stable server-owned A/B assignment."""

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts" / "v1"
EXPERIMENT_ID = "glm-l1-v1"
PROMPT_VERSION = "cinema-p1"
RULES_VERSION = "cost-r1"
RULE_FILES = (
    "main.py",
    "mcp_server.py",
    "mcp_client.py",
    "java_client.py",
    "order_answers.py",
    "runtime_info.py",
    "time_normalization.py",
    "intent.py",
    "intent_routing.py",
    "query_semantics.py",
    "task_progress.py",
    "rule_verifier.py",
    "glm_router.py",
    "react_tools.py",
    "react_agent.py",
    "versions.py",
    "agent_budget.py",
    "reflection.py",
    "query_answers.py",
    "clarification_feedback.py",
)


@lru_cache(maxsize=1)
def prompt_bundle() -> dict[str, str]:
    """Pin the complete prompt bundle together, including lazily used prompts."""
    return {
        name: (PROMPTS / f"{name}.txt").read_text(encoding="utf-8").rstrip("\n")
        for name in ("understanding", "decision", "reflection", "glm_router")
    }


def load_prompt(name: str) -> str:
    """Load a checked-in prompt; request content cannot select arbitrary files."""
    if name not in ("understanding", "decision", "reflection", "glm_router"):
        raise ValueError("Unknown prompt name")
    return prompt_bundle()[name]


@lru_cache(maxsize=1)
def fingerprints() -> tuple[str, str]:
    """Pin one process to the source/prompt fingerprints it started with."""

    def digest(paths: list[Path]) -> str:
        hasher = hashlib.sha256()
        for path in sorted(paths):
            hasher.update(path.name.encode())
            hasher.update(path.read_bytes())
        return hasher.hexdigest()

    prompt_hash = hashlib.sha256(json.dumps(prompt_bundle(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return prompt_hash, digest([ROOT / "app" / name for name in RULE_FILES])


def runtime_version(user_id: int, session_id: str) -> dict[str, Any]:
    """Keep every turn of a trusted user's session in the same experiment arm."""
    profile = json.loads((ROOT / "config" / "agent_versions.json").read_text(encoding="utf-8"))
    if profile["experiment_id"] != EXPERIMENT_ID:
        raise ValueError("Unregistered experiment")
    enabled = os.getenv("AGENT_AB_ENABLED", "true").lower() == "true"
    share = max(0, min(100, int(os.getenv("AGENT_AB_B_PERCENT", str(profile["b_percent"])))))
    bucket = int(hashlib.sha256(f"{EXPERIMENT_ID}:{user_id}:{session_id}".encode()).hexdigest(), 16) % 100
    variant = "B" if not enabled or bucket < share else "A"
    forced = os.getenv("AGENT_AB_FORCE_VARIANT", "")
    if forced in ("A", "B"):
        variant = forced
    prompt_hash, rules_hash = fingerprints()
    configuration = {
        key: os.getenv(key, "")
        for key in (
            "GLM_L1_ENABLED",
            "GLM_L1_THRESHOLD",
            "GLM_L1_TIMEOUT_SECONDS",
            "AGENT_L0_ENABLED",
            "AGENT_RULE_VERIFIER_ENABLED",
            "AGENT_MAX_STEPS",
            "AGENT_MAX_MODEL_CALLS",
            "AGENT_MAX_TOTAL_TOKENS",
            "AGENT_MAX_SIMPLE_MODEL_CALLS",
            "AGENT_MAX_TOOL_CALLS",
            "AGENT_MAX_INVALID_CALLS",
            "AGENT_TIMEOUT_SECONDS",
            "INTENT_L1_ENABLED",
            "INTENT_L1_THRESHOLD",
            "QWEN_MODEL",
        )
    }
    configuration_hash = hashlib.sha256(
        json.dumps({"profile": profile, "environment": configuration}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "experiment_id": EXPERIMENT_ID,
        "experiment_variant": variant,
        "prompt_version": PROMPT_VERSION,
        "rules_version": RULES_VERSION,
        "prompt_hash": prompt_hash,
        "rules_hash": rules_hash,
        "configuration_hash": configuration_hash,
        "l1_enabled": variant == "B" and os.getenv("GLM_L1_ENABLED", "true").lower() == "true",
    }
