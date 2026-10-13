"""Compare pinned A/B exports; unlabelled live completion is not task accuracy."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evaluation.eval_traces import records, trace_report, trial_report
from evaluation.metrics import percentile


def report(rows: list[dict[str, Any]], environment: str | None = None) -> dict[str, Any]:
    """Keep variants, versions, stage token usage and independent scores visible."""
    scored = bool(rows and "case_id" in rows[0])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if scored:
        for row in rows:
            version = row.get("runtime_version", {})
            variant = version.get("experiment_variant")
            if variant in ("A", "B"):
                groups[variant].append(row)
    else:
        # Merge duplicate exports before grouping; child spans are not turns.
        merged: dict[str, dict[str, Any]] = {}
        for row in sorted(rows, key=lambda item: str(item.get("recorded_at", ""))):
            identity = row.get("run_id") or row.get("id")
            if not identity:
                continue
            saved = merged.setdefault(identity, {})
            saved.update(
                {key: value for key, value in row.items() if value is not None and key not in ("outputs", "metadata")}
            )
            saved["outputs"] = {**saved.get("outputs", {}), **(row.get("outputs") or {})}
            saved["metadata"] = {**saved.get("metadata", {}), **(row.get("metadata") or {})}
        for row in merged.values():
            variant = row.get("outputs", {}).get("runtime_version", {}).get("experiment_variant")
            if (
                not row.get("parent_run_id")
                and str(row.get("name", "")).startswith("cinema.agent.")
                and variant in ("A", "B")
                and (not environment or row.get("metadata", {}).get("environment") == environment)
            ):
                groups[variant].append(row)
    if not groups:
        raise ValueError("No A/B version labels found; old traces cannot be retroactively assigned")
    result = {"scope": "scored trials" if scored else "unlabelled live telemetry; accuracy unavailable", "variants": {}}
    for variant, selected in sorted(groups.items()):
        summary = trial_report(selected) if scored else trace_report(selected)
        versions = [row.get("runtime_version", {}) if scored else row["outputs"]["runtime_version"] for row in selected]
        summary["version_fingerprints"] = dict(
            Counter(
                f"{v.get('experiment_id')}:{v.get('prompt_hash')}:{v.get('rules_hash')}:{v.get('configuration_hash')}"
                for v in versions
            )
        )
        if len(summary["version_fingerprints"]) != 1:
            raise ValueError(f"Variant {variant} mixes version fingerprints; select one deployment cohort")
        summary["l1_statuses"] = dict(
            Counter((row if scored else row["outputs"]).get("l1_status", "unknown") for row in selected)
        )
        summary["l1_accept_rate"] = summary["l1_statuses"].get("accepted", 0) / len(selected)
        if scored:
            summary["by_style"] = {
                style: trial_report([row for row in selected if (row.get("phrasing_style") or "unknown") == style])
                for style in sorted({(row.get("phrasing_style") or "unknown") for row in selected})
            }
            summary["by_intent"] = {
                intent: trial_report([row for row in selected if (row.get("expected_intent") or "unknown") == intent])
                for intent in sorted({(row.get("expected_intent") or "unknown") for row in selected})
            }
        durations = [row["total_ms"] for row in selected if scored and row.get("total_ms") is not None]
        first = [row["ttft_ms"] for row in selected if scored and row.get("ttft_ms") is not None]
        summary.update(
            total_p50_ms=percentile(durations, 0.5),
            total_p95_ms=percentile(durations, 0.95),
            ttft_p50_ms=percentile(first, 0.5),
            ttft_p95_ms=percentile(first, 0.95),
        )
        result["variants"][variant] = summary
    if scored and set(groups) == {"A", "B"}:
        ids = [{(row["case_id"], row.get("repetition")) for row in groups[variant]} for variant in ("A", "B")]
        result["paired_case_rounds"] = len(ids[0] & ids[1])
        result["same_case_rounds"] = ids[0] == ids[1]
    if set(groups) == {"A", "B"}:
        fingerprints = [set(result["variants"][arm]["version_fingerprints"]) for arm in ("A", "B")]
        if fingerprints[0] != fingerprints[1]:
            raise ValueError("A/B versions differ beyond experiment arm; use the same pinned deployment")
    result["warning"] = (
        "Do not pool changed fingerprints, infer business accuracy from completion, or call missing usage free. Online groups may have different case mix."
    )
    return result


def markdown(result: dict[str, Any]) -> str:
    """Produce a readable Markdown artifact with explicit metric scope."""
    lines = ["# Agent A/B 对比", "", f"范围：{result['scope']}", ""]
    for variant, summary in result["variants"].items():
        success = summary["task_success_rate"]
        value = f"{success:.1%}" if success is not None else "不可判定（无独立标签）"
        lines += [
            f"## {variant} 组",
            "",
            f"- 样本 {summary['n']}；任务成功率 {value}。",
            f"- 事实正确率 {summary['fact_check_rate']}；工具链正确率 {summary['tool_chain_rate']}；多余调用任务比例 {summary['extra_tool_task_rate']}（null 表示无独立标签）。",
            f"- 澄清率 {summary['clarification_rate']:.1%}；平均模型调用 {summary['avg_model_calls']}。",
            f"- 输入/输出 Token {summary['input_tokens']}/{summary['output_tokens']}；缺失用量调用 {summary['usage_missing_calls']}。",
            f"- L1 状态：{json.dumps(summary['l1_statuses'], ensure_ascii=False)}。",
            f"- 首字 P50/P95：{summary['ttft_p50_ms']}/{summary['ttft_p95_ms']} ms；完整回答 P50/P95：{summary['total_p50_ms']}/{summary['total_p95_ms']} ms。",
            "",
        ]
    lines += ["同一版本指纹内比较；线上流量需控制意图与问题风格分布。验证器通过率、结束率不能替代准确率。", ""]
    return "\n".join(lines)


def main() -> None:
    """Read one or more export paths, write JSON and Markdown without model calls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--environment", help="Filter metadata traces by deployment environment")
    options = parser.parse_args()
    for directory in options.directories:
        metadata = (directory if directory.is_dir() else directory.parent) / "metadata.json"
        if metadata.exists():
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("data_unchanged") is False or saved.get("deployment_unchanged") is False:
                raise ValueError("A/B acceptance invalid: business facts or measured source changed during evaluation")
    result = report([row for directory in options.directories for row in records(directory)], options.environment)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    options.output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(json.dumps({"groups": {key: value["n"] for key, value in result["variants"].items()}}))


if __name__ == "__main__":
    main()
