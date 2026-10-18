"""Render movie and screening facts consistently, without model reinterpretation."""

# 导入当前步骤使用的模块或类型。
# isort: off
from datetime import date, datetime, timedelta, timezone
from app.query_semantics import GENERAL_POLICY_WORDS, movie_fields
# 导入当前步骤使用的模块或类型。
from typing import Any
from app.time_normalization import TIME_FILTERS
from app.ticket_price import valid_ticket_prices


def valid_release_result(rows: list[dict[str, Any]], entities: dict[str, Any]) -> bool:
    """Check real release dates, including labelled soft-constraint alternatives."""
    start, end = entities.get("release_date_from"), entities.get("release_date_to")
    if not start:
        return True
    for row in rows:
        raw_date = row.get("release_date")
        if raw_date in (None, ""):
            matches = False
        else:
            try:
                released = date.fromisoformat(str(raw_date))
                matches = start <= released.isoformat() <= end
            except (TypeError, ValueError):
                return False
        if entities.get("release_date_preferred"):
            if type(row.get("matches_release_window")) is not bool or row["matches_release_window"] != matches:
                return False
        elif not matches:
            return False
    return True


def _valid_screening_time(start: datetime, entities: dict[str, Any]) -> bool:
    if start.tzinfo is not None:
        start = start.astimezone(timezone(timedelta(hours=8)))
    day = start.date().isoformat()
    if entities.get("screening_date") and day != entities["screening_date"]:
        return False
    if entities.get("screening_date_from") and not entities["screening_date_from"] <= day <= entities["screening_date_to"]:
        return False
    hour_from, hour_to = entities.get("screening_hour_from"), entities.get("screening_hour_to")
    return hour_from is None or hour_from <= start.hour < hour_to


def recommendation_answer(data: list[dict[str, Any]], entities: dict[str, Any]) -> str:
    """Show the chosen release interval and explicitly label relaxed preferences."""
    if not valid_ticket_prices(data, entities):
        return "当前返回的场次价格信息无法确认满足预算，请稍后重试。"
    start, end = entities.get("release_date_from"), entities.get("release_date_to")
    lines = []
    maximum = entities.get("max_ticket_price")
    if maximum is not None:
        comparison = "不超过" if entities.get("price_upper_inclusive", True) else "低于"
        lines.append(f"按可购票场次票面价格筛选：每张{comparison}{maximum}元，优惠及最终实付金额以支付页面为准。")
        if entities.get("preference"):
            lines.append(f"题材或偏好：{entities['preference']}。")
        if not entities.get("screening_date_from") and not entities.get("screening_date"):
            lines.append("观影范围：当前可购票的今天及之后场次（北京时间）。")
    if start:
        lines.append(f"按上映日期筛选：{start} 至 {end}（北京时间，含起止日）。")
        if entities.get("release_date_preferred"):
            lines[-1] = f"优先推荐上映日期在 {start} 至 {end} 的影片（北京时间，含起止日）。"
    windows = entities.get("temporal", {}).get("windows", [])
    if any(window.get("assumed_target") for window in windows if window.get("target") == "release"):
        lines.append("我先按上述上映日期范围为你推荐；如果你想按观影日期查询，可以直接告诉我。")
    if any(window.get("status") == "ambiguous" for window in windows):
        lines.append("你未限定具体时间范围，先按上映日期由近到远推荐。")
    viewing = bool(entities.get("screening_date_from") or entities.get("screening_date") or entities.get("screening_hour_from") is not None)
    if viewing:
        viewing_start = entities.get("screening_date_from") or entities.get("screening_date")
        viewing_end = entities.get("screening_date_to") or viewing_start
        period = f"观影日期：{viewing_start} 至 {viewing_end}（北京时间，含起止日）" if viewing_start else "观影范围：今天及之后（北京时间）"
        if entities.get("screening_hour_from") is not None:
            period += f"，每天 {entities['screening_hour_from']:02d}:00 至 {entities['screening_hour_to']:02d}:00（不含结束时刻）"
        lines.append(period + "。")
    if not data:
        if maximum is not None:
            lines.append("没有查到同时满足上述预算及其他条件的可购票场次。可以提高预算或调整日期，当前未放宽筛选条件。")
        elif viewing:
            detail = "同时满足上映日期条件且有可购票场次的影片" if start else "有可购票场次的影片"
            lines.append(f"没有查到符合上述条件的{detail}。可以调整题材或观影日期；未查到可购票场次不代表没有排期。")
        elif start:
            lines.append("没有查到符合上述上映日期和题材条件的影片。可以调整题材或扩大上映日期范围。")
        else:
            lines.append("没有查到符合题材或偏好的影片，可以换一个题材或补充其他偏好。")
        return "\n".join(lines)
    if viewing or maximum is not None:
        lines.append("以下影片具有符合条件的当前可订购场次：")
    for row in data:
        alternative = ""
        if entities.get("release_date_preferred") and row.get("matches_release_window") is False:
            alternative = "｜超出优先日期范围，作为补充推荐" if row.get("release_date") else "｜上映日期未收录，无法确认是否符合时间偏好"
        lines.append(f"• {row['title']}｜{row.get('genre', '')}｜上映日期：{row.get('release_date') or '暂未收录'}{alternative}")
        for slot in row.get("screenings", [])[:3]:
            lines.append(f"  场次 {slot['id']}｜{slot['start_time']}｜{slot['cinema_name']} {slot['hall_name']}｜¥{slot['price']}")
    return "\n".join(lines)
# isort: on


# 声明当前处理单元及其入口。
def valid_movie_result(data: Any, entities: dict[str, Any]) -> bool:
    """Reject version drift and missing schedule evidence instead of relabeling catalogue rows."""
    # 为 `scope` 保存当前步骤所需的值。
    scope = entities.get("movie_scope", "catalog")
    # 检查 `if isinstance(data, list)`，据此选择当前处理分支。
    if isinstance(data, list):
        # 将当前计算结果返回给调用方。
        return scope == "catalog" and not any(entities.get(key) is not None for key in TIME_FILTERS) and all(isinstance(row, dict) and "title" in row for row in data)
    # 为 `required` 保存当前步骤所需的值。
    required = {
        # 补充当前表达式的 `"movie_scope"` 参数或元素。
        "movie_scope",
        # 补充当前表达式的 `"screening_date"` 参数或元素。
        "screening_date",
        # 补充当前表达式的 `"from_date"` 参数或元素。
        "from_date",
        # 补充当前表达式的 `"time_zone"` 参数或元素。
        "time_zone",
        # 补充当前表达式的 `"items"` 参数或元素。
        "items",
        # 补充当前表达式的 `"showing_only"` 参数或元素。
        "showing_only",
        # 补充当前表达式的 `"total"` 参数或元素。
        "total",
        # 补充当前表达式的 `"page"` 参数或元素。
        "page",
        # 补充当前表达式的 `"page_size"` 参数或元素。
        "page_size",
        # 补充当前表达式的 `"has_more"` 参数或元素。
        "has_more",
    }
    # 检查 `if not isinstance(data, dict) or not required.issubset(data) or data["movie_scope"] != scope`，据此选择当前处理分支。
    if not isinstance(data, dict) or not required.issubset(data) or data["movie_scope"] != scope:
        # 将当前计算结果返回给调用方。
        return False
    # 检查 `if data["time_zone"] != "Asia/Shanghai" or data["showing_only"] != entities.get("showing_only", False)`，据此选择当前处理分支。
    if data["time_zone"] != "Asia/Shanghai" or data["showing_only"] != entities.get("showing_only", False):
        # 将当前计算结果返回给调用方。
        return False
    # 检查 `if data["page"] != entities.get("page", 1) or type(data["total"]) is not int or data["total"] < 0`，据此选择当前处理分支。
    if data["page"] != entities.get("page", 1) or type(data["total"]) is not int or data["total"] < 0:
        # 将当前计算结果返回给调用方。
        return False
    # 为 `rows` 保存当前步骤所需的值。
    rows = data["items"]
    for key in TIME_FILTERS:
        if entities.get(key) is not None and data.get(key) != entities[key]:
            return False
    # 检查 `if not isinstance(rows, list) or len(rows) > data["total"]`，据此选择当前处理分支。
    if not isinstance(rows, list) or len(rows) > data["total"]:
        # 将当前计算结果返回给调用方。
        return False
    # 为 `requested_day` 保存当前步骤所需的值。
    requested_day = entities.get("screening_date")
    # 检查 `if data["screening_date"] != (requested_day or "")`，据此选择当前处理分支。
    if data["screening_date"] != (requested_day or ""):
        # 将当前计算结果返回给调用方。
        return False
    # 进入对应的循环、异常处理或资源管理分支。
    try:
        date.fromisoformat(data["from_date"])
    # 进入对应的循环、异常处理或资源管理分支。
    except (ValueError, TypeError):
        # 将当前计算结果返回给调用方。
        return False
    # 为 `seen` 保存当前步骤所需的值。
    seen = set()
    if not all(isinstance(row, dict) for row in rows) or not valid_release_result(rows, entities):
        return False
    # 进入对应的循环、异常处理或资源管理分支。
    for row in rows:
        # 检查 `if not isinstance(row, dict) or "title" not in row or type(row.get("id")) is not int or row["id"] in seen`，据此选择当前处理分支。
        if not isinstance(row, dict) or "title" not in row or type(row.get("id")) is not int or row["id"] in seen:
            # 将当前计算结果返回给调用方。
            return False
        seen.add(row["id"])
        # 检查 `if scope != "scheduled"`，据此选择当前处理分支。
        if scope != "scheduled":
            # 结束本次循环并处理下一项。
            continue
        # 检查 `if type(row.get("screening_count")) is not int or row["screening_count"] <= 0`，据此选择当前处理分支。
        if type(row.get("screening_count")) is not int or row["screening_count"] <= 0:
            # 将当前计算结果返回给调用方。
            return False
        # 为 `slots` 保存当前步骤所需的值。
        slots = row.get("screenings")
        # 检查 `if not isinstance(slots, list) or (not slots and not row.get("screenings_truncated"))`，据此选择当前处理分支。
        if not isinstance(slots, list) or (not slots and not row.get("screenings_truncated")):
            # 将当前计算结果返回给调用方。
            return False
        # 进入对应的循环、异常处理或资源管理分支。
        for slot in slots:
            # 检查 `if not isinstance(slot, dict) or not {"id", "start_time", "cinema_name", "hall_name", "price"}.issubset(`，据此选择当前处理分支。
            if not isinstance(slot, dict) or not {"id", "start_time", "cinema_name", "hall_name", "price"}.issubset(
                # 继续构造当前业务表达式或数据结构。
                slot
            # 继续构造当前业务表达式或数据结构。
            ):
                # 将当前计算结果返回给调用方。
                return False
            # 检查 `if not isinstance(slot["start_time"], str)`，据此选择当前处理分支。
            if not isinstance(slot["start_time"], str):
                # 将当前计算结果返回给调用方。
                return False
            # 为 `day` 保存当前步骤所需的值。
            day = slot["start_time"][:10]
            # 进入对应的循环、异常处理或资源管理分支。
            try:
                start = datetime.fromisoformat(slot["start_time"])
            # 进入对应的循环、异常处理或资源管理分支。
            except ValueError:
                # 将当前计算结果返回给调用方。
                return False
            # 检查 `if (requested_day and day != requested_day) or (not requested_day and day < data["from_date"])`，据此选择当前处理分支。
            if not _valid_screening_time(start, entities) or (not requested_day and not entities.get("screening_date_from") and day < data["from_date"]):
                # 将当前计算结果返回给调用方。
                return False
    # 将当前计算结果返回给调用方。
    return True


# 声明当前处理单元及其入口。
def valid_screening_result(data: Any, entities: dict[str, Any]) -> bool:
    """Check real screening rows and keep an explicitly requested date intact."""
    # 检查 `if not isinstance(data, list)`，据此选择当前处理分支。
    if not isinstance(data, list):
        # 将当前计算结果返回给调用方。
        return False
    # 进入对应的循环、异常处理或资源管理分支。
    for row in data:
        # 检查 `if not isinstance(row, dict) or not {"id", "title", "start_time", "cinema_name", "hall_name", "price"}.issubset(`，据此选择当前处理分支。
        if not isinstance(row, dict) or not {"id", "title", "start_time", "cinema_name", "hall_name", "price"}.issubset(
            # 继续构造当前业务表达式或数据结构。
            row
        # 继续构造当前业务表达式或数据结构。
        ):
            # 将当前计算结果返回给调用方。
            return False
        # 进入对应的循环、异常处理或资源管理分支。
        try:
            # 为 `start` 保存当前步骤所需的值。
            start = datetime.fromisoformat(row["start_time"])
        # 进入对应的循环、异常处理或资源管理分支。
        except (ValueError, TypeError):
            # 将当前计算结果返回给调用方。
            return False
        # 检查 `if entities.get("screening_date") and start.date().isoformat() != entities["screening_date"]`，据此选择当前处理分支。
        if not _valid_screening_time(start, entities):
            # 将当前计算结果返回给调用方。
            return False
    # 将当前计算结果返回给调用方。
    return True


# 声明当前处理单元及其入口。
def movie_details(movie: dict[str, Any]) -> list[str]:
    """Retain available catalogue facts without generating missing credits or descriptions."""
    # 将当前计算结果返回给调用方。
    return [
        # 继续构造当前业务表达式或数据结构。
        f"  {label}：{movie[field]}"
        # 进入对应的循环、异常处理或资源管理分支。
        for field, label in (
            # 补充当前表达式的 `("director", "导演")` 参数或元素。
            ("director", "导演"),
            # 补充当前表达式的 `("actors", "主演")` 参数或元素。
            ("actors", "主演"),
            # 补充当前表达式的 `("description", "简介")` 参数或元素。
            ("description", "简介"),
            # 补充当前表达式的 `("release_date", "上映日期")` 参数或元素。
            ("release_date", "上映日期"),
        )
        # 检查 `if movie.get(field)`，据此选择当前处理分支。
        if movie.get(field)
    ]


# 声明当前处理单元及其入口。
def movie_answer(data: Any, question: str = "") -> str:
    """Keep showing state separate from the proof and scope of actual cinema schedules."""
    # 检查 `if isinstance(data, list)`，据此选择当前处理分支。
    if isinstance(data, list):
        # 检查 `if not data`，据此选择当前处理分支。
        if not data:
            # 将当前计算结果返回给调用方。
            return "没有找到符合条件的影片资料。"
        # 为 `lines` 保存当前步骤所需的值。
        lines = ["影片资料："]
        # 进入对应的循环、异常处理或资源管理分支。
        for movie in data:
            lines.append(f"• {movie['title']}｜{movie.get('genre', '')}｜{movie.get('duration', '未知')} 分钟")
            # 继续构造当前业务表达式或数据结构。
            lines.extend(movie_details(movie))
        # 检查 `if len(data) == 20`，据此选择当前处理分支。
        if len(data) == 20:
            lines.append("当前返回最多 20 部影片，可补充片名或类型缩小范围。")
        # 将当前计算结果返回给调用方。
        return "\n".join(lines)
    # 为 `scope` 保存当前步骤所需的值。
    scope = data["movie_scope"]
    # 为 `day` 保存当前步骤所需的值。
    day = data["screening_date"] or data["from_date"]
    # 检查 `if scope == "scheduled"`，据此选择当前处理分支。
    if scope == "scheduled":
        # 为 `period` 保存当前步骤所需的值。
        period = f"{day}（北京时间）" if data["screening_date"] else f"自 {day} 起（北京时间，今天及之后）"
        # 为 `kind` 保存当前步骤所需的值。
        kind = "上映且有有效排期的电影" if data["showing_only"] else "有有效排期的电影"
    # 检查 `elif scope == "showing"`，据此选择当前处理分支。
    elif scope == "showing":
        period, kind = f"截至 {day}（北京时间）", "上映中的电影"
    # 进入对应的循环、异常处理或资源管理分支。
    else:
        period, kind = "", "影片资料"
    if data.get("screening_date_from"):
        period = f"{data['screening_date_from']} 至 {data['screening_date_to']}（北京时间，含起止日）"
    if data.get("release_date_from"):
        period += f"上映日期 {data['release_date_from']} 至 {data['release_date_to']}："
    if data.get("screening_hour_from") is not None:
        period += f"，每天 {data['screening_hour_from']:02d}:00 至 {data['screening_hour_to']:02d}:00（不含结束时刻）"
    rows, total = data["items"], data["total"]
    # 检查 `if not rows`，据此选择当前处理分支。
    if not rows:
        # 将当前计算结果返回给调用方。
        return (
            # 继续构造当前业务表达式或数据结构。
            f"{period}没有符合条件的{kind}。"
            # 检查 `if not total`，据此选择当前处理分支。
            if not total
            else f"第 {data['page']} 页为空，共有 {total} 部符合条件的电影。"
        )
    # 为 `lines` 保存当前步骤所需的值。
    lines = [f"{period}{kind}共 {total} 部；第 {data['page']} 页展示 {len(rows)} 部："]
    # 进入对应的循环、异常处理或资源管理分支。
    for movie in rows:
        # 继续构造当前业务表达式或数据结构。
        lines.append(
            f"• {movie['title']}"
            # 继续构造当前业务表达式或数据结构。
            + (
                f"｜{movie['screening_count']} 个场次"
                # 检查 `if scope == "scheduled"`，据此选择当前处理分支。
                if scope == "scheduled"
                else f"｜{movie.get('genre', '')}｜{movie.get('duration', '未知')} 分钟"
            )
        )
        # 检查 `if any(word in question for word in ("导演", "主演", "演员", "简介", "资料", "介绍", "上映日期"))`，据此选择当前处理分支。
        if data.get("release_date_from") or movie_fields(question) or any(word in question for word in ("资料", "介绍")):
            # 继续构造当前业务表达式或数据结构。
            lines.extend(movie_details(movie))
        # 检查 `if scope == "scheduled" and any(word in question for word in ("片长", "时长")) and movie.get("duration")`，据此选择当前处理分支。
        if scope == "scheduled" and any(word in question for word in ("片长", "时长")) and movie.get("duration"):
            lines.append(f"  片长：{movie['duration']} 分钟")
        # 进入对应的循环、异常处理或资源管理分支。
        for slot in movie.get("screenings", []):
            # 继续构造当前业务表达式或数据结构。
            lines.append(
                f"  场次 {slot['id']}｜{slot['start_time']}｜{slot['cinema_name']} {slot['hall_name']}｜¥{slot['price']}"
            )
        # 检查 `if movie.get("screenings_truncated")`，据此选择当前处理分支。
        if movie.get("screenings_truncated"):
            lines.append("  场次摘要未全部展示，可按片名进一步查询场次。")
    # 检查 `if data["has_more"]`，据此选择当前处理分支。
    if data["has_more"]:
        lines.append("还有其他影片，可继续查询下一页。")
    # 将当前计算结果返回给调用方。
    return "\n".join(lines)


# 声明当前处理单元及其入口。
def policy_answer(data: dict[str, Any]) -> str:
    """Render live refund authority and non-refund knowledge without mixing their scope."""
    policy = data.get("policy", {})
    sections = [f"当前退票规则（版本 {policy.get('version', '未知')}）：\n{policy.get('policy', '')}"]
    cutoff = policy.get("cutoff_minutes")
    if type(cutoff) is int and cutoff >= 0:
        sections.append(f"实时退票截止参数：开场前 {cutoff} 分钟；具体订单资格以订单查询为准。")
    # Refund passages can be stale; only the live policy is authoritative for refunds.
    contexts = [
        text for text in data.get("answer_context", [])
        if isinstance(text, str) and text.strip()
        and not any(word in text for word in ("退票", "退款", "退钱", "退费", "退订"))
        and not any(word in text for word in GENERAL_POLICY_WORDS)
    ]
    if contexts:
        sections.append("检索到的票务说明：\n" + "\n".join(contexts))
    return "\n\n".join(sections)


def screening_answer(data: list[dict[str, Any]], entities: dict[str, Any]) -> str:
    """An empty bookable list must never be described as an empty schedule."""
    # 为 `day` 保存当前步骤所需的值。
    day = entities.get("screening_date")
    # 为 `scope` 保存当前步骤所需的值。
    scope = entities.get("screening_scope", "bookable")
    # 为 `period` 保存当前步骤所需的值。
    period = f"{day}（北京时间）" if day else "（北京时间）"
    # 为 `kind` 保存当前步骤所需的值。
    kind = "当前可订购场次" if scope == "bookable" else "有效排期场次"
    # 检查 `if scope == "scheduled" and not day`，据此选择当前处理分支。
    if scope == "scheduled" and not day:
        # 为 `period` 保存当前步骤所需的值。
        period = "今天及之后（北京时间）"
    if entities.get("screening_date_from"):
        period = f"{entities['screening_date_from']} 至 {entities['screening_date_to']}（北京时间，含起止日）"
    if entities.get("screening_hour_from") is not None:
        period += f"，每天 {entities['screening_hour_from']:02d}:00 至 {entities['screening_hour_to']:02d}:00（不含结束时刻）"
    if entities.get("candidate_titles") and entities.get("movie_query"):
        period = f"《{entities['movie_query']}》\n" + period
    # 检查 `if not data`，据此选择当前处理分支。
    if not data:
        # 将当前计算结果返回给调用方。
        return f"{period}没有符合条件的{kind}。"
    # 为 `rows` 保存当前步骤所需的值。
    rows = data[:12]
    # 为 `lines` 保存当前步骤所需的值。
    lines = [f"{period}{kind}："]
    # 继续构造当前业务表达式或数据结构。
    lines.extend(
        f"• 场次 {row['id']}｜{row['title']}｜{row['start_time']}｜{row['cinema_name']} "
        f"{row['hall_name']}｜¥{row['price']}"
        # 进入对应的循环、异常处理或资源管理分支。
        for row in rows
    )
    # 检查 `if len(data) > len(rows)`，据此选择当前处理分支。
    if len(data) > len(rows):
        lines.append("场次较多，当前展示前 12 个，可补充影片或影院缩小范围。")
    # 检查 `if len(data) == 50`，据此选择当前处理分支。
    if len(data) == 50:
        lines.append("本次查询达到 50 个场次上限，结果可能未全部返回。")
    # 将当前计算结果返回给调用方。
    return "\n".join(lines)
