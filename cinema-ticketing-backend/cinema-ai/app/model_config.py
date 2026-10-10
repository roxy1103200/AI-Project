"""Qwen model configuration; credentials stay in the Agent process."""

# 导入当前步骤使用的模块或类型。
# isort: off
import logging
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
import re
# 导入当前步骤使用的模块或类型。
from pathlib import Path

# 导入当前步骤使用的模块或类型。
from langchain_openai import ChatOpenAI
# isort: on

# 为 `ROOT` 保存当前步骤所需的值。
ROOT = Path(__file__).resolve().parent.parent
# 为 `LOGGER` 保存当前步骤所需的值。
LOGGER = logging.getLogger("uvicorn.error")
# 为 `DEFAULT_MODEL` 保存当前步骤所需的值。
DEFAULT_MODEL = "qwen3.7-flash"
# 为 `DEFAULT_BASE_URL` 保存当前步骤所需的值。
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# 声明当前处理单元及其入口。
def load_qwen_key() -> str:
    """Load one Qwen key from environment or the private project key file."""
    # 为 `key` 保存当前步骤所需的值。
    key = (os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    # 检查 `if key`，据此选择当前处理分支。
    if key:
        # 将当前计算结果返回给调用方。
        return key
    # 为 `path` 保存当前步骤所需的值。
    path = Path(os.getenv("QWEN_API_KEY_FILE") or "../../API/qwen.txt")
    # 检查 `if not path.is_absolute()`，据此选择当前处理分支。
    if not path.is_absolute():
        # 为 `path` 保存当前步骤所需的值。
        path = ROOT / path
    # 检查 `if not path.is_file()`，据此选择当前处理分支。
    if not path.is_file():
        # 将当前计算结果返回给调用方。
        return ""
    # 为 `content` 保存当前步骤所需的值。
    content = path.read_text(encoding="utf-8-sig").strip()
    # Accept a plain key or a key with a local label; never log file contents.
    # Provider keys may contain dots and base64 punctuation; preserve the entire token.
    # 为 `keys` 保存当前步骤所需的值。
    keys = set(re.findall(r"(?<![\w-])sk-[A-Za-z0-9._~+/=-]+", content))
    # 检查 `if len(keys) != 1`，据此选择当前处理分支。
    if len(keys) != 1:
        # 抛出当前异常，交由上层错误处理流程处理。
        raise ValueError("QWEN_API_KEY_FILE must contain exactly one Qwen API key")
    # 将当前计算结果返回给调用方。
    return keys.pop()


# 声明当前处理单元及其入口。
def create_model() -> ChatOpenAI | None:
    """Build the Qwen OpenAI-compatible client without making a network request."""
    # 为 `key` 保存当前步骤所需的值。
    key = load_qwen_key()
    # 检查 `if not key`，据此选择当前处理分支。
    if not key:
        # 执行当前异步调用或运行状态记录。
        LOGGER.info("Qwen key not configured; using factual result templates")
        # 将当前计算结果返回给调用方。
        return None
    # 为 `model_name` 保存当前步骤所需的值。
    model_name = (os.getenv("QWEN_MODEL") or DEFAULT_MODEL).strip()
    # 为 `base_url` 保存当前步骤所需的值。
    base_url = (os.getenv("QWEN_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    # 为 `thinking` 保存当前步骤所需的值。
    thinking = os.getenv("QWEN_ENABLE_THINKING", "false").strip().lower() == "true"
    # 为 `max_tokens` 保存当前步骤所需的值。
    max_tokens = max(128, min(8192, int(os.getenv("QWEN_MAX_TOKENS", "2048"))))
    # 为 `model` 保存当前步骤所需的值。
    model = ChatOpenAI(
        # 为 `model` 保存当前步骤所需的值。
        model=model_name,
        # 为 `api_key` 保存当前步骤所需的值。
        api_key=key,
        # 为 `base_url` 保存当前步骤所需的值。
        base_url=base_url,
        # 为 `temperature` 保存当前步骤所需的值。
        temperature=0,
        # 为 `max_tokens` 保存当前步骤所需的值。
        max_tokens=max_tokens,
        # 为 `timeout` 保存当前步骤所需的值。
        timeout=30,
        # 为 `max_retries` 保存当前步骤所需的值。
        max_retries=1,
        # 为 `extra_body` 保存当前步骤所需的值。
        extra_body={"enable_thinking": thinking},
        # 为 `stream_usage` 保存当前步骤所需的值。
        stream_usage=False,
    )
    # 执行当前异步调用或运行状态记录。
    LOGGER.info("Internal Agent model: %s; thinking=%s", model_name, thinking)
    # 将当前计算结果返回给调用方。
    return model
