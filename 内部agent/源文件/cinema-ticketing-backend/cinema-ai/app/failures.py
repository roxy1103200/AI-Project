"""Safe error categories without exposing credentials or conversation contents."""

# 导入当前步骤使用的模块或类型。
# isort: off
import logging

# 导入当前步骤使用的模块或类型。
import httpx
# 导入当前步骤使用的模块或类型。
from openai import APIConnectionError, APIStatusError, APITimeoutError

# 导入当前步骤使用的模块或类型。
from app.tracing import current_trace_id, record_failure
# isort: on

# 为 `LOGGER` 保存当前步骤所需的值。
LOGGER = logging.getLogger("uvicorn.error")


# 声明当前处理单元及其入口。
class CinemaQueryError(Exception):
    """Safe business failure received through MCP, without upstream details."""

    # 声明当前处理单元及其入口。
    def __init__(self, code: str, message: str) -> None:
        # 调用 `super` 执行当前业务操作。
        super().__init__(message)
        # 为 `self.code` 保存当前步骤所需的值。
        self.code = code


# 声明当前处理单元及其入口。
def describe_failure(exception: Exception, stage: str) -> tuple[str, str]:
    """Log only error type/status and return a stable, user-readable failure."""
    # MCP transport task groups can wrap the original HTTP exception.
    # 检查 `while isinstance(exception, ExceptionGroup)`，据此选择当前处理分支。
    while isinstance(exception, ExceptionGroup):
        # 为 `exception` 保存当前步骤所需的值。
        exception = exception.exceptions[0]
    # 为 `status` 保存当前步骤所需的值。
    status = getattr(exception, "status_code", None)
    # 检查 `if isinstance(exception, httpx.HTTPStatusError)`，据此选择当前处理分支。
    if isinstance(exception, httpx.HTTPStatusError):
        # 为 `status` 保存当前步骤所需的值。
        status = exception.response.status_code
    # 执行当前异步调用或运行状态记录。
    LOGGER.warning(
        # 补充当前表达式的 `"Agent failure stage=%s type=%s status=%s tr` 参数或元素。
        "Agent failure stage=%s type=%s status=%s trace_id=%s",
        # 补充当前表达式的 `stage` 参数或元素。
        stage,
        # 调用 `type` 执行当前业务操作。
        type(exception).__name__,
        # 补充当前表达式的 `status` 参数或元素。
        status,
        # 调用 `current_trace_id` 执行当前业务操作。
        current_trace_id(),
    )
    # 继续构造当前业务表达式或数据结构。
    code, message = _failure_details(exception, status)
    # 调用 `record_failure` 执行当前业务操作。
    record_failure(stage, exception, code, status)
    # 将当前计算结果返回给调用方。
    return code, message


# 声明当前处理单元及其入口。
def _failure_details(exception: Exception, status: int | None) -> tuple[str, str]:
    """Map upstream exceptions to the existing public error contract."""
    # 检查 `if isinstance(exception, CinemaQueryError)`，据此选择当前处理分支。
    if isinstance(exception, CinemaQueryError):
        # 将当前计算结果返回给调用方。
        return exception.code, str(exception)
    # 检查 `if isinstance(exception, (APITimeoutError, httpx.TimeoutException, TimeoutError))`，据此选择当前处理分支。
    if isinstance(exception, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
        # 将当前计算结果返回给调用方。
        return "query_timeout", "实时查询超时，请稍后重试。"
    # 检查 `if isinstance(exception, (APIConnectionError, httpx.RequestError))`，据此选择当前处理分支。
    if isinstance(exception, (APIConnectionError, httpx.RequestError)):
        # 将当前计算结果返回给调用方。
        return "service_unreachable", "无法连接实时查询服务，请检查服务网络后重试。"
    # 检查 `if isinstance(exception, APIStatusError)`，据此选择当前处理分支。
    if isinstance(exception, APIStatusError):
        # 检查 `if status == 401`，据此选择当前处理分支。
        if status == 401:
            # 将当前计算结果返回给调用方。
            return "model_auth_failed", "Qwen 模型鉴权失败，请检查服务端密钥及对应地域的接口地址。"
        # 检查 `if status == 403`，据此选择当前处理分支。
        if status == 403:
            # 将当前计算结果返回给调用方。
            return "model_access_denied", "Qwen 模型访问被拒绝，请检查模型权限或服务开通状态。"
        # 检查 `if status == 429`，据此选择当前处理分支。
        if status == 429:
            # 将当前计算结果返回给调用方。
            return "model_rate_limited", "Qwen 模型请求受限，请稍后重试并检查服务额度。"
        # 检查 `if status in (400, 404)`，据此选择当前处理分支。
        if status in (400, 404):
            # 将当前计算结果返回给调用方。
            return "model_request_rejected", "Qwen 拒绝了模型请求，请检查模型名称和接口配置。"
        # 将当前计算结果返回给调用方。
        return "model_unavailable", "Qwen 模型服务暂时不可用，请稍后重试。"
    # 检查 `if isinstance(exception, httpx.HTTPStatusError)`，据此选择当前处理分支。
    if isinstance(exception, httpx.HTTPStatusError):
        # 检查 `if status == 404`，据此选择当前处理分支。
        if status == 404:
            # 将当前计算结果返回给调用方。
            return "data_not_found", "没有找到可查询的记录，请检查影片或订单信息。"
        # 检查 `if status in (401, 403)`，据此选择当前处理分支。
        if status in (401, 403):
            # 将当前计算结果返回给调用方。
            return "business_auth_failed", "业务查询服务鉴权失败，请检查内部服务凭证。"
        # 将当前计算结果返回给调用方。
        return "business_unavailable", "业务查询服务暂时不可用，请稍后重试。"
    # 将当前计算结果返回给调用方。
    return "agent_error", "实时查询暂时失败，请稍后重试。"
