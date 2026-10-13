"""Summarize exported trace directories or scored trials without external requests."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def records(directory: Path) -> list[dict[str, Any]]:
    """Read UTF-8 JSONL; malformed exports fail explicitly instead of disappearing."""
    if directory.is_file():
        paths = [directory]
    elif (directory / "trials.jsonl").exists():
        paths = [directory / "trials.jsonl"]
    else:
        paths = sorted(directory.rglob("traces.jsonl"))
    if not paths:
        raise ValueError("No trials.jsonl or traces.jsonl found")
    result = []
    for path in paths:
        for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{index}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected an object at {path}:{index}")
            result.append(row)
    return result


def trial_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Use independent gold scores when provided; retain unknown token usage."""
    unique = {}
    for row in rows:
        identity = (row["case_id"], row.get("variant"), row.get("repetition"))
        if identity in unique:
            raise ValueError("Duplicate trial identity; refusing denominator inflation")
        unique[identity] = row
    tasks = []
    for row in unique.values():
        calls = row.get("model_calls", [])
        known = [call["usage"] for call in calls if isinstance(call.get("usage"), dict)]
        tasks.append(
            {
                "completed": bool(row.get("completed")) and not row.get("errors"),
                "task_success": row.get("score", {}).get("task_success"),
                "answer_correct": row.get("score", {}).get("answer_correct"),
                "tool_correct": row.get("score", {}).get("tool_correct"),
                "clarified": row.get("stop_reason") == "needs_user",
                "reflection_status": row.get("reflection_status", "unknown"),
                "route": row.get("route", "unknown"),
                "intent": row.get("detected_intent", "unknown"),
                "slot_summary": row.get("slot_summary", {}),
                "understanding_layer": row.get("understanding_layer", "unknown"),
                "extra_tool_calls": row.get("score", {}).get("extra_tool_calls"),
                "model_calls": len(calls),
                "usage_missing_calls": len(calls) - len(known),
                "input_tokens": sum(usage.get("input_tokens", 0) for usage in known),
                "output_tokens": sum(usage.get("output_tokens", 0) for usage in known),
                "token_observed": bool(known) or not calls,
            }
        )
    stages = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "usage_missing_calls": 0})
    for row in rows:
        for call in row.get("model_calls", []):
            stage = stages[call.get("stage", "unknown")]
            stage["calls"] += 1
            if not isinstance(call.get("usage"), dict):
                stage["usage_missing_calls"] += 1
            else:
                for key in ("input_tokens", "output_tokens"):
                    stage[key] += call["usage"].get(key, 0)
    result = aggregate(tasks)
    result.update(
        source_kind="scored_trials",
        stages=dict(stages),
        token_scope="provider returned chat usage; missing usage excluded; rerank separate",
    )
    rerank_calls = [call for row in rows for call in row.get("rerank_calls", [])]
    result["rerank_records"] = len(rerank_calls)
    return result


def trace_report(rows: list[dict[str, Any]], environment: str | None = None) -> dict[str, Any]:
    """Merge create/update and duplicate day/session archives once per run ID."""
    runs: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: str(item.get("recorded_at", ""))):
        identity = str(row.get("run_id") or row.get("id") or "")
        if not identity:
            continue
        saved = runs.setdefault(identity, {})
        for key, value in row.items():
            if key in ("inputs", "outputs", "metadata") and isinstance(value, dict):
                saved[key] = {**saved.get(key, {}), **value}
            elif value is not None:
                saved[key] = value
    roots = [
        row
        for row in runs.values()
        if not row.get("parent_run_id") and str(row.get("name", "")).startswith("cinema.agent.")
    ]
    if environment:
        roots = [row for row in roots if row.get("metadata", {}).get("environment") == environment]
    tasks = []
    for row in roots:
        output = row.get("outputs", {})
        tasks.append(
            {
                "completed": output.get("status") == "completed",
                "task_success": output.get("task_success"),
                "answer_correct": None,
                "tool_correct": None,
                "clarified": output.get("stop_reason") == "needs_user",
                "reflection_status": output.get("reflection_status", "unknown"),
                "route": output.get("route", "unknown"),
                "intent": output.get("intent", "unknown"),
                "slot_summary": output.get("slot_summary", {}),
                "understanding_layer": output.get("understanding_layer", "unknown"),
                "extra_tool_calls": None,
                "model_calls": output.get("model_call_count"),
                "usage_missing_calls": output.get("usage_missing_calls", 0),
                "input_tokens": output.get("input_tokens", 0),
                "output_tokens": output.get("output_tokens", 0),
                "token_observed": "input_tokens" in output and "output_tokens" in output,
            }
        )
    result = aggregate(tasks)
    result.update(
        source_kind="metadata_traces",
        deduplicated_runs=len(runs),
        environment=environment or "all",
        token_scope="root cumulative counters only; may include conservative reservation when usage is missing",
    )
    return result


def aggregate(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinguish execution completion, verifier acceptance, and labeled task success."""
    n = len(tasks)
    if not n:
        raise ValueError("No matching Agent turns found")

    def labeled_rate(key: str) -> float | None:
        labeled = [task[key] for task in tasks if type(task.get(key)) is bool]
        return sum(labeled) / len(labeled) if labeled else None

    return {
        "n": n,
        "completed": sum(task["completed"] for task in tasks),
        "completion_rate": sum(task["completed"] for task in tasks) / n,
        "clarifications": sum(task["clarified"] for task in tasks),
        "clarification_rate": sum(task["clarified"] for task in tasks) / n,
        "task_success_rate": labeled_rate("task_success"),
        "fact_check_rate": labeled_rate("answer_correct"),
        "tool_chain_rate": labeled_rate("tool_correct"),
        "labeled_tasks": {
            key: sum(type(task.get(key)) is bool for task in tasks)
            for key in ("task_success", "answer_correct", "tool_correct")
        },
        "extra_tool_task_rate": sum(
            task.get("extra_tool_calls", 0) > 0 for task in tasks if type(task.get("extra_tool_calls")) is int
        )
        / n
        if all(type(task.get("extra_tool_calls")) is int for task in tasks)
        else None,
        "verifier_pass_rate": sum(
            task["reflection_status"] in ("passed", "rules_passed", "rules_empty") for task in tasks
        )
        / n,
        "reflection_statuses": dict(Counter(task["reflection_status"] for task in tasks)),
        "routes": dict(Counter(task["route"] for task in tasks)),
        "understanding_layers": dict(Counter(task.get("understanding_layer", "unknown") for task in tasks)),
        "clarification_intents": dict(Counter(task["intent"] for task in tasks if task["clarified"])),
        "missing_slot_patterns": dict(
            Counter(
                "+".join(sorted(task["slot_summary"].get("missing_slots", []))) or "unobserved"
                for task in tasks
                if task["clarified"]
            )
        ),
        "model_calls": sum(task["model_calls"] or 0 for task in tasks),
        "model_call_unknown_tasks": sum(task["model_calls"] is None for task in tasks),
        "input_tokens": sum(task["input_tokens"] for task in tasks),
        "output_tokens": sum(task["output_tokens"] for task in tasks),
        "token_unobserved_tasks": sum(not task["token_observed"] for task in tasks),
        "usage_missing_calls": sum(task["usage_missing_calls"] for task in tasks),
        "avg_model_calls": sum(task["model_calls"] or 0 for task in tasks) / n
        if all(task["model_calls"] is not None for task in tasks)
        else None,
        "avg_known_tokens": sum(task["input_tokens"] + task["output_tokens"] for task in tasks) / n,
    }


def analyze(directory: Path, environment: str | None = None) -> dict[str, Any]:
    """Select the input schema without using conversation text in the output."""
    rows = records(directory)
    return trial_report(rows) if rows and "case_id" in rows[0] else trace_report(rows, environment)


def markdown(result: dict[str, Any]) -> str:
    """Keep the report usable without exposing prompts, slot values, or identities."""

    def percentage(value: float | None) -> str:
        return "不可判定（无独立验收标签）" if value is None else f"{value:.1%}"

    lines = [
        "# Agent 基线回归统计",
        "",
        f"- 样本数：{result['n']}。",
        f"- 执行结束率：{percentage(result['completion_rate'])}。",
        f"- 严格任务成功率：{percentage(result['task_success_rate'])}。",
        f"- 关键事实通过率：{percentage(result['fact_check_rate'])}。",
        f"- 工具链正确率：{percentage(result['tool_chain_rate'])}。",
        f"- 多余工具调用任务占比：{percentage(result['extra_tool_task_rate'])}。",
        f"- 澄清率：{percentage(result['clarification_rate'])}（{result['clarifications']} 次）。",
        f"- 验证器通过占比：{percentage(result['verifier_pass_rate'])}；不能当作事实准确率。",
        f"- 可观察模型调用：{result['model_calls']}；调用数缺失任务 {result['model_call_unknown_tasks']}。",
        f"- 可观察输入/输出 Token：{result['input_tokens']}/{result['output_tokens']}；用量缺失调用 {result['usage_missing_calls']}；无 Token 观测任务 {result['token_unobserved_tasks']}。",
        "",
        "## 缺槽位聚类",
        "",
    ]
    lines.extend(f"- {key}：{value} 次。" for key, value in result["missing_slot_patterns"].items())
    lines += ["", "## 模型阶段", ""]
    lines.extend(
        f"- {name}：{stage['calls']} 次，输入/输出 Token {stage['input_tokens']}/{stage['output_tokens']}，用量缺失 {stage['usage_missing_calls']} 次。"
        for name, stage in result.get("stages", {}).items()
    )
    lines += [
        "",
        f"计量范围：{result['token_scope']}。",
        "",
        "元数据导出没有业务事实，不能独立还原任务正确率；旧导出没有槽位摘要时显示 unobserved。根节点累计 Token 只计算一次，缺失用量不能视为零成本。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    """Generate local reports and optional reproducible acceptance gates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--min-task-success", type=float)
    options = parser.parse_args()
    result = analyze(options.directory, options.environment)
    if options.baseline:
        previous = json.loads(options.baseline.read_text(encoding="utf-8"))
        result["baseline_delta"] = {
            key: result[key] - previous[key]
            for key in (
                "task_success_rate",
                "clarification_rate",
                "input_tokens",
                "output_tokens",
                "avg_model_calls",
                "avg_known_tokens",
            )
            if result.get(key) is not None and previous.get(key) is not None
        }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    options.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"n": result["n"], "output": str(options.output.with_suffix(".md"))}, ensure_ascii=True))
    if options.min_task_success is not None and (
        result["task_success_rate"] is None
        or result["task_success_rate"] < options.min_task_success
        or result["labeled_tasks"]["task_success"] != result["n"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
