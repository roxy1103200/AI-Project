"""Fixed-date regressions for relative dates, routing, tool grounding and replies."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.failures import CinemaQueryError
from app.intent import QuestionPlan, understand
from app.query_answers import recommendation_answer, valid_screening_result
from app.react_agent import CinemaReAct, initial_state
from app.react_tools import validate_arguments, validate_result
from app.task_progress import build_tasks
from app.time_normalization import normalize_times
from app.tracing import summarize_payload

TODAY = date(2026, 10, 13)
QUESTION = "你给我推荐悬疑题材的电影，最好是最近一周的电影，然后给我明确的时间信息"


class RelativeTimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clock = patch("app.intent.beijing_today", return_value=TODAY)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        environment = patch.dict(
            "os.environ",
            {
                "AGENT_L0_ENABLED": "true",
                "GLM_L1_ENABLED": "false",
                "LANGSMITH_TRACING": "false",
                "CLARIFICATION_FEEDBACK_ENABLED": "false",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

    async def state(self, question: str, history: list[dict[str, str]] | None = None) -> dict:
        history = history or []
        plan = await understand(None, question, history)
        state = {**initial_state(1, "relative-time", question, history), **plan}
        state["tasks"] = build_tasks(state)
        return state

    async def test_original_question_becomes_one_grounded_recommendation(self) -> None:
        state = await self.state(QUESTION)
        self.assertEqual(state["intent"], "recommend")
        self.assertEqual(state["clarification"], "")
        self.assertEqual(len(state["tasks"]), 1)
        arguments = validate_arguments("recommend_movies", {}, state)
        self.assertEqual(
            arguments,
            {
                "preference": "悬疑",
                "release_date_from": "2026-10-07",
                "release_date_to": "2026-10-13",
                "release_date_preferred": True,
            },
        )
        self.assertIsNone(state["entities"]["screening_date"])
        with self.assertRaises(CinemaQueryError):
            validate_arguments("recommend_movies", {"release_date_from": "2026-01-01"}, state)
        with self.assertRaises(CinemaQueryError):
            validate_arguments("ask_user", {"question": "请提供具体日期"}, state)

    async def test_hard_and_soft_conditions_produce_different_validation_and_answers(self) -> None:
        rows = [
            {"title": "区间内电影", "genre": "悬疑", "release_date": "2026-10-07", "matches_release_window": True},
            {"title": "补充电影", "genre": "悬疑", "release_date": "2026-09-30", "matches_release_window": False},
        ]
        soft = await self.state(QUESTION)
        arguments = validate_arguments("recommend_movies", {}, soft)
        validate_result("recommend_movies", rows, arguments, user_id=1)
        answer = recommendation_answer(rows, soft["entities"])
        self.assertIn("2026-10-07 至 2026-10-13", answer)
        self.assertIn("超出优先日期范围", answer)
        hard = await self.state("推荐悬疑电影，必须是最近一周上映的")
        with self.assertRaises(CinemaQueryError):
            validate_result("recommend_movies", rows, validate_arguments("recommend_movies", {}, hard), user_id=1)

    async def test_week_and_month_ranges_are_queryable(self) -> None:
        for phrase, start, end in (
            ("上周", "2026-10-05", "2026-10-11"),
            ("本周", "2026-10-12", "2026-10-18"),
            ("下周末", "2026-10-24", "2026-10-25"),
            ("下个月", "2026-11-01", "2026-11-30"),
            ("明天到后天", "2026-10-14", "2026-10-15"),
        ):
            with self.subTest(phrase=phrase):
                state = await self.state(f"《测试电影》{phrase}有哪些场次")
                self.assertFalse(state["clarification"])
                self.assertEqual(state["entities"]["screening_date_from"], start)
                self.assertEqual(state["entities"]["screening_date_to"], end)
                arguments = validate_arguments("search_screenings", {}, state)
                self.assertEqual(arguments["screening_date_to"], end)

    async def test_releasing_this_week_does_not_mean_screenings_this_week(self) -> None:
        release = await self.state("推荐本周上映的悬疑电影")
        self.assertEqual(release["entities"]["release_date_to"], "2026-10-13")
        screening = await self.state("本周有哪些场次")
        self.assertEqual(screening["entities"]["screening_date_to"], "2026-10-18")
        listing = await self.state("未来一周上映的电影有哪些")
        self.assertEqual(listing["entities"]["movie_scope"], "catalog")
        self.assertEqual(listing["entities"]["release_date_to"], "2026-10-19")

    async def test_followup_inherits_target_and_film_but_replaces_interval(self) -> None:
        history = [{"role": "user", "content": "《测试电影》本周有哪些场次"}]
        followup = await self.state("那下周呢", history)
        self.assertEqual(followup["entities"]["movie_query"], "测试电影")
        self.assertEqual(followup["entities"]["screening_date_from"], "2026-10-19")
        history = [{"role": "user", "content": "推荐最近一周上映的悬疑电影"}]
        followup = await self.state("那上个月呢", history)
        self.assertEqual(followup["intent"], "recommend")
        self.assertEqual(followup["entities"]["preference"], "悬疑")
        self.assertEqual(followup["entities"]["release_date_from"], "2026-09-01")

    async def test_invalid_vague_and_conflicting_dates_are_not_broadened(self) -> None:
        for question in (
            "2026-02-30有哪些场次",
            "最近有哪些场次",
            "过几天有哪些场次",
            "2026-10-10和2026-10-12有哪些场次",
        ):
            with self.subTest(question=question):
                state = await self.state(question)
                self.assertTrue(state["clarification"])
                self.assertEqual(
                    state["preflight_reason"], "invalid_date" if "2026-02-30" in question else "unresolved_time"
                )
        soft = await self.state("推荐悬疑电影，最好是最近上映的")
        self.assertFalse(soft["clarification"])
        self.assertIsNone(soft["entities"]["release_date_from"])
        policy = await self.state("最近的退票规则是什么")
        self.assertFalse(policy["clarification"])

    async def test_short_followups_keep_evening_and_ambiguous_movie_lists_are_clarified(self) -> None:
        history = [{"role": "user", "content": "《测试电影》明晚有哪些场次"}]
        followup = await self.state("后天呢", history)
        self.assertEqual(followup["entities"]["screening_date"], "2026-10-15")
        self.assertEqual(followup["entities"]["screening_hour_from"], 18)
        self.assertEqual(followup["entities"]["movie_query"], "测试电影")
        state = await self.state("本周有哪些电影")
        self.assertTrue(state["clarification"])
        evening = await self.state("晚上有哪些电影")
        self.assertEqual(evening["entities"]["movie_scope"], "scheduled")
        self.assertEqual(evening["entities"]["screening_hour_from"], 18)

    async def test_free_form_entities_still_reach_understanding_after_time_resolution(self) -> None:
        payload = QuestionPlan(
            intent="screenings", normalized_question="查询流浪地球场次", confidence=0.9, movie_query="流浪地球"
        ).model_dump_json()
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
        result = await understand(model, "流浪地球明天有票吗", [])
        model.bind.return_value.ainvoke.assert_awaited_once()
        self.assertEqual(result["entities"]["movie_query"], "流浪地球")

    def test_calendar_boundaries_and_missing_year(self) -> None:
        for question, anchor, start, end in (
            ("最近一周上映的电影", date(2027, 1, 2), "2026-12-27", "2027-01-02"),
            ("下个月上映的电影", date(2026, 12, 20), "2027-01-01", "2027-01-31"),
            ("昨天上映的电影", date(2028, 3, 1), "2028-02-29", "2028-02-29"),
            ("三天后上映的电影", TODAY, "2026-10-16", "2026-10-16"),
            ("明年上映的电影", TODAY, "2027-01-01", "2027-12-31"),
            ("12月31日到1月2日的场次", date(2026, 12, 20), "2026-12-31", "2027-01-02"),
        ):
            with self.subTest(question=question):
                window = normalize_times(question, anchor, "release").windows[0]
                self.assertEqual((window.date_from, window.date_to), (start, end))
        window = normalize_times("1月2日有哪些场次", TODAY, "screening").windows[0]
        self.assertEqual(window.reason, "year_required")

    async def test_evening_recommendations_require_matching_screening_evidence(self) -> None:
        state = await self.state("推荐明晚能看的悬疑电影")
        arguments = validate_arguments("recommend_movies", {}, state)
        self.assertEqual(arguments["screening_date_from"], "2026-10-14")
        self.assertEqual(arguments["screening_hour_from"], 18)
        row = {
            "title": "测试电影",
            "genre": "悬疑",
            "screenings": [
                {"id": 1, "start_time": "2026-10-14T18:00:00", "cinema_name": "影院", "hall_name": "厅", "price": 30}
            ],
        }
        validate_result("recommend_movies", [row], arguments, user_id=1)
        row["screenings"][0]["start_time"] = "2026-10-14T10:00:00"
        with self.assertRaises(CinemaQueryError):
            validate_result("recommend_movies", [row], arguments, user_id=1)
        self.assertFalse(valid_screening_result([{**row["screenings"][0], "title": "测试电影"}], arguments))

    async def test_model_cannot_change_resolved_dates_or_add_unrequested_screenings(self) -> None:
        payload = QuestionPlan(
            intent="screenings",
            normalized_question="查询场次",
            confidence=0.9,
            release_date_from="2001-01-01",
            requested_intents=["screenings"],
        ).model_dump_json()
        model = Mock()
        model.bind.return_value.ainvoke = AsyncMock(return_value=SimpleNamespace(content=payload))
        with patch.dict("os.environ", {"AGENT_L0_ENABLED": "false"}):
            plan = await understand(model, QUESTION, [])
        self.assertEqual(plan["intent"], "recommend")
        self.assertEqual(plan["entities"]["release_date_from"], "2026-10-07")
        self.assertNotIn("screenings", plan["requested_intents"])

    async def test_trace_retains_resolution_without_expression_or_arbitrary_text(self) -> None:
        state = await self.state(QUESTION)
        state["temporal_summary"]["windows"][0]["expression"] = "PRIVATE-EXPRESSION"
        safe = summarize_payload(state)
        self.assertEqual(safe["temporal_summary"]["reference_date"], "2026-10-13")
        self.assertNotIn("PRIVATE-EXPRESSION", str(safe))

    async def test_full_graph_uses_date_filtered_tool_and_formats_real_dates(self) -> None:
        rows = [{"title": "测试悬疑片", "genre": "悬疑", "release_date": "2026-10-08", "matches_release_window": True}]
        execute = AsyncMock(return_value=rows)
        workflow = CinemaReAct(
            lambda: None,
            execute,
            AsyncMock(return_value=[]),
            lambda state: recommendation_answer(state["result"], state["entities"]),
        )
        result = await workflow.graph.ainvoke(initial_state(1, "relative-time", QUESTION, []), config=workflow.config)
        self.assertEqual(execute.await_args.args[0], "recommend_movies")
        self.assertEqual(execute.await_args.args[1]["release_date_from"], "2026-10-07")
        self.assertIn("上映日期：2026-10-08", result["answer"])
        self.assertFalse(result["needs_clarification"])
