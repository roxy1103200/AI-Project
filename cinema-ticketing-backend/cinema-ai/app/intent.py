"""Understand cinema questions before dispatching a fixed, read-only business tool."""

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["chat", "movies", "screenings", "seats", "order", "refund", "policy", "recommend", "unsupported"]
ORDER_PATTERN = re.compile(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])")
SCREENING_PATTERN = re.compile(r"场次\s*(?:编号|ID|id|号)?\s*[:：#]?\s*([1-9][0-9]{0,18})(?![0-9])")
logger = logging.getLogger("uvicorn.error")
BEIJING_TIME = timezone(timedelta(hours=8))
GREETINGS = {"你好", "您好", "你好呀", "你好啊", "嗨", "hello", "hi", "在吗", "你是谁", "你能做什么", "能干什么"}
SYNONYMS = {
    "退钱": "退票",
    "退订": "退票",
    "退款": "退票",
    "排片": "排期",
    "放映时间": "场次时间",
    "开映": "开场",
    "影票": "电影票",
    "票价": "场次价格",
    "动画": "动漫",
    "搞笑": "喜剧",
    "吓人": "恐怖",
}


class QuestionPlan(BaseModel):
    """Validated model extraction, containing no identity or SQL fields."""

    model_config = ConfigDict(extra="forbid")
    intent: Intent
    normalized_question: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    movie_query: str = Field(default="", max_length=120)
    cinema_query: str = Field(default="", max_length=120)
    screening_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    screening_id: int | None = Field(default=None, gt=0)
    order_no: str = Field(default="", max_length=64)
    order_nos: list[str] = Field(default_factory=list, max_length=20)
    preference: str = Field(default="", max_length=120)
    movie_scope: Literal["catalog", "showing", "scheduled"] = "catalog"
    screening_scope: Literal["scheduled", "bookable"] = "bookable"
    showing_only: bool = False
    page: int = Field(default=1, ge=1, le=10000)


def beijing_today() -> date:
    """Resolve one business date independently of the operating system timezone."""
    return datetime.now(BEIJING_TIME).date()


def explicit_date(question: str, today: date) -> str | None:
    """Keep explicit dates even when invalid, so validation asks instead of broadening a query."""
    text = re.sub(r"《[^》]+》", "", question)
    match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", text)
    if match:
        return f"{int(match[1]):04d}-{int(match[2]):02d}-{int(match[3]):02d}"
    match = re.search(r"(\d{1,2})月(\d{1,2})(?:日|号)?", text)
    if match:
        return f"{today.year:04d}-{int(match[1]):02d}-{int(match[2]):02d}"
    for word, offset in (("后天", 2), ("明天", 1), ("今天", 0), ("今日", 0)):
        if word in text:
            return (today + timedelta(days=offset)).isoformat()
    match = re.search(r"(下周|本周|这周|周|下星期|本星期|星期)([一二三四五六日天])", text)
    if match:
        weekday = "一二三四五六日".index(match[2].replace("天", "日"))
        offset = weekday - today.weekday()
        if match[1].startswith("下"):
            offset += 7
        elif not match[1].startswith(("本", "这")):
            offset %= 7
        return (today + timedelta(days=offset)).isoformat()
    return None


def listing_kind(question: str) -> tuple[str, str, str, bool]:
    """Distinguish film state, actual scheduled films, and bookable screening details."""
    text = re.sub(r"《[^》]+》", "", question)
    scheduled = any(word in text for word in ("排期", "排片", "放映的电影", "放映哪些电影", "放映安排"))
    showing = "上映" in text or "热映" in text
    detail = any(word in text for word in ("场次", "几点", "时间", "票价", "多少钱", "什么时候放"))
    booking = any(word in text for word in ("有票", "买票", "购票", "订票", "订购"))
    if booking:
        return "screenings", "catalog", "bookable", showing
    if scheduled and not detail:
        return "movies", "scheduled", "scheduled", showing
    if detail and not any(word in text for word in ("上映时间", "上映日期", "什么时候上映")):
        return "screenings", "catalog", "scheduled", showing
    if showing and not any(
        word in text for word in ("上映时间", "上映日期", "什么时候上映", "导演", "主演", "简介", "片长")
    ):
        return "movies", "showing", "bookable", False
    return "movies", "catalog", "bookable", False


def general_listing(question: str) -> bool:
    """Recognize unfiltered lists that need no model extraction or invented search keywords."""
    text = question
    if "《" in text:
        return False
    text = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}(?:日|号)?|第\d+页", "", text)
    text = re.sub(r"(?:下周|本周|这周|周|下星期|本星期|星期)[一二三四五六日天]", "", text)
    words = (
        "今天",
        "今日",
        "明天",
        "后天",
        "电影",
        "影片",
        "场次",
        "正在",
        "目前",
        "当前",
        "上映",
        "热映",
        "排期",
        "排片",
        "放映",
        "安排",
        "有哪些",
        "有什么",
        "哪些",
        "多少",
        "清单",
        "列表",
        "可以",
        "可订购",
        "订购",
        "可购票",
        "购票",
        "买票",
        "还有票",
        "有票",
        "现在",
        "查询",
        "查看",
        "帮我",
        "请",
        "在",
        "中",
        "的",
        "且",
        "有",
        "呢",
    )
    for word in sorted(words, key=len, reverse=True):
        text = text.replace(word, "")
    return not text.strip(" ?？!！。,:：、，")


def normalize_question(question: str) -> str:
    """Normalize whitespace and common domain synonyms without altering identifiers."""
    text = re.sub(r"\s+", " ", question).strip()
    parts = re.split(r"(《[^》]+》)", text)
    for index in range(0, len(parts), 2):
        for original, canonical in SYNONYMS.items():
            parts[index] = parts[index].replace(original, canonical)
    return "".join(parts)[:1000]


def rule_plan(question: str, history: list[dict[str, str]], today: date | None = None) -> QuestionPlan:
    """Provide a conservative fallback if structured model extraction is unavailable."""
    normalized = normalize_question(question)
    today = today or beijing_today()
    intent, movie_scope, screening_scope, showing_only = listing_kind(question)
    greeting = question.strip().lower().rstrip("！!。.?？~～ ")
    if greeting in GREETINGS:
        return QuestionPlan(intent="chat", normalized_question=normalized, confidence=1)
    request_text = re.sub(r"《[^》]+》", "", normalized)
    order_match = ORDER_PATTERN.search(request_text)
    if order_match or any(word in request_text for word in ("订单", "出票", "支付状态", "我的票", "购票记录")):
        intent = "refund" if any(word in request_text for word in ("退票", "能退", "可退")) else "order"
    elif any(word in request_text for word in ("退票", "退改")):
        intent = (
            "policy" if any(word in request_text for word in ("规则", "多久", "提前", "须知", "条件")) else "refund"
        )
    elif any(word in request_text for word in ("座位", "选座", "座位图", "空座")):
        intent = "seats"
    elif any(word in request_text for word in ("规则", "须知", "优惠", "会员")):
        intent = "policy"
    elif intent == "screenings" or movie_scope != "catalog":
        pass
    elif any(word in request_text for word in ("推荐", "喜欢", "适合")):
        intent = "recommend"
    elif any(word in request_text for word in ("电影", "影片", "导演", "主演", "片长", "上映")) or "《" in question:
        intent = "movies"
    else:
        intent = "unsupported"
    title = re.search(r"《([^》]+)》", question)
    screening_match = SCREENING_PATTERN.search(question)
    plan = QuestionPlan(
        intent=intent,
        normalized_question=normalized,
        confidence=0.8 if intent != "unsupported" else 0.4,
        order_no=order_match.group() if order_match else "",
        order_nos=list(dict.fromkeys(match.group() for match in ORDER_PATTERN.finditer(request_text))),
        movie_query=title.group(1) if title else "",
        screening_date=explicit_date(question, today),
        screening_id=int(screening_match.group(1)) if screening_match else None,
        preference=next((genre for genre in ("动漫", "喜剧", "恐怖", "科幻", "爱情") if genre in normalized), ""),
        movie_scope=movie_scope,
        screening_scope=screening_scope,
        showing_only=showing_only,
        page=min(10000, max(1, int(match[1]))) if (match := re.search(r"第\s*(\d+)\s*页", question)) else 1,
    )
    screening_reply = SCREENING_PATTERN.fullmatch(question.strip())
    page_reply = bool(re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip()))
    if (
        history
        and (not general_listing(question) or page_reply)
        and (
            any(word in question for word in ("那", "呢", "这部", "刚才", "这个订单"))
            or ORDER_PATTERN.fullmatch(question.strip())
            or screening_reply
            or "下一页" in question
            or re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip())
        )
    ):
        previous_index = next(
            (index for index in range(len(history) - 1, -1, -1) if history[index].get("role") == "user"), -1
        )
        previous = history[previous_index]["content"] if previous_index >= 0 else ""
        if previous:
            prior = rule_plan(previous, history[:previous_index], today)
            if plan.intent == "unsupported" or ORDER_PATTERN.fullmatch(question.strip()):
                plan.intent = prior.intent if prior.intent != "unsupported" else plan.intent
                plan.movie_scope = prior.movie_scope
                plan.screening_scope = prior.screening_scope
                plan.showing_only = prior.showing_only
                plan.screening_date = plan.screening_date or prior.screening_date
            if screening_reply and prior.intent == "seats":
                plan.intent = "seats"
            plan.movie_query = plan.movie_query or prior.movie_query
            plan.cinema_query = plan.cinema_query or prior.cinema_query
            plan.order_no = plan.order_no or prior.order_no
            plan.order_nos = plan.order_nos or prior.order_nos
            plan.preference = plan.preference or prior.preference
            plan.screening_id = plan.screening_id or prior.screening_id
            if "下一页" in question:
                plan.page = min(10000, prior.page + 1)
            plan.confidence = 0.75 if plan.intent != "unsupported" else 0.4
            plan.normalized_question = f"{normalized}（承接问题：{prior.normalized_question[:400]}）"[:1000]
    return plan


async def understand(model: ChatOpenAI | None, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Extract intent/entities, resolve follow-up context, then validate required slots."""
    source = "rules"
    today = beijing_today()
    rules = rule_plan(question, history, today)
    plan = rules.model_copy()
    fixed_lookup = rules.intent == "screenings" or (
        rules.intent == "movies"
        and (
            rules.movie_scope != "catalog"
            or any(
                word in question for word in ("导演", "主演", "演员", "简介", "资料", "片长", "上映日期", "上映时间")
            )
        )
    )
    ambiguous_listing = (
        rules.intent == "movies"
        and rules.movie_scope == "catalog"
        and bool(rules.screening_date)
        and general_listing(question)
    )
    if model and plan.intent != "chat" and not ambiguous_listing and not (fixed_lookup and general_listing(question)):
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
            f"当前北京时间日期={today.isoformat()}；日期转为 YYYY-MM-DD，未指定日期填 null，不臆造日期或影院。\n"
            "所有字段必须输出，缺少实体用空字符串；confidence 表示理解置信度，不确定时降低。\n"
            f"JSON 字段规范：{json.dumps(QuestionPlan.model_json_schema(), ensure_ascii=False)}"
        )
        try:
            async with asyncio.timeout(15):
                response = await model.bind(
                    response_format={"type": "json_object"},
                    max_tokens=1000,
                    timeout=15,
                    extra_body={"enable_thinking": False},
                ).ainvoke(
                    [
                        SystemMessage(content=prompt),
                        HumanMessage(
                            content=json.dumps({"question": question, "history": history[-10:]}, ensure_ascii=False)
                        ),
                    ]
                )
            plan = QuestionPlan.model_validate_json(str(response.content))
            source = "model"
        except ValueError:
            logger.warning("Intent extraction failed: invalid structured output")
            source = "invalid_model_output"
        except Exception as exc:
            logger.warning("Intent extraction unavailable: %s", type(exc).__name__)
            # A safe rule fallback can still return verified business data when the model is unavailable.
            source = "model_unavailable"
    # Explicit business meaning and dates are constraints, never suggestions for the model.
    if fixed_lookup:
        plan.intent = rules.intent
        plan.movie_scope = rules.movie_scope
        plan.screening_scope = rules.screening_scope
        plan.showing_only = rules.showing_only
        plan.normalized_question = rules.normalized_question
        plan.confidence = max(plan.confidence, rules.confidence)
        plan.page = rules.page
        if not rules.screening_date:
            plan.screening_date = None
    plan.screening_date = rules.screening_date
    if rules.movie_query:
        plan.movie_query = rules.movie_query
    if (
        (rules.intent == "seats" and (rules.screening_id or rules.movie_query or rules.screening_date))
        or (rules.intent == "recommend" and "推荐" in question)
        or (rules.intent == "policy" and any(word in question for word in ("规则", "须知", "条件")))
    ):
        plan.intent = rules.intent
        plan.confidence = max(plan.confidence, rules.confidence)
    if general_listing(question) and not re.fullmatch(r"第\s*\d+\s*页[？?]?", question.strip()):
        plan.movie_query = ""
        plan.cinema_query = ""
        plan.preference = ""
    if re.search(r"(?:所有|全部)(?:的)?(?:电影|影片)", re.sub(r"《[^》]+》", "", question)):
        plan.movie_query = ""
    user_text = (
        "\n".join(message.get("content", "") for message in history if message.get("role") == "user") + "\n" + question
    )
    for field in ("movie_query", "cinema_query"):
        keyword = getattr(plan, field).strip()
        if keyword and (
            keyword not in user_text
            or keyword in {"今天", "明天", "后天", "上映", "电影", "影片", "排期", "场次"}
            or keyword in {question, normalize_question(question)}
        ):
            setattr(plan, field, "")
    if fixed_lookup and plan.preference and plan.preference not in normalize_question(user_text):
        plan.preference = rules.preference
    # Identifiers are extracted from user text, independently of model completeness.
    plan.order_nos = rules.order_nos
    if plan.order_nos:
        plan.order_no = plan.order_nos[0]
        plan.intent = rules.intent
        plan.confidence = max(plan.confidence, rules.confidence)
    if plan.order_no and plan.order_no.lower() not in user_text.lower():
        plan.order_no = ""
    if plan.order_no and not ORDER_PATTERN.fullmatch(plan.order_no):
        plan.order_no = ""
    if plan.screening_id not in {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}:
        plan.screening_id = None
    invalid_date = ""
    if plan.screening_date:
        try:
            datetime.strptime(plan.screening_date, "%Y-%m-%d")
        except ValueError:
            invalid_date = plan.screening_date
            plan.screening_date = None
            plan.confidence = 0
    clarification = ""
    if invalid_date:
        clarification = f"日期 {invalid_date} 不存在，请提供有效日期，例如 2026-10-10。"
    elif plan.intent in ("order", "refund") and not plan.order_no:
        clarification = "请提供要查询的订单号，我会查询你本人订单的状态或退票资格。"
    elif plan.intent == "seats" and not plan.screening_id:
        clarification = "请提供要查询的场次编号，例如：查询场次 12 的座位。也可以先查询影片场次。"
    elif plan.intent == "unsupported" or plan.confidence < 0.65:
        clarification = (
            "你想查询影片资料、场次票价、本人订单，还是退票规则？请补充具体问题。购票或退款操作请在业务页面完成。"
        )
    elif (
        plan.intent == "movies" and plan.movie_scope == "catalog" and rules.screening_date and general_listing(question)
    ):
        clarification = "你想查询该日期上映中的影片，还是实际安排了场次的电影？"
    elif (
        (plan.intent == "screenings" or plan.movie_scope == "scheduled")
        and not plan.screening_date
        and re.search(r"本周|下周|这周|本月|下个月|\d+[月号日]", re.sub(r"《[^》]+》", "", question))
    ):
        clarification = "请补充具体场次日期，例如 2026-09-30，以便准确查询。"
    return {
        "intent": plan.intent,
        "normalized_question": plan.normalized_question,
        "confidence": plan.confidence,
        "intent_source": source,
        "entities": plan.model_dump(exclude={"intent", "normalized_question", "confidence"}),
        "clarification": clarification,
    }
