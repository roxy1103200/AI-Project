"""Private diagnostics retain only typed, nonsecret evaluation fields."""

import unittest
from app.runtime_info import safe_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_unknown_fields_and_bad_counts_are_removed(self):
        value = safe_diagnostics(
            {
                "token": "secret",
                "model_call_count": True,
                "tool_call_count": 2,
                "token_usage": {"input_tokens": 12, "api_key": "secret", "total_tokens": -1},
            }
        )
        self.assertEqual(value, {"tool_call_count": 2, "token_usage": {"input_tokens": 12}})

    def test_date_objects_keep_no_raw_expression(self):
        packet = {
            "temporal_summary": {
                "reference_date": "2026-10-17",
                "time_zone": "Asia/Shanghai",
                "windows": [
                    {
                        "target": "release",
                        "status": "resolved",
                        "date_from": "2026-10-11",
                        "date_to": "2026-10-17",
                        "expression": "PRIVATE",
                    }
                ],
            }
        }
        result = safe_diagnostics(packet)
        self.assertNotIn("expression", result["temporal_summary"]["windows"][0])
        self.assertNotIn("PRIVATE", str(result))
