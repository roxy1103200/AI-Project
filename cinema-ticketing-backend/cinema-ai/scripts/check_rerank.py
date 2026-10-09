"""Send one public synthetic query to verify reranking; no business or memory data is read."""

import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.reranker import DashScopeReranker, RerankSettings  # noqa: E402


async def main() -> int:
    """Report safe status fields and exit nonzero if the provider was not actually used."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    logging.basicConfig(level=logging.INFO)
    samples = [
        Document(page_content="请前往我的订单页面查看购买的电影票及订单状态。", metadata={"sample": "orders"}),
        Document(page_content="会员积分用于参加影院会员活动，详情以活动说明为准。", metadata={"sample": "membership"}),
        Document(page_content="可以在场次页面查看影院的电影放映时间和影厅。", metadata={"sample": "screenings"}),
    ]
    reranker = DashScopeReranker(RerankSettings.from_env())
    try:
        selected = await reranker.rerank("在哪里查看购买的电影票订单？", samples)
        success = bool(selected) and all("rerank_score" in document.metadata for document in selected)
        print(
            json.dumps(
                {
                    "status": "success" if success else "fallback",
                    "model": reranker.settings.model,
                    "sample_order": [document.metadata["sample"] for document in selected],
                },
                ensure_ascii=False,
            )
        )
        return 0 if success else 1
    finally:
        await reranker.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
