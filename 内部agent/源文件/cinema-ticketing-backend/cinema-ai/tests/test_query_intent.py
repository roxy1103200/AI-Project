"""Semantic regression checks with a fixed Beijing date and deliberately wrong model plans."""

import unittest
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.intent import QuestionPlan, normalize_question, understand
from app.query_answers import movie_answer, screening_answer, valid_movie_result, valid_screening_result


class QueryIntentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = patch("app.intent.beijing_today", return_value=date(2026, 10, 8))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    async def test_showing_scheduled_and_bookable_are_independent(self) -> None:
        questions = [
            ("今天在排期的电影有哪些", "movies", "scheduled", "scheduled", False),
            ("上映中的电影有哪些", "movies", "showing", "bookable", False),
            ("今天哪些场次可以买票", "screenings", "catalog", "bookable", False),
            ("今天上映中且有排期的电影", "movies", "scheduled", "scheduled", True),
            ("今天放映哪些电影", "movies", "scheduled", "scheduled", False),
            ("《测试》今天有哪些场次", "screenings", "catalog", "scheduled", False),
        ]
        for question, intent, movie_scope, screening_scope, showing_only in questions:
            with self.subTest(question=question):
                plan = await understand(None, question, [])
                self.assertEqual(plan["intent"], intent)
                self.assertEqual(plan["entities"]["movie_scope"], movie_scope)
                self.assertEqual(plan["entities"]["screening_scope"], screening_scope)
                self.assertEqual(plan["entities"]["showing_only"], showing_only)
                self.assertFalse(plan["clarification"])

    async def test_unfiltered_lists_skip_model_calls(self) -> None:
        model = Mock()
        model.bind.side_effect = AssertionError("No model request for a deterministic list")
        for question in ("今天在排期的电影有哪些", "上映中的电影有哪些", "今天哪些场次可以买票"):
            result = await understand(model, question, [])
            self.assertEqual(result["intent_source"], "rules")
        model.bind.assert_not_called()
        result = await understand(model, "今天有哪些电影", [])
        self.assertTrue(result["clarification"])
        model.bind.assert_not_called()

    async def test_model_cannot_replace_semantics_date_title_or_add_invented_filters(self) -> None:
        model = Mock()
        payload = QuestionPlan(
            intent="movies",
            normalized_question="查上映电影",
            confidence=0.9,
            movie_scope="showing",
            screening_date="2001-01-01",
            movie_query="不存在的片名",
            cinema_query="虚构影院",
        ).model_dump_json()
        model.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
        plan = await understand(model, "《测试电影》今天在排期吗", [])
        self.assertEqual(plan["intent"], "movies")
        self.assertEqual(plan["entities"]["movie_scope"], "scheduled")
        self.assertEqual(plan["entities"]["screening_date"], "2026-10-08")
        self.assertEqual(plan["entities"]["movie_query"], "测试电影")
        self.assertEqual(plan["entities"]["cinema_query"], "")
        model.bind.return_value.ainvoke.return_value = SimpleNamespace(
            content=QuestionPlan(intent="movies", normalized_question="查电影", confidence=0.9).model_dump_json()
        )
        plan = await understand(model, "《测试电影》今天在排期吗", [])
        self.assertEqual(plan["entities"]["screening_date"], "2026-10-08")

    async def test_model_failure_keeps_explicit_business_constraints(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(side_effect=RuntimeError("fixture unavailable"))
        plan = await understand(model, "《测试电影》明天已排期的电影", [])
        self.assertEqual(plan["entities"]["movie_scope"], "scheduled")
        self.assertEqual(plan["entities"]["screening_date"], "2026-10-09")
        self.assertFalse(plan["clarification"])

    async def test_followups_keep_kind_title_date_and_pagination(self) -> None:
        history = [{"role": "user", "content": "《测试电影》今天有哪些场次可以买票"}]
        second = await understand(None, "那明天呢", history)
        self.assertEqual(second["entities"]["screening_scope"], "bookable")
        self.assertEqual(second["entities"]["movie_query"], "测试电影")
        self.assertEqual(second["entities"]["screening_date"], "2026-10-09")
        third = await understand(None, "那后天呢", history + [{"role": "user", "content": "那明天呢"}])
        self.assertEqual(third["entities"]["screening_date"], "2026-10-10")
        self.assertEqual(third["entities"]["movie_query"], "测试电影")
        history = [{"role": "user", "content": "《测试电影》今天已排期的电影"}]
        page = await understand(None, "第2页", history)
        self.assertEqual(page["entities"]["movie_scope"], "scheduled")
        self.assertEqual(page["entities"]["movie_query"], "测试电影")
        self.assertEqual(page["entities"]["screening_date"], "2026-10-08")
        self.assertEqual(page["entities"]["page"], 2)
        next_page = await understand(None, "下一页", history + [{"role": "user", "content": "第2页"}])
        self.assertEqual(next_page["entities"]["page"], 3)

    async def test_explicit_dates_are_validated_and_unqualified_lists_are_clarified(self) -> None:
        for text in ("2026-10-09排期电影", "2026/10/9排期电影", "10月9日排期电影"):
            self.assertEqual((await understand(None, text, []))["entities"]["screening_date"], "2026-10-09")
        self.assertTrue((await understand(None, "2026-02-30排期电影", []))["clarification"])
        self.assertTrue((await understand(None, "今天有哪些电影", []))["clarification"])
        self.assertEqual(normalize_question("《今天排期》排片"), "《今天排期》排期")

    async def test_seats_and_orders_are_not_reclassified_as_movie_lists(self) -> None:
        plan = await understand(None, "今天场次12还有哪些座位", [])
        self.assertEqual(plan["intent"], "seats")
        self.assertEqual(plan["entities"]["screening_id"], 12)
        plan = await understand(None, "OTEST12 今天能退票吗", [])
        self.assertEqual(plan["intent"], "refund")

    async def test_new_general_list_does_not_inherit_previous_title(self) -> None:
        history = [{"role": "user", "content": "《测试电影》今天在排期吗"}]
        result = await understand(None, "今天在排期的电影有哪些呢", history)
        self.assertEqual(result["entities"]["movie_query"], "")
        self.assertEqual(result["entities"]["screening_date"], "2026-10-08")

    async def test_weekdays_are_resolved_and_week_ranges_require_clarification(self) -> None:
        for text, day in (("本周三", "2026-10-07"), ("周三", "2026-10-14"), ("下周一", "2026-10-12")):
            plan = await understand(None, f"{text}已排期的电影有哪些", [])
            self.assertEqual(plan["entities"]["screening_date"], day)
        model = Mock()
        payload = QuestionPlan(
            intent="movies",
            movie_scope="scheduled",
            normalized_question="排期",
            confidence=0.9,
            screening_date="2026-10-09",
        ).model_dump_json()
        model.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
        self.assertTrue((await understand(model, "下周已排期的电影有哪些", []))["clarification"])

    async def test_title_words_do_not_change_intent_or_allow_invented_dates(self) -> None:
        model = Mock()
        payload = QuestionPlan(
            intent="movies",
            movie_scope="showing",
            normalized_question="上映",
            confidence=0.9,
            screening_date="2001-01-01",
        ).model_dump_json()
        model.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
        result = await understand(model, "《夏日幽灵》已排期吗", [])
        self.assertEqual(result["entities"]["movie_scope"], "scheduled")
        self.assertIsNone(result["entities"]["screening_date"])
        self.assertEqual(result["normalized_question"], "《夏日幽灵》已排期吗")
        result = await understand(None, "《上映排期退票》今天有哪些场次", [])
        self.assertEqual(result["intent"], "screenings")

    async def test_catalogue_questions_keep_scope_even_if_model_requests_showing(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(
            return_value=SimpleNamespace(
                content=QuestionPlan(
                    intent="movies", movie_scope="showing", normalized_question="上映电影", confidence=0.9
                ).model_dump_json()
            )
        )
        plan = await understand(model, "《测试电影》的导演是谁", [])
        self.assertEqual(plan["entities"]["movie_scope"], "catalog")


class QueryAnswerTests(unittest.TestCase):
    def test_screening_contract_rejects_changed_date_and_missing_facts(self) -> None:
        row = {
            "id": 1,
            "title": "测试",
            "start_time": "2026-10-08T18:00:00",
            "cinema_name": "影院",
            "hall_name": "厅",
            "price": 30,
        }
        entities = {"screening_date": "2026-10-08"}
        self.assertTrue(valid_screening_result([row], entities))
        self.assertTrue(valid_screening_result([], entities))
        self.assertFalse(valid_screening_result([{"id": 1, "title": "测试"}], entities))
        self.assertFalse(valid_screening_result([row], {"screening_date": "2026-10-09"}))
        self.assertFalse(valid_screening_result([{**row, "start_time": "2026-02-30T18:00:00"}], entities))

    def test_catalogue_answers_preserve_credits_and_description(self) -> None:
        answer = movie_answer([{"title": "测试", "director": "导演甲", "actors": "演员乙", "description": "简介内容"}])
        for fact in ("导演甲", "演员乙", "简介内容"):
            self.assertIn(fact, answer)

    def test_movie_contract_rejects_wrong_scope_date_and_unproven_schedule(self) -> None:
        entities = {"movie_scope": "scheduled", "screening_date": "2026-10-08"}
        data = {
            "movie_scope": "scheduled",
            "screening_date": "2026-10-08",
            "from_date": "2026-10-08",
            "time_zone": "Asia/Shanghai",
            "showing_only": False,
            "page": 1,
            "page_size": 20,
            "total": 1,
            "has_more": False,
            "items": [
                {
                    "id": 1,
                    "title": "测试",
                    "screening_count": 1,
                    "screenings": [
                        {
                            "id": 3,
                            "start_time": "2026-10-08T09:00:00",
                            "cinema_name": "影院",
                            "hall_name": "影厅",
                            "price": 30,
                        }
                    ],
                }
            ],
        }
        self.assertTrue(valid_movie_result(data, entities))
        self.assertFalse(valid_movie_result(data["items"], entities))
        for field, value in (("movie_scope", "showing"), ("screening_date", "2026-10-09"), ("time_zone", "UTC")):
            wrong = deepcopy(data)
            wrong[field] = value
            self.assertFalse(valid_movie_result(wrong, entities))
        wrong = deepcopy(data)
        wrong["items"][0]["screenings"][0]["start_time"] = "2026-10-09T09:00:00"
        self.assertFalse(valid_movie_result(wrong, entities))
        wrong["items"][0]["screenings"] = []
        self.assertFalse(valid_movie_result(wrong, entities))

    def test_empty_bookable_and_empty_scheduled_answers_are_distinct(self) -> None:
        self.assertIn(
            "当前可订购", screening_answer([], {"screening_scope": "bookable", "screening_date": "2026-10-08"})
        )
        self.assertNotIn("没有排期", screening_answer([], {"screening_scope": "bookable"}))
        self.assertIn("有效排期", screening_answer([], {"screening_scope": "scheduled"}))

    def test_movie_lists_use_backend_scope_count_page_and_actual_screenings(self) -> None:
        data = {
            "movie_scope": "scheduled",
            "screening_date": "2026-10-08",
            "from_date": "2026-10-08",
            "showing_only": False,
            "total": 21,
            "page": 2,
            "has_more": False,
            "items": [
                {
                    "id": 2,
                    "title": "预排电影",
                    "screening_count": 15,
                    "screenings_truncated": True,
                    "screenings": [
                        {
                            "id": 9,
                            "start_time": "2026-10-08T18:00:00",
                            "cinema_name": "测试影院",
                            "hall_name": "1号厅",
                            "price": 30,
                        }
                    ],
                }
            ],
        }
        answer = movie_answer(data)
        self.assertIn("共 21 部", answer)
        self.assertIn("第 2 页", answer)
        self.assertIn("有效排期", answer)
        self.assertNotIn("上映中的", answer)
        self.assertIn("场次 9", answer)
        self.assertIn("未全部展示", answer)
        data.update(movie_scope="showing", items=[], total=0)
        self.assertIn("上映中的电影", movie_answer(data))
        self.assertNotIn("没有排期", movie_answer(data))


if __name__ == "__main__":
    unittest.main()
