"""Website regression v1: 32 independent scenarios, separate from frozen Golden v1."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    question: str
    check: str
    action: str = ""


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    turns: tuple[Turn, ...]


AMBIGUOUS = "这周的悬疑题材电影有哪部"
CASES = (
    Case("T01", "本周上映日期", (Turn("推荐本周上映的悬疑电影", "release_week"),)),
    Case("T02", "滚动七天软偏好", (Turn("推荐悬疑电影，最好是最近一周上映的，给出上映日期", "release_recent_soft"),)),
    Case("T03", "本周可购票", (Turn("这周有票的悬疑电影", "bookable_week"),)),
    Case("T04", "明晚场次", (Turn("明晚有哪些场次", "tomorrow_evening"),)),
    Case("T05", "下周排期", (Turn("下周有哪些排期", "scheduled_next_week"),)),
    Case("T06", "最近七天硬约束", (Turn("只看最近一周上映的悬疑电影", "release_recent_hard"),)),
    Case("T07", "不合法日期", (Turn("2026年2月30日有哪些场次", "clarify"),)),
    Case("T08", "空结果措辞", (Turn("这周有票的恐怖电影有哪些", "empty_week"),)),
    Case("D01", "澄清上映对象", (Turn(AMBIGUOUS, "clarify"), Turn("新上映的", "release_week"))),
    Case("D02", "澄清观影对象", (Turn(AMBIGUOUS, "clarify"), Turn("有票的", "bookable_week"))),
    Case("D03", "下周继续追问", (Turn("这周有票的悬疑电影", "bookable_week"), Turn("那下周呢", "bookable_next_week"))),
    Case(
        "D04", "晚上继续追问", (Turn("明天《回归悬疑新片》有哪些场次", "tomorrow"), Turn("晚上呢", "tomorrow_evening"))
    ),
    Case(
        "D05",
        "最近七天偏好澄清",
        (Turn("推荐悬疑电影，最好是最近一周的电影", "clarify"), Turn("按上映日期", "release_recent_soft")),
    ),
    Case(
        "D06", "reset 清理上下文", (Turn("这周有票的悬疑电影", "bookable_week"), Turn("有票的", "reset_clean", "reset"))
    ),
    *(
        Case(f"O{i:02d}", title, (Turn(f"我的订单 {{O{i:02d}}} 现在是什么状态，能退票吗？", f"order_{i:02d}"),))
        for i, title in enumerate(
            (
                "未付款",
                "关单处理中",
                "取消未收款",
                "已出票可退",
                "超过退票截止",
                "已经验票",
                "退款处理中",
                "退款结果未知",
                "已退款",
                "迟到付款补偿中",
                "迟到付款已补偿",
            ),
            1,
        )
    ),
    Case(
        "O12",
        "退款状态实时变化",
        (Turn("我的订单 {O12} 的状态", "order_12"), Turn("现在呢", "order_12_updated", "advance")),
    ),
    Case("S01", "其他账号订单", (Turn("查询订单 {O14} 的状态", "foreign_order"),)),
    Case("S02", "过期转接授权", (Turn("我的订单 {O04} 的状态", "expired_handoff", "expired"),)),
    Case("S03", "账号切换隔离", (Turn("我的订单 {O04} 的状态", "account_isolation", "account_switch"),)),
    Case("S04", "Java 服务故障", (Turn("我的订单 {O04} 的状态", "service_error", "java_unavailable"),)),
    Case("S05", "未知订单契约", (Turn("我的订单 {O13} 的状态", "contract_error"),)),
    Case(
        "S06",
        "中断停止完成持久化",
        (
            Turn("本周上映的悬疑电影有哪些", "truncated", "truncate"),
            Turn("推荐本周上映的悬疑电影", "stopped", "stop"),
            Turn("我的订单 {O04} 的状态", "persisted"),
        ),
    ),
)
assert len(CASES) == 32
CORE = {"T01", "T03", "T08", "D01", "D02", "O07", "O08", "O10", "S01", "S06"}
