"""Qwen model configuration; credentials stay in the Agent process."""

import logging
import os
import re
from pathlib import Path

from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parent.parent
LOGGER = logging.getLogger("uvicorn.error")
DEFAULT_MODEL = "qwen3.7-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def load_qwen_key() -> str:
    """Load one Qwen key from environment or the private project key file."""
    key = (os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if key:
        return key
    path = Path(os.getenv("QWEN_API_KEY_FILE") or "../../API/qwen.txt")
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        return ""
    content = path.read_text(encoding="utf-8-sig").strip()
    # Accept a plain key or a key with a local label; never log file contents.
    # Provider keys may contain dots and base64 punctuation; preserve the entire token.
    keys = set(re.findall(r"(?<![\w-])sk-[A-Za-z0-9._~+/=-]+", content))
    if len(keys) != 1:
        raise ValueError("QWEN_API_KEY_FILE must contain exactly one Qwen API key")
    return keys.pop()


def create_model() -> ChatOpenAI | None:
    """Build the Qwen OpenAI-compatible client without making a network request."""
    key = load_qwen_key()
    if not key:
        LOGGER.info("Qwen key not configured; using factual result templates")
        return None
    model_name = (os.getenv("QWEN_MODEL") or DEFAULT_MODEL).strip()
    base_url = (os.getenv("QWEN_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    thinking = os.getenv("QWEN_ENABLE_THINKING", "false").strip().lower() == "true"
    max_tokens = max(128, min(8192, int(os.getenv("QWEN_MAX_TOKENS", "2048"))))
    model = ChatOpenAI(
        model=model_name,
        api_key=key,
        base_url=base_url,
        temperature=0,
        max_tokens=max_tokens,
        timeout=30,
        max_retries=1,
        extra_body={"enable_thinking": thinking},
        stream_usage=False,
    )
    LOGGER.info("Internal Agent model: %s; thinking=%s", model_name, thinking)
    return model
