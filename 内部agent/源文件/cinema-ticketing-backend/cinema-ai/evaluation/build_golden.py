"""Freeze held-out cinema acceptance cases and preserve every clarification event."""

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def followups(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add 24 explicitly labeled recovery cases; do not label them via model output."""
    source = {case["id"]: case for case in cases}
    result = []
    order = source["F_O1C"]["plans"][0][0]["arguments"]["order_no"]
    seat = source["F_S06"]["plans"][0][0]["arguments"]["screening_id"]
    replies = {
        "refund": (
            order,
            f"那就是{order}",
            f"订单号是{order}",
            f"查下{order}能退不",
            f"提供订单号：{order}",
            f"刚才那张是{order}",
            f"我的订单号为{order}，请查询退票资格",
            f"就{order}这单",
        ),
        "seats": (
            f"场次{seat}",
            f"{seat}号场",
            f"查询场次{seat}的可选座位",
            f"看看{seat}这场的空位",
            f"场次编号：{seat}",
            f"我说的是{seat}号场的空座",
            f"查询场次{seat}的剩余座位数量",
            f"{seat}这场还有座吗",
        ),
        "screenings": (
            "2026-10-12",
            "那就2026-10-12吧",
            "日期改成2026年10月12日",
            "就瞅瞅2026-10-12那天有啥场",
            "查询2026-10-12的排期",
            "就查2026-10-12",
            "2026/10/12",
            "换成10月12日，查下场次",
        ),
    }
    for intent, questions in replies.items():
        original = source[{"refund": "F_C04", "seats": "F_C02", "screenings": "F_C03"}[intent]]
        for index, question in enumerate(questions):
            if intent in ("refund", "seats"):
                case = copy.deepcopy(source["F_O1C" if intent == "refund" else "F_S06"])
            else:
                case = {
                    "user_id": original["user_id"],
                    "group": "simple",
                    "expected_intent": "screenings",
                    "accepted_intents": ["screenings"],
                    "plans": [
                        [
                            {
                                "name": "search_screenings",
                                "arguments": {"screening_date": "2026-10-12", "query_scope": "scheduled"},
                                "user_id": original["user_id"],
                            }
                        ]
                    ],
                    "answer_checks": ["2026-10-12", "北京时间"],
                    "answer_associations": [],
                }
            case.update(
                id=f"FOLLOW_{intent}_{index + 1:02d}",
                question=question,
                group="followup",
                source_case_id=original["source_case_id"],
                phrasing_style="标准" if index % 2 == 0 else "口语",
                history=[
                    {"role": "user", "content": original["question"]},
                    {
                        "role": "assistant",
                        "content": {
                            "refund": "请提供订单号。",
                            "seats": "请提供场次编号。",
                            "screenings": "日期不存在，请提供有效的场次日期。",
                        }[intent],
                    },
                ],
                label_source="explicit_acceptance_definition",
                expected_clarification=False,
            )
            result.append(case)
    return result


def build(source: Path, output: Path, bindings_output: Path) -> dict[str, Any]:
    """Deidentify concrete order numbers; private live bindings stay outside gold."""
    cases = json.loads((source / "cases.json").read_text(encoding="utf-8"))
    trials = [
        json.loads(line) for line in (source / "trials.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    clarifications = [row for row in trials if row.get("stop_reason") == "needs_user"]
    selected = {row["case_id"] for row in clarifications}
    for case in cases:
        case["label_source"] = "frozen_independent_acceptance"
        case["expected_clarification"] = case["plans"] == [[]] and case["expected_intent"] != "chat"
        case["clarification_observations"] = [
            {"repetition": row["repetition"], "observed": True}
            for row in clarifications
            if row["case_id"] == case["id"]
        ]
    cases += followups(cases)
    serialized = json.dumps(cases, ensure_ascii=False, indent=2)
    orders = sorted(set(re.findall(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])", serialized)))
    bindings = {f"OGOLD{index + 1:06d}": order for index, order in enumerate(orders)}
    for fixture, actual in bindings.items():
        serialized = serialized.replace(actual, fixture)
    sanitized = json.loads(serialized)
    if not 100 <= len(sanitized) <= 200 or len({case["id"] for case in sanitized}) != len(sanitized):
        raise ValueError("Golden set must contain 100-200 uniquely identified cases")
    if not selected <= {case["id"] for case in sanitized}:
        raise ValueError("Clarification case coverage incomplete")
    output.mkdir(parents=True, exist_ok=True)
    (output / "cases.json").write_text(serialized + "\n", encoding="utf-8")
    events = [
        {
            "case_id": row["case_id"],
            "repetition": row["repetition"],
            "variant": row.get("variant"),
            "source_stop_reason": "needs_user",
        }
        for row in clarifications
    ]
    (output / "observed_clarifications.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metadata = {
        "version": "golden-v1",
        "n": len(sanitized),
        "source_questions": len(sanitized) - 24,
        "new_followup_questions": 24,
        "observed_clarification_events": len(events),
        "distinct_clarified_questions": len(selected),
        "frozen_business_date": "2026-10-11",
        "use": "held_out_acceptance_only; never train from this set",
        "source_cases_sha256": hashlib.sha256((source / "cases.json").read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256((output / "cases.json").read_bytes()).hexdigest(),
        "snapshot_sha256": hashlib.sha256((source / "snapshot.json").read_bytes()).hexdigest(),
        "clarification_note": "Observed clarification does not mean clarification is the desired outcome; gold plans remain authoritative",
        "bindings_required_for_live": sorted(bindings),
        "duplicate_events_are_not_additional_questions": True,
    }
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bindings_output.parent.mkdir(parents=True, exist_ok=True)
    bindings_output.write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def main() -> None:
    """Materialize versioned cases plus separately stored development bindings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bindings-output", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(build(options.source, options.output, options.bindings_output), ensure_ascii=True))


if __name__ == "__main__":
    main()
