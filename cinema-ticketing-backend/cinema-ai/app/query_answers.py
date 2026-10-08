"""Render movie and screening facts consistently, without model reinterpretation."""

from datetime import date, datetime
from typing import Any


def valid_movie_result(data: Any, entities: dict[str, Any]) -> bool:
    """Reject version drift and missing schedule evidence instead of relabeling catalogue rows."""
    scope = entities.get("movie_scope", "catalog")
    if isinstance(data, list):
        return scope == "catalog" and all(isinstance(row, dict) and "title" in row for row in data)
    required = {
        "movie_scope",
        "screening_date",
        "from_date",
        "time_zone",
        "items",
        "showing_only",
        "total",
        "page",
        "page_size",
        "has_more",
    }
    if not isinstance(data, dict) or not required.issubset(data) or data["movie_scope"] != scope:
        return False
    if data["time_zone"] != "Asia/Shanghai" or data["showing_only"] != entities.get("showing_only", False):
        return False
    if data["page"] != entities.get("page", 1) or type(data["total"]) is not int or data["total"] < 0:
        return False
    rows = data["items"]
    if not isinstance(rows, list) or len(rows) > data["total"]:
        return False
    requested_day = entities.get("screening_date")
    if data["screening_date"] != (requested_day or ""):
        return False
    try:
        date.fromisoformat(data["from_date"])
    except (ValueError, TypeError):
        return False
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or "title" not in row or type(row.get("id")) is not int or row["id"] in seen:
            return False
        seen.add(row["id"])
        if scope != "scheduled":
            continue
        if type(row.get("screening_count")) is not int or row["screening_count"] <= 0:
            return False
        slots = row.get("screenings")
        if not isinstance(slots, list) or (not slots and not row.get("screenings_truncated")):
            return False
        for slot in slots:
            if not isinstance(slot, dict) or not {"id", "start_time", "cinema_name", "hall_name", "price"}.issubset(
                slot
            ):
                return False
            if not isinstance(slot["start_time"], str):
                return False
            day = slot["start_time"][:10]
            try:
                datetime.fromisoformat(slot["start_time"])
            except ValueError:
                return False
            if (requested_day and day != requested_day) or (not requested_day and day < data["from_date"]):
                return False
    return True


def valid_screening_result(data: Any, entities: dict[str, Any]) -> bool:
    """Check real screening rows and keep an explicitly requested date intact."""
    if not isinstance(data, list):
        return False
    for row in data:
        if not isinstance(row, dict) or not {"id", "title", "start_time", "cinema_name", "hall_name", "price"}.issubset(
            row
        ):
            return False
        try:
            start = datetime.fromisoformat(row["start_time"])
        except (ValueError, TypeError):
            return False
        if entities.get("screening_date") and start.date().isoformat() != entities["screening_date"]:
            return False
    return True


def movie_details(movie: dict[str, Any]) -> list[str]:
    """Retain available catalogue facts without generating missing credits or descriptions."""
    return [
        f"  {label}：{movie[field]}"
        for field, label in (
            ("director", "导演"),
            ("actors", "主演"),
            ("description", "简介"),
            ("release_date", "上映日期"),
        )
        if movie.get(field)
    ]


def movie_answer(data: Any, question: str = "") -> str:
    """Keep showing state separate from the proof and scope of actual cinema schedules."""
    if isinstance(data, list):
        if not data:
            return "没有找到符合条件的影片资料。"
        lines = ["影片资料："]
        for movie in data:
            lines.append(f"• {movie['title']}｜{movie.get('genre', '')}｜{movie.get('duration', '未知')} 分钟")
            lines.extend(movie_details(movie))
        if len(data) == 20:
            lines.append("当前返回最多 20 部影片，可补充片名或类型缩小范围。")
        return "\n".join(lines)
    scope = data["movie_scope"]
    day = data["screening_date"] or data["from_date"]
    if scope == "scheduled":
        period = f"{day}（北京时间）" if data["screening_date"] else f"自 {day} 起（北京时间，今天及之后）"
        kind = "上映且有有效排期的电影" if data["showing_only"] else "有有效排期的电影"
    elif scope == "showing":
        period, kind = f"截至 {day}（北京时间）", "上映中的电影"
    else:
        period, kind = "", "影片资料"
    rows, total = data["items"], data["total"]
    if not rows:
        return (
            f"{period}没有符合条件的{kind}。"
            if not total
            else f"第 {data['page']} 页为空，共有 {total} 部符合条件的电影。"
        )
    lines = [f"{period}{kind}共 {total} 部；第 {data['page']} 页展示 {len(rows)} 部："]
    for movie in rows:
        lines.append(
            f"• {movie['title']}"
            + (
                f"｜{movie['screening_count']} 个场次"
                if scope == "scheduled"
                else f"｜{movie.get('genre', '')}｜{movie.get('duration', '未知')} 分钟"
            )
        )
        if any(word in question for word in ("导演", "主演", "演员", "简介", "资料", "介绍", "上映日期")):
            lines.extend(movie_details(movie))
        if scope == "scheduled" and any(word in question for word in ("片长", "时长")) and movie.get("duration"):
            lines.append(f"  片长：{movie['duration']} 分钟")
        for slot in movie.get("screenings", []):
            lines.append(
                f"  场次 {slot['id']}｜{slot['start_time']}｜{slot['cinema_name']} {slot['hall_name']}｜¥{slot['price']}"
            )
        if movie.get("screenings_truncated"):
            lines.append("  场次摘要未全部展示，可按片名进一步查询场次。")
    if data["has_more"]:
        lines.append("还有其他影片，可继续查询下一页。")
    return "\n".join(lines)


def screening_answer(data: list[dict[str, Any]], entities: dict[str, Any]) -> str:
    """An empty bookable list must never be described as an empty schedule."""
    day = entities.get("screening_date")
    scope = entities.get("screening_scope", "bookable")
    period = f"{day}（北京时间）" if day else "（北京时间）"
    kind = "当前可订购场次" if scope == "bookable" else "有效排期场次"
    if scope == "scheduled" and not day:
        period = "今天及之后（北京时间）"
    if not data:
        return f"{period}没有符合条件的{kind}。"
    rows = data[:12]
    lines = [f"{period}{kind}："]
    lines.extend(
        f"• 场次 {row['id']}｜{row['title']}｜{row['start_time']}｜{row['cinema_name']} "
        f"{row['hall_name']}｜¥{row['price']}"
        for row in rows
    )
    if len(data) > len(rows):
        lines.append("场次较多，当前展示前 12 个，可补充影片或影院缩小范围。")
    if len(data) == 50:
        lines.append("本次查询达到 50 个场次上限，结果可能未全部返回。")
    return "\n".join(lines)
