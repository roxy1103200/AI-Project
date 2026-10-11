"""Four synthetic public-film questions: verify GLM routing without business data."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.agent_budget import BudgetedModel, RequestBudget
from app.glm_router import classify, create_glm_model
from app.intent import rule_plan

QUESTIONS = (
    "帮我看看星际穿越是谁拍的",
    "我想了解一下流浪地球的片长",
    "查一下盗梦空间的导演",
    "我想看功夫这部电影的介绍",
)


class SyntheticObserver:
    """Keep diagnostic output only for the declared public synthetic questions."""

    def __init__(self, inner: Any, responses: list[Any]) -> None:
        self.inner, self.responses = inner, responses

    def bind(self, **kwargs: Any) -> "SyntheticObserver":
        return SyntheticObserver(self.inner.bind(**kwargs), self.responses)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        response = await self.inner.ainvoke(*args, **kwargs)
        self.responses.append(response)
        return response


async def smoke() -> dict[str, Any]:
    """Send only the four declared synthetic questions; no Java/MCP/DB calls."""
    model = create_glm_model()
    if model is None:
        raise ValueError("GLM classifier is not configured")
    rows = []
    for index, question in enumerate(QUESTIONS):
        responses: list[Any] = []
        budget = RequestBudget(max_calls=1, max_tokens=4096, timeout_seconds=10)
        candidate, status, elapsed = await classify(
            BudgetedModel(SyntheticObserver(model, responses), budget, "glm_l1", 320), question, rule_plan(question, [])
        )
        rows.append(
            {
                "case_id": f"SMOKE_{index + 1}",
                "status": status,
                "intent": candidate.intent if candidate else None,
                "movie_query": candidate.movie_query if candidate else None,
                "duration_ms": elapsed,
                "synthetic_response": str(responses[0].content) if responses else None,
                **budget.snapshot(),
            }
        )
    await model.root_async_client.close()
    return {
        "scope": "four synthetic classifier requests only; not an end-to-end evaluation",
        "model": "glm-4.7-flash",
        "n": len(rows),
        "rows": rows,
    }


def main() -> None:
    """Write metadata and usage; never print credentials or provider error bodies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    result = asyncio.run(smoke())
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"n": result["n"], "statuses": [row["status"] for row in result["rows"]]}))


if __name__ == "__main__":
    main()
