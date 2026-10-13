"""Model-visible read-only tools and checks at the Agent execution boundary."""

# 导入当前步骤使用的模块或类型。
# isort: off
import json
# 导入当前步骤使用的模块或类型。
import re
# 导入当前步骤使用的模块或类型。
from datetime import date
# 导入当前步骤使用的模块或类型。
from typing import Annotated, Any, Literal

# 导入当前步骤使用的模块或类型。
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# 导入当前步骤使用的模块或类型。
from app.failures import CinemaQueryError
# 导入当前步骤使用的模块或类型。
from app.intent import ORDER_PATTERN, SCREENING_PATTERN, normalize_question
# 导入当前步骤使用的模块或类型。
from app.query_answers import valid_movie_result, valid_screening_result
# 导入当前步骤使用的模块或类型。
from app.task_progress import progress
# isort: on

# 为 `Keyword` 保存当前步骤所需的值。
Keyword = Annotated[str, Field(max_length=120)]


# 声明当前处理单元及其入口。
class ToolArguments(BaseModel):
    """Reject unknown fields, including model-supplied identities."""

    # 为 `model_config` 保存当前步骤所需的值。
    model_config = ConfigDict(extra="forbid")


# 声明当前处理单元及其入口。
class MovieArguments(ToolArguments):
    """Search film facts, showing status, or actual scheduled films."""

    # 设置当前结构中的 `query` 字段。
    query: Keyword = ""
    # 设置当前结构中的 `movie_scope` 字段。
    movie_scope: Literal["catalog", "showing", "scheduled"] = "catalog"
    # 设置当前结构中的 `screening_date` 字段。
    screening_date: date | None = Field(
        # 为 `default` 保存当前步骤所需的值。
        default=None, description="YYYY-MM-DD；不限定日期时使用 JSON null，不要传字符串 None。"
    )
    # 设置当前结构中的 `cinema_query` 字段。
    cinema_query: Keyword = ""
    # 设置当前结构中的 `showing_only` 字段。
    showing_only: bool = False
    # 设置当前结构中的 `page` 字段。
    page: int = Field(default=1, ge=1, le=10000)
    # 设置当前结构中的 `page_size` 字段。
    page_size: int = Field(default=20, ge=1, le=50)


# 声明当前处理单元及其入口。
class ScreeningArguments(ToolArguments):
    """Use search keywords rather than invented database IDs."""

    # 设置当前结构中的 `movie_query` 字段。
    movie_query: Keyword = ""
    # 设置当前结构中的 `cinema_query` 字段。
    cinema_query: Keyword = ""
    # 设置当前结构中的 `screening_date` 字段。
    screening_date: date | None = Field(
        # 为 `default` 保存当前步骤所需的值。
        default=None, description="YYYY-MM-DD；不限定日期时使用 JSON null，不要传字符串 None。"
    )
    # 设置当前结构中的 `query_scope` 字段。
    query_scope: Literal["scheduled", "bookable"] = "bookable"
    # 设置当前结构中的 `showing_only` 字段。
    showing_only: bool = False


# 声明当前处理单元及其入口。
class SeatArguments(ToolArguments):
    """Query a screening supplied by the user or a current verified observation."""

    # 设置当前结构中的 `screening_id` 字段。
    screening_id: int = Field(gt=0, strict=True)


# 声明当前处理单元及其入口。
class OrderArguments(ToolArguments):
    """Query an explicitly supplied order within the authenticated user's scope."""

    # 设置当前结构中的 `order_no` 字段。
    order_no: str = Field(pattern=r"^[Oo][A-Za-z0-9]{5,63}$")


# 声明当前处理单元及其入口。
class PolicyArguments(ToolArguments):
    """Retrieve source-backed ticket policy explanations."""

    # 设置当前结构中的 `question` 字段。
    question: str = Field(min_length=1, max_length=2000)


# 声明当前处理单元及其入口。
class RecommendationArguments(ToolArguments):
    """Identity is injected by the executor, never included in this schema."""

    # 设置当前结构中的 `preference` 字段。
    preference: Keyword = ""


# 声明当前处理单元及其入口。
class ClarificationArguments(ToolArguments):
    """End the current turn with a question instead of guessing an identifier."""

    # 设置当前结构中的 `question` 字段。
    question: str = Field(min_length=1, max_length=500)


# 设置当前结构中的 `ARGUMENT_MODELS` 字段。
ARGUMENT_MODELS: dict[str, type[ToolArguments]] = {
    # 设置当前结构中的 `search_movies` 字段。
    "search_movies": MovieArguments,
    # 设置当前结构中的 `search_screenings` 字段。
    "search_screenings": ScreeningArguments,
    # 设置当前结构中的 `query_seats` 字段。
    "query_seats": SeatArguments,
    # 设置当前结构中的 `query_order` 字段。
    "query_order": OrderArguments,
    # 设置当前结构中的 `query_ticket_policy` 字段。
    "query_ticket_policy": PolicyArguments,
    # 设置当前结构中的 `recommend_movies` 字段。
    "recommend_movies": RecommendationArguments,
    # 设置当前结构中的 `ask_user` 字段。
    "ask_user": ClarificationArguments,
}
# 为 `DESCRIPTIONS` 保存当前步骤所需的值。
DESCRIPTIONS = {
    # 设置当前结构中的 `search_movies` 字段。
    "search_movies": "查询影片资料 catalog、上映中 showing 或真实已排期 scheduled；上映不代表有排期。排期可按北京时间日期筛选。",
    # 设置当前结构中的 `search_screenings` 字段。
    "search_screenings": "查询电影和影院的场次编号、开场时间、票价；scheduled 是真实排期，bookable 是当前可订购。得到真实场次编号后可调用 query_seats。",
    # 设置当前结构中的 `query_seats` 字段。
    "query_seats": "查询一个真实场次的座位快照，不锁座。编号必须来自用户明确提供或本轮场次查询结果。多个场次而用户未指定时先 ask_user。",
    # 设置当前结构中的 `query_order` 字段。
    "query_order": "只查询登录用户本人的订单、出票信息及当前 can_refund、refund_reason；订单号必须来自用户消息，不执行退款。",
    # 设置当前结构中的 `query_ticket_policy` 字段。
    "query_ticket_policy": "检索购票与退票规则及来源；具体订单能否退票以 query_order 的实时资格为准。",
    # 设置当前结构中的 `recommend_movies` 字段。
    "recommend_movies": "按用户给出的偏好推荐电影；用户身份由服务器自动注入，不能传 user_id。",
    # 设置当前结构中的 `ask_user` 字段。
    "ask_user": "缺少条件或有多个候选场次需用户选择时，提出明确的问题并结束本轮，不能猜测编号。",
}
# 为 `TOOL_SPECS` 保存当前步骤所需的值。
TOOL_SPECS = [
    # 继续构造当前业务表达式或数据结构。
    {
        # 设置当前结构中的 `type` 字段。
        "type": "function",
        # 设置当前结构中的 `function` 字段。
        "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()},
    }
    # 进入对应的循环、异常处理或资源管理分支。
    for name, schema in ARGUMENT_MODELS.items()
]
# 为 `TOOL_LABELS` 保存当前步骤所需的值。
TOOL_LABELS = {
    # 设置当前结构中的 `search_movies` 字段。
    "search_movies": "查询影片信息",
    # 设置当前结构中的 `search_screenings` 字段。
    "search_screenings": "查询放映场次",
    # 设置当前结构中的 `query_seats` 字段。
    "query_seats": "查询实时座位",
    # 设置当前结构中的 `query_order` 字段。
    "query_order": "查询本人订单",
    # 设置当前结构中的 `query_ticket_policy` 字段。
    "query_ticket_policy": "检索票务规则",
    # 设置当前结构中的 `recommend_movies` 字段。
    "recommend_movies": "查询电影推荐",
    # 设置当前结构中的 `ask_user` 字段。
    "ask_user": "确认缺少的查询条件",
}


# 声明当前处理单元及其入口。
def validate_arguments(
    # 设置当前结构中的 `name` 字段。
    name: str,
    # 设置当前结构中的 `supplied` 字段。
    supplied: dict[str, Any],
    # 设置当前结构中的 `state` 字段。
    state: dict[str, Any],
# 继续构造当前业务表达式或数据结构。
) -> dict[str, Any]:
    """Validate tool schema, immutable query constraints, and identifier provenance."""
    # 检查 `if name not in ARGUMENT_MODELS`，据此选择当前处理分支。
    if name not in ARGUMENT_MODELS:
        # 抛出当前异常，交由上层错误处理流程处理。
        raise CinemaQueryError("invalid_tool_call", "只能调用已开放的只读查询工具。")
    # Providers may serialize a missing optional date as text. Canonicalize only
    # empty sentinels; real dates still have to match the user's task below.
    # 检查 `if name in ("search_movies", "search_screenings")`，据此选择当前处理分支。
    if name in ("search_movies", "search_screenings"):
        # 为 `supplied_date` 保存当前步骤所需的值。
        supplied_date = supplied.get("screening_date")
        # 检查 `if isinstance(supplied_date, str) and supplied_date.strip().lower() in ("", "none", "null")`，据此选择当前处理分支。
        if isinstance(supplied_date, str) and supplied_date.strip().lower() in ("", "none", "null"):
            # 为 `supplied` 保存当前步骤所需的值。
            supplied = {**supplied, "screening_date": None}
    # 为 `arguments` 保存当前步骤所需的值。
    arguments = dict(supplied)
    # 为 `entities` 保存当前步骤所需的值。
    entities = state["entities"]
    # 检查 `if name == "ask_user" and isinstance(supplied.get("question"), str)`，据此选择当前处理分支。
    if name == "ask_user" and isinstance(supplied.get("question"), str):
        # 检查 `if "订单号" in supplied["question"] and entities.get("order_nos")`，据此选择当前处理分支。
        if "订单号" in supplied["question"] and entities.get("order_nos"):
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", "用户已提供订单号，请逐一查询，无需重复索要。")
        # 检查 `if "日期" in supplied["question"] and entities.get("screening_date")`，据此选择当前处理分支。
        if "日期" in supplied["question"] and entities.get("screening_date"):
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", "用户已提供有效日期，请使用该日期查询。")
    # 设置当前结构中的 `constraints` 字段。
    constraints: dict[str, Any] = {}
    # 检查 `if name == "search_movies" and state["intent"] == "movies"`，据此选择当前处理分支。
    if name == "search_movies" and state["intent"] == "movies":
        # 为 `constraints` 保存当前步骤所需的值。
        constraints = {
            # 设置当前结构中的 `movie_scope` 字段。
            "movie_scope": entities["movie_scope"],
            # 设置当前结构中的 `showing_only` 字段。
            "showing_only": entities["showing_only"],
            # 设置当前结构中的 `page` 字段。
            "page": entities["page"],
            # 设置当前结构中的 `query` 字段。
            "query": entities["movie_query"] or entities["preference"],
            # 设置当前结构中的 `cinema_query` 字段。
            "cinema_query": entities["cinema_query"],
        }
    # 检查 `if name == "search_screenings"`，据此选择当前处理分支。
    if name == "search_screenings":
        # 为 `constraints` 保存当前步骤所需的值。
        constraints = {
            # 设置当前结构中的 `query_scope` 字段。
            "query_scope": entities["screening_scope"],
            # 设置当前结构中的 `showing_only` 字段。
            "showing_only": entities["showing_only"],
        }
        # 进入对应的循环、异常处理或资源管理分支。
        for key in ("movie_query", "cinema_query"):
            # 检查 `if entities[key]`，据此选择当前处理分支。
            if entities[key]:
                # 继续构造当前业务表达式或数据结构。
                constraints[key] = entities[key]
    # 检查 `if name in ("search_movies", "search_screenings")`，据此选择当前处理分支。
    if name in ("search_movies", "search_screenings"):
        constraints["screening_date"] = entities["screening_date"]
    # 检查 `if "tasks" in state and name != "ask_user"`，据此选择当前处理分支。
    if "tasks" in state and name != "ask_user":
        # 为 `requested` 保存当前步骤所需的值。
        requested = [task for task in progress(state) if task["name"] == name and task["status"] in ("pending", "done")]
        # 检查 `if not requested`，据此选择当前处理分支。
        if not requested:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", "用户未要求此项查询，请完成尚未完成的子任务。")
        # 检查 `if name == "query_order" and isinstance(supplied.get("order_no"), str)`，据此选择当前处理分支。
        if name == "query_order" and isinstance(supplied.get("order_no"), str):
            # 进入对应的循环、异常处理或资源管理分支。
            for item in requested:
                # 检查 `if supplied["order_no"].lower() == item["arguments"]["order_no"].lower()`，据此选择当前处理分支。
                if supplied["order_no"].lower() == item["arguments"]["order_no"].lower():
                    # 为 `supplied` 保存当前步骤所需的值。
                    supplied = {**supplied, "order_no": item["arguments"]["order_no"]}
                    arguments["order_no"] = supplied["order_no"]
                    # 结束当前循环。
                    break
        # 为 `task` 保存当前步骤所需的值。
        task = next(
            # 继续构造当前业务表达式或数据结构。
            (
                # 继续构造当前业务表达式或数据结构。
                item
                # 进入对应的循环、异常处理或资源管理分支。
                for item in requested
                # 检查 `if all(key not in supplied or supplied[key] == value for key, value in item["arguments"].items())`，据此选择当前处理分支。
                if all(key not in supplied or supplied[key] == value for key, value in item["arguments"].items())
            ),
            # 补充当前表达式的 `requested[0]` 参数或元素。
            requested[0],
        )
        # 为 `constraints` 保存当前步骤所需的值。
        constraints = dict(task["arguments"])
        # Parameters inferred from unquoted prose can be refined using user/evidence provenance below.
        # 进入对应的循环、异常处理或资源管理分支。
        for key in ("query", "movie_query", "cinema_query", "preference"):
            # 检查 `if key in supplied and key in constraints`，据此选择当前处理分支。
            if key in supplied and key in constraints:
                # 为 `literal_title` 保存当前步骤所需的值。
                literal_title = entities["movie_query"] and f"《{entities['movie_query']}》" in "".join(
                    item["content"] for item in state["messages"] if item["role"] == "user"
                )
                # 检查 `if key in ("cinema_query", "preference") or not literal_title`，据此选择当前处理分支。
                if key in ("cinema_query", "preference") or not literal_title:
                    # 为 `all_movies` 保存当前步骤所需的值。
                    all_movies = key in ("query", "movie_query") and re.search(
                        r"(?:所有|全部)(?:的)?(?:电影|影片)", state["question"]
                    )
                    # 检查 `if not all_movies`，据此选择当前处理分支。
                    if not all_movies:
                        # 继续构造当前业务表达式或数据结构。
                        constraints[key] = supplied[key]
    # 进入对应的循环、异常处理或资源管理分支。
    for key, value in constraints.items():
        # 检查 `if key in supplied and supplied[key] != value`，据此选择当前处理分支。
        if key in supplied and supplied[key] != value:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", f"查询参数与当前子任务要求不一致：{key}。")
        # 继续构造当前业务表达式或数据结构。
        arguments[key] = value
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        # 为 `arguments` 保存当前步骤所需的值。
        arguments = ARGUMENT_MODELS[name].model_validate(arguments).model_dump(mode="json")
    # 进入对应的循环、异常处理或资源管理分支。
    except (ValidationError, TypeError, ValueError) as exc:
        # 抛出当前异常，交由上层错误处理流程处理。
        raise CinemaQueryError("invalid_tool_call", "工具参数不符合规范，请修正参数或向用户追问。") from exc
    # 为 `user_text` 保存当前步骤所需的值。
    user_text = "\n".join(item["content"] for item in state["messages"] if item["role"] == "user")
    # 检查 `if name == "query_order"`，据此选择当前处理分支。
    if name == "query_order":
        # 为 `known_orders` 保存当前步骤所需的值。
        known_orders = {match.group().lower() for match in ORDER_PATTERN.finditer(user_text)}
        # 检查 `if arguments["order_no"].lower() not in known_orders`，据此选择当前处理分支。
        if arguments["order_no"].lower() not in known_orders:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", "订单号必须由用户明确提供，不能从助手回复中猜测。")
    # 检查 `if name == "query_seats"`，据此选择当前处理分支。
    if name == "query_seats":
        # 为 `known_ids` 保存当前步骤所需的值。
        known_ids = {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}
        # 进入对应的循环、异常处理或资源管理分支。
        for observation in state.get("observations", []):
            # 为 `data` 保存当前步骤所需的值。
            data = observation["data"]
            # 检查 `if observation["name"] == "search_screenings"`，据此选择当前处理分支。
            if observation["name"] == "search_screenings":
                known_ids.update(row["id"] for row in data if type(row.get("id")) is int)
            # 检查 `elif observation["name"] == "search_movies" and isinstance(data, dict)`，据此选择当前处理分支。
            elif observation["name"] == "search_movies" and isinstance(data, dict):
                # 继续构造当前业务表达式或数据结构。
                known_ids.update(
                    slot["id"]
                    # 进入对应的循环、异常处理或资源管理分支。
                    for movie in data["items"]
                    # 进入对应的循环、异常处理或资源管理分支。
                    for slot in movie.get("screenings", [])
                    # 检查 `if type(slot.get("id")) is int`，据此选择当前处理分支。
                    if type(slot.get("id")) is int
                )
        # 检查 `if arguments["screening_id"] not in known_ids`，据此选择当前处理分支。
        if arguments["screening_id"] not in known_ids:
            # 抛出当前异常，交由上层错误处理流程处理。
            raise CinemaQueryError("invalid_tool_call", "场次编号缺少依据，请先查询场次或向用户追问。")
    # 检查 `if name in ("search_movies", "search_screenings", "recommend_movies")`，据此选择当前处理分支。
    if name in ("search_movies", "search_screenings", "recommend_movies"):
        # 为 `permitted_text` 保存当前步骤所需的值。
        permitted_text = normalize_question(user_text) + user_text
        # 为 `permitted_keywords` 保存当前步骤所需的值。
        permitted_keywords = [str(value) for value in entities.values() if isinstance(value, str) and value]
        permitted_keywords += [item["content"] for item in state.get("memories", [])]
        # 进入对应的循环、异常处理或资源管理分支。
        for observation in state.get("observations", []):
            # 为 `data` 保存当前步骤所需的值。
            data = observation["data"]
            # 为 `rows` 保存当前步骤所需的值。
            rows = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
            permitted_keywords += [row.get("title", "") for row in rows if isinstance(row, dict)]
        # 进入对应的循环、异常处理或资源管理分支。
        for key in ("query", "movie_query", "cinema_query", "preference"):
            # 为 `keyword` 保存当前步骤所需的值。
            keyword = arguments.get(key, "")
            # 检查 `if keyword and keyword not in permitted_text and not any(keyword in text for text in permitted_keywords)`，据此选择当前处理分支。
            if keyword and keyword not in permitted_text and not any(keyword in text for text in permitted_keywords):
                # 抛出当前异常，交由上层错误处理流程处理。
                raise CinemaQueryError("invalid_tool_call", "查询关键词必须来自用户要求、已确认偏好或本轮结果。")
    # 将当前计算结果返回给调用方。
    return arguments


# 声明当前处理单元及其入口。
def validate_result(name: str, data: Any, arguments: dict[str, Any], *, user_id: int) -> None:
    """Keep each observation's factual query contract before giving it to the model."""
    # 为 `valid` 保存当前步骤所需的值。
    valid = data is not None
    # 检查 `if name == "search_movies"`，据此选择当前处理分支。
    if name == "search_movies":
        # 为 `valid` 保存当前步骤所需的值。
        valid = valid_movie_result(data, arguments)
    # 检查 `elif name == "search_screenings"`，据此选择当前处理分支。
    elif name == "search_screenings":
        # 为 `valid` 保存当前步骤所需的值。
        valid = valid_screening_result(data, {**arguments, "screening_scope": arguments["query_scope"]})
    # 检查 `elif name == "query_seats"`，据此选择当前处理分支。
    elif name == "query_seats":
        # 为 `valid` 保存当前步骤所需的值。
        valid = isinstance(data, list) and all(
            # 调用 `isinstance` 执行当前业务操作。
            isinstance(row, dict) and "seat_code" in row and "booking_status" in row for row in data
        )
    # 检查 `elif name == "query_order"`，据此选择当前处理分支。
    elif name == "query_order":
        # 为 `valid` 保存当前步骤所需的值。
        valid = isinstance(data, dict) and "status" in data
        # 检查 `if valid`，据此选择当前处理分支。
        if valid:
            # 检查 `if "order_no" in data and data["order_no"].lower() != arguments["order_no"].lower()`，据此选择当前处理分支。
            if "order_no" in data and data["order_no"].lower() != arguments["order_no"].lower():
                # 抛出当前异常，交由上层错误处理流程处理。
                raise CinemaQueryError("query_contract_mismatch", "订单查询返回了不匹配的记录，请稍后重试。")
            # 检查 `if "user_id" in data and data["user_id"] != user_id`，据此选择当前处理分支。
            if "user_id" in data and data["user_id"] != user_id:
                # 抛出当前异常，交由上层错误处理流程处理。
                raise CinemaQueryError("business_auth_failed", "订单查询归属校验失败，请重新连接助手。")
    # 检查 `elif name == "query_ticket_policy"`，据此选择当前处理分支。
    elif name == "query_ticket_policy":
        # 为 `valid` 保存当前步骤所需的值。
        valid = isinstance(data, dict) and "policy" in data and "answer_context" in data
    # 检查 `elif name == "recommend_movies"`，据此选择当前处理分支。
    elif name == "recommend_movies":
        # 为 `valid` 保存当前步骤所需的值。
        valid = isinstance(data, list) and all(isinstance(row, dict) and "title" in row for row in data)
    # 检查 `if not valid`，据此选择当前处理分支。
    if not valid:
        # 抛出当前异常，交由上层错误处理流程处理。
        raise CinemaQueryError("query_contract_mismatch", "查询结果与请求条件不一致，请更新查询服务后重试。")


# 声明当前处理单元及其入口。
def observation_text(data: Any, limit: int = 12000) -> str:
    """Bound model context without claiming that a truncated observation is complete."""
    # 为 `text` 保存当前步骤所需的值。
    text = json.dumps(data, ensure_ascii=False, default=str)
    # 检查 `if len(text) <= limit`，据此选择当前处理分支。
    if len(text) <= limit:
        # 将当前计算结果返回给调用方。
        return text
    # 将当前计算结果返回给调用方。
    return json.dumps({"truncated": True, "data_excerpt": text[:limit]}, ensure_ascii=False)
