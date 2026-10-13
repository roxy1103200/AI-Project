"""Cheap, conservative checks for canonical answers to deterministic single tasks."""

import re
from typing import Any

from app.query_semantics import movie_fields
from app.task_progress import is_complete


def verify_simple(state: dict[str, Any]) -> str:
    """Return passed/empty/incomplete only for provable cases; otherwise use the LLM."""
    if state.get("route") != "simple" or state.get("understanding_layer") not in ("l0", "l1"):
        return ""
    if not is_complete(state) or state.get("last_tool_error") or state.get("invalid_call_count"):
        return ""
    blocks = state.get("evidence_blocks", [])
    if len(state.get("observations", [])) != 1 or len(blocks) != 1 or state.get("draft_answer") != blocks[0]:
        return ""
    observation = state["observations"][0]
    name, data = observation["name"], observation["data"]
    if name == "search_movies":
        rows = data if isinstance(data, list) else data.get("items", [])
        if not rows:
            return "empty"
        fields = movie_fields(state["question"])
        if any(any(row.get(field) in (None, "") for field in fields) for row in rows):
            return "incomplete"
        return "passed"
    if name == "search_screenings":
        return "passed" if data else "empty"
    if name == "query_seats":
        if re.search(r"连.{0,3}座|连着|挨着|中间|靠.{0,2}边|推荐|第.{0,3}排", state["question"]):
            return ""
        if not data:
            return "incomplete"
        codes = [row.get("seat_code") for row in data]
        valid = all(isinstance(code, str) and code for code in codes) and len(set(codes)) == len(codes)
        valid = valid and all(row.get("booking_status") in ("AVAILABLE", "LOCKED", "SOLD", "DISABLED") for row in data)
        return "passed" if valid else "incomplete"
    if name == "query_order":
        if re.search(r"手续费|到账|渠道|流程|怎么退|如何退", state["question"]):
            return ""
        required = {"status"}
        question = state["question"]
        if re.search(r"金额|多少钱|花了|付了", question):
            required.add("total_amount")
        if re.search(r"影片|看啥片|什么电影", question):
            required.add("movie_title")
        if re.search(r"开场|开演|几点", question):
            required.add("start_time")
        if re.search(r"座位|哪.{0,2}座|哪.{0,2}排", question):
            required.add("items")
        if state["intent"] == "refund":
            required.update(("can_refund", "refund_reason"))
        return "passed" if all(data.get(field) not in (None, "") for field in required) else "incomplete"
    if name == "query_ticket_policy" and state["entities"].get("policy_kind") == "ticket_policy":
        if not re.search(r"退票|退款|退钱|退改", state["question"]):
            return ""
        if re.search(r"手续费|扣.{0,3}钱|到账|多久到账|渠道|哪里|流程|怎么退|如何退", state["question"]):
            return ""
        policy = data.get("policy", {})
        cutoff = policy.get("cutoff_minutes")
        return (
            "passed" if type(cutoff) is int and cutoff >= 0 and policy.get("version") and policy.get("policy") else ""
        )
    return ""
