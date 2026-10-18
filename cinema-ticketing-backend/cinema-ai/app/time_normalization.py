"""Resolve cinema date constraints against one request-owned Beijing date."""

import calendar
import re
from contextlib import suppress
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.query_semantics import query_domains

TimeTarget = Literal["release", "screening", "unspecified"]
ResolvedTimeTarget = Literal["release", "screening"]
TIME_POLICY_VERSION = "recommendation-time-v2"

RELEASE_FILTERS = ("release_date_from", "release_date_to")
SCREENING_FILTERS = ("screening_date_from", "screening_date_to", "screening_hour_from", "screening_hour_to")
TIME_FILTERS = RELEASE_FILTERS + SCREENING_FILTERS
DATE_TOKEN = r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:今年|明年|去年)?(?:\d{4}年)?\d{1,2}月\d{1,2}[日号]?)"
DAY_TOKEN = r"(?:大后天|后天|明天|明晚|明早|今天|今日|今晚|今早|昨天|昨日|前天)"
WEEKDAY_TOKEN = r"(?:(?:上|下|本|这)?(?:周|星期)[一二三四五六日天])"
RANGE_TOKEN = rf"(?:{DATE_TOKEN}|{DAY_TOKEN}|{WEEKDAY_TOKEN})"
EXPRESSION = re.compile(
    rf"{RANGE_TOKEN}\s*(?:至|到|~|～)\s*{RANGE_TOKEN}|{DATE_TOKEN}"
    r"|(?:最近|近|过去|未来|接下来|今后)(?:的)?\s*[\d一二两三四五六七八九十]+\s*(?:个)?(?:星期|周|天|日|月)"
    r"|(?:上|下|本|这)(?:周|星期)(?:末|[一二三四五六日天])?"
    r"|(?:周|星期)(?:末|[一二三四五六日天])"
    r"|(?:上|下|本|这|这个)(?:个)?月"
    r"|[\d一二两三四五六七八九十]+(?:天|日|周|个月)(?:前|后)"
    r"|今年|去年|明年"
    r"|大后天|后天|明天|明晚|明早|今天|今日|今晚|今早|昨天|昨日|前天"
    r"|最近|近期|过几天"
)


class TimeWindow(BaseModel):
    """Keep an interval, its business meaning, and any unresolved assumption."""

    expression: str = Field(max_length=120)
    target: TimeTarget
    status: Literal["resolved", "ambiguous", "invalid"] = "resolved"
    strength: Literal["hard", "soft"] = "hard"
    date_from: str | None = None
    date_to: str | None = None
    hour_from: int | None = None
    hour_to: int | None = None
    assumed_target: bool = False
    reason: Literal["none", "vague", "year_required", "invalid_date", "conflict", "target_required"] = "none"


class TemporalContext(BaseModel):
    """Carry the same reference date through understanding, tools, and tracing."""

    reference_date: str = ""
    time_zone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    windows: list[TimeWindow] = Field(default_factory=list, max_length=12)


def is_time_followup(question: str) -> bool:
    """Recognize date or daypart-only corrections without treating a new query as a follow-up."""
    text = question.strip(" ？?！!。").removeprefix("那").removesuffix("呢")
    return (
        EXPRESSION.fullmatch(text) is not None
        or re.fullmatch(r"早上|早晨|上午|中午|下午|晚上|晚间|夜场|凌晨", text) is not None
    )


def is_query_refinement(question: str) -> bool:
    """Recognize bounded corrections without inheriting unrelated standalone requests."""
    return (
        is_time_followup(question)
        or bool(re.fullmatch(r"新上映的|上映的|有票的|按上映日期|按观影日期", question.strip(" ？?。")))
        or bool(
            re.search(
                r"^(?:我是说|我说的是|改成|换成|还是|按观影日期|按上映日期)|这些电影|这些影片|这几部", question.strip()
            )
        )
    )


def references_recommendations(question: str) -> bool:
    """Identify an additive query about the previous recommendation set."""
    return bool(re.search(r"这些(?:电影|影片)?|这几部", question)) and bool(
        re.search(r"场次|有票|买票|购票|排期|放映|票价|多少钱|能看|观影|今晚|明晚", question)
    )


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = {word: index for index, word in enumerate("零一二三四五六七八九")}
    text = text.replace("两", "二")
    if "十" in text:
        tens, units = text.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return digits.get(text, 0)


def _month(day: date, offset: int) -> date:
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _calendar_date(text: str, today: date, context: str) -> date:
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        return date(*(int(part) for part in re.split(r"[-/]", text)))
    match = re.fullmatch(r"(今年|明年|去年)?(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?", text)
    assert match is not None
    year = int(match[2]) if match[2] else today.year + {"明年": 1, "去年": -1}.get(match[1], 0)
    result = date(year, int(match[3]), int(match[4]))
    if not match[1] and not match[2]:
        if re.search(r"未来|接下来|即将|下次", context) and result < today:
            result = result.replace(year=year + 1)
        elif abs((result - today).days) > 180:
            raise LookupError("year_required")
    return result


def _bounds(expression: str, today: date, target: str, context: str) -> tuple[date, date]:
    parts = re.split(r"\s*(?:至|到|~|～)\s*", expression)
    if len(parts) == 2:
        start = _bounds(parts[0], today, target, context)[0]
        # A December-to-January interval supplies the missing year of its end.
        end_context = context if not (start.month == 12 and "年" not in parts[1]) else "未来"
        end = (
            _calendar_date(parts[1], start, end_context)
            if re.fullmatch(DATE_TOKEN, parts[1])
            else _bounds(parts[1], today, target, context)[1]
        )
        if end < start:
            raise ValueError("reversed_range")
        return start, end
    if re.fullmatch(DATE_TOKEN, expression):
        day = _calendar_date(expression, today, context)
        return day, day
    offset = re.fullmatch(r"([\d一二两三四五六七八九十]+)(天|日|周|个月)(前|后)", expression)
    if offset:
        amount = _number(offset[1]) * (-1 if offset[3] == "前" else 1)
        if not 1 <= abs(amount) <= 366 or (offset[2] == "个月" and abs(amount) > 12):
            raise ValueError("invalid_offset")
        day = (
            _month(today, amount)
            if offset[2] == "个月"
            else today + timedelta(days=amount * (7 if offset[2] == "周" else 1))
        )
        return day, day
    if expression in ("今年", "去年", "明年"):
        year = today.year + {"去年": -1, "明年": 1}.get(expression, 0)
        end = today if expression == "今年" and target == "release" else date(year, 12, 31)
        return date(year, 1, 1), end
    rolling = re.fullmatch(
        r"(最近|近|过去|未来|接下来|今后)(?:的)?\s*([\d一二两三四五六七八九十]+)\s*(?:个)?(星期|周|天|日|月)",
        expression,
    )
    if rolling:
        amount = _number(rolling[2])
        if not 1 <= amount <= 366 or (rolling[3] == "月" and amount > 12):
            raise ValueError("invalid_range")
        future = rolling[1] in ("未来", "接下来", "今后")
        if rolling[3] == "月":
            return (
                (today, _month(today, amount) - timedelta(days=1))
                if future
                else (_month(today, -amount) + timedelta(days=1), today)
            )
        days = amount * (7 if rolling[3] in ("周", "星期") else 1)
        return (today, today + timedelta(days=days - 1)) if future else (today - timedelta(days=days - 1), today)
    week = re.fullmatch(r"(上|下|本|这)?(?:周|星期)(末|[一二三四五六日天])?", expression)
    if week:
        monday = today - timedelta(days=today.weekday())
        monday += timedelta(days={"上": -7, "下": 7}.get(week[1], 0))
        if week[2] == "末":
            if not week[1] and today.weekday() == 6:
                return today, today
            return monday + timedelta(days=5), monday + timedelta(days=6)
        if week[2]:
            day = monday + timedelta(days="一二三四五六日".index(week[2].replace("天", "日")))
            if not week[1] and day < today:
                day += timedelta(days=7)
            return day, day
        end = monday + timedelta(days=6)
        return monday, end
    month = re.fullmatch(r"(上|下|本|这|这个)(?:个)?月", expression)
    if month:
        first = _month(today.replace(day=1), {"上": -1, "下": 1}.get(month[1], 0))
        end = _month(first, 1) - timedelta(days=1)
        if target == "release" and month[1] in ("本", "这", "这个"):
            end = today
        return first, end
    offsets = {
        "前天": -2,
        "昨天": -1,
        "昨日": -1,
        "今天": 0,
        "今日": 0,
        "今晚": 0,
        "今早": 0,
        "明天": 1,
        "明晚": 1,
        "明早": 1,
        "后天": 2,
        "大后天": 3,
    }
    if expression in offsets:
        day = today + timedelta(days=offsets[expression])
        return day, day
    raise LookupError("vague")


def daypart_interval(text: str) -> tuple[int | None, int | None]:
    """Use documented cinema dayparts without matching unrelated words like 早点."""
    if re.search(r"晚上|晚间|晚场|今晚|明晚|夜场|夜间|夜里", text):
        return 18, 24
    if "下午" in text:
        return 12, 18
    if re.search(r"上午|早上|早场|今早|明早", text):
        return 0, 12
    return None, None


def normalize_times(question: str, today: date, default_target: TimeTarget) -> TemporalContext:
    """Resolve common Chinese day/range expressions; preserve ambiguity explicitly."""
    text = re.sub(r"《[^》]+》", lambda match: " " * len(match[0]), question)
    result = TemporalContext(reference_date=today.isoformat())
    for match in list(EXPRESSION.finditer(text))[:12]:
        left = max(text.rfind(mark, 0, match.start()) for mark in "，,；;。") + 1
        right = min((pos for mark in "，,；;。" if (pos := text.find(mark, match.end())) >= 0), default=len(text))
        context = text[left:right]
        after = text[match.end() : right]
        before = text[left : match.start()]
        if re.match(r"(?:内|之内|期间|的)?(?:新)?(?:上映|首映|发行|新片)", after) or re.search(
            r"(?:上映|首映|发行)(?:于|日期为|日期是)?\s*$", before
        ):
            target, assumed = "release", False
        elif (
            re.search(
                r"场次|排期|排片|排场|排上了|开场|票价|多少钱|几点|有票|买票|购票|订购|座位|余票|还有座|空位|空座|放啥片|放映的电影|放映哪些电影|放映安排|影院.*放映|(?:能|可以|想|准备).{0,3}看|今晚|明晚|明早|今早",
                context,
            )
            or daypart_interval(context)[0] is not None
            or bool(query_domains(context) & {"screenings", "seats"})
        ):
            target, assumed = "screening", False
        elif re.search(r"新上映|上映日期|首映|发行|新片|上映的", context):
            target, assumed = "release", False
        else:
            target, assumed = default_target, default_target != "unspecified"
        strength = (
            "soft"
            if target != "screening"
            and re.search(r"最好|优先|尽量|偏好", context)
            and not re.search(r"必须|只要|仅限|一定要", context)
            else "hard"
        )
        window = TimeWindow(expression=match[0], target=target, strength=strength, assumed_target=assumed)
        try:
            start, end = _bounds(match[0], today, target, context)
            window.date_from, window.date_to = start.isoformat(), end.isoformat()
            if target == "unspecified":
                window.status, window.reason = "ambiguous", "target_required"
        except LookupError as error:
            window.status, window.reason = "ambiguous", str(error)
        except (ValueError, OverflowError):
            window.status, window.reason = "invalid", "invalid_date"
        if target == "screening":
            window.hour_from, window.hour_to = daypart_interval(context)
        result.windows.append(window)
    hour_from, hour_to = daypart_interval(text)
    if not result.windows and hour_from is not None:
        result.windows.append(
            TimeWindow(expression="观影时段", target="screening", hour_from=hour_from, hour_to=hour_to)
        )
    return result


def restore_displayed_times(prior: TemporalContext, pending: str) -> TemporalContext:
    """Keep previously displayed absolute intervals when a follow-up crosses midnight."""
    result = prior.model_copy(deep=True)
    for target, label in (("release", r"(?:按上映日期筛选：|优先推荐上映日期在 )"), ("screening", r"观影日期：")):
        match = re.search(label + r"(\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})", pending)
        if match:
            with suppress(ValueError):
                start, end = date.fromisoformat(match[1]), date.fromisoformat(match[2])
                if start <= end:
                    for window in result.windows:
                        if window.target == target:
                            window.date_from, window.date_to = start.isoformat(), end.isoformat()
    return result


def resolve_query_times(
    question: str,
    intent: str,
    today: date,
    *,
    prior: TemporalContext | None = None,
    pending: str = "",
    choice: ResolvedTimeTarget | None = None,
) -> TemporalContext:
    """Resolve explicit, inherited and assumed meanings through one shared policy."""
    if intent not in ("recommend", "movies", "screenings", "seats"):
        return TemporalContext(reference_date=today.isoformat())
    prior = restore_displayed_times(prior, pending) if prior else None
    if prior and choice:
        return clarify_time_target(prior, choice, question, pending, today)
    targets = {window.target for window in prior.windows} if prior else set()
    inherited: TimeTarget = next(iter(targets)) if len(targets) == 1 else "unspecified"
    context = normalize_times(question, today, inherited)
    text = re.sub(r"《[^》]+》", "", question)
    if intent == "recommend" and "推荐" in text:
        for window in context.windows:
            if (
                window.target == "unspecified"
                and window.reason == "target_required"
                and re.fullmatch(
                    r"(?:最近|近|过去)(?:的)?\s*(?:一|1)(?:个)?(?:周|星期)|(?:最近|近|过去)(?:的)?\s*(?:七|7)\s*(?:天|日)",
                    window.expression,
                )
            ):
                window.target, window.assumed_target = "release", True
                window.status, window.reason = "resolved", "none"
    if not prior:
        return context
    if not context.windows:
        context = prior.model_copy(deep=True)
        context.reference_date = today.isoformat()
        return context
    for window in context.windows:
        previous = next((item for item in prior.windows if item.target == window.target), None)
        if not previous:
            continue
        if window.assumed_target:
            window.assumed_target = previous.assumed_target
        if not re.search(r"必须|只要|仅限|一定要|最好|优先|尽量", question):
            window.strength = previous.strength
        if window.target == "screening" and window.status == "resolved":
            if window.date_from is None:
                window.date_from, window.date_to = previous.date_from, previous.date_to
            if window.hour_from is None and is_time_followup(question):
                window.hour_from, window.hour_to = previous.hour_from, previous.hour_to
    if references_recommendations(question):
        present = {window.target for window in context.windows}
        context.windows.extend(window.model_copy(deep=True) for window in prior.windows if window.target not in present)
    return context


def apply_time_filters(plan: Any, context: TemporalContext) -> None:
    """Project grounded intervals into backwards-compatible tool fields."""
    plan.temporal = context
    for key in TIME_FILTERS:
        setattr(plan, key, None)
    plan.release_date_preferred = False
    if context.windows:
        plan.screening_date = None
    for target in ("release", "screening"):
        windows = [window for window in context.windows if window.target == target]
        resolved = [window for window in windows if window.status == "resolved"]
        if len({(window.date_from, window.date_to, window.hour_from, window.hour_to) for window in resolved}) > 1:
            for window in windows:
                window.status, window.reason = "ambiguous", "conflict"
            continue
        if not resolved or any(window.status != "resolved" for window in windows):
            continue
        window = resolved[0]
        prefix = "release_date" if target == "release" else "screening_date"
        setattr(plan, prefix + "_from", window.date_from)
        setattr(plan, prefix + "_to", window.date_to)
        if target == "release":
            plan.release_date_preferred = all(window.strength == "soft" for window in resolved)
        else:
            if window.date_from == window.date_to:
                plan.screening_date = window.date_from
                plan.screening_date_from = plan.screening_date_to = None
            plan.screening_hour_from, plan.screening_hour_to = window.hour_from, window.hour_to


def temporal_clarification(context: TemporalContext, intent: str, preference: str = "", movie_query: str = "") -> str:
    """Ask only when an unresolved condition is required for the requested task."""
    for window in context.windows:
        if window.status == "resolved":
            continue
        if window.status == "invalid":
            return f"日期或时间范围“{window.expression}”不存在或无效，请提供有效日期或起止日期。"
        if window.reason == "year_required":
            return f"“{window.expression}”指哪一年？请补充年份，以便准确查询。"
        if window.reason == "conflict":
            return "你提供了多个时间范围，请确认要查询的起止日期，或分别说明每个范围对应的影片。"
        if window.target == "unspecified":
            period = (
                f"（{window.date_from} 至 {window.date_to}，北京时间）" if window.date_from and window.date_to else ""
            )
            subject = f"《{movie_query}》" if movie_query else f"{preference}片" if preference else "影片"
            return f"你想找“{window.expression}”{period}新上映的{subject}，还是这个期间有可购票场次的{subject}？"
        if window.target == "release" and intent == "recommend" and window.strength == "soft":
            continue
        kind = "上映日期范围" if window.target == "release" else "场次日期范围"
        return f"请明确“{window.expression}”的{kind}，例如最近7天，或提供起止日期。"
    return ""


def time_target_choice(question: str, history: list[dict[str, str]]) -> ResolvedTimeTarget | None:
    """Recognize an answer to clarification or an explicit correction of a displayed scope."""
    if not history or history[-1].get("role") != "assistant":
        return None
    pending = history[-1].get("content", "")
    binary = bool(re.search(r"新上映的.*还是.*可购票场次", pending, re.DOTALL))
    if not binary and not (re.search(r"上映日期|观影日期", pending) and is_query_refinement(question)):
        return None
    text = EXPRESSION.sub("", question).strip(" ，,。？?！!；;")
    if len(text) > 60:
        return None
    release = bool(re.search(r"新上映|上映的|上映日期|首映|新片", text)) or (
        binary and bool(re.search(r"前者|第一[个种项]", text))
    )
    screening = bool(re.search(r"有票|买票|购票|订购|场次|排期|排片|观影|放映|能看", text)) or (
        binary and bool(re.search(r"后者|第二[个种项]", text))
    )
    if references_recommendations(question):
        return None
    return ("release" if release else "screening") if release != screening else None


def clarify_time_target(
    prior: TemporalContext, target: ResolvedTimeTarget, question: str, pending: str, today: date
) -> TemporalContext:
    """Resolve a user's choice while keeping the dates displayed in the pending question."""
    context = normalize_times(question, today, target)
    if context.windows:
        if target == "release" and not re.search(r"必须|只要|仅限|一定要|最好|优先|尽量|偏好", question):
            for window in context.windows:
                window.strength = (
                    "soft" if prior.windows and all(item.strength == "soft" for item in prior.windows) else "hard"
                )
        return context
    context = prior.model_copy(deep=True)
    context.reference_date = today.isoformat()
    displayed = re.search(r"（(\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})，北京时间）", pending)
    for window in context.windows:
        window.target, window.assumed_target = target, False
        if displayed and len(context.windows) == 1:
            with suppress(ValueError):
                start, end = date.fromisoformat(displayed[1]), date.fromisoformat(displayed[2])
                if start <= end:
                    window.date_from, window.date_to = start.isoformat(), end.isoformat()
        if window.date_from and window.date_to and window.status != "invalid":
            window.status, window.reason = "resolved", "none"
        elif window.reason == "target_required":
            window.reason = "vague"
        if target == "screening":
            window.strength = "hard"
    return context


def time_arguments(entities: dict[str, Any], target: str, *, include_preference: bool = False) -> dict[str, Any]:
    """Add only active filters, preserving existing unfiltered tool contracts."""
    keys = RELEASE_FILTERS if target == "release" else SCREENING_FILTERS
    if include_preference:
        keys += ("release_date_preferred",)
    return {key: entities[key] for key in keys if entities.get(key) is not None and entities.get(key) is not False}


def temporal_summary(context: TemporalContext) -> dict[str, Any]:
    """Trace normalized dates and finite reasons without logging user expressions."""
    return {
        "reference_date": context.reference_date,
        "time_zone": context.time_zone,
        "windows": [window.model_dump(exclude={"expression"}) for window in context.windows],
    }


def recommendation_time_arguments(entities: dict[str, Any]) -> dict[str, Any]:
    """Keep release preferences and actual viewing dates independently actionable."""
    arguments = {
        **time_arguments(entities, "release", include_preference=True),
        **time_arguments(entities, "screening"),
    }
    if entities.get("screening_date"):
        arguments.update(screening_date_from=entities["screening_date"], screening_date_to=entities["screening_date"])
    return arguments


def sanitize_temporal_summary(value: Any) -> dict[str, Any]:
    """Allow only normalized dates and finite metadata in stored trace summaries."""
    if not isinstance(value, dict) or value.get("time_zone") != "Asia/Shanghai":
        return {}
    try:
        reference = date.fromisoformat(value["reference_date"]).isoformat()
    except (KeyError, ValueError, TypeError):
        return {}
    safe: dict[str, Any] = {"reference_date": reference, "time_zone": "Asia/Shanghai", "windows": []}
    windows = value.get("windows", [])
    if not isinstance(windows, list):
        return safe
    for window in windows[:12]:
        if not isinstance(window, dict):
            continue
        clean = {}
        for key, allowed in (
            ("target", {"release", "screening", "unspecified"}),
            ("status", {"resolved", "ambiguous", "invalid"}),
            ("strength", {"hard", "soft"}),
            ("reason", {"none", "vague", "year_required", "invalid_date", "conflict", "target_required"}),
        ):
            if isinstance(window.get(key), str) and window[key] in allowed:
                clean[key] = window[key]
        for key in ("date_from", "date_to"):
            with suppress(KeyError, ValueError, TypeError):
                clean[key] = date.fromisoformat(window[key]).isoformat()
        for key in ("hour_from", "hour_to"):
            if type(window.get(key)) is int and 0 <= window[key] <= 24:
                clean[key] = window[key]
        if type(window.get("assumed_target")) is bool:
            clean["assumed_target"] = window["assumed_target"]
        safe["windows"].append(clean)
    return safe
