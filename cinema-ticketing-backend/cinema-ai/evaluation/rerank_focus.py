"""Measure evidence ranking on frozen real knowledge candidates, independently of Agent planning."""

import argparse
import asyncio
import contextvars
import json
import math
import os
import random
import re
from dataclasses import asdict, replace
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv
from langchain_core.documents import Document

from evaluation.rerank_metrics import observe_reranker, rerank_summary
from evaluation.run import AI_ROOT, services

QUESTIONS = [
    ("R01", "选座后座位会为我保留多久？", [["锁定", "五分钟|5\\s*分钟"]]),
    ("R02", "购票超时还没付钱会怎样？", [["超时", "自动取消", "释放座位"]]),
    ("R03", "购票之前是否需要先登录？", [["先登录"]]),
    ("R04", "支付和出票由哪个系统完成？", [["支付", "出票", "Java 后端"]]),
    ("R05", "退票需要满足什么条件？", [["已(?:经)?出票", "未开场|距离开场超过"]]),
    ("R06", "影片开始以后还可以退票吗？", [["影片开始后", "不允许|不可退票"]]),
    ("R07", "退票结果以哪个服务的校验为准？", [["Java 订单服务", "状态校验"]]),
    ("R08", "AI 可以直接修改订单退票吗？", [["AI", "不能直接修改订单"]]),
    ("R09", "影院、影厅和场次信息以什么数据为准？", [["Java 业务服务", "返回的数据"]]),
    ("R10", "知识库没有匹配规则时应该怎么回答？", [["没有匹配内容", "不能自行编造"]]),
    ("R11", "会员权益里生日赠票有多少张？", []),
    ("R12", "学生购票优惠具体几折？", []),
]


def relevant(text: str, rules: list[list[str]]) -> bool:
    """Use question-specific passage facts declared before any cloud ranking."""
    return any(all(re.search(pattern, text) for pattern in group) for group in rules)


async def prepare(directory: Path, java_url: str) -> None:
    """Freeze actual local/database candidates, with no paid model requests."""
    os.environ["JAVA_API_URL"] = java_url
    from app.java_client import JavaApiClient
    from app.policy_retrieval import load_retriever, policy_candidates
    from app.reranker import RerankSettings

    api = JavaApiClient()
    retriever, settings = load_retriever(), RerankSettings.from_env()
    cases = []
    try:
        policy = await api.get("/internal/refund-policy")
        for case_id, question, rules in QUESTIONS:
            local, business = await asyncio.gather(
                retriever.ainvoke(question), api.get("/internal/knowledge/search", {"query": question})
            )
            candidates = policy_candidates(question, local, business, settings.top_k)
            cases.append(
                {
                    "id": case_id,
                    "question": question,
                    "answerable": bool(rules),
                    "relevance_rules": rules,
                    "candidates": [{"text": doc.page_content, "metadata": doc.metadata} for doc in candidates],
                    "relevant_candidate_ids": [
                        doc.metadata["chunk_id"] for doc in candidates if relevant(doc.page_content, rules)
                    ],
                    "business_documents": business,
                }
            )
    finally:
        await api.aclose()
    (directory / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "scope": "evidence_only; frozen real candidates; excludes Java retrieval and answer generation",
                "case_count": len(cases),
                "positive_questions": sum(case["answerable"] for case in cases),
                "negative_questions": sum(not case["answerable"] for case in cases),
                "settings": asdict(settings),
                "authoritative_policy_excluded_from_ranking": policy,
                "repeats": 2,
                "concurrency": 1,
                "note": "Relevance is not authority: outdated refund prose may be relevant but contradict live policy.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def ranking_score(case: dict, selected: list[Document]) -> dict:
    """Report evidence coverage/order; do not treat negative queries as positive Recall samples."""
    gold = set(case["relevant_candidate_ids"])
    ids = [doc.metadata["chunk_id"] for doc in selected]
    pool = {doc["metadata"]["chunk_id"]: doc for doc in case["candidates"]}
    provenance_correct = all(
        doc.metadata["chunk_id"] in pool
        and doc.page_content == pool[doc.metadata["chunk_id"]]["text"]
        and {key: value for key, value in doc.metadata.items() if key != "rerank_score"}
        == pool[doc.metadata["chunk_id"]]["metadata"]
        for doc in selected
    )
    ranks = [position + 1 for position, identity in enumerate(ids) if identity in gold]
    dcg = sum(1 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(gold), len(ids)) + 1))
    return {
        "provenance_correct": provenance_correct,
        "candidate_recall_hit": bool(gold) if case["answerable"] else None,
        "top1_hit": bool(ids and ids[0] in gold) if case["answerable"] else None,
        "selected_hit": bool(ranks) if case["answerable"] else None,
        "mrr": (1 / ranks[0] if ranks else 0) if case["answerable"] else None,
        "ndcg_at_n": (dcg / ideal if ideal else 0) if case["answerable"] else None,
        "negative_has_selected_passages": bool(selected) if not case["answerable"] else None,
    }


def summarize_focus(rows: list[dict]) -> dict:
    """Aggregate all fixed positives, including upstream recall misses as zero."""
    output = {}
    for variant in ("baseline", "react"):
        selected = [row for row in rows if row["variant"] == variant]
        positives = [row for row in selected if row["answerable"]]
        negatives = [row for row in selected if not row["answerable"]]
        output[variant] = {
            "n": len(selected),
            "positive_n": len(positives),
            "negative_n": len(negatives),
            **{
                key: mean(row["score"][key] for row in positives) if positives else None
                for key in ("candidate_recall_hit", "top1_hit", "selected_hit", "mrr", "ndcg_at_n")
            },
            "provenance_correct_rate": mean(row["score"]["provenance_correct"] for row in selected),
            "negative_returned_evidence_count": sum(
                row["score"]["negative_has_selected_passages"] for row in negatives
            ),
            "rerank": rerank_summary(selected),
        }
    return output


async def measure(directory: Path) -> None:
    """Alternate two ranking settings on identical saved candidates without a chat model."""
    from app.reranker import DashScopeReranker, RerankSettings

    cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
    settings = RerankSettings(**json.loads((directory / "metadata.json").read_text(encoding="utf-8"))["settings"])
    active = contextvars.ContextVar("rerank_evidence_trial")
    rankers = {
        "baseline": DashScopeReranker(replace(settings, enabled=False)),
        "react": DashScopeReranker(replace(settings, enabled=True)),
    }
    for ranker in rankers.values():
        observe_reranker(ranker, active)
    output = directory / "trials.jsonl"
    if output.exists():
        raise ValueError("Use a new output directory; scored evidence runs are never silently repeated")
    rows = []
    try:
        with output.open("w", encoding="utf-8") as stream:
            for repetition in (1, 2):
                ordered = list(cases)
                random.Random(20261009 + repetition).shuffle(ordered)
                for index, case in enumerate(ordered):
                    variants = ("baseline", "react") if (index + repetition) % 2 else ("react", "baseline")
                    for variant in variants:
                        row = {
                            "case_id": case["id"],
                            "variant": variant,
                            "repetition": repetition,
                            "question": case["question"],
                            "answerable": case["answerable"],
                            "rerank_calls": [],
                        }
                        token = active.set(row)
                        try:
                            documents = [
                                Document(page_content=doc["text"], metadata=doc["metadata"])
                                for doc in case["candidates"]
                            ]
                            ranked = await rankers[variant].rerank(case["question"], documents)
                        finally:
                            active.reset(token)
                        row["score"] = ranking_score(case, ranked)
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                        stream.flush()
                        rows.append(row)
    finally:
        for ranker in rankers.values():
            await ranker.aclose()
    (directory / "summary.json").write_text(
        json.dumps(summarize_focus(rows), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"evidence_trials": len(rows), "summary": summarize_focus(rows)}, ensure_ascii=True), flush=True)


async def main() -> None:
    """Prepare while Java is available, then measure separately after end-to-end timing ends."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--java-url")
    options = parser.parse_args()
    load_dotenv(AI_ROOT / ".env")
    directory = options.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if options.prepare_only:
        if options.java_url:
            await prepare(directory, options.java_url)
        else:
            service_logs = directory / "preparation-service"
            service_logs.mkdir(exist_ok=True)
            async with services(service_logs):
                await prepare(directory, os.environ["JAVA_API_URL"])
        print(json.dumps({"prepared_evidence_questions": len(QUESTIONS)}))
    else:
        await measure(directory)


if __name__ == "__main__":
    asyncio.run(main())
