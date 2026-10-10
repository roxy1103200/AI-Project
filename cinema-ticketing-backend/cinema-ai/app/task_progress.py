"""Track requested business outcomes separately from a model's initial single intent."""

# 导入当前步骤使用的模块或类型。
# isort: off
import re
# 导入当前步骤使用的模块或类型。
from typing import Any

# 导入当前步骤使用的模块或类型。
from app.intent import SCREENING_PATTERN, rule_plan
# isort: on

# 为 `FACT_WORDS` 保存当前步骤所需的值。
FACT_WORDS = ("导演", "片长", "主演", "演员", "简介", "资料", "上映日期", "上映时间")
# 为 `SEAT_WORDS` 保存当前步骤所需的值。
SEAT_WORDS = ("座位", "空座", "选座", "余座")


# 声明当前处理单元及其入口。
def build_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Decompose explicit requests while keeping dates/scopes local to each query."""
    question, entities = state["question"], state["entities"]
    # 为 `text` 保存当前步骤所需的值。
    text = re.sub(r"《[^》]+》", "", question)
    # 为 `rules` 保存当前步骤所需的值。
    rules = rule_plan(question, state["messages"][:-1])
    # 设置当前结构中的 `tasks` 字段。
    tasks: list[dict[str, Any]] = []

    # 声明当前处理单元及其入口。
    def add(name: str, arguments: dict[str, Any], label: str) -> None:
        tasks.append({"name": name, "arguments": arguments, "label": label})

    # 为 `order_nos` 保存当前步骤所需的值。
    order_nos = entities.get("order_nos") or ([entities["order_no"]] if entities["order_no"] else [])
    # 检查 `if state["intent"] in ("order", "refund") or order_nos`，据此选择当前处理分支。
    if state["intent"] in ("order", "refund") or order_nos:
        # 进入对应的循环、异常处理或资源管理分支。
        for number in order_nos:
            # 调用 `add` 执行当前业务操作。
            add("query_order", {"order_no": number}, f"查询订单 {number}")
    # 为 `facts` 保存当前步骤所需的值。
    facts = any(word in text for word in FACT_WORDS)
    # 为 `seats` 保存当前步骤所需的值。
    seats = state["intent"] == "seats" or any(word in text for word in SEAT_WORDS)
    # 为 `explicit_ids` 保存当前步骤所需的值。
    explicit_ids = list(dict.fromkeys(int(match[1]) for match in SCREENING_PATTERN.finditer(question)))
    # 检查 `if not explicit_ids and entities["screening_id"]`，据此选择当前处理分支。
    if not explicit_ids and entities["screening_id"]:
        # 为 `explicit_ids` 保存当前步骤所需的值。
        explicit_ids = [entities["screening_id"]]
    # 为 `slots` 保存当前步骤所需的值。
    slots = (
        state["intent"] == "screenings"
        # 调用 `or` 执行当前业务操作。
        or (seats and not explicit_ids)
        # 调用 `or` 执行当前业务操作。
        or (facts and any(word in text for word in ("场次", "排期", "排片", "票价")))
        # 调用 `or` 执行当前业务操作。
        or (
            # 继续构造当前业务表达式或数据结构。
            not explicit_ids
            and state["intent"] != "movies"
            and any(word in text for word in ("场次", "票价"))
            and any(word in text for word in ("查", "找", "比较"))
        )
    )
    # 检查 `if facts or (state["intent"] == "movies" and not slots)`，据此选择当前处理分支。
    if facts or (state["intent"] == "movies" and not slots):
        # 为 `args` 保存当前步骤所需的值。
        args = {
            # 设置当前结构中的 `query` 字段。
            "query": entities["movie_query"] or entities["preference"],
            # 设置当前结构中的 `movie_scope` 字段。
            "movie_scope": "catalog" if facts else rules.movie_scope,
            # 设置当前结构中的 `screening_date` 字段。
            "screening_date": None if facts else entities["screening_date"],
            # 设置当前结构中的 `cinema_query` 字段。
            "cinema_query": "" if facts else entities["cinema_query"],
            # 设置当前结构中的 `showing_only` 字段。
            "showing_only": False if facts else rules.showing_only,
            # 设置当前结构中的 `page` 字段。
            "page": entities["page"],
        }
        # 调用 `add` 执行当前业务操作。
        add("search_movies", args, "查询影片资料" if facts else "查询影片列表")
    # 检查 `if slots`，据此选择当前处理分支。
    if slots:
        # 调用 `add` 执行当前业务操作。
        add(
            # 补充当前表达式的 `"search_screenings"` 参数或元素。
            "search_screenings",
            # 继续构造当前业务表达式或数据结构。
            {
                # 设置当前结构中的 `movie_query` 字段。
                "movie_query": entities["movie_query"],
                # 设置当前结构中的 `cinema_query` 字段。
                "cinema_query": entities["cinema_query"],
                # 设置当前结构中的 `screening_date` 字段。
                "screening_date": entities["screening_date"],
                # 设置当前结构中的 `query_scope` 字段。
                "query_scope": rules.screening_scope,
                # 设置当前结构中的 `showing_only` 字段。
                "showing_only": rules.showing_only,
            },
            # 补充当前表达式的 `"查询场次与票价"` 参数或元素。
            "查询场次与票价",
        )
    # 检查 `if seats`，据此选择当前处理分支。
    if seats:
        # 检查 `if explicit_ids`，据此选择当前处理分支。
        if explicit_ids:
            # 进入对应的循环、异常处理或资源管理分支。
            for screening_id in explicit_ids:
                # 调用 `add` 执行当前业务操作。
                add("query_seats", {"screening_id": screening_id}, f"查询场次 {screening_id} 的座位")
        # 进入对应的循环、异常处理或资源管理分支。
        else:
            # 调用 `add` 执行当前业务操作。
            add("query_seats", {}, "查询指定场次的座位")
    # 检查 `if state["intent"] == "recommend"`，据此选择当前处理分支。
    if state["intent"] == "recommend":
        # 调用 `add` 执行当前业务操作。
        add("recommend_movies", {"preference": entities["preference"]}, "按偏好推荐电影")
    # 检查 `if state["intent"] == "policy" or any(word in text for word in ("规则", "须知", "政策"))`，据此选择当前处理分支。
    if state["intent"] == "policy" or any(word in text for word in ("规则", "须知", "政策")):
        # 调用 `add` 执行当前业务操作。
        add("query_ticket_policy", {}, "检索当前票务规则")
    # 将当前计算结果返回给调用方。
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
                    key in ("query", "movie_query", "cinema_query", "preference")
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
