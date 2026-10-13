"""Preflight missing slots and high certainty rules before any paid understanding."""

import os
import re
from datetime import date
from typing import Any

from app.intent_classifier import predict_intent
from app.query_semantics import movie_fields, policy_kind, prose, query_domains


def preliminary_route(rules: Any, question: str, history: list[dict[str, str]]) -> tuple[str, str]:
    """Return the winning layer and its reason; empty layer requires the LLM."""
    text = prose(question)
    domains = query_domains(question, bool(rules.order_no))
    multiple = len(domains - {"general_policy"}) > 1 or len(rules.order_nos) > 1 or question.count("《") > 1
    if rules.screening_date:
        try:
            date.fromisoformat(rules.screening_date)
        except ValueError:
            return "preflight", "invalid_date"
    if rules.intent == "chat":
        return "l0", "greeting"
    transaction = re.search(r"(?:直接|替我|帮我).{0,12}(?:下单|付款|付掉|付钱|把钱付|支付)", text)
    if transaction and not re.search(r"状态|规则|怎么|如何|查询|查一下", text):
        rules.intent = "unsupported"
        return "preflight", "unsupported_transaction"
    if rules.intent == "policy" and policy_kind(question) == "general_policy" and not multiple:
        return "preflight", "policy_source_unavailable"
    if rules.intent in ("order", "refund") and not rules.order_no and not multiple:
        return "preflight", "missing_order_no"
    if (
        rules.intent == "seats"
        and not rules.screening_id
        and not (rules.movie_query or rules.cinema_query or rules.screening_date)
    ):
        return "preflight", "missing_screening_id"
    unresolved_date = re.search(r"本周|下周|这周|本月|周末|最近|过几天|这个月|下个月|\d+[月号日]", text)
    if (
        (
            rules.intent == "screenings"
            or rules.movie_scope == "scheduled"
            or (rules.intent == "seats" and not rules.screening_id)
        )
        and not rules.screening_date
        and unresolved_date
    ):
        return "preflight", "missing_date"
    if multiple:
        return "", "composite_requires_understanding"
    if os.getenv("AGENT_L0_ENABLED", "true").lower() != "true":
        return "", "llm_required"
    if history and re.search(r"那|它|这部|刚才|前面|下一页|第\s*\d+\s*页", text):
        return "", "context_requires_understanding"
    if rules.intent in ("order", "refund") and rules.order_no:
        return "l0", "explicit_order"
    if rules.intent == "seats" and rules.screening_id:
        return "l0", "explicit_screening"
    if rules.intent == "movies" and rules.movie_query and movie_fields(question):
        return "l0", "explicit_movie_fields"
    if (
        rules.intent == "policy"
        and policy_kind(question) == "ticket_policy"
        and re.search(r"退票|退款|购票.*(?:规则|须知)", text)
    ):
        return "l0", "ticket_policy"
    if (
        rules.intent == "screenings"
        and rules.screening_date
        and (rules.movie_query or re.search(r"场次|排期|票价", text))
    ):
        return "l0", "explicit_screening_date"
    predicted = predict_intent(question)
    if predicted and predicted[0] == rules.intent and rules.intent in ("movies", "screenings", "recommend"):
        # Classification cannot invent a title, a date, or a referenced entity.
        if rules.intent == "movies" and not rules.movie_query and not re.search(r"所有|全部|有哪些|几部", text):
            return "", "entity_extraction_required"
        rules.confidence = predicted[1]
        return "l1", "validated_local_classifier"
    return "", "llm_required"


def slot_summary(plan: dict[str, Any], reason: str = "") -> dict[str, Any]:
    """Expose only presence flags and finite enums, never business values or text."""
    entities = plan["entities"]
    missing = {
        "missing_order_no": ["order_no"],
        "missing_screening_id": ["screening_id"],
        "missing_date": ["screening_date"],
        "invalid_date": ["valid_date"],
        "policy_source_unavailable": ["policy_source"],
    }.get(reason, [])
    if not missing and plan.get("clarification"):
        if plan["intent"] in ("order", "refund") and not entities.get("order_no"):
            missing = ["order_no"]
        elif plan["intent"] == "seats" and not entities.get("screening_id"):
            missing = ["screening_id"]
    return {
        "order_no": bool(entities.get("order_no")),
        "screening_date": True if entities.get("screening_date") else None,
        "screening_id": bool(entities.get("screening_id")),
        "movie_query": bool(entities.get("movie_query")),
        "cinema_query": bool(entities.get("cinema_query")),
        "missing_slots": missing,
        "policy_kind": entities.get("policy_kind", "none"),
    }
