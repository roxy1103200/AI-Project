"""Track requested business outcomes separately from a model's initial single intent."""

# 导入当前步骤使用的模块或类型。
# isort: off
import re
from datetime import date

# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
from app.intent import SCREENING_PATTERN, rule_plan
from app.query_semantics import movie_fields, query_domains
from app.time_normalization import time_arguments, recommendation_time_arguments
# isort: on

# 为 `FACT_WORDS` 保存当前步骤所需的值。
FACT_WORDS = ("导演", "片长", "时长", "多长", "谁导", "主演", "演员", "简介", "资料", "上映日期", "上映时间")
# 为 `SEAT_WORDS` 保存当前步骤所需的值。
SEAT_WORDS = ("座位", "空座", "空位", "选座", "余座", "还有座", "剩几个座")


# 声明当前处理单元及其入口。
def build_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Combine one understanding result with explicit outcome and dependency rules."""
    if state.get("clarification") or state.get("needs_clarification"):
        return []
    question, entities = state["question"], state["entities"]
    text = re.sub(r"《[^》]+》", "", question)
    reference = entities.get("temporal", {}).get("reference_date")
    rules = rule_plan(question, state["messages"][:-1], date.fromisoformat(reference) if reference else None)
    requested = set(state.get("requested_intents", []))
    domains = query_domains(question, bool(entities.get("order_no")))
    if "screenings" not in domains and (entities.get("order_no") or entities.get("screening_id")):
        requested.discard("screenings")
    if "movies" not in domains and "screenings" in domains and state["intent"] != "movies":
        requested.discard("movies")
    tasks: list[dict[str, Any]] = []

    def add(name: str, arguments: dict[str, Any], label: str) -> None:
        if any(task["name"] == name and task["arguments"] == arguments for task in tasks):
            return
        tasks.append({"id": f"task-{len(tasks) + 1}", "name": name, "arguments": arguments, "label": label})

    order_nos = entities.get("order_nos") or ([entities["order_no"]] if entities["order_no"] else [])
    if state["intent"] in ("order", "refund") or order_nos:
        for number in order_nos:
            add("query_order", {"order_no": number}, f"查询订单 {number}")
    recommendation_dates = state["intent"] == "recommend" and set(movie_fields(question)) <= {"release_date"} and not entities["movie_query"]
    facts = (bool(movie_fields(question)) or any(word in text for word in FACT_WORDS)) and not recommendation_dates
    if recommendation_dates:
        requested.discard("movies")
    seats = state["intent"] == "seats" or "seats" in requested or "seats" in domains or any(word in text for word in SEAT_WORDS)
    explicit_ids = list(dict.fromkeys(int(match[1]) for match in SCREENING_PATTERN.finditer(question)))
    if not explicit_ids and entities["screening_id"]:
        explicit_ids = [entities["screening_id"]]
    slot_words = ("场次", "排期", "排片", "票价", "多少钱", "哪几场", "几场", "最低价", "最便宜")
    slots = (
        state["intent"] == "screenings"
        or "screenings" in requested
        or ("screenings" in domains and (state["intent"] != "movies" or facts))
        or (seats and not explicit_ids)
        or (facts and any(word in text for word in slot_words))
        or (
            not explicit_ids
            and state["intent"] != "movies"
            and any(word in text for word in slot_words)
            and any(word in text for word in ("查", "找", "比较", "看看", "瞅"))
        )
    )
    titles = entities.get("candidate_titles") or list(dict.fromkeys(re.findall(r"《([^》]+)》", question)))
    if "screenings" not in domains and entities.get("order_no"):
        slots = False
    movie_queries = titles if len(titles) > 1 else [entities["movie_query"] or entities["preference"]]
    if facts or "movies" in requested or (state["intent"] == "movies" and not slots):
        for query in movie_queries:
            add(
                "search_movies",
                {
                    "query": query,
                    "movie_scope": "catalog" if facts else rules.movie_scope,
                    "screening_date": None if facts else entities["screening_date"],
                    "cinema_query": "" if facts else entities["cinema_query"],
                    "showing_only": False if facts else rules.showing_only,
                    "page": entities["page"],
                    **time_arguments(entities, "release"),
                    **({} if facts else time_arguments(entities, "screening")),
                },
                "查询影片资料" if facts else "查询影片列表",
            )
    if slots:
        for query in titles if titles else [entities["movie_query"]]:
            add(
                "search_screenings",
                {
                    "movie_query": query,
                    "cinema_query": entities["cinema_query"],
                    "screening_date": entities["screening_date"],
                    "query_scope": rules.screening_scope,
                    "showing_only": rules.showing_only,
                    **time_arguments(entities, "screening"),
                },
                "查询场次与票价",
            )
    if seats:
        if explicit_ids:
            for screening_id in explicit_ids:
                add("query_seats", {"screening_id": screening_id}, f"查询场次 {screening_id} 的座位")
        else:
            add("query_seats", {}, "查询指定场次的座位")
    if state["intent"] == "recommend" or "recommend" in requested:
        add("recommend_movies", {"preference": entities["preference"], **recommendation_time_arguments(entities)}, "按偏好推荐电影")
    policy_words = ("规则", "须知", "政策", "退票期限", "退票截止", "提前多久", "最晚多久", "啥时候不能退")
    if state["intent"] == "policy" or "policy" in requested or "policy" in domains or any(word in text for word in policy_words):
        add("query_ticket_policy", {}, "检索当前票务规则")
    return tasks


# 声明当前处理单元及其入口。
def screening_rows(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect only this turn's validated discovery evidence in chronological order."""
    # 为 `rows` 保存当前步骤所需的值。
    rows = {}
    # 进入对应的循环、异常处理或资源管理分支。
    for item in observations:
        # 检查 `if item["name"] == "search_screenings"`，据此选择当前处理分支。
        if item["name"] == "search_screenings":
            # 为 `values` 保存当前步骤所需的值。
            values = item["data"]
        # 检查 `elif item["name"] == "search_movies" and isinstance(item["data"], dict)`，据此选择当前处理分支。
        elif item["name"] == "search_movies" and isinstance(item["data"], dict):
            # 为 `values` 保存当前步骤所需的值。
            values = [slot for movie in item["data"].get("items", []) for slot in movie.get("screenings", [])]
        # 进入对应的循环、异常处理或资源管理分支。
        else:
            # 结束本次循环并处理下一项。
            continue
        # 进入对应的循环、异常处理或资源管理分支。
        for row in values:
            # 检查 `if type(row.get("id")) is int`，据此选择当前处理分支。
            if type(row.get("id")) is int:
                rows[row["id"]] = row
    # 将当前计算结果返回给调用方。
    return sorted(rows.values(), key=lambda row: (row.get("start_time", ""), row["id"]))


# 声明当前处理单元及其入口。
def progress(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve dependencies, selected seat IDs, and completion from validated observations."""
    # 为 `observations` 保存当前步骤所需的值。
    observations = state.get("observations", [])
    # 为 `result` 保存当前步骤所需的值。
    result = []
    # 进入对应的循环、异常处理或资源管理分支。
    for task in state.get("tasks", []):
        # 为 `current` 保存当前步骤所需的值。
        current = dict(task)
        current["status"] = "pending"
        # 为 `matches` 保存当前步骤所需的值。
        matches = [
            # 继续构造当前业务表达式或数据结构。
            item
            # 进入对应的循环、异常处理或资源管理分支。
            for item in observations
            # 检查 `if item["name"] == task["name"]`，据此选择当前处理分支。
            if item["name"] == task["name"]
            # 继续构造当前业务表达式或数据结构。
            and all(
                # 继续构造当前业务表达式或数据结构。
                (
                    (item.get("task_id") is not None and item.get("task_id") == task.get("id"))
                    or str(item["arguments"].get(key, "")).lower() == str(value).lower()
                )
                # 进入对应的循环、异常处理或资源管理分支。
                for key, value in task["arguments"].items()
            )
        ]
        # 检查 `if task["name"] == "query_seats" and not task["arguments"]`，据此选择当前处理分支。
        if task["name"] == "query_seats" and not task["arguments"]:
            # 为 `discovery` 保存当前步骤所需的值。
            discovery = any(item["name"] == "search_screenings" for item in observations)
            # 为 `rows` 保存当前步骤所需的值。
            rows = screening_rows(observations)
            # 检查 `if not discovery and not rows`，据此选择当前处理分支。
            if not discovery and not rows:
                current["status"] = "blocked"
            # 检查 `elif not rows`，据此选择当前处理分支。
            elif not rows:
                current["status"] = "empty"
            # 进入对应的循环、异常处理或资源管理分支。
            else:
                # 为 `text` 保存当前步骤所需的值。
                text = state["question"]
                # 检查 `if re.search(r"第一场|首场|最早", text)`，据此选择当前处理分支。
                if re.search(r"第一场|首场|最早", text):
                    # 为 `rows` 保存当前步骤所需的值。
                    rows = rows[:1]
                # 检查 `elif re.search(r"前[两二2]场", text)`，据此选择当前处理分支。
                elif re.search(r"前[两二2]场", text):
                    # 为 `rows` 保存当前步骤所需的值。
                    rows = rows[:2]
                # 检查 `elif not re.search(r"逐场|每场|各场|所有场次|全部场次", text) and len(rows) > 1`，据此选择当前处理分支。
                elif not re.search(r"逐场|每场|各场|所有场次|全部场次", text) and len(rows) > 1:
                    current["status"] = "clarify"
                    # 为 `rows` 保存当前步骤所需的值。
                    rows = []
                # 检查 `if rows`，据此选择当前处理分支。
                if rows:
                    # 进入对应的循环、异常处理或资源管理分支。
                    for row in rows:
                        # 为 `number` 保存当前步骤所需的值。
                        number = row["id"]
                        # 为 `done` 保存当前步骤所需的值。
                        done = any(
                            item["name"] == "query_seats" and item["arguments"]["screening_id"] == number
                            # 进入对应的循环、异常处理或资源管理分支。
                            for item in observations
                        )
                        # 继续构造当前业务表达式或数据结构。
                        result.append(
                            # 继续构造当前业务表达式或数据结构。
                            {
                                # 补充当前表达式的 `**task` 参数或元素。
                                **task,
                                # 设置当前结构中的 `arguments` 字段。
                                "id": f"{task['id']}:{number}",
                                "arguments": {"screening_id": number},
                                # 设置当前结构中的 `label` 字段。
                                "label": f"查询场次 {number} 的座位",
                                # 设置当前结构中的 `status` 字段。
                                "status": "done" if done else "pending",
                            }
                        )
                    # 结束本次循环并处理下一项。
                    continue
        # 检查 `elif matches`，据此选择当前处理分支。
        elif matches:
            current["status"] = "done"
        # 继续构造当前业务表达式或数据结构。
        result.append(current)
    # 将当前计算结果返回给调用方。
    return result


# 声明当前处理单元及其入口。
def is_complete(state: dict[str, Any]) -> bool:
    """Stop once every explicit outcome has evidence or an authoritative empty result."""
    # 为 `items` 保存当前步骤所需的值。
    items = progress(state)
    # 将当前计算结果返回给调用方。
    return bool(items) and all(item["status"] in ("done", "empty") for item in items)


# 声明当前处理单元及其入口。
def next_call(state: dict[str, Any]) -> dict[str, Any] | None:
    """Offer one bounded recovery action when a model finishes before its requested work."""
    # 进入对应的循环、异常处理或资源管理分支。
    for task in progress(state):
        # 检查 `if task["status"] == "clarify"`，据此选择当前处理分支。
        if task["status"] == "clarify":
            # 将当前计算结果返回给调用方。
            return {"name": "ask_user", "args": {"question": "查询到多个场次，请提供要查询座位的场次编号。"}}
        # 检查 `if task["status"] == "pending"`，据此选择当前处理分支。
        if task["status"] == "pending":
            # 为 `args` 保存当前步骤所需的值。
            args = dict(task["arguments"])
            # 检查 `if task["name"] == "query_ticket_policy"`，据此选择当前处理分支。
            if task["name"] == "query_ticket_policy":
                args["question"] = state["question"]
            # 将当前计算结果返回给调用方。
            return {"name": task["name"], "args": args}
    # 将当前计算结果返回给调用方。
    return None


def select_route(state: dict[str, Any]) -> tuple[str, str]:
    """Route from existing plan data without paying for a second classifier call."""
    if state.get("needs_clarification") or state["intent"] == "chat":
        return "direct", "clarification" if state.get("needs_clarification") else "chat"
    tasks = state.get("tasks", [])
    if len(tasks) != 1:
        return "react", "multiple_tasks" if tasks else "uncertain_plan"
    if tasks[0]["name"] == "query_seats" and not tasks[0]["arguments"].get("screening_id"):
        return "react", "discovery_dependency"
    if len(re.findall(r"《[^》]+》", state["question"])) > 1:
        return "react", "multiple_entities"
    if re.search(r"顺便|再帮我|再查|再看|同时|一并|分别|对比|比较|先.{0,80}再", state["question"]):
        return "react", "composite_expression"
    if state["confidence"] < 0.8:
        return "react", "uncertain_plan"
    return "simple", "single_complete_task"


def matching_task(state: dict[str, Any], name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Associate validated evidence with one pending task, keeping record ownership."""
    candidates = [item for item in progress(state) if item["name"] == name and item["status"] == "pending"]
    exact = next(
        (
            item
            for item in candidates
            if all(
                str(arguments.get(key, "")).lower() == str(value).lower() for key, value in item["arguments"].items()
            )
        ),
        None,
    )
    return exact or (candidates[0] if len(candidates) == 1 else None)
