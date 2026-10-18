"""Independent v2 scoring from fixture facts, not the Agent's normalization implementation."""

import re
from datetime import datetime, timedelta, timezone

BEIJING = timezone(timedelta(hours=8))


def active_parameter(value: object) -> bool:
    """Java's optional JSON fields are recorded as 'null'; only non-null values filter."""
    return value not in (None, "", "null", "None")


def movie_date(value: object) -> str:
    """Decode the Java fixture's SQL date serialization without importing runtime code."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, BEIJING).date().isoformat()
    return str(value)[:10] if value is not None else ""


def recommendation_titles(answer: str) -> list[str]:
    """Read only the deterministic recommendation rows displayed to the user."""
    return re.findall(r"^• ([^\n｜]+)｜", answer, re.MULTILINE)


def score_time_policy(row: dict) -> list[str]:
    """Check scope, provenance, actual queries and independently filtered movie facts."""
    failures = []

    def require(condition: object, message: str) -> None:
        if not condition:
            failures.append(message)

    mode = row["check"].removeprefix("rt:")
    answer = row["answer"]
    context = row.get("record", {}).get("context", {})
    windows = context.get("temporal_summary", {}).get("windows", [])
    calls = [call for call in row.get("evidence", {}).get("java", {}).get("calls", []) if call["status"] == 200]
    today = datetime.fromisoformat(row["reference_date"]).date()
    start, end = today - timedelta(days=6), today
    target = "release"
    if mode in {"release_next", "bookable_week"}:
        monday = today - timedelta(days=today.weekday())
        start, end = (
            (monday + timedelta(days=7), monday + timedelta(days=13))
            if mode == "release_next"
            else (monday, monday + timedelta(days=6))
        )
    if mode in {"screening_recent", "bookable_week", "candidates"}:
        target = "screening"
    if mode == "candidates":
        start = end = today
    matched = next(
        (
            w
            for w in windows
            if w.get("target") == target
            and w.get("date_from") == start.isoformat()
            and w.get("date_to") == end.isoformat()
        ),
        {},
    )
    require(matched.get("status") == "resolved", "时间对象或日期区间未正确解决")
    require(not re.search(r"新上映的.*还是.*可购票场次", answer, re.DOTALL), "仍在询问不必要的时间对象")
    require(bool(calls), "缺少本轮 Java 查询证据")
    prefix = "releaseDate" if target == "release" else "screeningDate"
    matching = [
        call
        for call in calls
        if (
            call["parameters"].get(prefix + "From") == start.isoformat()
            and call["parameters"].get(prefix + "To") == end.isoformat()
        )
        or (target == "screening" and start == end and call["parameters"].get("screeningDate") == start.isoformat())
    ]
    require(bool(matching), "Java 实际查询条件与日期口径不一致")
    if target == "screening":
        if mode != "candidates":
            require(not any(w.get("target") == "release" for w in windows), "纠正后仍残留默认上映限制")
            require(
                not any(active_parameter(call["parameters"].get("releaseDateFrom")) for call in calls),
                "Java 收到已撤销的上映条件",
            )
        if mode == "screening_recent":
            require(
                any(
                    call["parameters"].get("movieScope") == "scheduled"
                    or call["parameters"].get("queryScope") == "scheduled"
                    for call in calls
                ),
                "未要求有票却添加了可订购限制",
            )
        if mode == "candidates":
            expected_titles = set(recommendation_titles(row.get("prior_answer", "")))
            observations = row.get("evidence", {}).get("agent", {}).get("observations", [])
            queried = {
                item.get("arguments", {}).get("movie_query")
                for item in observations
                if item.get("tool") == "search_screenings"
            }
            require(bool(expected_titles) and queried == expected_titles, "未按上一轮推荐集合查询场次")
            require(
                all(str(call["parameters"].get("screeningHourFrom")) == "18" for call in matching), "今晚时段条件丢失"
            )
        return failures

    soft = mode in {"soft", "science_soft"}
    assumed = mode not in {"explicit", "genre_explicit"}
    require(matched.get("assumed_target") is assumed, "默认含义与用户明确含义的来源标记错误")
    require(matched.get("strength") == ("soft" if soft else "hard"), "日期软硬条件错误")
    require(not any(w.get("target") == "screening" for w in windows), "仅按上映推荐却增加了观影限制")
    require(
        not any(
            any(key.startswith("screening") and active_parameter(value) for key, value in call["parameters"].items())
            for call in calls
        ),
        "Java 查询被额外附加观影条件",
    )
    require(context.get("tool_calls") == ["recommend_movies"], "简单推荐应只有一次推荐业务查询")
    if assumed:
        require("我先按" in answer and "已确认" not in answer, "默认含义未披露或被写成用户已确认")
    require(start.isoformat() in answer and end.isoformat() in answer, "回答没有实际绝对日期")
    require("以下影片具有符合条件的当前可订购场次" not in answer, "上映查询虚构可订购结论")

    genre = (
        "科幻"
        if mode.startswith("science")
        else "悬疑"
        if mode in {"genre", "genre_explicit", "soft", "release_next"}
        else ""
    )
    movies = row.get("fixture", {}).get("movies", [])
    eligible = [
        movie
        for movie in movies
        if movie.get("status") not in {"OFFLINE", "ARCHIVED"}
        and (not genre or genre in movie.get("genre", "") or genre in movie["title"])
    ]

    def inside(movie: dict) -> bool:
        return start.isoformat() <= movie_date(movie.get("release_date")) <= end.isoformat()

    if not soft:
        eligible = [movie for movie in eligible if inside(movie)]
    eligible.sort(key=lambda m: (movie_date(m.get("release_date")), m["id"]), reverse=True)
    if soft:
        eligible.sort(key=lambda m: not inside(m))
    expected = [movie["title"] for movie in eligible[:5]]
    actual = recommendation_titles(answer)
    require(actual == expected, "推荐影片或排序与独立夹具预期不一致")
    for movie in eligible[:5]:
        line = next((line for line in answer.splitlines() if line.startswith("• " + movie["title"] + "｜")), "")
        released = movie_date(movie.get("release_date"))
        require(released in line if released else "暂未收录" in line, "上映日期未按事实展示")
        if soft and not inside(movie):
            require("补充推荐" in line if released else "无法确认" in line, "范围外或未知日期未标注")
    if not expected:
        require("没有查到" in answer or "未找到" in answer, "空结果没有明确说明")
    return failures
