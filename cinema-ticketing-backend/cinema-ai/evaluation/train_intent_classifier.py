"""Train a local nine-intent classifier with scenario-isolated validation and test sets."""

import argparse
import hashlib
import importlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.intent_classifier import LABELS, classifier_text


def validate_corpus(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Reject semantic leakage and labels too sparse for independent validation."""
    partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    groups: dict[str, str] = {}
    questions: dict[str, str] = {}
    for row in rows:
        split, label, group = row.get("split"), row.get("intent"), row.get("scenario_id")
        if split not in ("train", "validation", "test") or label not in LABELS or not group:
            raise ValueError("Each sample requires split, one of nine intents, and scenario_id")
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError("Every sample requires nonempty question text")
        text = classifier_text(row["question"])
        if groups.setdefault(group, split) != split or questions.setdefault(text, split) != split:
            raise ValueError("A scenario or equivalent question spans training/validation/test")
        partitions[split].append(row)
    for split, minimum in (("train", 5), ("validation", 3), ("test", 3)):
        counts = Counter(label for label, _ in {(row["intent"], row["scenario_id"]) for row in partitions[split]})
        if any(counts[label] < minimum for label in LABELS):
            raise ValueError(f"Insufficient independent groups in {split}; need >= {minimum} per intent")
    return dict(partitions)


def reject_held_out(rows: list[dict[str, Any]], golden: Path) -> None:
    """Keep frozen acceptance and unreviewed feedback out of classifier training."""
    cases = json.loads(golden.read_text(encoding="utf-8"))
    questions = {classifier_text(case["question"]) for case in cases}
    groups = {case.get("source_case_id") for case in cases} - {None}
    if any(
        row.get("label_source") in ("frozen_independent_acceptance", "explicit_acceptance_definition")
        or classifier_text(row["question"]) in questions
        or row.get("scenario_id") in groups
        for row in rows
    ):
        raise ValueError("Corpus overlaps frozen golden acceptance; collect independent scenarios")
    if any(row.get("label_quality") == "silver" and row.get("review_status") != "reviewed" for row in rows):
        raise ValueError("Unreviewed feedback cannot become training labels")


def measure(model: Any, rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Evaluate accepted predictions, including per-class support and abstention."""
    accepted, correct = Counter(), Counter()
    total_correct = 0
    for row in rows:
        labels, probabilities = model.predict(classifier_text(row["question"]), k=1)
        label = labels[0].removeprefix("__label__")
        total_correct += label == row["intent"]
        if float(probabilities[0]) >= threshold:
            accepted[label] += 1
            correct[label] += label == row["intent"]
    count = sum(accepted.values())
    return {
        "n": len(rows),
        "accuracy": total_correct / len(rows),
        "accepted": count,
        "coverage": count / len(rows),
        "accepted_precision": sum(correct.values()) / count if count else None,
        "per_class": {label: {"accepted": accepted[label], "correct": correct[label]} for label in sorted(LABELS)},
    }


def deployment_gate(report: dict[str, Any]) -> bool:
    """Do not deploy a high confidence gate based on a handful of easy examples."""
    return bool(
        report["accepted"] >= 30
        and (report["accepted_precision"] or 0) >= 0.98
        and all(
            item["accepted"] >= 3 and item["correct"] / item["accepted"] >= 0.95
            for item in report["per_class"].values()
        )
    )


def main() -> None:
    """Train locally only after checking the complete, labeled split manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--held-out", type=Path, default=Path(__file__).parent / "golden/v1/cases.json")
    options = parser.parse_args()
    rows = [json.loads(line) for line in options.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    reject_held_out(rows, options.held_out)
    partitions = validate_corpus(rows)
    if options.audit_only:
        print(json.dumps({split: len(items) for split, items in partitions.items()}))
        return
    threshold = max(0.85, min(1.0, options.threshold))
    options.output.parent.mkdir(parents=True, exist_ok=True)
    training = options.output.with_suffix(".train.txt")
    training.write_text(
        "\n".join(f"__label__{row['intent']} {classifier_text(row['question'])}" for row in partitions["train"]) + "\n",
        encoding="utf-8",
    )
    fasttext = importlib.import_module("fasttext")
    model = fasttext.train_supervised(
        input=str(training), epoch=30, dim=32, wordNgrams=2, bucket=100000, thread=1, verbose=0
    )
    validation = measure(model, partitions["validation"], threshold)
    test = measure(model, partitions["test"], threshold)
    model.save_model(str(options.output))
    report = {
        "sha256": hashlib.sha256(options.output.read_bytes()).hexdigest(),
        "threshold": threshold,
        "corpus_sha256": hashlib.sha256(options.corpus.read_bytes()).hexdigest(),
        "validation": validation,
        "test": test,
        "deployment_approved": deployment_gate(validation) and deployment_gate(test),
    }
    options.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"deployment_approved": report["deployment_approved"]}))


if __name__ == "__main__":
    main()
