"""Check cloud-readback validation without credentials or network access."""

import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch("dotenv.load_dotenv"):
    from scripts.check_langsmith import SENTINEL, read_case


def stored_span(name: str, *, children: list | None = None, error: str | None = None) -> SimpleNamespace:
    """Provide the legacy SDK dict interface and a nested cloud span tree."""
    start = datetime.now(UTC)
    return SimpleNamespace(
        name=name,
        start_time=start,
        end_time=start + timedelta(milliseconds=12),
        child_runs=children or [],
        error=error,
        dict=lambda: {"name": name},
    )


class ReadbackTests(unittest.TestCase):
    """Guard recursive span discovery, legacy schema compatibility and privacy checks."""

    def setUp(self) -> None:
        nodes = [stored_span(name) for name in ("prepare", "respond")]
        nodes += [stored_span("agent", children=[stored_span("FakeListChatModel")])]
        nodes += [stored_span("tools", children=[stored_span("tool.search_movies")])]
        self.run = stored_span("cinema.agent.verify_success", children=[stored_span("LangGraph", children=nodes)])
        self.tracing = SimpleNamespace(client=SimpleNamespace(read_run=Mock(return_value=self.run)))

    def test_reads_nested_model_and_tool_spans_using_legacy_sdk_schema(self) -> None:
        result = read_case(self.tracing, "synthetic-id", False)
        self.assertEqual(result["span_count"], 8)
        self.assertFalse(result["private_text_uploaded"])
        self.assertTrue(all(item["duration"] == 12 for item in result["timings_ms"]))

    def test_rejects_missing_error_on_failed_answer(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected error code"):
            read_case(self.tracing, "synthetic-id", True)
        self.run.error = "business_unavailable"
        self.assertEqual(read_case(self.tracing, "synthetic-id", True)["outcome"], "failed")

    def test_rejects_private_diagnostic_content_in_cloud_record(self) -> None:
        self.run.dict = lambda: {"private": SENTINEL}
        with self.assertRaisesRegex(RuntimeError, "Private diagnostic text"):
            read_case(self.tracing, "synthetic-id", False)
