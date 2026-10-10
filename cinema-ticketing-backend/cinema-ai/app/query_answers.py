"""Render movie and screening facts consistently, without model reinterpretation."""

# 导入当前步骤使用的模块或类型。
# isort: off
from datetime import date, datetime
# 导入当前步骤使用的模块或类型。
from typing import Any
# isort: on


# 声明当前处理单元及其入口。
def valid_movie_result(data: Any, entities: dict[str, Any]) -> bool:
    """Reject version drift and missing schedule evidence instead of relabeling catalogue rows."""
    # 为 `scope` 保存当前步骤所需的值。
    scope = entities.get("movie_scope", "catalog")
    # 检查 `if isinstance(data, list)`，据此选择当前处理分支。
    if isinstance(data, list):
        # 将当前计算结果返回给调用方。
        return scope == "catalog" and all(isinstance(row, dict) and "title" in row for row in data)
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
                datetime.fromisoformat(slot["start_time"])
            # 进入对应的循环、异常处理或资源管理分支。
            except ValueError:
                # 将当前计算结果返回给调用方。
                return False
            # 检查 `if (requested_day and day != requested_day) or (not requested_day and day < data["from_date"])`，据此选择当前处理分支。
            if (requested_day and day != requested_day) or (not requested_day and day < data["from_date"]):
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
        if entities.get("screening_date") and start.date().isoformat() != entities["screening_date"]:
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
        if any(word in question for word in ("导演", "主演", "演员", "简介", "资料", "介绍", "上映日期")):
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
