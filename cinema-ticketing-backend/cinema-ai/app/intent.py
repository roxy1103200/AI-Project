"""Understand cinema questions before dispatching a fixed, read-only business tool."""

# 导入当前步骤使用的模块或类型。
# isort: off
import asyncio
# 导入当前步骤使用的模块或类型。
import json
# 导入当前步骤使用的模块或类型。
import logging
# 导入当前步骤使用的模块或类型。
import re
# 导入当前步骤使用的模块或类型。
from datetime import date, datetime, timedelta, timezone
# 导入当前步骤使用的模块或类型。
from typing import Any, Literal

# 导入当前步骤使用的模块或类型。
from langchain_core.messages import HumanMessage, SystemMessage
# 导入当前步骤使用的模块或类型。
from langchain_openai import ChatOpenAI
# 导入当前步骤使用的模块或类型。
from pydantic import BaseModel, ConfigDict, Field
# isort: on

# 为 `Intent` 保存当前步骤所需的值。
Intent = Literal["chat", "movies", "screenings", "seats", "order", "refund", "policy", "recommend", "unsupported"]
# 为 `ORDER_PATTERN` 保存当前步骤所需的值。
ORDER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])")
# 为 `SCREENING_PATTERN` 保存当前步骤所需的值。
SCREENING_PATTERN = re.compile(r"场次\s*(?:编号|ID|id|号)?\s*[:：#]?\s*([1-9][0-9]{0,18})(?![0-9])")
# 为 `logger` 保存当前步骤所需的值。
logger = logging.getLogger("uvicorn.error")
# 为 `BEIJING_TIME` 保存当前步骤所需的值。
BEIJING_TIME = timezone(timedelta(hours=8))
# 为 `GREETINGS` 保存当前步骤所需的值。
GREETINGS = {"你好", "您好", "你好呀", "你好啊", "嗨", "hello", "hi", "在吗", "你是谁", "你能做什么", "能干什么"}
# 为 `SYNONYMS` 保存当前步骤所需的值。
SYNONYMS = {
    # 补充当前表达式的 `"退钱": "退票"` 参数或元素。
    "退钱": "退票",
    # 补充当前表达式的 `"退订": "退票"` 参数或元素。
    "退订": "退票",
    # 补充当前表达式的 `"退款": "退票"` 参数或元素。
    "退款": "退票",
    # 补充当前表达式的 `"排片": "排期"` 参数或元素。
    "排片": "排期",
    # 补充当前表达式的 `"放映时间": "场次时间"` 参数或元素。
    "放映时间": "场次时间",
    # 补充当前表达式的 `"开映": "开场"` 参数或元素。
    "开映": "开场",
    # 补充当前表达式的 `"影票": "电影票"` 参数或元素。
    "影票": "电影票",
    # 补充当前表达式的 `"票价": "场次价格"` 参数或元素。
    "票价": "场次价格",
    # 补充当前表达式的 `"动画": "动漫"` 参数或元素。
    "动画": "动漫",
    # 补充当前表达式的 `"搞笑": "喜剧"` 参数或元素。
    "搞笑": "喜剧",
    # 补充当前表达式的 `"吓人": "恐怖"` 参数或元素。
    "吓人": "恐怖",
}


# 声明当前处理单元及其入口。
class QuestionPlan(BaseModel):
    """Validated model extraction, containing no identity or SQL fields."""

    # 为 `model_config` 保存当前步骤所需的值。
    model_config = ConfigDict(extra="forbid")
    # 设置当前结构中的 `intent` 字段。
    intent: Intent
    # 设置当前结构中的 `normalized_question` 字段。
    normalized_question: str = Field(min_length=1, max_length=1000)
    # 设置当前结构中的 `confidence` 字段。
    confidence: float = Field(ge=0, le=1)
    # 设置当前结构中的 `movie_query` 字段。
    movie_query: str = Field(default="", max_length=120)
    # 设置当前结构中的 `cinema_query` 字段。
    cinema_query: str = Field(default="", max_length=120)
    # 设置当前结构中的 `screening_date` 字段。
    screening_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    # 设置当前结构中的 `screening_id` 字段。
    screening_id: int | None = Field(default=None, gt=0)
    # 设置当前结构中的 `order_no` 字段。
    order_no: str = Field(default="", max_length=64)
    # 设置当前结构中的 `order_nos` 字段。
    order_nos: list[str] = Field(default_factory=list, max_length=20)
    # 设置当前结构中的 `preference` 字段。
    preference: str = Field(default="", max_length=120)
    # 设置当前结构中的 `movie_scope` 字段。
    movie_scope: Literal["catalog", "showing", "scheduled"] = "catalog"
    # 设置当前结构中的 `screening_scope` 字段。
    screening_scope: Literal["scheduled", "bookable"] = "bookable"
    # 设置当前结构中的 `showing_only` 字段。
    showing_only: bool = False
    # 设置当前结构中的 `page` 字段。
    page: int = Field(default=1, ge=1, le=10000)


# 声明当前处理单元及其入口。
def beijing_today() -> date:
    """Resolve one business date independently of the operating system timezone."""
    # 将当前计算结果返回给调用方。
    return datetime.now(BEIJING_TIME).date()


# 声明当前处理单元及其入口。
def explicit_date(question: str, today: date) -> str | None:
    """Keep explicit dates even when invalid, so validation asks instead of broadening a query."""
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"《[^》]+》", "", question)
    # 为 `match` 保存当前步骤所需的值。
    match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    # 检查 `if match`，据此选择当前处理分支。
    if match:
        # 将当前计算结果返回给调用方。
        return f"{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}"
    # 为 `match` 保存当前步骤所需的值。
    match = re.search(r"(\d{1,2})月(\d{1,2})(?:日|号)?", text)
    # 检查 `if match`，据此选择当前处理分支。
    if match:
        # 将当前计算结果返回给调用方。
        return f"{today.year:04d}-{int(match[1]):02d}-{int(match[2]):02d}"
    # 进入对应的循环、异常处理或资源管理分支。
    for word, offset in (("后天", 2), ("明天", 1), ("今天", 0), ("今日", 0)):
        # 检查 `if word in text`，据此选择当前处理分支。
        if word in text:
            # 将当前计算结果返回给调用方。
            return (today + timedelta(days=offset)).isoformat()
    # 为 `match` 保存当前步骤所需的值。
    match = re.search(r"(下周|本周|这周|周|下星期|本星期|星期)([一二三四五六日天])", text)
    # 检查 `if match`，据此选择当前处理分支。
    if match:
        # 为 `weekday` 保存当前步骤所需的值。
        weekday = "一二三四五六日".index(match[2].replace("天", "日"))
        # 为 `offset` 保存当前步骤所需的值。
        offset = weekday - today.weekday()
        # 检查 `if match[1].startswith("下")`，据此选择当前处理分支。
        if match[1].startswith("下"):
            # 继续构造当前业务表达式或数据结构。
            offset += 7
        # 检查 `elif not match[1].startswith(("本", "这"))`，据此选择当前处理分支。
        elif not match[1].startswith(("本", "这")):
            # 继续构造当前业务表达式或数据结构。
            offset %= 7
        # 将当前计算结果返回给调用方。
        return (today + timedelta(days=offset)).isoformat()
    # 将当前计算结果返回给调用方。
    return None


# 声明当前处理单元及其入口。
def listing_kind(question: str) -> tuple[str, str, str, bool]:
    """Distinguish film state, actual scheduled films, and bookable screening details."""
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"《[^》]+》", "", question)
    # 为 `scheduled` 保存当前步骤所需的值。
    scheduled = any(word in text for word in ("排期", "排片", "放映的电影", "放映哪些电影", "放映安排"))
    # 为 `showing` 保存当前步骤所需的值。
    showing = "上映" in text or "热映" in text
    # 为 `detail` 保存当前步骤所需的值。
    detail = any(word in text for word in ("场次", "几点", "时间", "票价", "多少钱", "什么时候放"))
    # 为 `booking` 保存当前步骤所需的值。
    booking = any(word in text for word in ("有票", "买票", "购票", "订票", "订购"))
    # 检查 `if booking`，据此选择当前处理分支。
    if booking:
        # 将当前计算结果返回给调用方。
        return "screenings", "catalog", "bookable", showing
    # 检查 `if scheduled and not detail`，据此选择当前处理分支。
    if scheduled and not detail:
        # 将当前计算结果返回给调用方。
        return "movies", "scheduled", "scheduled", showing
    # 检查 `if detail and not any(word in text for word in ("上映时间", "上映日期", "什么时候上映"))`，据此选择当前处理分支。
    if detail and not any(word in text for word in ("上映时间", "上映日期", "什么时候上映")):
        # 将当前计算结果返回给调用方。
        return "screenings", "catalog", "scheduled", showing
    # 检查 `if showing and not any(`，据此选择当前处理分支。
    if showing and not any(
        word in text for word in ("上映时间", "上映日期", "什么时候上映", "导演", "主演", "简介", "片长")
    # 继续构造当前业务表达式或数据结构。
    ):
        # 将当前计算结果返回给调用方。
        return "movies", "showing", "bookable", False
    # 将当前计算结果返回给调用方。
    return "movies", "catalog", "bookable", False


# 声明当前处理单元及其入口。
def general_listing(question: str) -> bool:
    """Recognize unfiltered lists that need no model extraction or invented search keywords."""
    # 为 `text` 保存当前步骤所需的值。
    text = question
    # 检查 `if "《" in text`，据此选择当前处理分支。
    if "《" in text:
        # 将当前计算结果返回给调用方。
        return False
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}(?:日|号)?|第\d+页", "", text)
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"(?:下周|本周|这周|周|下星期|本星期|星期)[一二三四五六日天]", "", text)
    # 为 `words` 保存当前步骤所需的值。
    words = (
        # 补充当前表达式的 `"今天"` 参数或元素。
        "今天",
        # 补充当前表达式的 `"今日"` 参数或元素。
        "今日",
        # 补充当前表达式的 `"明天"` 参数或元素。
        "明天",
        # 补充当前表达式的 `"后天"` 参数或元素。
        "后天",
        # 补充当前表达式的 `"电影"` 参数或元素。
        "电影",
        # 补充当前表达式的 `"影片"` 参数或元素。
        "影片",
        # 补充当前表达式的 `"场次"` 参数或元素。
        "场次",
        # 补充当前表达式的 `"正在"` 参数或元素。
        "正在",
        # 补充当前表达式的 `"目前"` 参数或元素。
        "目前",
        # 补充当前表达式的 `"当前"` 参数或元素。
        "当前",
        # 补充当前表达式的 `"上映"` 参数或元素。
        "上映",
        # 补充当前表达式的 `"热映"` 参数或元素。
        "热映",
        # 补充当前表达式的 `"排期"` 参数或元素。
        "排期",
        # 补充当前表达式的 `"排片"` 参数或元素。
        "排片",
        # 补充当前表达式的 `"放映"` 参数或元素。
        "放映",
        # 补充当前表达式的 `"安排"` 参数或元素。
        "安排",
        # 补充当前表达式的 `"有哪些"` 参数或元素。
        "有哪些",
        # 补充当前表达式的 `"有什么"` 参数或元素。
        "有什么",
        # 补充当前表达式的 `"哪些"` 参数或元素。
        "哪些",
        # 补充当前表达式的 `"多少"` 参数或元素。
        "多少",
        # 补充当前表达式的 `"清单"` 参数或元素。
        "清单",
        # 补充当前表达式的 `"列表"` 参数或元素。
        "列表",
        # 补充当前表达式的 `"可以"` 参数或元素。
        "可以",
        # 补充当前表达式的 `"可订购"` 参数或元素。
        "可订购",
        # 补充当前表达式的 `"订购"` 参数或元素。
        "订购",
        # 补充当前表达式的 `"可购票"` 参数或元素。
        "可购票",
        # 补充当前表达式的 `"购票"` 参数或元素。
        "购票",
        # 补充当前表达式的 `"买票"` 参数或元素。
        "买票",
        # 补充当前表达式的 `"还有票"` 参数或元素。
        "还有票",
        # 补充当前表达式的 `"有票"` 参数或元素。
        "有票",
        # 补充当前表达式的 `"现在"` 参数或元素。
        "现在",
        # 补充当前表达式的 `"查询"` 参数或元素。
        "查询",
        # 补充当前表达式的 `"查看"` 参数或元素。
        "查看",
        # 补充当前表达式的 `"帮我"` 参数或元素。
        "帮我",
        # 补充当前表达式的 `"请"` 参数或元素。
        "请",
        # 补充当前表达式的 `"在"` 参数或元素。
        "在",
        # 补充当前表达式的 `"中"` 参数或元素。
        "中",
        # 补充当前表达式的 `"的"` 参数或元素。
        "的",
        # 补充当前表达式的 `"且"` 参数或元素。
        "且",
        # 补充当前表达式的 `"有"` 参数或元素。
        "有",
        # 补充当前表达式的 `"呢"` 参数或元素。
        "呢",
    )
    # 进入对应的循环、异常处理或资源管理分支。
    for word in sorted(words, key=len, reverse=True):
        # 为 `text` 保存当前步骤所需的值。
        text = text.replace(word, "")
    # 将当前计算结果返回给调用方。
    return not text.strip(" ?？!！。,:：、，")


# 声明当前处理单元及其入口。
def normalize_question(question: str) -> str:
    """Normalize whitespace and common domain synonyms without altering identifiers."""
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"\s+", " ", question).strip()
    # 为 `parts` 保存当前步骤所需的值。
    parts = re.split(r"(《[^》]+》)", text)
    # 进入对应的循环、异常处理或资源管理分支。
    for index in range(0, len(parts), 2):
        # 进入对应的循环、异常处理或资源管理分支。
        for original, canonical in SYNONYMS.items():
            # 继续构造当前业务表达式或数据结构。
            parts[index] = parts[index].replace(original, canonical)
    # 将当前计算结果返回给调用方。
    return "".join(parts)[:1000]


# 声明当前处理单元及其入口。
def rule_plan(question: str, history: list[dict[str, str]], today: date | None = None) -> QuestionPlan:
    """Provide a conservative fallback if structured model extraction is unavailable."""
    # 为 `normalized` 保存当前步骤所需的值。
    normalized = normalize_question(question)
    # 为 `today` 保存当前步骤所需的值。
    today = today or beijing_today()
    # 继续构造当前业务表达式或数据结构。
    intent, movie_scope, screening_scope, showing_only = listing_kind(question)
    # 为 `greeting` 保存当前步骤所需的值。
    greeting = question.strip().lower().rstrip("！!。.?？~～ ")
    # 检查 `if greeting in GREETINGS`，据此选择当前处理分支。
    if greeting in GREETINGS:
        # 将当前计算结果返回给调用方。
        return QuestionPlan(intent="chat", normalized_question=normalized, confidence=1)
    # 为 `request_text` 保存当前步骤所需的值。
    request_text = re.sub(r"《[^》]+》", "", normalized)
    # 为 `order_match` 保存当前步骤所需的值。
    order_match = ORDER_PATTERN.search(request_text)
    # 检查 `if order_match or any(word in request_text for word in ("订单", "出票", "支付状态", "我的票", "购票记录"))`，据此选择当前处理分支。
    if order_match or any(word in request_text for word in ("订单", "出票", "支付状态", "我的票", "购票记录")):
        # 为 `intent` 保存当前步骤所需的值。
        intent = "refund" if any(word in request_text for word in ("退票", "能退", "可退")) else "order"
    # 检查 `elif any(word in request_text for word in ("退票", "退改"))`，据此选择当前处理分支。
    elif any(word in request_text for word in ("退票", "退改")):
        # 为 `intent` 保存当前步骤所需的值。
        intent = (
            "policy" if any(word in request_text for word in ("规则", "多久", "提前", "须知", "条件")) else "refund"
        )
    # 检查 `elif any(word in request_text for word in ("座位", "选座", "座位图", "空座"))`，据此选择当前处理分支。
    elif any(word in request_text for word in ("座位", "选座", "座位图", "空座")):
        # 为 `intent` 保存当前步骤所需的值。
        intent = "seats"
    # 检查 `elif any(word in request_text for word in ("规则", "须知", "优惠", "会员"))`，据此选择当前处理分支。
    elif any(word in request_text for word in ("规则", "须知", "优惠", "会员")):
        # 为 `intent` 保存当前步骤所需的值。
        intent = "policy"
    # 检查 `elif intent == "screenings" or movie_scope != "catalog"`，据此选择当前处理分支。
    elif intent == "screenings" or movie_scope != "catalog":
        # 此分支不执行额外操作。
        pass
    # 检查 `elif any(word in request_text for word in ("推荐", "喜欢", "适合"))`，据此选择当前处理分支。
    elif any(word in request_text for word in ("推荐", "喜欢", "适合")):
        # 为 `intent` 保存当前步骤所需的值。
        intent = "recommend"
    # 检查 `elif any(word in request_text for word in ("电影", "影片", "导演", "主演", "片长", "上映")) or "《" in question`，据此选择当前处理分支。
    elif any(word in request_text for word in ("电影", "影片", "导演", "主演", "片长", "上映")) or "《" in question:
        # 为 `intent` 保存当前步骤所需的值。
        intent = "movies"
    # 进入对应的循环、异常处理或资源管理分支。
    else:
        # 为 `intent` 保存当前步骤所需的值。
        intent = "unsupported"
    # 为 `title` 保存当前步骤所需的值。
    title = re.search(r"《([^》]+)》", question)
    # 为 `screening_match` 保存当前步骤所需的值。
    screening_match = SCREENING_PATTERN.search(question)
    # 为 `plan` 保存当前步骤所需的值。
    plan = QuestionPlan(
        # 为 `intent` 保存当前步骤所需的值。
        intent=intent,
        # 为 `normalized_question` 保存当前步骤所需的值。
        normalized_question=normalized,
        # 为 `confidence` 保存当前步骤所需的值。
        confidence=0.8 if intent != "unsupported" else 0.4,
        # 为 `order_no` 保存当前步骤所需的值。
        order_no=order_match.group() if order_match else "",
        # 为 `order_nos` 保存当前步骤所需的值。
        order_nos=list(dict.fromkeys(match.group() for match in ORDER_PATTERN.finditer(request_text))),
        # 为 `movie_query` 保存当前步骤所需的值。
        movie_query=title.group(1) if title else "",
        # 为 `screening_date` 保存当前步骤所需的值。
        screening_date=explicit_date(question, today),
        # 为 `screening_id` 保存当前步骤所需的值。
        screening_id=int(screening_match.group(1)) if screening_match else None,
        # 为 `preference` 保存当前步骤所需的值。
        preference=next((genre for genre in ("动漫", "喜剧", "恐怖", "科幻", "爱情") if genre in normalized), ""),
        # 为 `movie_scope` 保存当前步骤所需的值。
        movie_scope=movie_scope,
        # 为 `screening_scope` 保存当前步骤所需的值。
        screening_scope=screening_scope,
        # 为 `showing_only` 保存当前步骤所需的值。
        showing_only=showing_only,
        # 为 `page` 保存当前步骤所需的值。
        page=min(10000, max(1, int(match[1]))) if (match := re.search(r"第\s*(\d+)\s*页", question)) else 1,
    )
    # 为 `screening_reply` 保存当前步骤所需的值。
    screening_reply = SCREENING_PATTERN.fullmatch(question.strip())
    # 为 `page_reply` 保存当前步骤所需的值。
    page_reply = bool(re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip()))
    # 检查 `if (`，据此选择当前处理分支。
    if (
        # 继续构造当前业务表达式或数据结构。
        history
        # 调用 `and` 执行当前业务操作。
        and (not general_listing(question) or page_reply)
        # 调用 `and` 执行当前业务操作。
        and (
            # 调用 `any` 执行当前业务操作。
            any(word in question for word in ("那", "呢", "这部", "刚才", "这个订单"))
            # 继续构造当前业务表达式或数据结构。
            or ORDER_PATTERN.fullmatch(question.strip())
            # 继续构造当前业务表达式或数据结构。
            or screening_reply
            or "下一页" in question
            or re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip())
        )
    # 继续构造当前业务表达式或数据结构。
    ):
        # 为 `previous_index` 保存当前步骤所需的值。
        previous_index = next(
            # 为 `(index for index in range(len(history) - …` 保存当前步骤所需的值。
            (index for index in range(len(history) - 1, -1, -1) if history[index].get("role") == "user"), -1
        )
        # 为 `previous` 保存当前步骤所需的值。
        previous = history[previous_index]["content"] if previous_index >= 0 else ""
        # 检查 `if previous`，据此选择当前处理分支。
        if previous:
            # 为 `prior` 保存当前步骤所需的值。
            prior = rule_plan(previous, history[:previous_index], today)
            # 检查 `if plan.intent == "unsupported" or ORDER_PATTERN.fullmatch(question.strip())`，据此选择当前处理分支。
            if plan.intent == "unsupported" or ORDER_PATTERN.fullmatch(question.strip()):
                # 为 `plan.intent` 保存当前步骤所需的值。
                plan.intent = prior.intent if prior.intent != "unsupported" else plan.intent
                # 为 `plan.movie_scope` 保存当前步骤所需的值。
                plan.movie_scope = prior.movie_scope
                # 为 `plan.screening_scope` 保存当前步骤所需的值。
                plan.screening_scope = prior.screening_scope
                # 为 `plan.showing_only` 保存当前步骤所需的值。
                plan.showing_only = prior.showing_only
                # 为 `plan.screening_date` 保存当前步骤所需的值。
                plan.screening_date = plan.screening_date or prior.screening_date
            # 检查 `if screening_reply and prior.intent == "seats"`，据此选择当前处理分支。
            if screening_reply and prior.intent == "seats":
                # 为 `plan.intent` 保存当前步骤所需的值。
                plan.intent = "seats"
            # 为 `plan.movie_query` 保存当前步骤所需的值。
            plan.movie_query = plan.movie_query or prior.movie_query
            # 为 `plan.cinema_query` 保存当前步骤所需的值。
            plan.cinema_query = plan.cinema_query or prior.cinema_query
            # 为 `plan.order_no` 保存当前步骤所需的值。
            plan.order_no = plan.order_no or prior.order_no
            # 为 `plan.order_nos` 保存当前步骤所需的值。
            plan.order_nos = plan.order_nos or prior.order_nos
            # 为 `plan.preference` 保存当前步骤所需的值。
            plan.preference = plan.preference or prior.preference
            # 为 `plan.screening_id` 保存当前步骤所需的值。
            plan.screening_id = plan.screening_id or prior.screening_id
            # 检查 `if "下一页" in question`，据此选择当前处理分支。
            if "下一页" in question:
                # 为 `plan.page` 保存当前步骤所需的值。
                plan.page = min(10000, prior.page + 1)
            # 为 `plan.confidence` 保存当前步骤所需的值。
            plan.confidence = 0.75 if plan.intent != "unsupported" else 0.4
            # 为 `plan.normalized_question` 保存当前步骤所需的值。
            plan.normalized_question = f"{normalized}（承接问题：{prior.normalized_question[:400]}）"[:1000]
    # 将当前计算结果返回给调用方。
    return plan


# 声明当前处理单元及其入口。
async def understand(model: ChatOpenAI | None, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Extract intent/entities, resolve follow-up context, then validate required slots."""
    # 为 `source` 保存当前步骤所需的值。
    source = "rules"
    # 为 `today` 保存当前步骤所需的值。
    today = beijing_today()
    # 为 `rules` 保存当前步骤所需的值。
    rules = rule_plan(question, history, today)
    # 为 `plan` 保存当前步骤所需的值。
    plan = rules.model_copy()
    # 为 `fixed_lookup` 保存当前步骤所需的值。
    fixed_lookup = rules.intent == "screenings" or (
        # 为 `rules.intent` 保存当前步骤所需的值。
        rules.intent == "movies"
        # 调用 `and` 执行当前业务操作。
        and (
            rules.movie_scope != "catalog"
            # 继续构造当前业务表达式或数据结构。
            or any(
                word in question for word in ("导演", "主演", "演员", "简介", "资料", "片长", "上映日期", "上映时间")
            )
        )
    )
    # 为 `ambiguous_listing` 保存当前步骤所需的值。
    ambiguous_listing = (
        # 为 `rules.intent` 保存当前步骤所需的值。
        rules.intent == "movies"
        and rules.movie_scope == "catalog"
        # 继续构造当前业务表达式或数据结构。
        and bool(rules.screening_date)
        # 继续构造当前业务表达式或数据结构。
        and general_listing(question)
    )
    # 检查 `if model and plan.intent != "chat" and not ambiguous_listing and not (fixed_lookup and general_listing(question))`，据此选择当前处理分支。
    if model and plan.intent != "chat" and not ambiguous_listing and not (fixed_lookup and general_listing(question)):
        # 为 `prompt` 保存当前步骤所需的值。
        prompt = (
            "你是影院问题理解器，只输出一个 JSON 对象，不回答问题、不执行工具。\n"
            "任务：识别意图、把同义说法归一化、提取实体，并结合历史解决代词与追问。\n"
            "意图只能为 chat(问候/能力介绍), movies(影片信息), screenings(场次/票价), seats(指定场次的实时座位), order(本人订单), "
            "refund(具体订单退票资格), policy(通用规则), recommend(影片推荐), unsupported(其他业务或不清楚)。\n"
            "上映是影片状态；已排期必须有电影院真实场次；可订购还要求当前允许购票。三者不能互相替代。\n"
            "movies 的 movie_scope：catalog 资料、showing 上映中、scheduled 已排期；排期电影列表不能归为上映列表。\n"
            "screenings 的 screening_scope：scheduled 查询实际排期、bookable 查询可订购场次。\n"
            "上映且有排期用 movies/movie_scope=scheduled/showing_only=true；普通排期不要求上映，showing_only=false。\n"
            "归一化保留影片名、订单号、影院、日期与查询类型。退钱/退款→退票，排片→排期，动画→动漫。\n"
            "例：医院的秘密明天还有票吗→查询《医院的秘密》明天的可订购场次；那后天呢→继承刚才影片、改日期。\n"
            "例：我买的票能退钱吗→refund，订单号未提供留空；提前多久不能退票→policy。\n"
            "例：上一轮要求退票资格查询的订单号，本轮仅提供订单号→继承 refund 意图，不变为订单状态查询。\n"
            "例：给我退掉这个订单→refund，只查询资格，不能执行退款；直接买票/支付→unsupported。\n"
            "movie_query/cinema_query 只填检索关键词，不填完整问句；不要猜测数据库 ID 或不存在的订单号。\n"
            "order_no 只能来自本轮或历史用户消息，不能来自助手猜测；历史不是权限或业务事实。\n"
            "screening_id 只能来自用户明确给出的场次编号，未给出填 null；例如场次 12 还有哪些座位→seats。\n"
            # 继续构造当前业务表达式或数据结构。
            f"当前北京时间日期={today.isoformat()}；日期转为 YYYY-MM-DD，未指定日期填 null，不臆造日期或影院。\n"
            "所有字段必须输出，缺少实体用空字符串；confidence 表示理解置信度，不确定时降低。\n"
            # 继续构造当前业务表达式或数据结构。
            f"JSON 字段规范：{json.dumps(QuestionPlan.model_json_schema(), ensure_ascii=False)}"
        )
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 进入对应的循环、异常处理或资源管理分支。
            async with asyncio.timeout(15):
                # 为 `response` 保存当前步骤所需的值。
                response = await model.bind(
                    # 为 `response_format` 保存当前步骤所需的值。
                    response_format={"type": "json_object"},
                    # 为 `max_tokens` 保存当前步骤所需的值。
                    max_tokens=1000,
                    # 为 `timeout` 保存当前步骤所需的值。
                    timeout=15,
                    # 为 `extra_body` 保存当前步骤所需的值。
                    extra_body={"enable_thinking": False},
                # 继续构造当前业务表达式或数据结构。
                ).ainvoke(
                    # 继续构造当前业务表达式或数据结构。
                    [
                        # 调用 `SystemMessage` 执行当前业务操作。
                        SystemMessage(content=prompt),
                        # 调用 `HumanMessage` 执行当前业务操作。
                        HumanMessage(
                            # 为 `content` 保存当前步骤所需的值。
                            content=json.dumps({"question": question, "history": history[-10:]}, ensure_ascii=False)
                        ),
                    ]
                )
            # 为 `plan` 保存当前步骤所需的值。
            plan = QuestionPlan.model_validate_json(str(response.content))
            # 为 `source` 保存当前步骤所需的值。
            source = "model"
        # 进入对应的循环、异常处理或资源管理分支。
        except ValueError:
            # 执行当前异步调用或运行状态记录。
            logger.warning("Intent extraction failed: invalid structured output")
            # 为 `source` 保存当前步骤所需的值。
            source = "invalid_model_output"
        # 进入对应的循环、异常处理或资源管理分支。
        except Exception as exc:
            # 执行当前异步调用或运行状态记录。
            logger.warning("Intent extraction unavailable: %s", type(exc).__name__)
            # A safe rule fallback can still return verified business data when the model is unavailable.
            # 为 `source` 保存当前步骤所需的值。
            source = "model_unavailable"
    # Explicit business meaning and dates are constraints, never suggestions for the model.
    # 检查 `if fixed_lookup`，据此选择当前处理分支。
    if fixed_lookup:
        # 为 `plan.intent` 保存当前步骤所需的值。
        plan.intent = rules.intent
        # 为 `plan.movie_scope` 保存当前步骤所需的值。
        plan.movie_scope = rules.movie_scope
        # 为 `plan.screening_scope` 保存当前步骤所需的值。
        plan.screening_scope = rules.screening_scope
        # 为 `plan.showing_only` 保存当前步骤所需的值。
        plan.showing_only = rules.showing_only
        # 为 `plan.normalized_question` 保存当前步骤所需的值。
        plan.normalized_question = rules.normalized_question
        # 为 `plan.confidence` 保存当前步骤所需的值。
        plan.confidence = max(plan.confidence, rules.confidence)
        # 为 `plan.page` 保存当前步骤所需的值。
        plan.page = rules.page
        # 检查 `if not rules.screening_date`，据此选择当前处理分支。
        if not rules.screening_date:
            # 为 `plan.screening_date` 保存当前步骤所需的值。
            plan.screening_date = None
    # 为 `plan.screening_date` 保存当前步骤所需的值。
    plan.screening_date = rules.screening_date
    # 检查 `if rules.movie_query`，据此选择当前处理分支。
    if rules.movie_query:
        # 为 `plan.movie_query` 保存当前步骤所需的值。
        plan.movie_query = rules.movie_query
    # 检查 `if (`，据此选择当前处理分支。
    if (
        (rules.intent == "seats" and (rules.screening_id or rules.movie_query or rules.screening_date))
        # 调用 `or` 执行当前业务操作。
        or (rules.intent == "recommend" and "推荐" in question)
        # 调用 `or` 执行当前业务操作。
        or (rules.intent == "policy" and any(word in question for word in ("规则", "须知", "条件")))
    # 继续构造当前业务表达式或数据结构。
    ):
        # 为 `plan.intent` 保存当前步骤所需的值。
        plan.intent = rules.intent
        # 为 `plan.confidence` 保存当前步骤所需的值。
        plan.confidence = max(plan.confidence, rules.confidence)
    # 检查 `if general_listing(question) and not re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip())`，据此选择当前处理分支。
    if general_listing(question) and not re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip()):
        # 为 `plan.movie_query` 保存当前步骤所需的值。
        plan.movie_query = ""
        # 为 `plan.cinema_query` 保存当前步骤所需的值。
        plan.cinema_query = ""
        # 为 `plan.preference` 保存当前步骤所需的值。
        plan.preference = ""
    # 检查 `if re.search(r"(?`，据此选择当前处理分支。
    if re.search(r"(?:所有|全部)(?:的)?(?:电影|影片)", re.sub(r"《[^》]+》", "", question)):
        # 为 `plan.movie_query` 保存当前步骤所需的值。
        plan.movie_query = ""
    # 为 `user_text` 保存当前步骤所需的值。
    user_text = (
        "\n".join(message.get("content", "") for message in history if message.get("role") == "user") + "\n" + question
    )
    # 进入对应的循环、异常处理或资源管理分支。
    for field in ("movie_query", "cinema_query"):
        # 为 `keyword` 保存当前步骤所需的值。
        keyword = getattr(plan, field).strip()
        # 检查 `if keyword and (`，据此选择当前处理分支。
        if keyword and (
            # 继续构造当前业务表达式或数据结构。
            keyword not in user_text
            or keyword in {"今天", "明天", "后天", "上映", "电影", "影片", "排期", "场次"}
            # 继续构造当前业务表达式或数据结构。
            or keyword in {question, normalize_question(question)}
        # 继续构造当前业务表达式或数据结构。
        ):
            # 调用 `setattr` 执行当前业务操作。
            setattr(plan, field, "")
    # 检查 `if fixed_lookup and plan.preference and plan.preference not in normalize_question(user_text)`，据此选择当前处理分支。
    if fixed_lookup and plan.preference and plan.preference not in normalize_question(user_text):
        # 为 `plan.preference` 保存当前步骤所需的值。
        plan.preference = rules.preference
    # Identifiers are extracted from user text, independently of model completeness.
    # 为 `plan.order_nos` 保存当前步骤所需的值。
    plan.order_nos = rules.order_nos
    # 检查 `if plan.order_nos`，据此选择当前处理分支。
    if plan.order_nos:
        # 为 `plan.order_no` 保存当前步骤所需的值。
        plan.order_no = plan.order_nos[0]
        # 为 `plan.intent` 保存当前步骤所需的值。
        plan.intent = rules.intent
        # 为 `plan.confidence` 保存当前步骤所需的值。
        plan.confidence = max(plan.confidence, rules.confidence)
    # 检查 `if plan.order_no and plan.order_no.lower() not in user_text.lower()`，据此选择当前处理分支。
    if plan.order_no and plan.order_no.lower() not in user_text.lower():
        # 为 `plan.order_no` 保存当前步骤所需的值。
        plan.order_no = ""
    # 检查 `if plan.order_no and not ORDER_PATTERN.fullmatch(plan.order_no)`，据此选择当前处理分支。
    if plan.order_no and not ORDER_PATTERN.fullmatch(plan.order_no):
        # 为 `plan.order_no` 保存当前步骤所需的值。
        plan.order_no = ""
    # 检查 `if plan.screening_id not in {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}`，据此选择当前处理分支。
    if plan.screening_id not in {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}:
        # 为 `plan.screening_id` 保存当前步骤所需的值。
        plan.screening_id = None
    # 为 `invalid_date` 保存当前步骤所需的值。
    invalid_date = ""
    # 检查 `if plan.screening_date`，据此选择当前处理分支。
    if plan.screening_date:
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            datetime.strptime(plan.screening_date, "%Y-%m-%d")
        # 进入对应的循环、异常处理或资源管理分支。
        except ValueError:
            # 为 `invalid_date` 保存当前步骤所需的值。
            invalid_date = plan.screening_date
            # 为 `plan.screening_date` 保存当前步骤所需的值。
            plan.screening_date = None
            # 为 `plan.confidence` 保存当前步骤所需的值。
            plan.confidence = 0
    # 为 `clarification` 保存当前步骤所需的值。
    clarification = ""
    # 检查 `if invalid_date`，据此选择当前处理分支。
    if invalid_date:
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = f"日期 {invalid_date} 不存在，请提供有效日期，例如 2026-10-10。"
    # 检查 `elif plan.intent in ("order", "refund") and not plan.order_no`，据此选择当前处理分支。
    elif plan.intent in ("order", "refund") and not plan.order_no:
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = "请提供要查询的订单号，我会查询你本人订单的状态或退票资格。"
    # 检查 `elif plan.intent == "seats" and not plan.screening_id`，据此选择当前处理分支。
    elif plan.intent == "seats" and not plan.screening_id:
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = "请提供要查询的场次编号，例如：查询场次 12 的座位。也可以先查询影片场次。"
    # 检查 `elif plan.intent == "unsupported" or plan.confidence < 0.65`，据此选择当前处理分支。
    elif plan.intent == "unsupported" or plan.confidence < 0.65:
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = (
            "你想查询影片资料、场次票价、本人订单，还是退票规则？请补充具体问题。购票或退款操作请在业务页面完成。"
        )
    # 检查 `elif (`，据此选择当前处理分支。
    elif (
        # 为 `plan.intent` 保存当前步骤所需的值。
        plan.intent == "movies" and plan.movie_scope == "catalog" and rules.screening_date and general_listing(question)
    # 继续构造当前业务表达式或数据结构。
    ):
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = "你想查询该日期上映中的影片，还是实际安排了场次的电影？"
    # 检查 `elif (`，据此选择当前处理分支。
    elif (
        (plan.intent == "screenings" or plan.movie_scope == "scheduled")
        # 继续构造当前业务表达式或数据结构。
        and not plan.screening_date
        and re.search(r"本周|下周|这周|本月|下个月|\d+[月号日]", re.sub(r"《[^》]+》", "", question))
    # 继续构造当前业务表达式或数据结构。
    ):
        # 为 `clarification` 保存当前步骤所需的值。
        clarification = "请补充具体场次日期，例如 2026-09-30，以便准确查询。"
    # 将当前计算结果返回给调用方。
    return {
        # 设置当前结构中的 `intent` 字段。
        "intent": plan.intent,
        # 设置当前结构中的 `normalized_question` 字段。
        "normalized_question": plan.normalized_question,
        # 设置当前结构中的 `confidence` 字段。
        "confidence": plan.confidence,
        # 设置当前结构中的 `intent_source` 字段。
        "intent_source": source,
        # 设置当前结构中的 `entities` 字段。
        "entities": plan.model_dump(exclude={"intent", "normalized_question", "confidence"}),
        # 设置当前结构中的 `clarification` 字段。
        "clarification": clarification,
    }
