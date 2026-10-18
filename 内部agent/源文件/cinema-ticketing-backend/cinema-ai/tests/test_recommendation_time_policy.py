"""Recommendation time policy v2: independent dates, parameters and reply assertions."""

import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

from app.intent import rule_plan, understand
from app.query_answers import recommendation_answer, screening_answer, valid_release_result
from app.react_agent import initial_state
from app.react_tools import validate_arguments
from app.failures import CinemaQueryError
from app.task_progress import build_tasks
from app.time_normalization import references_recommendations


TODAY = date(2026, 10, 17)
QUESTION = "给我推荐最近一周的电影"


class RecommendationTimePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        clock = patch("app.intent.beijing_today", return_value=TODAY)
        clock.start()
        self.addCleanup(clock.stop)
        settings = patch.dict("os.environ", {"AGENT_L0_ENABLED": "true", "GLM_L1_ENABLED": "false"})
        settings.start()
        self.addCleanup(settings.stop)

    async def plan(self, question: str, history: list[dict] | None = None) -> dict:
        return await understand(None, question, history or [])

    async def history(self, question: str = QUESTION) -> list[dict]:
        plan = await self.plan(question)
        return [
            {"role": "user", "content": question},
            {"role": "assistant", "content": recommendation_answer([], plan["entities"])},
        ]

    async def test_a01_a04_direct_recommendation_keeps_both_normalization_stages(self) -> None:
        for question in (QUESTION, "给我推荐最近一周的悬疑电影", "帮我推荐最近7天的电影", "最近一周有啥电影推荐一下"):
            with self.subTest(question=question):
                rules = rule_plan(question, [], TODAY)
                result = await self.plan(question)
                self.assertFalse(result["clarification"])
                self.assertEqual(result["intent"], "recommend")
                self.assertEqual(result["understanding_layer"], "l0")
                self.assertEqual(rules.temporal.model_dump(), result["entities"]["temporal"])
                self.assertEqual(result["entities"]["release_date_from"], "2026-10-11")
                self.assertEqual(result["entities"]["release_date_to"], "2026-10-17")
                self.assertTrue(result["entities"]["temporal"]["windows"][0]["assumed_target"])
                self.assertIsNone(result["entities"]["screening_date_from"])
                state = {**initial_state(1, "policy", question, []), **result}
                tasks = build_tasks(state)
                self.assertEqual([task["name"] for task in tasks], ["recommend_movies"])
                self.assertEqual(tasks[0]["arguments"]["preference"], "悬疑" if "悬疑" in question else "")

    async def test_a05_a09_explicit_time_meaning_wins(self) -> None:
        for question, target, start, end in (
            ("推荐最近一周上映的电影", "release", "2026-10-11", "2026-10-17"),
            ("推荐本周上映的悬疑电影", "release", "2026-10-12", "2026-10-18"),
            ("推荐这周有票的悬疑电影", "screening", "2026-10-12", "2026-10-18"),
            ("推荐今晚能买票的悬疑电影", "screening", "2026-10-17", "2026-10-17"),
        ):
            with self.subTest(question=question):
                result = await self.plan(question)
                self.assertFalse(result["clarification"])
                window = result["temporal_summary"]["windows"][0]
                self.assertEqual((window["target"], window["date_from"], window["date_to"]), (target, start, end))
                self.assertFalse(window["assumed_target"])
        both = await self.plan("推荐最近一周上映、今晚能买票的悬疑电影")
        self.assertEqual({w["target"] for w in both["temporal_summary"]["windows"]}, {"release", "screening"})
        self.assertFalse(both["clarification"])
        state = {**initial_state(1, "policy", "推荐最近一周上映、今晚能买票的悬疑电影", []), **both}
        state["tasks"] = build_tasks(state)
        args = validate_arguments("recommend_movies", {}, state)
        self.assertEqual(args["release_date_from"], "2026-10-11")
        self.assertEqual(args["screening_date_from"], "2026-10-17")
        self.assertEqual(args["screening_hour_from"], 18)

    async def test_p01_p03_soft_and_hard_dates(self) -> None:
        for question, preferred in (
            ("推荐悬疑电影，最好是最近一周的", True),
            ("只推荐最近一周上映的悬疑电影", False),
            ("最好推荐悬疑电影，但上映日期必须在最近一周", False),
        ):
            with self.subTest(question=question):
                result = await self.plan(question)
                self.assertFalse(result["clarification"])
                self.assertEqual(result["entities"]["release_date_preferred"], preferred)
                state = {**initial_state(1, "policy", question, []), **result}
                self.assertEqual([task["name"] for task in build_tasks(state)], ["recommend_movies"])

    async def test_p04_p07_and_b01_b02_necessary_clarifications_remain(self) -> None:
        for question in (
            "这周的悬疑题材电影有哪部",
            "推荐下周的电影",
            "查一下座位",
            "我的订单能退吗",
            "推荐2026年2月30日上映的电影",
            "只要2026年10月11日至17日上映，同时必须2026年10月18日至24日上映的电影",
        ):
            with self.subTest(question=question):
                result = await self.plan(question)
                self.assertTrue(result["clarification"])
                state = {**initial_state(1, "policy", question, []), **result}
                self.assertEqual(build_tasks(state), [])

    async def test_p08_explicit_genre_never_becomes_a_date(self) -> None:
        result = await self.plan("推荐最近一周的科幻电影")
        self.assertFalse(result["clarification"])
        self.assertEqual(result["entities"]["preference"], "科幻")

    async def test_c01_c02_corrections_replace_assumed_release_filter(self) -> None:
        history = await self.history("给我推荐最近一周的悬疑电影")
        for question, start, end, scope in (
            ("我是说按观影日期", "2026-10-11", "2026-10-17", "scheduled"),
            ("我是说这周有票的", "2026-10-12", "2026-10-18", "bookable"),
        ):
            with self.subTest(question=question):
                result = await self.plan(question, history)
                self.assertFalse(result["clarification"])
                entities = result["entities"]
                self.assertIsNone(entities["release_date_from"])
                self.assertEqual(entities["screening_date_from"], start)
                self.assertEqual(entities["screening_date_to"], end)
                self.assertEqual(entities["screening_scope"], scope)
                self.assertEqual(entities["preference"], "悬疑")

    async def test_c03_c04_followups_inherit_time_target_and_genre(self) -> None:
        for first, target in (("推荐最近一周的悬疑电影", "release"), ("推荐这周有票的悬疑电影", "screening")):
            result = await self.plan("那下周呢", await self.history(first))
            self.assertFalse(result["clarification"])
            self.assertEqual(result["entities"][f"{target}_date_from"], "2026-10-19")
            self.assertEqual(result["entities"][f"{target}_date_to"], "2026-10-25")
            self.assertEqual(result["entities"]["preference"], "悬疑")

    async def test_c05_candidates_are_preserved_without_inventing_ids(self) -> None:
        self.assertFalse(references_recommendations("这些电影的导演是谁"))
        history = await self.history("推荐最近一周的悬疑电影")
        history[-1]["content"] += "\n• 测试甲｜悬疑｜上映日期：2026-10-17\n• 测试乙｜悬疑｜上映日期：2026-10-16"
        question = "这些电影今晚有票吗"
        result = await self.plan(question, history)
        self.assertFalse(result["clarification"])
        state = {**initial_state(1, "policy", question, history), **result}
        tasks = build_tasks(state)
        self.assertEqual([t["name"] for t in tasks], ["search_screenings", "search_screenings"])
        self.assertEqual({t["arguments"]["movie_query"] for t in tasks}, {"测试甲", "测试乙"})
        self.assertTrue(all(t["arguments"]["screening_date"] == "2026-10-17" for t in tasks))
        state["tasks"] = tasks
        for task in tasks:
            self.assertEqual(
                validate_arguments("search_screenings", task["arguments"], state)["movie_query"],
                task["arguments"]["movie_query"],
            )
        with self.assertRaises(CinemaQueryError):
            validate_arguments("search_screenings", {"movie_query": "悬疑"}, state)
        empty = screening_answer([], {**result["entities"], "movie_query": "测试乙"})
        self.assertIn("《测试乙》", empty)
        self.assertIn("没有符合条件", empty)

    async def test_c06_c10_genre_change_keeps_displayed_dates_across_midnight(self) -> None:
        history = await self.history("推荐最近一周的悬疑电影")
        with patch("app.intent.beijing_today", return_value=date(2026, 10, 18)):
            result = await self.plan("换成科幻的", history)
            self.assertFalse(result["clarification"])
            self.assertEqual(result["entities"]["release_date_from"], "2026-10-11")
            self.assertEqual(result["entities"]["release_date_to"], "2026-10-17")
            self.assertEqual(result["entities"]["preference"], "科幻")
            refreshed = await self.plan("还是最近一周，换成科幻", history)
            self.assertEqual(refreshed["entities"]["release_date_from"], "2026-10-12")
            self.assertEqual(refreshed["entities"]["release_date_to"], "2026-10-18")

    async def test_c07_c08_daypart_and_empty_history(self) -> None:
        history = [
            {"role": "user", "content": "明天《回归悬疑新片》有哪些场次"},
            {"role": "assistant", "content": "查询结果"},
        ]
        result = await self.plan("晚上呢", history)
        self.assertEqual(result["entities"]["screening_date"], "2026-10-18")
        self.assertEqual(result["entities"]["screening_hour_from"], 18)
        fresh = await self.plan("那下周呢")
        self.assertTrue(fresh["clarification"])
        self.assertEqual(fresh["entities"]["preference"], "")

    async def test_b03_b05_calendar_boundaries(self) -> None:
        for day, start in (
            (date(2026, 11, 2), "2026-10-27"),
            (date(2027, 1, 3), "2026-12-28"),
            (date(2028, 3, 2), "2028-02-25"),
        ):
            with self.subTest(day=day), patch("app.intent.beijing_today", return_value=day):
                result = await self.plan(QUESTION)
                self.assertEqual(result["entities"]["release_date_from"], start)
                self.assertEqual(result["entities"]["release_date_to"], day.isoformat())

    async def test_b06_b07_a10_dates_results_and_default_wording(self) -> None:
        entities = (await self.plan(QUESTION))["entities"]
        rows = [{"id": 1, "title": "无场次新片", "genre": "喜剧", "release_date": "2026-10-11"}]
        self.assertTrue(valid_release_result(rows, entities))
        self.assertTrue(valid_release_result([{**rows[0], "release_date": "2026-10-17"}], entities))
        for release in (None, "2026-10-10", "2026-10-18"):
            self.assertFalse(valid_release_result([{**rows[0], "release_date": release}], entities))
        answer = recommendation_answer(rows, entities)
        self.assertIn("我先按", answer)
        self.assertNotIn("已确认", answer)
        self.assertNotIn("可订购", answer)
        self.assertIn("无场次新片", answer)
        self.assertIn("没有查到", recommendation_answer([], entities))
        soft = (await self.plan("推荐悬疑电影，最好是最近一周的"))["entities"]
        older = [{**rows[0], "release_date": "2026-10-10", "matches_release_window": False}]
        self.assertTrue(valid_release_result(older, soft))
        self.assertIn("超出优先日期范围", recommendation_answer(older, soft))

    async def test_b08_title_is_not_a_time_expression(self) -> None:
        result = await self.plan("《最近一周》的导演是谁")
        self.assertEqual(result["temporal_summary"]["windows"], [])

    async def test_simple_default_does_not_invoke_understanding_model(self) -> None:
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(side_effect=AssertionError("unnecessary understanding"))
        result = await understand(model, QUESTION, [])
        model.bind.assert_not_called()
        self.assertFalse(result["clarification"])

    async def test_c09_missing_recommendation_context_never_broadens_to_all_movies(self) -> None:
        model = Mock()
        result = await understand(model, "这些电影今晚有票吗", [])
        model.bind.assert_not_called()
        self.assertEqual(result["preflight_reason"], "missing_recommendation_context")
        self.assertIn("片名", result["clarification"])
        state = {**initial_state(2, "new-account", "这些电影今晚有票吗", []), **result}
        self.assertEqual(build_tasks(state), [])
