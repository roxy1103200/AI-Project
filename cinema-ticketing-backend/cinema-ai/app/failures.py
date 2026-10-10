"""Safe error categories without exposing credentials or conversation contents."""

import logging

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from app.tracing import current_trace_id, record_failure

LOGGER = logging.getLogger("uvicorn.error")


class CinemaQueryError(Exception):
    """Safe business failure received through MCP, without upstream details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def describe_failure(exception: Exception, stage: str) -> tuple[str, str]:
    """Log only error type/status and return a stable, user-readable failure."""
    # MCP transport task groups can wrap the original HTTP exception.
    while isinstance(exception, ExceptionGroup):
        exception = exception.exceptions[0]
    status = getattr(exception, "status_code", None)
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
    LOGGER.warning(
        "Agent failure stage=%s type=%s status=%s trace_id=%s",
        stage,
        type(exception).__name__,
        status,
        current_trace_id(),
    )
    code, message = _failure_details(exception, status)
    record_failure(stage, exception, code, status)
    return code, message


def _failure_details(exception: Exception, status: int | None) -> tuple[str, str]:
    """Map upstream exceptions to the existing public error contract."""
    if isinstance(exception, CinemaQueryError):
        return exception.code, str(exception)
    if isinstance(exception, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return "query_timeout", "实时查询超时，请稍后重试。"
    if isinstance(exception, (APIConnectionError, httpx.RequestError)):
        return "service_unreachable", "无法连接实时查询服务，请检查服务网络后重试。"
    if isinstance(exception, APIStatusError):
        if status == 401:
            return "model_auth_failed", "Qwen 模型鉴权失败，请检查服务端密钥及对应地域的接口地址。"
        if status == 403:
            return "model_access_denied", "Qwen 模型访问被拒绝，请检查模型权限或服务开通状态。"
        if status == 429:
            return "model_rate_limited", "Qwen 模型请求受限，请稍后重试并检查服务额度。"
        if status in (400, 404):
            return "model_request_rejected", "Qwen 拒绝了模型请求，请检查模型名称和接口配置。"
        return "model_unavailable", "Qwen 模型服务暂时不可用，请稍后重试。"
    if isinstance(exception, httpx.HTTPStatusError):
        if status == 404:
            return "data_not_found", "没有找到可查询的记录，请检查影片或订单信息。"
        if status in (401, 403):
            return "business_auth_failed", "业务查询服务鉴权失败，请检查内部服务凭证。"
        return "business_unavailable", "业务查询服务暂时不可用，请稍后重试。"
    return "agent_error", "实时查询暂时失败，请稍后重试。"
