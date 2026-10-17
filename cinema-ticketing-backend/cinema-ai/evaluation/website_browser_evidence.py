"""Cross-check manually observed CUA browser scenarios against durable gateway history.

This collects API evidence only; it does not claim to drive or re-run browser actions.
"""

import argparse
import asyncio
import json
from pathlib import Path

from evaluation.website_regression import URLS, WEB, WebsiteRegression, save


async def collect(environment: Path) -> None:
    private = json.loads((environment / "private.json").read_text(encoding="utf-8"))
    output = environment / "browser-evidence"
    output.mkdir(exist_ok=True)
    if (output / "observations.json").exists():
        raise FileExistsError("Browser evidence already exists; preserve it before any further session reset")
    runner = WebsiteRegression(private, output)
    histories = {}
    try:
        await runner.login()
        for account in ("a", "b"):
            restored = await runner.json(
                "GET", WEB + "/ai-gateway/agent/session", headers={"X-Auth-Token": runner.tokens[account]}
            )
            rows = []
            for message in restored["messages"]:
                if message["role"] != "assistant" or not message.get("messageId"):
                    continue
                evidence = await runner.json(
                    "GET",
                    URLS["gateway"] + "/internal/regression/messages/" + message["messageId"],
                    headers=runner.headers,
                )
                rows.append({"history": message, "gateway": evidence})
            histories[account] = rows
        a_text = "\n".join(row["history"]["content"] for row in histories["a"])
        b_text = "\n".join(row["history"]["content"] for row in histories["b"])
        observations = [
            {
                "id": "B01",
                "description": "模糊首问在页面列出上映/可购票两个选项，确认有票后按观影日期回答",
                "verified": all(
                    word in a_text for word in ("新上映的悬疑片", "可购票场次", "2026-10-12 至 2026-10-18")
                ),
            },
            {
                "id": "B02",
                "description": "那下周呢保留悬疑题材和观影对象，显示 10/19 至 10/25",
                "verified": "2026-10-19 至 2026-10-25" in a_text and "回归悬疑新片" in a_text,
            },
            {
                "id": "B03",
                "description": "退款 UNKNOWN 显示处理中、不可用、结果待核对、不承诺到账日期",
                "verified": all(
                    word in a_text for word in ("退款处理中，电影票暂不可使用", "请勿重复申请", "目前无法确认到账时间")
                ),
            },
            {
                "id": "B04",
                "description": "取消与补偿退款分开说明",
                "verified": "订单已取消，已收款项正在原路退回，退款结果仍在核对" in a_text,
            },
            {
                "id": "B05",
                "description": "退出 A 后订单/面板清理，B 仅显示自己的 000014 订单和空聊天；B 查询 A 的 000008 被拒绝",
                "verified": "OWEBREG000010" not in b_text
                and "¥42" not in b_text
                and any(row["gateway"]["error_code"] == "data_not_found" for row in histories["b"]),
            },
            {
                "id": "B06",
                "description": "立即停止显示已停止回答/回答未完成；异常契约显示失败并可重试",
                "verified": any(row["gateway"]["error_code"] == "interrupted" for row in histories["a"])
                and any(row["gateway"]["error_code"] == "query_contract_mismatch" for row in histories["a"]),
            },
        ]
        for row in observations:
            row["status"] = "PASS" if row.pop("verified") else "FAIL"
            row["method"] = "CUA 页面观察 + 网站持久化记录交叉核对"
        save(output / "observations.json", observations)
        save(output / "history-evidence.json", histories)
        print(
            json.dumps(
                {
                    "browser_scenarios": len(observations),
                    "passed": sum(row["status"] == "PASS" for row in observations),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await runner.client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", type=Path, required=True)
    asyncio.run(collect(parser.parse_args().environment))
