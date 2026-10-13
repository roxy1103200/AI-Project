"""Optional local fastText classifier; confidence never authorizes entity guesses."""

import hashlib
import importlib
import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

LABELS = frozenset({"chat", "movies", "screenings", "seats", "order", "refund", "policy", "recommend", "unsupported"})
LOGGER = logging.getLogger("uvicorn.error")


def classifier_text(question: str) -> str:
    """Match training preprocessing and avoid memorizing concrete order identifiers."""
    text = re.sub(r"(?<![A-Za-z0-9])[Oo][A-Za-z0-9]{5,63}(?![A-Za-z0-9])", " order_id ", question)
    text = re.sub(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", " date_value ", text)
    return " ".join(text.replace("\n", " ").lower())


@lru_cache(maxsize=2)
def load_classifier(path: str, modified: tuple[int, int]) -> Any:
    """Load only a locally validated artifact matching its evaluation manifest."""
    del modified
    artifact = Path(path)
    manifest = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Classifier manifest must be an object")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if manifest.get("sha256") != digest or manifest.get("deployment_approved") is not True:
        raise ValueError("Classifier artifact has not passed its independent validation gate")
    threshold = float(manifest["threshold"])
    if not math.isfinite(threshold) or not 0.85 <= threshold <= 1:
        raise ValueError("Classifier threshold must be validated in [0.85, 1]")
    model = importlib.import_module("fasttext").load_model(str(artifact))
    if {label.removeprefix("__label__") for label in model.labels} != LABELS:
        raise ValueError("Classifier must contain exactly nine intent labels")
    return model, threshold


def predict_intent(question: str) -> tuple[str, float] | None:
    """Fail back to the LLM on disabled, missing, invalid, or low confidence models."""
    if os.getenv("INTENT_L1_ENABLED", "false").lower() != "true":
        return None
    path = Path(os.getenv("INTENT_L1_MODEL_PATH", "data/models/intent.bin"))
    try:
        modified = (path.stat().st_mtime_ns, path.with_suffix(".json").stat().st_mtime_ns)
        model, validated_threshold = load_classifier(str(path.resolve()), modified)
        labels, probabilities = model.predict(classifier_text(question), k=1)
        intent, confidence = labels[0].removeprefix("__label__"), float(probabilities[0])
        threshold = max(validated_threshold, min(1.0, float(os.getenv("INTENT_L1_THRESHOLD", "0.85"))))
        return (
            (intent, confidence)
            if intent in LABELS and math.isfinite(confidence) and threshold <= confidence <= 1
            else None
        )
    except (OSError, ValueError, ImportError, RuntimeError, IndexError, TypeError, KeyError):
        LOGGER.warning("Local intent classifier unavailable; escalating to structured understanding")
        return None
