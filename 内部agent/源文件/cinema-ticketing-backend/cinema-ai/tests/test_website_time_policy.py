"""Test the independent website scorer, including deliberately incorrect observations."""

import copy
import unittest

from evaluation.website_cases import CASES as V1_CASES
from evaluation.website_cases_v2 import CASES as V2_CASES
from evaluation.website_time_policy import movie_date, score_time_policy


class WebsiteTimePolicyScoringTests(unittest.TestCase):
    def row(self) -> dict:
        return {
            "check": "rt:default",
            "reference_date": "2026-10-17",
            "answer": "按上映日期筛选：2026-10-11 至 2026-10-17（北京时间）。\n我先按上述上映日期范围推荐。\n• 夹具影片｜喜剧｜上映日期：2026-10-11",
            "record": {
                "context": {
                    "tool_calls": ["recommend_movies"],
                    "temporal_summary": {
                        "windows": [
                            {
                                "target": "release",
                                "date_from": "2026-10-11",
                                "date_to": "2026-10-17",
                                "status": "resolved",
                                "strength": "hard",
                                "assumed_target": True,
                            }
                        ]
                    },
                }
            },
            "evidence": {
                "java": {
                    "calls": [
                        {"status": 200, "parameters": {"releaseDateFrom": "2026-10-11", "releaseDateTo": "2026-10-17"}}
                    ]
                }
            },
            "fixture": {
                "movies": [
                    {"id": 1, "title": "夹具影片", "genre": "喜剧", "status": "ON_SHOW", "release_date": "2026-10-11"}
                ]
            },
        }

    def test_correct_facts_pass_and_wrong_answers_fail(self) -> None:
        row = self.row()
        self.assertEqual(score_time_policy(row), [])
        for mutation in ("wrong_title", "wrong_date", "invented_confirmation", "extra_screening", "repeated_query"):
            broken = copy.deepcopy(row)
            if mutation == "wrong_title":
                broken["answer"] = broken["answer"].replace("夹具影片", "编造影片")
            elif mutation == "wrong_date":
                broken["evidence"]["java"]["calls"][0]["parameters"]["releaseDateFrom"] = "2026-10-12"
            elif mutation == "invented_confirmation":
                broken["answer"] = broken["answer"].replace("我先按", "已确认")
            elif mutation == "extra_screening":
                broken["evidence"]["java"]["calls"][0]["parameters"]["screeningDate"] = "2026-10-17"
            else:
                broken["record"]["context"]["tool_calls"].append("recommend_movies")
            with self.subTest(mutation=mutation):
                self.assertTrue(score_time_policy(broken))

    def test_fixture_change_is_not_accepted_as_a_valid_answer(self) -> None:
        row = self.row()
        row["fixture"]["movies"][0]["release_date"] = "2026-10-10"
        self.assertTrue(score_time_policy(row))

    def test_null_optional_fields_are_not_active_filters(self) -> None:
        row = self.row()
        row["evidence"]["java"]["calls"][0]["parameters"]["screeningDateFrom"] = "null"
        self.assertEqual(score_time_policy(row), [])

    def test_java_sql_dates_and_null_are_supported(self) -> None:
        self.assertEqual(movie_date(1792166400000), "2026-10-17")
        self.assertEqual(movie_date(None), "")

    def test_v1_is_preserved_and_only_d05_baseline_expectation_changes(self) -> None:
        self.assertEqual(len(V1_CASES), 32)
        self.assertEqual(len({case.id for case in V2_CASES}), len(V2_CASES))
        original = {case.id: case for case in V1_CASES}
        for case in V2_CASES:
            if case.id in original and case.id != "D05":
                self.assertEqual(case, original[case.id])
        self.assertEqual(original["D05"].turns[0].check, "clarify")
        self.assertEqual(next(case for case in V2_CASES if case.id == "D05").turns[0].check, "rt:soft")
