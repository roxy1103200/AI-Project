"""Track requested business outcomes separately from a model's initial single intent."""

import re
from typing import Any

from app.intent import SCREENING_PATTERN, rule_plan

FACT_WORDS = ("导演", "片长", "主演", "演员", "简介", "资料", "上映日期", "上映时间")
SEAT_WORDS = ("座位", "空座", "选座", "余座")


def build_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Decompose explicit requests while keeping dates/scopes local to each query."""
    question, entities = state["question"], state["entities"]
    text = re.sub(r"《[^》]+》", "", question)
    rules = rule_plan(question, state["messages"][:-1])
    tasks: list[dict[str, Any]] = []

    def add(name: str, arguments: dict[str, Any], label: str) -> None:
        tasks.append({"name": name, "arguments": arguments, "label": label})

    order_nos = entities.get("order_nos") or ([entities["order_no"]] if entities["order_no"] else [])
    if state["intent"] in ("order", "refund") or order_nos:
        for number in order_nos:
            add("query_order", {"order_no": number}, f"查询订单 {number}")
    facts = any(word in text for word in FACT_WORDS)
    seats = state["intent"] == "seats" or any(word in text for word in SEAT_WORDS)
    explicit_ids = list(dict.fromkeys(int(match[1]) for match in SCREENING_PATTERN.finditer(question)))
    if not explicit_ids and entities["screening_id"]:
        explicit_ids = [entities["screening_id"]]
    slots = (
        state["intent"] == "screenings"
        or (seats and not explicit_ids)
        or (facts and any(word in text for word in ("场次", "排期", "排片", "票价")))
        or (
            not explicit_ids
            and state["intent"] != "movies"
            and any(word in text for word in ("场次", "票价"))
            and any(word in text for word in ("查", "找", "比较"))
        )
    )
    if facts or (state["intent"] == "movies" and not slots):
        args = {
            "query": entities["movie_query"] or entities["preference"],
            "movie_scope": "catalog" if facts else rules.movie_scope,
            "screening_date": None if facts else entities["screening_date"],
            "cinema_query": "" if facts else entities["cinema_query"],
            "showing_only": False if facts else rules.showing_only,
            "page": entities["page"],
        }
        add("search_movies", args, "查询影片资料" if facts else "查询影片列表")
    if slots:
        add(
            "search_screenings",
            {
                "movie_query": entities["movie_query"],
                "cinema_query": entities["cinema_query"],
                "screening_date": entities["screening_date"],
                "query_scope": rules.screening_scope,
                "showing_only": rules.showing_only,
            },
            "查询场次与票价",
        )
    if seats:
        if explicit_ids:
            for screening_id in explicit_ids:
                add("query_seats", {"screening_id": screening_id}, f"查询场次 {screening_id} 的座位")
        else:
            add("query_seats", {}, "查询指定场次的座位")
    if state["intent"] == "recommend":
        add("recommend_movies", {"preference": entities["preference"]}, "按偏好推荐电影")
    if state["intent"] == "policy" or any(word in text for word in ("规则", "须知", "政策")):
        add("query_ticket_policy", {}, "检索当前票务规则")
    return tasks


def screening_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect only this turn's validated discovery evidence in chronological order."""
    rows = {}
    for item in observations:
        if item["name"] == "search_screenings":
            values = item["data"]
        elif item["name"] == "search_movies" and isinstance(item["data"], dict):
            values = [slot for movie in item["data"].get("items", []) for slot in movie.get("screenings", [])]
        else:
            continue
        for row in values:
            if type(row.get("id")) is int:
                rows[row["id"]] = row
    return sorted(rows.values(), key=lambda row: (row.get("start_time", ""), row["id"]))


def progress(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve dependencies, selected seat IDs, and completion from validated observations."""
    observations = state.get("observations", [])
    result = []
    for task in state.get("tasks", []):
        current = dict(task)
        current["status"] = "pending"
        matches = [
            item
            for item in observations
            if item["name"] == task["name"]
            and all(
                (
                    key in ("query", "movie_query", "cinema_query", "preference")
                    or str(item["arguments"].get(key, "")).lower() == str(value).lower()
                )
                for key, value in task["arguments"].items()
            )
        ]
        if task["name"] == "query_seats" and not task["arguments"]:
            discovery = any(item["name"] == "search_screenings" for item in observations)
            rows = screening_rows(observations)
            if not discovery and not rows:
                current["status"] = "blocked"
            elif not rows:
                current["status"] = "empty"
            else:
                text = state["question"]
                if re.search(r"第一场|首场|最早", text):
                    rows = rows[:1]
                elif re.search(r"前[两二2]场", text):
                    rows = rows[:2]
                elif not re.search(r"逐场|每场|各场|所有场次|全部场次", text) and len(rows) > 1:
                    current["status"] = "clarify"
                    rows = []
                if rows:
                    for row in rows:
                        number = row["id"]
                        done = any(
                            item["name"] == "query_seats" and item["arguments"]["screening_id"] == number
                            for item in observations
                        )
                        result.append(
                            {
                                **task,
                                "arguments": {"screening_id": number},
                                "label": f"查询场次 {number} 的座位",
                                "status": "done" if done else "pending",
                            }
                        )
                    continue
        elif matches:
            current["status"] = "done"
        result.append(current)
    return result


def is_complete(state: dict[str, Any]) -> bool:
    """Stop once every explicit outcome has evidence or an authoritative empty result."""
    items = progress(state)
    return bool(items) and all(item["status"] in ("done", "empty") for item in items)


def next_call(state: dict[str, Any]) -> dict[str, Any] | None:
    """Offer one bounded recovery action when a model finishes before its requested work."""
    for task in progress(state):
        if task["status"] == "clarify":
            return {"name": "ask_user", "args": {"question": "查询到多个场次，请提供要查询座位的场次编号。"}}
        if task["status"] == "pending":
            args = dict(task["arguments"])
            if task["name"] == "query_ticket_policy":
                args["question"] = state["question"]
            return {"name": task["name"], "args": args}
    return None
