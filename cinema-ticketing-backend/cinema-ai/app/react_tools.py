"""Model-visible read-only tools and checks at the Agent execution boundary."""

import json
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.failures import CinemaQueryError
from app.intent import ORDER_PATTERN, SCREENING_PATTERN, normalize_question
from app.query_answers import valid_movie_result, valid_screening_result

Keyword = Annotated[str, Field(max_length=120)]


class ToolArguments(BaseModel):
    """Reject unknown fields, including model-supplied identities."""

    model_config = ConfigDict(extra="forbid")


class MovieArguments(ToolArguments):
    """Search film facts, showing status, or actual scheduled films."""

    query: Keyword = ""
    movie_scope: Literal["catalog", "showing", "scheduled"] = "catalog"
    screening_date: date | None = None
    cinema_query: Keyword = ""
    showing_only: bool = False
    page: int = Field(default=1, ge=1, le=10000)
    page_size: int = Field(default=20, ge=1, le=50)


class ScreeningArguments(ToolArguments):
    """Use search keywords rather than invented database IDs."""

    movie_query: Keyword = ""
    cinema_query: Keyword = ""
    screening_date: date | None = None
    query_scope: Literal["scheduled", "bookable"] = "bookable"
    showing_only: bool = False


class SeatArguments(ToolArguments):
    """Query a screening supplied by the user or a current verified observation."""

    screening_id: int = Field(gt=0, strict=True)


class OrderArguments(ToolArguments):
    """Query an explicitly supplied order within the authenticated user's scope."""

    order_no: str = Field(pattern=r"^[Oo][A-Za-z0-9]{5,63}$")


class PolicyArguments(ToolArguments):
    """Retrieve source-backed ticket policy explanations."""

    question: str = Field(min_length=1, max_length=2000)


class RecommendationArguments(ToolArguments):
    """Identity is injected by the executor, never included in this schema."""

    preference: Keyword = ""


class ClarificationArguments(ToolArguments):
    """End the current turn with a question instead of guessing an identifier."""

    question: str = Field(min_length=1, max_length=500)


ARGUMENT_MODELS: dict[str, type[ToolArguments]] = {
    "search_movies": MovieArguments,
    "search_screenings": ScreeningArguments,
    "query_seats": SeatArguments,
    "query_order": OrderArguments,
    "query_ticket_policy": PolicyArguments,
    "recommend_movies": RecommendationArguments,
    "ask_user": ClarificationArguments,
}
DESCRIPTIONS = {
    "search_movies": "查询影片资料 catalog、上映中 showing 或真实已排期 scheduled；上映不代表有排期。排期可按北京时间日期筛选。",
    "search_screenings": "查询电影和影院的场次编号、开场时间、票价；scheduled 是真实排期，bookable 是当前可订购。得到真实场次编号后可调用 query_seats。",
    "query_seats": "查询一个真实场次的座位快照，不锁座。编号必须来自用户明确提供或本轮场次查询结果。多个场次而用户未指定时先 ask_user。",
    "query_order": "只查询登录用户本人的订单、出票信息及当前 can_refund、refund_reason；订单号必须来自用户消息，不执行退款。",
    "query_ticket_policy": "检索购票与退票规则及来源；具体订单能否退票以 query_order 的实时资格为准。",
    "recommend_movies": "按用户给出的偏好推荐电影；用户身份由服务器自动注入，不能传 user_id。",
    "ask_user": "缺少条件或有多个候选场次需用户选择时，提出明确的问题并结束本轮，不能猜测编号。",
}
TOOL_SPECS = [
    {
        "type": "function",
        "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()},
    }
    for name, schema in ARGUMENT_MODELS.items()
]
TOOL_LABELS = {
    "search_movies": "查询影片信息",
    "search_screenings": "查询放映场次",
    "query_seats": "查询实时座位",
    "query_order": "查询本人订单",
    "query_ticket_policy": "检索票务规则",
    "recommend_movies": "查询电影推荐",
    "ask_user": "确认缺少的查询条件",
}


def validate_arguments(
    name: str,
    supplied: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Validate tool schema, immutable query constraints, and identifier provenance."""
    if name not in ARGUMENT_MODELS:
        raise CinemaQueryError("invalid_tool_call", "只能调用已开放的只读查询工具。")
    arguments = dict(supplied)
    entities = state["entities"]
    constraints: dict[str, Any] = {}
    if name == "search_movies" and state["intent"] == "movies":
        constraints = {
            "movie_scope": entities["movie_scope"],
            "showing_only": entities["showing_only"],
            "page": entities["page"],
            "query": entities["movie_query"] or entities["preference"],
            "cinema_query": entities["cinema_query"],
        }
    if name == "search_screenings":
        constraints = {
            "query_scope": entities["screening_scope"],
            "showing_only": entities["showing_only"],
        }
        for key in ("movie_query", "cinema_query"):
            if entities[key]:
                constraints[key] = entities[key]
    if name in ("search_movies", "search_screenings"):
        constraints["screening_date"] = entities["screening_date"]
    for key, value in constraints.items():
        if key in supplied and supplied[key] != value:
            raise CinemaQueryError("invalid_tool_call", f"不能改变用户已经确认的查询条件：{key}。")
        arguments[key] = value
    try:
        arguments = ARGUMENT_MODELS[name].model_validate(arguments).model_dump(mode="json")
    except (ValidationError, TypeError, ValueError) as exc:
        raise CinemaQueryError("invalid_tool_call", "工具参数不符合规范，请修正参数或向用户追问。") from exc
    user_text = "\n".join(item["content"] for item in state["messages"] if item["role"] == "user")
    if name == "query_order":
        known_orders = {match.group().lower() for match in ORDER_PATTERN.finditer(user_text)}
        if arguments["order_no"].lower() not in known_orders:
            raise CinemaQueryError("invalid_tool_call", "订单号必须由用户明确提供，不能从助手回复中猜测。")
    if name == "query_seats":
        known_ids = {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}
        for observation in state.get("observations", []):
            data = observation["data"]
            if observation["name"] == "search_screenings":
                known_ids.update(row["id"] for row in data if type(row.get("id")) is int)
            elif observation["name"] == "search_movies" and isinstance(data, dict):
                known_ids.update(
                    slot["id"]
                    for movie in data["items"]
                    for slot in movie.get("screenings", [])
                    if type(slot.get("id")) is int
                )
        if arguments["screening_id"] not in known_ids:
            raise CinemaQueryError("invalid_tool_call", "场次编号缺少依据，请先查询场次或向用户追问。")
    if name in ("search_movies", "search_screenings", "recommend_movies"):
        permitted_text = normalize_question(user_text) + user_text
        permitted_keywords = [str(value) for value in entities.values() if isinstance(value, str) and value]
        permitted_keywords += [item["content"] for item in state.get("memories", [])]
        for observation in state.get("observations", []):
            data = observation["data"]
            rows = data if isinstance(data, list) else data.get("items", []) if isinstance(data, dict) else []
            permitted_keywords += [row.get("title", "") for row in rows if isinstance(row, dict)]
        for key in ("query", "movie_query", "cinema_query", "preference"):
            keyword = arguments.get(key, "")
            if keyword and keyword not in permitted_text and not any(keyword in text for text in permitted_keywords):
                raise CinemaQueryError("invalid_tool_call", "查询关键词必须来自用户要求、已确认偏好或本轮结果。")
    return arguments


def validate_result(name: str, data: Any, arguments: dict[str, Any], *, user_id: int) -> None:
    """Keep each observation's factual query contract before giving it to the model."""
    valid = data is not None
    if name == "search_movies":
        valid = valid_movie_result(data, arguments)
    elif name == "search_screenings":
        valid = valid_screening_result(data, {**arguments, "screening_scope": arguments["query_scope"]})
    elif name == "query_seats":
        valid = isinstance(data, list) and all(
            isinstance(row, dict) and "seat_code" in row and "booking_status" in row for row in data
        )
    elif name == "query_order":
        valid = isinstance(data, dict) and "status" in data
        if valid:
            if "order_no" in data and data["order_no"].lower() != arguments["order_no"].lower():
                raise CinemaQueryError("query_contract_mismatch", "订单查询返回了不匹配的记录，请稍后重试。")
            if "user_id" in data and data["user_id"] != user_id:
                raise CinemaQueryError("business_auth_failed", "订单查询归属校验失败，请重新连接助手。")
    elif name == "query_ticket_policy":
        valid = isinstance(data, dict) and "policy" in data and "answer_context" in data
    elif name == "recommend_movies":
        valid = isinstance(data, list) and all(isinstance(row, dict) and "title" in row for row in data)
    if not valid:
        raise CinemaQueryError("query_contract_mismatch", "查询结果与请求条件不一致，请更新查询服务后重试。")


def observation_text(data: Any, limit: int = 12000) -> str:
    """Bound model context without claiming that a truncated observation is complete."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return json.dumps({"truncated": True, "data_excerpt": text[:limit]}, ensure_ascii=False)
