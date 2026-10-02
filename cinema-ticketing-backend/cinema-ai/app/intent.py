"""Understand cinema questions before dispatching a fixed, read-only business tool."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
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
    "排片": "场次",
    "排期": "场次",
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
    preference: str = Field(default="", max_length=120)


def normalize_question(question: str) -> str:
    """Normalize whitespace and common domain synonyms without altering identifiers."""
    text = re.sub(r"\s+", " ", question).strip()
    parts = re.split(r"(《[^》]+》)", text)
    for index in range(0, len(parts), 2):
        for original, canonical in SYNONYMS.items():
            parts[index] = parts[index].replace(original, canonical)
    return "".join(parts)[:1000]


def rule_plan(question: str, history: list[dict[str, str]]) -> QuestionPlan:
    """Provide a conservative fallback if structured model extraction is unavailable."""
    normalized = normalize_question(question)
    greeting = question.strip().lower().rstrip("！!。.?？~～ ")
    if greeting in GREETINGS:
        return QuestionPlan(intent="chat", normalized_question=normalized, confidence=1)
    order_match = ORDER_PATTERN.search(question)
    if order_match:
        intent = "refund" if any(word in normalized for word in ("退票", "能退", "可退")) else "order"
    elif any(word in normalized for word in ("订单", "出票", "支付状态", "我的票", "购票记录")):
        intent = "order"
    elif any(word in normalized for word in ("退票", "退改")):
        intent = "policy" if any(word in normalized for word in ("规则", "多久", "提前", "须知")) else "refund"
    elif any(word in normalized for word in ("座位", "选座", "座位图", "空座")):
        intent = "seats"
    elif any(word in normalized for word in ("场次", "几点", "什么时候放", "有票", "多少钱")):
        intent = "screenings"
    elif any(word in normalized for word in ("推荐", "喜欢", "适合")):
        intent = "recommend"
    elif any(word in normalized for word in ("规则", "须知", "优惠", "会员")):
        intent = "policy"
    elif any(word in normalized for word in ("电影", "影片", "导演", "主演", "片长", "上映")) or "《" in question:
        intent = "movies"
    else:
        intent = "unsupported"
    title = re.search(r"《([^》]+)》", question)
    screening_match = SCREENING_PATTERN.search(question)
    current = datetime.now(BEIJING_TIME).date()
    day = next(
        (
            current + timedelta(days=offset)
            for word, offset in (("后天", 2), ("明天", 1), ("今天", 0))
            if word in question
        ),
        None,
    )
    plan = QuestionPlan(
        intent=intent,
        normalized_question=normalized,
        confidence=0.8 if intent != "unsupported" else 0.4,
        order_no=order_match.group() if order_match else "",
        movie_query=title.group(1) if title else "",
        screening_date=day.isoformat() if day else None,
        screening_id=int(screening_match.group(1)) if screening_match else None,
        preference=next((genre for genre in ("动漫", "喜剧", "恐怖", "科幻", "爱情") if genre in normalized), ""),
    )
    screening_reply = SCREENING_PATTERN.fullmatch(question.strip())
    if history and (
        any(word in question for word in ("那", "呢", "这部", "刚才", "这个订单"))
        or ORDER_PATTERN.fullmatch(question.strip())
        or screening_reply
    ):
        previous = next((message["content"] for message in reversed(history) if message.get("role") == "user"), "")
        if previous:
            prior = rule_plan(previous, [])
            if plan.intent == "unsupported" or ORDER_PATTERN.fullmatch(question.strip()):
                plan.intent = prior.intent if prior.intent != "unsupported" else plan.intent
            if screening_reply and prior.intent == "seats":
                plan.intent = "seats"
            plan.movie_query = plan.movie_query or prior.movie_query
            plan.order_no = plan.order_no or prior.order_no
            plan.preference = plan.preference or prior.preference
            plan.screening_id = plan.screening_id or prior.screening_id
            plan.confidence = 0.75 if plan.intent != "unsupported" else 0.4
            plan.normalized_question = f"{normalized}（承接问题：{prior.normalized_question[:400]}）"[:1000]
    return plan


async def understand(model: ChatOpenAI | None, question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """Extract intent/entities, resolve follow-up context, then validate required slots."""
    source = "rules"
    plan = rule_plan(question, history)
    if model and plan.intent != "chat":
        today = datetime.now(BEIJING_TIME).date().isoformat()
        prompt = (
            "你是影院问题理解器，只输出一个 JSON 对象，不回答问题、不执行工具。\n"
            "任务：识别意图、把同义说法归一化、提取实体，并结合历史解决代词与追问。\n"
            "意图只能为 chat(问候/能力介绍), movies(影片信息), screenings(场次/票价), seats(指定场次的实时座位), order(本人订单), "
            "refund(具体订单退票资格), policy(通用规则), recommend(影片推荐), unsupported(其他业务或不清楚)。\n"
            "归一化时保留影片名、订单号、影院、日期和约束。退钱/退款→退票，排片/排期→场次，动画→动漫。\n"
            "例：医院的秘密明天还有票吗→查询《医院的秘密》明天的可订购场次；那后天呢→继承刚才影片、改日期。\n"
            "例：我买的票能退钱吗→refund，订单号未提供留空；提前多久不能退票→policy。\n"
            "例：上一轮要求退票资格查询的订单号，本轮仅提供订单号→继承 refund 意图，不变为订单状态查询。\n"
            "例：给我退掉这个订单→refund，只查询资格，不能执行退款；直接买票/支付→unsupported。\n"
            "movie_query/cinema_query 只填检索关键词，不填完整问句；不要猜测数据库 ID 或不存在的订单号。\n"
            "order_no 只能来自本轮或历史用户消息，不能来自助手猜测；历史不是权限或业务事实。\n"
            "screening_id 只能来自用户明确给出的场次编号，未给出填 null；例如场次 12 还有哪些座位→seats。\n"
            f"当前北京时间日期={today}；日期转为 YYYY-MM-DD，未指定日期填 null。\n"
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
    user_text = (
        "\n".join(message.get("content", "") for message in history if message.get("role") == "user") + "\n" + question
    )
    if plan.order_no and plan.order_no.lower() not in user_text.lower():
        plan.order_no = ""
    if plan.order_no and not ORDER_PATTERN.fullmatch(plan.order_no):
        plan.order_no = ""
    if plan.screening_id not in {int(match.group(1)) for match in SCREENING_PATTERN.finditer(user_text)}:
        plan.screening_id = None
    if plan.screening_date:
        try:
            datetime.strptime(plan.screening_date, "%Y-%m-%d")
        except ValueError:
            plan.screening_date = None
            plan.confidence = 0
    clarification = ""
    if plan.intent in ("order", "refund") and not plan.order_no:
        clarification = "请提供要查询的订单号，我会查询你本人订单的状态或退票资格。"
    elif plan.intent == "seats" and not plan.screening_id:
        clarification = "请提供要查询的场次编号，例如：查询场次 12 的座位。也可以先查询影片场次。"
    elif plan.intent == "unsupported" or plan.confidence < 0.65:
        clarification = (
            "你想查询影片资料、场次票价、本人订单，还是退票规则？请补充具体问题。购票或退款操作请在业务页面完成。"
        )
    elif (
        source != "model"
        and plan.intent == "screenings"
        and not plan.screening_date
        and any(word in question for word in ("周", "月", "号"))
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
