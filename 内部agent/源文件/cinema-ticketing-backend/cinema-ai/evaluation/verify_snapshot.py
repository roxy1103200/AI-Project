"""Check that the live business facts still match the frozen scoring snapshot."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from evaluation.run import AI_ROOT, services


async def verify(directory: Path) -> dict:
    """Read the same Java endpoints without model calls or business mutations."""
    from app.java_client import JavaApiClient

    frozen = json.loads((directory / "snapshot.json").read_text(encoding="utf-8"))
    api = JavaApiClient()
    checks = []

    def check(name: str, before: object, after: object) -> None:
        # The response clock changes on every read; all business fields still compare exactly.
        if name.startswith("order_"):
            before = {key: value for key, value in before.items() if key != "server_time"}
            after = {key: value for key, value in after.items() if key != "server_time"}
        checks.append({"name": name, "unchanged": before == after, "before": before, "after": after})

    try:
        check("movies", frozen["movies"], await api.get("/internal/movies"))
        check("policy", frozen["policy"], await api.get("/internal/refund-policy"))
        check(
            "future_screenings",
            frozen["all_screenings"],
            await api.get("/internal/screenings", {"screeningDate": frozen["day"], "queryScope": "scheduled"}),
        )
        check(
            "comparison_screenings",
            frozen["comparison_screenings"],
            await api.get(
                "/internal/screenings", {"screeningDate": frozen["comparison_day"], "queryScope": "scheduled"}
            ),
        )
        for screening_id, seats in frozen["seats"].items():
            actual = await api.get(f"/api/screenings/{screening_id}/seats")
            check(f"seats_{screening_id}", seats, actual["data"])
        for order in frozen["orders"]:
            actual = await api.get(f"/internal/orders/{order['order_no']}", {"userId": frozen["user_id"]})
            check(f"order_{order['order_no']}", order, actual)
    finally:
        await api.aclose()
    result = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "all_unchanged": all(row["unchanged"] for row in checks),
        "ignored_response_fields": ["order.server_time"],
        "checks": checks,
    }
    (directory / "stability.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


async def main() -> None:
    """Reuse a running benchmark service, or own an isolated service for the final check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--java-url")
    options = parser.parse_args()
    load_dotenv(AI_ROOT / ".env")
    directory = options.directory.resolve()
    if options.java_url:
        os.environ["JAVA_API_URL"] = options.java_url
        result = await verify(directory)
    else:
        service_logs = directory / "stability-service"
        service_logs.mkdir(exist_ok=True)
        async with services(service_logs):
            result = await verify(directory)
    print(json.dumps({"all_unchanged": result["all_unchanged"], "checks": len(result["checks"])}))


if __name__ == "__main__":
    asyncio.run(main())
