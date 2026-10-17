"""Regress the authenticated website entry point, with independently computed builds.

python -m evaluation.website_regression --environment ../target/website-regression-RUN --core
Each run writes new evidence. No frozen Golden data or real financial state is changed.
"""

import argparse
import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

from evaluation.website_cases import CASES, CORE, Turn
from evaluation.website_environment import AI, BACKEND, ROOT

WEB = "http://127.0.0.1:15173"
URLS = {
    "java": "http://127.0.0.1:18080",
    "agent": "http://127.0.0.1:18000",
    "mcp": "http://127.0.0.1:18020",
    "gateway": "http://127.0.0.1:18010",
    "frontend": WEB,
}
BEIJING = timezone(timedelta(hours=8))


def digest(root: Path, files: list[Path]) -> str:
    value = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        value.update(path.relative_to(root).as_posix().encode())
        value.update(b"\0")
        value.update(path.read_bytes())
    return value.hexdigest()


def expected_builds() -> dict[str, str]:
    agent = digest(
        AI,
        [*AI.joinpath("app").rglob("*.py"), *AI.joinpath("prompts").rglob("*.txt"), AI / "config/agent_versions.json"],
    )
    gateway = BACKEND / "cinema-ai-gateway"
    frontend = ROOT / "cinema-ticketing-frontend"
    classes = BACKEND / "target/classes"
    return {
        "agent": agent,
        "mcp": agent,
        "gateway": digest(gateway, list(gateway.joinpath("app").rglob("*.py"))),
        "java": digest(classes, list(classes.joinpath("com/cinema/ticketing").rglob("*.class"))),
        "frontend": digest(
            frontend, [*frontend.joinpath("src").rglob("*.*"), frontend / "package.json", frontend / "vite.config.ts"]
        ),
    }


def save(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)


class WebsiteRegression:
    def __init__(self, private: dict, output: Path) -> None:
        self.private, self.output = private, output
        self.headers = {"X-Internal-Token": private["token"]}
        self.fixture_headers = {"X-Fixture-Token": private["fixture_token"]}
        self.client = httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(100, connect=5))
        self.tokens: dict[str, str] = {}
        self.orders: dict[str, str] = {}

    async def json(self, method: str, url: str, **kwargs) -> dict:
        response = await self.client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def preflight(self) -> list[dict]:
        expected = expected_builds()
        rows = []
        for name, url in URLS.items():
            route = (
                "/internal/ai/runtime"
                if name == "java"
                else "/__cinema_runtime"
                if name == "frontend"
                else "/internal/runtime"
            )
            try:
                actual = await self.json("GET", url + route, headers=self.headers)
                matched = actual.get("build_id") == expected[name] and not actual.get("workspace_changed", False)
                contracts = actual.get("contracts", {})
                wanted = (
                    {"sse": "cinema-sse-v1"}
                    if name == "frontend"
                    else {"order": "cinema-order-v2", "time": "cinema-time-v1"}
                )
                matched = matched and all(contracts.get(key) == value for key, value in wanted.items())
                rows.append(
                    {
                        "component": name,
                        "expected_build_id": expected[name],
                        "actual": actual,
                        "status": "PASS" if matched else "BLOCKED",
                    }
                )
                # Diagnostics must never be accessible without the private service credential.
                if name != "frontend":
                    unauthenticated = await self.client.get(url + route)
                    rows[-1]["authentication_enforced"] = unauthenticated.status_code in {400, 401, 403}
                    if not rows[-1]["authentication_enforced"]:
                        rows[-1]["status"] = "FAIL"
            except (httpx.HTTPError, ValueError) as exc:
                rows.append({"component": name, "status": "BLOCKED", "reason": type(exc).__name__})
        save(self.output / "preflight.json", rows)
        return rows

    async def login(self) -> None:
        for alias in ("a", "b"):
            result = await self.json(
                "POST",
                WEB + "/api/auth/login",
                json={"username": "website_reg_" + alias, "password": self.private["account_password"]},
            )
            self.tokens[alias] = result["data"]["token"]
        snapshot = await self.json("GET", "http://127.0.0.1:18090/snapshot", headers=self.fixture_headers)
        self.orders = snapshot["orders"]
        save(self.output / "fixture-snapshot.json", snapshot)

    async def session(self, account: str = "a") -> dict:
        value = await self.json(
            "GET", WEB + "/ai-gateway/agent/session", headers={"X-Auth-Token": self.tokens[account]}
        )
        session = {"sessionId": value["sessionId"], "bindingKey": value["bindingKey"], "account": account}
        value = await self.json("POST", WEB + "/ai-gateway/agent/reset", headers=self.browser_headers(session))
        session["sessionId"] = value["sessionId"]
        return session

    def browser_headers(self, session: dict) -> dict:
        return {
            "X-Auth-Token": self.tokens[session["account"]],
            "X-AI-Session": session["bindingKey"],
            "X-AI-Conversation": session["sessionId"],
        }

    async def turn(self, session: dict, turn: Turn) -> dict:
        question = turn.question.format(**self.orders)
        if turn.action == "reset":
            result = await self.json("POST", WEB + "/ai-gateway/agent/reset", headers=self.browser_headers(session))
            session["sessionId"] = result["sessionId"]
        if turn.action == "advance":
            await self.json("POST", "http://127.0.0.1:18090/advance", headers=self.fixture_headers)
        if turn.action in {"truncate", "java_unavailable"}:
            await self.json(
                "POST",
                "http://127.0.0.1:18081/__fixture/fault",
                headers=self.fixture_headers,
                json={
                    "mode": turn.action,
                    "path": "/internal/orders/" + self.orders["O04"] if turn.action == "java_unavailable" else "",
                },
            )
        credential = (
            await self.json(
                "POST",
                WEB + "/api/ai/handoff",
                headers={"X-Auth-Token": self.tokens[session["account"]]},
                json={"sessionId": session["sessionId"]},
            )
        )["data"]["credential"]
        if turn.action == "expired":
            credential = str(uuid.uuid4()) + str(uuid.uuid4())
        headers = self.browser_headers(session)
        if turn.action == "account_switch":
            headers["X-Auth-Token"] = self.tokens["b"]
        events, started = [], time.perf_counter()
        row = {"question": question, "check": turn.check, "reference_date": datetime.now(BEIJING).date().isoformat()}
        stopped = False
        async with self.client.stream(
            "POST",
            WEB + "/ai-gateway/agent/chat",
            headers=headers,
            json={"sessionId": session["sessionId"], "question": question, "credential": credential},
        ) as response:
            row["http_status"] = response.status_code
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    packet = json.loads(line[5:].strip())
                    events.append(packet)
                    if turn.action == "stop" and packet.get("type") == "status" and not stopped:
                        await self.json("POST", WEB + "/ai-gateway/agent/stop", headers=headers)
                        stopped = True
        row.update(
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            events=events,
            answer="".join(event.get("text", "") for event in events if event.get("type") == "delta"),
        )
        message_id = next((event["messageId"] for event in events if event.get("type") == "message"), "")
        if message_id:
            record = await self.json(
                "GET", URLS["gateway"] + "/internal/regression/messages/" + message_id, headers=self.headers
            )
            row["message_id"], row["record"] = message_id, record
            request_id = record["context"].get("request_id", "")
            row["evidence"] = {}
            if request_id:
                for component in ("java", "mcp", "agent"):
                    route = "/internal/ai/regression/" if component == "java" else "/internal/regression/"
                    row["evidence"][component] = await self.json(
                        "GET", URLS[component] + route + request_id, headers=self.headers
                    )
        if turn.check.startswith("order_") or turn.check == "persisted":
            alias = "O" + turn.check[6:8] if turn.check.startswith("order_") else "O04"
            row["facts"] = await self.json(
                "GET",
                URLS["java"] + "/internal/orders/" + self.orders[alias],
                headers=self.headers,
                params={"userId": 70001},
            )
            listed = (await self.json("GET", WEB + "/api/orders", headers={"X-Auth-Token": self.tokens["a"]}))["data"]
            row["website_facts"] = next((order for order in listed if order["order_no"] == self.orders[alias]), {})
        restored = await self.json(
            "GET",
            WEB + "/ai-gateway/agent/session",
            headers=headers if turn.action != "account_switch" else self.browser_headers(session),
        )
        row["persisted"] = any(
            item.get("messageId") == message_id and item.get("content") == row["answer"] and not item.get("failed")
            for item in restored["messages"]
        )
        row["failures"] = score(row)
        row["status"] = "FAIL" if row["failures"] else "PASS"
        return row


def score(row: dict) -> list[str]:
    failures = []

    def require(condition: object, message: str) -> None:
        if not condition:
            failures.append(message)

    check, answer, events = row["check"], row["answer"], row["events"]
    context = row.get("record", {}).get("context", {})
    calls = row.get("evidence", {}).get("java", {}).get("calls", [])
    errors = [event.get("code") for event in events if event.get("type") == "error"]
    completes = sum(event.get("type") == "complete" for event in events)
    special = {
        "foreign_order",
        "expired_handoff",
        "account_isolation",
        "service_error",
        "contract_error",
        "truncated",
        "stopped",
    }
    if check in special:
        require(completes == 0, "异常轮次不应发送正常完成")
        if check == "account_isolation":
            require(row["http_status"] in {401, 403, 409}, "旧会话不能绑定新账号")
        else:
            require(bool(errors), "异常必须有明确错误事件")
        expected = {
            "expired_handoff": {"handoff_expired"},
            "contract_error": {"query_contract_mismatch"},
            "stopped": {"interrupted"},
            "service_error": {"business_unavailable", "service_unreachable", "query_timeout"},
            "foreign_order": {"data_not_found", "business_auth_failed"},
        }
        if check in expected:
            require(bool(set(errors) & expected[check]), "错误代码不匹配: " + str(errors))
        require("¥42" not in answer and "测试座位" not in answer, "失败时泄露业务事实")
        return failures
    require(row["http_status"] == 200 and completes == 1 and not errors, "应仅正常完成一次")
    require(row.get("persisted"), "回答未准确保存到网站历史")
    require(bool(context.get("runtime_version", {}).get("rules_hash")), "缺少规则版本证据")
    require(
        context.get("temporal_summary", {}).get("reference_date") == row["reference_date"], "缺少或误用了参考业务日期"
    )
    require(
        all(type(context.get(key)) is int for key in ("model_call_count", "tool_call_count", "step_count")),
        "缺少实际调用计数",
    )
    require(context.get("model_call_count", 0) <= 8 and context.get("tool_call_count", 0) <= 8, "超过调用预算")
    require(
        not set(context.get("tool_calls", []))
        - {
            "search_movies",
            "search_screenings",
            "query_order",
            "query_seats",
            "recommend_movies",
            "query_ticket_policy",
            "request_clarification",
        },
        "调用了非只读工具",
    )
    if check == "clarify":
        require(not calls, "澄清轮不应查询业务数据")
        require(any(word in answer for word in ("上映", "日期", "确认", "请", "具体")), "缺少明确追问")
        return failures
    if check == "reset_clean":
        require("悬疑" not in str(context.get("entities", {})), "reset 后仍残留题材")
        require(not context.get("entities", {}).get("screening_date_from"), "reset 后残留本周")
        return failures
    if check.startswith("order_") or check == "persisted":
        facts, website = row["facts"], row["website_facts"]
        expected_states = {
            "01": ("UNPAID", "INIT", None, None, False),
            "02": ("UNPAID", "CLOSING", None, None, False),
            "03": ("CANCELLED", "CLOSED", None, None, False),
            "04": ("ISSUED", "SUCCESS", None, None, True),
            "05": ("ISSUED", "SUCCESS", None, None, False),
            "06": ("ISSUED", "SUCCESS", None, None, False),
            "07": ("REFUNDING", "SUCCESS", "PENDING", "CUSTOMER", False),
            "08": ("REFUNDING", "SUCCESS", "UNKNOWN", "CUSTOMER", False),
            "09": ("REFUNDED", "SUCCESS", "REFUNDED", "CUSTOMER", False),
            "10": ("CANCELLED", "SUCCESS", "UNKNOWN", "LATE_PAYMENT", False),
            "11": ("CANCELLED", "SUCCESS", "REFUNDED", "LATE_PAYMENT", False),
            "12": ("REFUNDING", "SUCCESS", "PENDING", "CUSTOMER", False),
            "12_updated": ("REFUNDED", "SUCCESS", "REFUNDED", "CUSTOMER", False),
        }
        wanted = expected_states[check[6:] if check.startswith("order_") else "04"]
        require(
            tuple(
                facts.get(key)
                for key in ("status", "payment_status", "refund_status", "refund_reason_type", "can_refund")
            )
            == wanted,
            "夹具或业务状态偏离该场景预期",
        )
        require(any(call["path"].endswith(facts["order_no"]) for call in calls), "未重新读取本轮订单")
        require(facts["refund_reason"] in answer, "回答未采用最新资格说明")
        for field in ("status", "payment_status", "refund_status", "refund_reason_type", "can_refund", "refund_reason"):
            require(facts.get(field) == website.get(field), "网站与 Agent 订单事实不一致: " + field)
        if facts["refund_status"] in {"UNKNOWN", "PENDING"}:
            require(not re.search(r"退款已(?:成功|完成|到账)|已退款|补偿退款已确认", answer), "未确认退款被说成已完成")
        if check == "order_12_updated":
            require(facts["status"] == "REFUNDED" and "已退款" in answer, "没有更新退款状态")
        return failures
    today = datetime.fromisoformat(row["reference_date"]).date()
    monday = today - timedelta(days=today.weekday())
    next_week = "next_week" in check
    recent = "recent" in check
    tomorrow = check.startswith("tomorrow")
    start, end = (
        (today - timedelta(days=6), today)
        if recent
        else (
            (today + timedelta(days=1),) * 2
            if tomorrow
            else (monday + timedelta(days=7 if next_week else 0), monday + timedelta(days=13 if next_week else 6))
        )
    )
    release = check.startswith("release")
    target = "release" if release else "screening"
    windows = context.get("temporal_summary", {}).get("windows", [])
    expected_window = next(
        (
            window
            for window in windows
            if window.get("target") == target
            and window.get("date_from") == start.isoformat()
            and window.get("date_to") == end.isoformat()
        ),
        None,
    )
    require(expected_window, "归一化时间对象或日期范围错误")
    if "soft" in check:
        require(expected_window and expected_window["strength"] == "soft", "软偏好被变成硬条件")
    query_calls = [call for call in calls if call["status"] == 200]
    require(bool(query_calls), "缺少关联到本轮的 Java 查询证据")
    prefix = "releaseDate" if release else "screeningDate"
    matching = [
        call
        for call in query_calls
        if (
            call["parameters"].get(prefix + "From") == start.isoformat()
            and call["parameters"].get(prefix + "To") == end.isoformat()
        )
        or (tomorrow and call["parameters"].get("screeningDate") == start.isoformat())
    ]
    require(bool(matching), "Java 实际收到的日期不符")
    if "evening" in check:
        require(
            any(str(call["parameters"].get("screeningHourFrom")) == "18" for call in matching), "晚间条件未传到 Java"
        )
    if check.startswith("scheduled"):
        require(
            any(
                call["parameters"].get("queryScope") == "scheduled"
                or call["parameters"].get("movieScope") == "scheduled"
                for call in matching
            ),
            "排期被当成可购票",
        )
    if check.startswith("bookable") or check == "empty_week":
        require(
            any(call["parameters"].get("movieScope", "bookable") == "bookable" for call in matching), "可购票范围错误"
        )
    if release:
        require("回归悬疑新片" in answer, "漏掉满足上映条件的影片")
        if "hard" in check or check == "release_week":
            require("回归悬疑旧片" not in answer, "上映硬条件被放宽")
    if check == "empty_week":
        require("没有查到" in answer or "未找到" in answer, "空结果没有说明")
        require("以下影片具有符合条件的当前可订购场次" not in answer, "空结果仍宣称有可购票影片")
    return failures


async def original_preflight(output: Path) -> None:
    """Read-only evidence from the original website; never restart or log its secret."""
    env = dotenv_values(AI / ".env")
    headers = {"X-Internal-Token": env.get("AI_INTERNAL_TOKEN", "local-internal-token")}
    rows = []
    async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
        for name, port, path in (
            ("frontend", 5173, "/__cinema_runtime"),
            ("gateway", 8010, "/internal/runtime"),
            ("agent", 8000, "/internal/runtime"),
            ("mcp", 8020, "/internal/runtime"),
            ("java", 8080, "/internal/ai/runtime"),
        ):
            try:
                response = await client.get(f"http://127.0.0.1:{port}{path}", headers=headers)
                actual = response.json() if "application/json" in response.headers.get("content-type", "") else {}
                rows.append(
                    {
                        "component": name,
                        "http_status": response.status_code,
                        "actual": actual,
                        "status": "PASS"
                        if actual.get("build_id") == expected_builds()[name] and not actual.get("workspace_changed")
                        else "BLOCKED",
                    }
                )
            except httpx.HTTPError as exc:
                rows.append({"component": name, "status": "BLOCKED", "reason": type(exc).__name__})
    save(output / "original-website-preflight.json", rows)


async def run(options: argparse.Namespace) -> None:
    output = options.environment / ("results-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    output.mkdir(parents=True)
    await original_preflight(output)
    runner = WebsiteRegression(json.loads((options.environment / "private.json").read_text(encoding="utf-8")), output)
    rows = []
    try:
        preflight = await runner.preflight()
        if any(row["status"] != "PASS" for row in preflight):
            print("BLOCKED: runtime identity mismatch; see " + str(output), flush=True)
            return
        await runner.login()
        selected = [
            case
            for case in CASES
            if (not options.core or case.id in CORE)
            and (not options.case_ids or case.id in options.case_ids.split(","))
        ]
        if options.case_ids and set(options.case_ids.split(",")) != {case.id for case in selected}:
            raise ValueError("Unknown case identifier or incompatible --core selection")
        for case in selected:
            row = {"id": case.id, "title": case.title, "turns": []}
            try:
                session = await runner.session()
                for turn in case.turns:
                    row["turns"].append(await runner.turn(session, turn))
                row["status"] = "FAIL" if any(turn["status"] == "FAIL" for turn in row["turns"]) else "PASS"
            except Exception as exc:
                row.update(status="BLOCKED", reason=type(exc).__name__)
                # URLs may contain fixture order numbers; no response headers or credential bodies.
                row["detail"] = str(exc).split("For more information")[0][:500]
            rows.append(row)
            save(output / "trials.json", rows)
            print(
                json.dumps(
                    {
                        "id": case.id,
                        "status": row["status"],
                        "failures": [turn.get("failures") for turn in row["turns"]],
                        "reason": row.get("reason"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        save(
            output / "summary.json",
            {
                "counts": dict(Counter(row["status"] for row in rows)),
                "scenarios": len(rows),
                "rounds": sum(len(row["turns"]) for row in rows),
                "scope": "isolated website + actual configured model",
                "original_website": "see separate preflight",
                "finished_at": datetime.now(BEIJING).isoformat(),
            },
        )
    finally:
        await runner.client.aclose()
    print("Evidence: " + str(output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--core", action="store_true")
    parser.add_argument("--case-ids", default="")
    asyncio.run(run(parser.parse_args()))
