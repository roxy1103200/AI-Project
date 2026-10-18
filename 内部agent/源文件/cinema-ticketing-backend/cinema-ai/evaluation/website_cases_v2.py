"""Website v2: preserve v1 evidence and replace only superseded recommendation expectations."""

from evaluation.website_cases import CASES as V1_CASES, CORE as V1_CORE, Case, Turn


def direct(case_id: str, title: str, question: str, check: str) -> Case:
    """Give new policy scenarios identifiers separate from the baseline."""
    return Case("RT-" + case_id, title, (Turn(question, check),))


DEFAULT = "给我推荐最近一周的电影"
GENRE = "给我推荐最近一周的悬疑电影"
REPLACEMENT_D05 = Case("D05", "最近七天软偏好直接推荐", (Turn("推荐悬疑电影，最好是最近一周的电影", "rt:soft"),))
CASES = tuple(REPLACEMENT_D05 if case.id == "D05" else case for case in V1_CASES) + (
    direct("A01", "原问题直接推荐", DEFAULT, "rt:default"),
    direct("A02", "悬疑推荐", GENRE, "rt:genre"),
    direct("A03", "数字七天", "帮我推荐最近7天的电影", "rt:default"),
    direct("A04", "口语推荐", "最近一周有啥电影推荐一下", "rt:default"),
    direct("A05", "明确上映日期", "推荐最近一周上映的电影", "rt:explicit"),
    direct("A10", "无题材无场次仍可推荐", DEFAULT, "rt:default"),
    direct("P01", "软日期偏好", "推荐悬疑电影，最好是最近一周的", "rt:soft"),
    direct("P02", "上映硬条件", "只推荐最近一周上映的悬疑电影", "rt:genre_explicit"),
    direct("P03", "强制日期优先", "最好推荐悬疑电影，但上映日期必须在最近一周", "rt:genre_explicit"),
    direct("P04", "保留必要澄清", "这周的悬疑题材电影有哪部", "clarify"),
    direct("P05", "未来范围不套默认", "推荐下周的电影", "clarify"),
    direct("P06", "座位缺条件", "查一下座位", "clarify"),
    direct("P07", "订单缺条件", "我的订单能退吗", "clarify"),
    direct("P08", "科幻硬日期空结果", "推荐最近一周的科幻电影", "rt:science_empty"),
    Case("RT-C01", "默认后纠正观影对象", (Turn(GENRE, "rt:genre"), Turn("我是说按观影日期", "rt:screening_recent"))),
    Case("RT-C02", "纠正本周有票", (Turn(GENRE, "rt:genre"), Turn("我是说这周有票的", "rt:bookable_week"))),
    Case("RT-C03", "继承上映对象改日期", (Turn(GENRE, "rt:genre"), Turn("那下周呢", "rt:release_next"))),
    Case(
        "RT-C04",
        "继承可购票对象",
        (Turn("推荐这周有票的悬疑电影", "bookable_week"), Turn("那下周呢", "bookable_next_week")),
    ),
    Case("RT-C05", "只查推荐集合今晚场次", (Turn(GENRE, "rt:genre"), Turn("这些电影今晚有票吗", "rt:candidates"))),
    Case("RT-C06", "只修改题材", (Turn(GENRE, "rt:genre"), Turn("换成科幻的", "rt:science_empty"))),
    Case("RT-C08", "重置后不继承", (Turn(GENRE, "rt:genre"), Turn("那下周呢", "clarify", "reset"))),
    Case("RT-C09", "切换账号后缺少推荐上下文", (Turn(GENRE, "rt:genre"), Turn("这些电影今晚有票吗", "clarify", "new_account_b"))),
    direct("B01", "日期无效不查", "推荐2026年2月30日上映的电影", "clarify"),
    direct("B02", "硬日期冲突不查", "只要2026年10月11日至17日上映，同时必须2026年10月18日至24日上映的电影", "clarify"),
    direct("B07", "软科幻范围外补充", "推荐科幻电影，最好是最近一周的", "rt:science_soft"),
    Case("RT-B08", "推荐查询故障不能当空结果", (Turn(DEFAULT, "service_error", "recommendation_unavailable"),)),
    *(
        direct(f"W04-{kind}-{attempt}", "直接推荐稳定性复测", question, check)
        for kind, question, check in (("A01", DEFAULT, "rt:default"), ("A02", GENRE, "rt:genre"), ("P01", "推荐悬疑电影，最好是最近一周的", "rt:soft"))
        for attempt in range(1, 4)
    ),
)
CORE = V1_CORE | {"RT-A01", "RT-A02", "RT-P01", "RT-C01", "RT-C02"}
