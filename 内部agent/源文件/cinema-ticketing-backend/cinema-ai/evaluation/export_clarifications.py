"""Export local deidentified slot feedback without invoking a model or training it."""

import argparse
import json
from contextlib import closing
from pathlib import Path

from app.clarification_feedback import DEFAULT_PATH, ClarificationFeedback


def main() -> None:
    """Keep weak labels separate from reviewed training data and frozen gold."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-only", action="store_true")
    parser.add_argument("--approve", action="append", default=[], help="Explicitly reviewed candidate ID; repeatable")
    options = parser.parse_args()
    with closing(ClarificationFeedback(options.database).connect()) as connection, connection:
        for identity in options.approve:
            if (
                connection.execute("UPDATE candidates SET review_status='reviewed' WHERE id=?", (identity,)).rowcount
                != 1
            ):
                raise ValueError("Unknown candidate ID")
        rows = connection.execute(
            "SELECT payload,occurrences,review_status FROM candidates ORDER BY created"
        ).fetchall()
    output = []
    for row in rows:
        if options.reviewed_only and row["review_status"] != "reviewed":
            continue
        candidate = json.loads(row["payload"])
        candidate.update(occurrences=row["occurrences"], review_status=row["review_status"])
        output.append(candidate)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output), encoding="utf-8")
    print(json.dumps({"exported": len(output), "reviewed_only": options.reviewed_only}))


if __name__ == "__main__":
    main()
