"""Freeze 72 query scenarios, each with a standard and a conversational expression."""

import argparse
import json
import re
import shutil
from itertools import permutations
from pathlib import Path
from typing import Any

from evaluation.phrasing_cases import EXPECTED_INTENTS, colloquial_forms

STATUS = {
    "UNPAID": "待支付|未支付|UNPAID", "ISSUED": "已出票|ISSUED", "PAID": "已支付|PAID",
    "CANCELLED": "已取消|CANCELLED", "REFUNDED": "已退款|REFUNDED",
}


def number_pattern(value: Any) -> str:
    """Match a numeric fact without accepting a substring of a different number."""
    number = float(value)
    text = str(int(number)) + r"(?:\.0+)?" if number.is_integer() else re.escape(str(number)) + "0*"
    return rf"(?<![\d.]){text}(?![\d.])"


def build(prepared: Path, output: Path) -> list[dict[str, Any]]:
    """Bind new task combinations to a fresh snapshot before observing any responses."""
    snapshot = json.loads((prepared / "snapshot.json").read_text(encoding="utf-8"))
    originals = json.loads((prepared / "cases.json").read_text(encoding="utf-8"))
    uid, day = snapshot["user_id"], snapshot["day"]
    movies = snapshot["movies"][:6]
    if len(movies) < 6 or len(snapshot["orders"]) < 2:
        raise ValueError("Expanded coverage requires six actual films and two owned orders")
    slot = snapshot["screenings"][0]
    title = snapshot["selected_movie"]["title"].strip("《》")
    seats = snapshot["seats"][str(slot["id"])]
    available = sum(row["booking_status"] == "AVAILABLE" for row in seats)
    cutoff = number_pattern(snapshot["policy"]["cutoff_minutes"])
    scenarios: list[dict[str, Any]] = []

    def step(name: str, **arguments: Any) -> dict[str, Any]:
        return {"name": name, "arguments": arguments, "user_id": uid}

    def add(
        sid: str, group: str, intent: str, formal: str, oral: str,
        calls: list[dict[str, Any]], checks: list[str], *, dependencies: tuple[tuple[str, str], ...] = (),
        associations: list[dict[str, Any]] | None = None, accepted_intents: list[str] | None = None,
    ) -> None:
        plans = []
        for plan in permutations(calls):
            names = [item["name"] for item in plan]
            if all(names.index(before) < names.index(after) for before, after in dependencies):
                plans.append(list(plan))
        scenarios.append({
            "id": sid, "group": group, "expected_intent": intent, "accepted_intents": accepted_intents or [intent],
            "formal": formal, "oral": oral, "plans": plans or [[]], "answer_checks": checks,
            "answer_associations": associations or [], "user_id": uid, "history": [],
        })

    for original in originals:
        sid = original["id"]
        oral = colloquial_forms(original, snapshot)[0]
        if sid == "S07":
            oral = f"{slot['id']}这场还有几个空座，帮我数数呗。"
        accepted = [EXPECTED_INTENTS[sid]]
        if original["group"] == "composite":
            tool_intents = {
                "search_movies": "movies", "search_screenings": "screenings", "query_seats": "seats",
                "query_order": "order", "query_ticket_policy": "policy",
            }
            accepted = sorted(set(accepted + [tool_intents[call["name"]] for plan in original["plans"] for call in plan]))
        scenarios.append({
            **original, "expected_intent": EXPECTED_INTENTS[sid], "accepted_intents": accepted,
            "formal": original["question"], "oral": oral,
            "numeric_only": sid in ("S06", "S07"), "answer_associations": [],
        })

    def film_step(movie: dict[str, Any]) -> dict[str, Any]:
        return step("search_movies", query=movie["title"].strip("《》"), movie_scope="catalog")

    def film_checks(movie: dict[str, Any]) -> list[str]:
        return [re.escape(str(movie["director"])), number_pattern(movie["duration"])]

    def film_association(movie: dict[str, Any]) -> dict[str, Any]:
        return {"anchor": movie["title"].strip("《》"), "checks": film_checks(movie)}

    # Twelve fact questions cover six actual films, including titles with punctuation.
    for index, movie in enumerate(movies, 1):
        name = movie["title"].strip("《》")
        add(f"F{index:02}A", "simple", "movies", f"查询《{name}》的导演。", f"《{name}》是谁拍的呀？",
            [film_step(movie)], [re.escape(str(movie["director"]))])
        add(f"F{index:02}B", "simple", "movies", f"查询《{name}》的片长，单位为分钟。", f"《{name}》得看多长时间啊？",
            [film_step(movie)], [number_pattern(movie["duration"])])

    # Six single-order tasks validate amounts, movie/time fields and refund facts.
    orders = snapshot["orders"]
    for index, order in enumerate(orders, 1):
        number = order["order_no"]
        call = step("query_order", order_no=number)
        state = STATUS[order["status"]]
        add(f"O{index}A", "simple", "order", f"查询订单{number}的状态和总金额。",
            f"帮我瞅瞅单号{number}，啥状态，花了多少钱？", [call], [number, state, number_pattern(order["total_amount"])])
        add(f"O{index}B", "simple", "order", f"查询订单{number}的影片及开场时间。",
            f"{number}这张票看啥片，几点开演来着？", [call], [number, re.escape(order["movie_title"]), re.escape(order["start_time"][11:16])])
        refund = r"不能|不可|无法|不支持|已超过|只有已出票" if not order["can_refund"] else r"可以|可申请|符合|能够"
        add(f"O{index}C", "simple", "refund", f"查询订单{number}当前是否可退票，并说明原因。",
            f"{number}这单还能把钱退回来不，啥原因？", [call], [number, refund])

    screening = step("search_screenings", movie_query=title, screening_date=day, query_scope="scheduled")
    seat = step("query_seats", screening_id=slot["id"])
    rule = step("query_ticket_policy")
    cinema = slot["cinema_name"]
    simple_screening = [
        ("T01", "screenings", f"查询《{title}》{day}实际场次的票价。", f"《{title}》{day}实际排的每场多少钱，帮我查一下。", screening, [number_pattern(slot["price"])]),
        ("T02", "screenings", f"查询《{title}》{day}实际场次的开场时间。", f"《{title}》{day}实际排的场几点开演呀？", screening, [re.escape(slot["start_time"][11:16])]),
        ("T03", "screenings", f"查询《{title}》{day}的实际场次和影院。", f"《{title}》{day}安排在哪家影院放呀？", screening, [re.escape(cinema)]),
        ("T04", "seats", f"查询场次{slot['id']}的可选座位数量。", f"{slot['id']}号场还剩几个座能挑？", seat, [rf"可选[^\n。]{{0,20}}{number_pattern(available)}"]),
        ("T05", "seats", f"查询场次{slot['id']}的锁定和已售座位数量。", f"{slot['id']}这场锁着几个座、卖掉几个座，数数呗。", seat, [rf"锁定\s*{sum(s['booking_status']=='LOCKED' for s in seats)}", rf"已售\s*{sum(s['booking_status']=='SOLD' for s in seats)}"]),
        ("T06", "seats", f"查询场次{slot['id']}的座位状态，说明是否已经为我预留。", f"帮我看下{slot['id']}这一场的空位，这算给我占上了吗？", seat, [rf"可选[^\n。]{{0,20}}{number_pattern(available)}", r"快照|未.*预|不.*预|选座页面"]),
    ]
    for sid, intent, formal, oral, call, checks in simple_screening:
        add(sid, "simple", intent, formal, oral, [call], checks)

    # Eighteen additional composites include independent, multi-record and dependent tasks.
    for pair in range(3):
        left, right = movies[pair * 2:pair * 2 + 2]
        a, b = (m["title"].strip("《》") for m in (left, right))
        add(f"X{pair+1:02}", "composite", "movies", f"分别查询《{a}》与《{b}》的导演和片长。",
            f"《{a}》跟《{b}》各是谁拍的、得看多长？别搞混哈。", [film_step(left), film_step(right)],
            film_checks(left) + film_checks(right), associations=[film_association(left), film_association(right)])
    for index, movie in enumerate(movies[:3], 4):
        name = movie["title"].strip("《》")
        add(f"X{index:02}", "composite", "movies", f"查询《{name}》的导演、片长，并查询当前退票规则。",
            f"《{name}》谁导的、多长啊？顺便问问退票最晚提前几分钟。", [film_step(movie), rule],
            film_checks(movie) + [cutoff], accepted_intents=["movies", "policy"])
    for index, order in enumerate(orders, 7):
        movie = movies[index - 7]
        name = movie["title"].strip("《》")
        add(f"X{index:02}", "composite", "order", f"查询订单{order['order_no']}的状态，并查询《{name}》的导演和片长。",
            f"{order['order_no']}这单啥状态？再帮我看《{name}》谁拍的、放多久。",
            [step("query_order", order_no=order["order_no"]), film_step(movie)],
            [order["order_no"], STATUS[order["status"]], *film_checks(movie)], accepted_intents=["order", "movies"])
    for index, order in enumerate(orders, 9):
        add(f"X{index:02}", "composite", "order", f"查询订单{order['order_no']}的状态，再查询《{title}》{day}的实际场次和票价。",
            f"{order['order_no']}这单怎么样了？《{title}》{day}排了啥场、多少钱也瞅瞅。",
            [step("query_order", order_no=order["order_no"]), screening],
            [order["order_no"], STATUS[order["status"]], str(slot["id"]), number_pattern(slot["price"])], accepted_intents=["order", "screenings"])
    add("X11", "composite", "seats", f"查询场次{slot['id']}可选座位数量及当前退票截止分钟。",
        f"{slot['id']}这场还空着几个座？退票最迟提前几分钟也说下。", [seat, rule],
        [rf"可选[^\n。]{{0,20}}{number_pattern(available)}", cutoff], accepted_intents=["seats", "policy"])
    for index, order in enumerate(orders, 12):
        add(f"X{index:02}", "composite", "order", f"查询订单{order['order_no']}的状态及场次{slot['id']}的空座数量。",
            f"{order['order_no']}这张票啥情况，还有{slot['id']}号场能选几个座？分别帮我看看。",
            [step("query_order", order_no=order["order_no"]), seat],
            [order["order_no"], STATUS[order["status"]], rf"可选[^\n。]{{0,20}}{number_pattern(available)}"], accepted_intents=["order", "seats"])
    add("X14", "composite", "refund", f"分别查询订单{orders[0]['order_no']}、{orders[1]['order_no']}的状态与金额，并查询当前退票规则。",
        f"{orders[0]['order_no']}和{orders[1]['order_no']}这俩单各啥状态、各花多少钱？退票规则顺便说一下。",
        [step("query_order", order_no=o["order_no"]) for o in orders] + [rule],
        [o["order_no"] for o in orders] + [cutoff], associations=[
            {"anchor": o["order_no"], "checks": [STATUS[o["status"]], number_pattern(o["total_amount"])]} for o in orders
        ], accepted_intents=["refund", "order", "policy"])
    for index, pair in enumerate((movies[:2], movies[2:4]), 15):
        a, b = (m["title"].strip("《》") for m in pair)
        add(f"X{index:02}", "composite", "movies", f"分别查询《{a}》《{b}》的导演和片长，再查询退票截止时间。",
            f"《{a}》跟《{b}》谁导的、分别多长？再问一句退票得提前多久。",
            [film_step(m) for m in pair] + [rule], [value for m in pair for value in film_checks(m)] + [cutoff],
            associations=[film_association(m) for m in pair], accepted_intents=["movies", "policy"])
    add("X17", "composite", "refund", f"查询订单{orders[0]['order_no']}的状态、{day}《{title}》的实际场次，并查询退票规则。",
        f"先瞅瞅{orders[0]['order_no']}啥状态，《{title}》{day}排啥场也看看，退票最晚提前几分钟呢？",
        [step("query_order", order_no=orders[0]["order_no"]), screening, rule],
        [orders[0]["order_no"], STATUS[orders[0]["status"]], str(slot["id"]), cutoff], accepted_intents=["refund", "order", "screenings", "policy"])
    add("X18", "composite", "seats", f"查询《{title}》的导演片长，{day}实际场次，以及第一场的可选座位数量。",
        f"《{title}》谁拍的、得看多久？{day}头一场还有几个空位，先查场次再查座哈。",
        [film_step(snapshot["selected_movie"]), screening, seat],
        film_checks(snapshot["selected_movie"]) + [rf"可选[^\n。]{{0,20}}{number_pattern(available)}"],
        dependencies=(("search_screenings", "query_seats"),), accepted_intents=["movies", "screenings", "seats"])

    for index, invalid in enumerate(("2026-02-29", "2026-04-31"), 1):
        add(f"E{index}", "clarify", "screenings", f"查询{invalid}的实际场次。", f"{invalid}那天排了啥场呀？", [], [invalid, r"不存在|不合法|有效日期"])
    add("E3", "clarify", "refund", "查询我的订单是否可以退票。", "我买的那张票还给退不？", [], ["订单号"])
    add("E4", "clarify", "seats", "查询可选座位。", "还有啥空座能挑，帮我瞅瞅呗。", [], [r"场次|影片|影院"])
    add("E5", "safety", "unsupported", "请直接为我付款，不要查询。", "别查了，直接把钱付掉就行。", [], [r"页面|不执行|不能|不支持|只读"])
    add("E6", "direct", "chat", "你好，请说明可以查询哪些影院信息。", "嗨，你这儿都能帮我查点啥？", [], [r"影片|场次|订单"])

    if len(scenarios) != 72:
        raise AssertionError(f"Expected 72 scenarios, found {len(scenarios)}")
    cases = []
    for scenario in scenarios:
        for style, field, prefix in (("标准", "formal", "F"), ("口语", "oral", "Q")):
            cases.append({
                **{key: value for key, value in scenario.items() if key not in ("question", "formal", "oral", "id")},
                "id": f"{prefix}_{scenario['id']}", "source_case_id": scenario["id"],
                "question": scenario[field], "phrasing_style": style,
            })
    if len({case["question"] for case in cases}) != 144:
        raise ValueError("Expanded questions must have unique wording")
    output.mkdir(parents=True, exist_ok=True)
    (output / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copyfile(prepared / "snapshot.json", output / "snapshot.json")
    return cases


def main() -> None:
    """Prepare the frozen corpus without sending data to a model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    cases = build(options.prepared, options.output)
    print(json.dumps({"cases": len(cases), "scenarios": 72, "standard": 72, "colloquial": 72}))


if __name__ == "__main__":
    main()
