"""Generate the requested, editable SVG architecture atlas from local code findings.

This script only writes documentation artifacts next to itself. It never imports
the business application, reads credentials, or calls model / business services.
"""

from __future__ import annotations

import ast
import html
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AI = ROOT / "cinema-ticketing-backend" / "cinema-ai"
GATEWAY = ROOT / "cinema-ticketing-backend" / "cinema-ai-gateway"
COLORS = {
    "blue": ("#eaf2ff", "#3262a8"),
    "teal": ("#e4f5f1", "#167564"),
    "purple": ("#f0ebff", "#7450a3"),
    "gold": ("#fff3d9", "#a4761c"),
    "red": ("#ffeded", "#b44a4a"),
    "gray": ("#eef1f5", "#617189"),
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


class Diagram:
    """Small native SVG builder with deliberate text layout and routed edges."""

    def __init__(self, number: str, title: str, subtitle: str, height: int = 1120):
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="{height}" viewBox="0 0 1600 {height}" role="img" aria-labelledby="title desc">',
            f"<title id='title'>{esc(title)}</title><desc id='desc'>{esc(subtitle)}</desc>",
            "<defs><marker id='arrow' markerWidth='9' markerHeight='9' refX='8' refY='4.5' orient='auto-start-reverse'><path d='M0,0 L9,4.5 L0,9' fill='#617189'/></marker></defs>",
            "<style>text{font-family:'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',sans-serif;fill:#203047} .body{font-size:19px} .muted{fill:#617189} .edge{fill:none;stroke:#617189;stroke-width:2.2;marker-end:url(#arrow);stroke-linejoin:round} .label{font-size:16px;fill:#43556f} .title{font-size:23px;font-weight:700}</style>",
            f"<rect width='1600' height='{height}' fill='#f8fafc'/>",
            "<rect x='0' y='0' width='1600' height='8' fill='#167564'/>",
            f"<text x='50' y='55' font-size='16' fill='#167564' letter-spacing='3'>CINEMA AI / CODE ATLAS · {esc(number)}</text>",
            f"<text x='50' y='103' font-size='36' font-weight='700'>{esc(title)}</text>",
            f"<text x='50' y='139' font-size='19' class='muted'>{esc(subtitle)}</text>",
        ]

    def group(self, x: int, y: int, w: int, h: int, title: str, tint: str = "gray"):
        fill, stroke = COLORS[tint]
        self.parts.extend([
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='18' fill='{fill}' fill-opacity='.38' stroke='{stroke}' stroke-opacity='.27' stroke-dasharray='7 6'/>",
            f"<text x='{x + 20}' y='{y + 31}' font-size='18' font-weight='700' class='muted'>{esc(title)}</text>",
        ])

    def box(self, x: int, y: int, w: int, title: str, lines: list[str], tint: str = "blue", h: int | None = None):
        h = h or (75 + 30 * len(lines))
        fill, stroke = COLORS[tint]
        self.parts.extend([
            f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='12' fill='{fill}' stroke='{stroke}' stroke-width='1.5'/>",
            f"<rect x='{x}' y='{y + 17}' width='4' height='26' rx='2' fill='{stroke}'/>",
            f"<text x='{x + 20}' y='{y + 35}' class='title'>{esc(title)}</text>",
        ])
        for i, line in enumerate(lines):
            self.parts.append(f"<text x='{x + 20}' y='{y + 69 + 30 * i}' class='body'>{esc(line)}</text>")

    def text(self, x: int, y: int, lines: list[str], size: int = 19, muted: bool = False):
        for i, line in enumerate(lines):
            cls = "muted" if muted else ""
            self.parts.append(f"<text x='{x}' y='{y + i * 30}' font-size='{size}' class='{cls}'>{esc(line)}</text>")

    def arrow(self, points: list[tuple[int, int]], label: str = "", at: tuple[int, int] | None = None, dashed: bool = False):
        path = "M" + " L".join(f"{x},{y}" for x, y in points)
        dash = " stroke-dasharray='7 5'" if dashed else ""
        self.parts.append(f"<path d='{path}' class='edge'{dash}/>")
        if label:
            x, y = at or points[len(points) // 2]
            width = sum(16 if ord(c) > 127 else 8.5 for c in label) + 14
            self.parts.extend([
                f"<rect x='{x - 7}' y='{y - 19}' width='{width:.1f}' height='25' rx='4' fill='#f8fafc'/>",
                f"<text x='{x}' y='{y}' class='label'>{esc(label)}</text>",
            ])

    def note(self, y: int, title: str, lines: list[str]):
        self.box(50, y, 1500, title, lines, "gray")

    def save(self, filename: str):
        self.parts.extend([
            f"<line x1='50' y1='{self.height - 53}' x2='1550' y2='{self.height - 53}' stroke='#d9e0ea'/>",
            f"<text x='50' y='{self.height - 25}' font-size='15' class='muted'>基于当前工作区代码 · 2026-10-12 · 默认值不代表运行配置 · 完整说明见 README.md / source-index.md</text>",
            "</svg>",
        ])
        source = "\n".join(self.parts)
        ET.fromstring(source)
        (HERE / filename).write_text(source, encoding="utf-8")


def system():
    d = Diagram("01", "AI 系统全貌：入口、编排、权威数据", "实线为主要请求 / 数据路径；虚线为辅助关联。浏览器只访问同源代理。", 1320)
    d.group(40, 180, 1520, 220, "访问入口：浏览器 → 同源代理 → Java API", "blue")
    d.box(65, 235, 420, "React 聊天界面", ["Dify / Agent 独立通道", "标签页 token、反馈、记忆确认"], "blue")
    d.box(590, 235, 405, "Vite / Nginx 同源代理", ["/ai-gateway → 8010", "/api → Java 8080"], "gray")
    d.box(1100, 235, 420, "Java 身份与业务 API", ["登录、转接凭证、记忆、反馈", "真实业务规则与参数化 SQL"], "gold")
    d.arrow([(485, 300), (590, 300)], "POST SSE", (490, 285))
    d.arrow([(995, 300), (1100, 300)], "/api", (1020, 285))
    d.group(40, 435, 1010, 530, "私有服务 / 内部 token 边界", "teal")
    d.box(70, 495, 420, "独立 AI 网关 · 8010", ["身份 / 归属 / 租约 / 限流", "Dify 转发、Agent 转发、历史", "统一事件、停止、持久化、反馈"], "teal")
    d.box(595, 495, 420, "内部 Agent · 8000", ["理解 → Simple / ReAct", "工具 → 校验 → 事实 → 反思", "Qwen / GLM / 预算 / 记忆"], "purple")
    d.box(595, 775, 420, "MCP 查询服务 · 8020", ["四个只读查询工具 /mcp", "固定接口 → Java → SQL"], "gold")
    d.box(70, 775, 420, "Redis", ["两通道历史、绑定、活动会话", "全局并发、取消、反馈快照"], "teal")
    d.arrow([(790, 370), (790, 420), (280, 420), (280, 495)])
    d.arrow([(490, 570), (595, 570)], "/ai/live", (495, 554))
    d.arrow([(805, 660), (805, 775)], "MCP", (820, 720))
    d.arrow([(280, 660), (280, 775)])
    d.arrow([(1015, 845), (1060, 845), (1060, 405), (1310, 405), (1310, 370)], "业务查询", (1074, 680))
    d.arrow([(490, 525), (540, 525), (540, 405), (1310, 405)], "登录 / 转接核验", (615, 398), True)
    d.group(1090, 435, 470, 530, "外部云端服务", "purple")
    d.box(1115, 495, 420, "Dify 云端 Chatbot", ["FAQ / 云端会话", "服务端 Key → 官方 API"], "purple")
    d.box(1115, 700, 420, "Qwen / GLM / Rerank", ["复杂理解、决策、反思", "分类 / 公开规则重排"], "purple")
    d.arrow([(490, 620), (550, 620), (550, 680), (1080, 680), (1080, 560), (1115, 560)], "Dify 通道", (650, 673))
    d.arrow([(1015, 610), (1070, 610), (1070, 770), (1115, 770)], "模型调用", (1040, 800))
    d.box(65, 1025, 420, "MySQL 权威记录", ["影院业务 / 反馈 / 用户记忆", "记忆变更与 outbox 同事务"], "gold")
    d.box(590, 1025, 420, "Chroma + Memory worker", ["用户确认偏好的向量投影", "BGE 本地嵌入 / Java 二次验证"], "teal")
    d.box(1115, 1025, 420, "LangSmith + 本地追踪", ["节点 / 模型 / 工具 / 耗时", "元数据摘要 / 按用户会话归档"], "gray")
    d.arrow([(1520, 370), (1545, 370), (1545, 985), (280, 985), (280, 1025)], "Java 维护权威记录", (70, 978), True)
    d.arrow([(970, 660), (970, 735), (1040, 735), (1040, 1005), (800, 1005), (800, 1025)], dashed=True)
    d.arrow([(1015, 530), (1080, 530), (1080, 995), (1325, 995), (1325, 1025)], dashed=True)
    d.text(65, 1235, ["关键边界：模型不接 MySQL，不任意写 SQL；真实订单始终按 Java 验证的本人身份查询。"], 20)
    d.save("01-system.svg")


def gateway():
    d = Diagram("02", "AI 网关：每次请求都证明身份与会话归属", "sessionStorage 只隔离标签页账号；Redis 支持同账号、同通道跨设备恢复。", 1360)
    d.box(65, 200, 430, "① 标签页请求", ["token + bindingKey + sessionId", "POST question；Agent 带 credential", "credentials: omit，不用共享 Cookie"], "blue")
    d.box(585, 200, 430, "② Java 核验当前登录", ["/internal/ai/auth/resolve", "取可信 userId / role / lifetime", "失效 401；不可用 503，拒绝放行"], "gold")
    d.box(1105, 200, 430, "③ Redis 证明会话归属", ["绑定 token 必须等于本次 token", "owner / UUID / 活动指针吻合", "Dify 匿名可用；Agent 要登录"], "teal")
    d.arrow([(495, 280), (585, 280)])
    d.arrow([(1015, 280), (1105, 280)])
    d.box(1105, 495, 430, "④ 限流与分布式租约", ["每会话聊天 12 / min", "同会话一个生成；全局默认 16", "120 秒租约，原子获取 / 释放"], "teal")
    d.box(585, 495, 430, "⑤ 选择固定通道", ["Dify：云端 API + provider IDs", "Agent：凭证解出 owner / session", "要求匹配 cinema:read，再转发"], "purple")
    d.box(65, 495, 430, "⑥ 流期间监测", ["约 0.5 秒检查取消标记", "约 2 秒复核已登录用户身份", "整轮 90 秒；失效 / 中止即取消"], "blue")
    d.arrow([(1320, 365), (1320, 495)])
    d.arrow([(1105, 575), (1015, 575)])
    d.arrow([(585, 575), (495, 575)])
    d.box(65, 790, 430, "⑦ 规范化上游事件", ["message / status / delta / error", "答案最多 40,000 字符", "暂存 complete，先完成持久化"], "blue")
    d.box(585, 790, 430, "⑧ 持久化并释放租约", ["快照 2 小时；回答快照 8,000 字", "历史保留 40 条消息", "保存失败不能发送成功 complete"], "teal")
    d.box(1105, 790, 430, "⑨ 浏览器确认结束", ["complete → 本轮协议完成", "error / EOF 无 complete → 失败", "stop / reset / feedback 再次验权"], "blue")
    d.arrow([(280, 660), (280, 790)])
    d.arrow([(495, 875), (585, 875)])
    d.arrow([(1015, 875), (1105, 875)])
    d.note(1080, "Redis 生命周期与共享范围", ["匿名 1 天；账号滑动 30 天；绑定 1 天；Dify / Agent 命名空间与历史独立。", "账号每通道一个活动会话：重置后其他设备的旧会话返回冲突，需要恢复连接。", "多 worker 共享 Redis / namespace 才共享租约与历史；Redis 故障时入口拒绝继续。"])
    d.save("02-gateway.svg")


def graph():
    d = Diagram("03", "内部 Agent：实际 LangGraph 节点与条件边", "蓝色为执行，紫色为模型决策 / 校验；虚线是提前退出；回边不代表无限循环。", 1600)
    d.box(50, 230, 150, "START", [], "gray", 75)
    d.box(270, 200, 380, "prepare", ["理解 / 预算 / tasks", "route / versions / 推荐记忆"], "blue", 145)
    d.box(880, 200, 350, "clarify", ["缺条件，明确追问"], "gold", 115)
    d.box(270, 490, 350, "simple", ["代码选定单任务工具", "不额外让模型选择工具"], "blue", 145)
    d.box(880, 490, 350, "agent", ["ReAct：工具提议 / 进度", "原生 tool calling + 代码兜底"], "purple", 145)
    d.box(880, 820, 350, "tools", ["参数 / 来源 / 身份校验", "执行 → 返回契约校验", "observations + tasks 更新"], "teal", 175)
    d.box(270, 820, 350, "draft", ["逐条观察格式化为事实块", "拼接草稿，不自由生成事实"], "blue", 175)
    d.box(270, 1180, 350, "reflect", ["规则优先；模型最多 1 次", "只选取 / 排序已有事实块", "缺任务且可补 → 回 agent"], "purple", 175)
    d.box(880, 1180, 350, "respond", ["事实 / 追问 / 限制说明", "或安全错误事件", "正文统一 delta；记录上下文"], "blue", 175)
    d.box(1320, 1225, 180, "END", [], "gray", 75)
    d.arrow([(200, 267), (270, 267)])
    d.arrow([(650, 250), (880, 250)], "需澄清", (720, 235))
    d.arrow([(445, 345), (445, 490)], "完整单任务", (460, 410))
    d.arrow([(650, 310), (755, 310), (755, 420), (1055, 420), (1055, 490)], "复杂 / 有依赖", (800, 405))
    d.arrow([(650, 210), (1450, 210), (1450, 1115), (1115, 1115), (1115, 1180)], "问候 / 熔断 → respond", (1260, 360), True)
    d.arrow([(1230, 255), (1290, 255), (1290, 1150), (1185, 1150), (1185, 1180)], "追问后结束", (1304, 470))
    d.arrow([(620, 570), (700, 570), (700, 770), (880, 770), (880, 855)], "待调用工具", (715, 755))
    d.arrow([(1055, 635), (1055, 820)], "待调用工具", (1070, 720))
    d.arrow([(405, 635), (405, 820)], "无待调用 → draft", (280, 735))
    d.arrow([(880, 600), (790, 600), (790, 715), (530, 715), (530, 820)], "无待调用", (560, 700))
    d.arrow([(1230, 900), (1260, 900), (1260, 680), (1185, 680), (1185, 635)], "ReAct 继续", (1280, 750))
    d.arrow([(880, 930), (620, 930)], "Simple → draft", (665, 915))
    d.arrow([(445, 995), (445, 1180)])
    d.arrow([(620, 1260), (880, 1260)], "校验后结束", (660, 1245))
    d.arrow([(305, 1180), (305, 1080), (665, 1080), (665, 390), (920, 390), (920, 490)], "补未完成任务（预算内）", (685, 1065))
    d.arrow([(1230, 1265), (1320, 1265)])
    d.text(65, 1435, ["提前退出边：simple → respond、agent → respond、tools → respond（已产生答案、错误或熔断时）。", "主图以文字合并这三条异常边，避免交叉遮挡；它们也是实际条件路由，不会进入 draft / reflect。", "硬上限：模型 8 次、ReAct 5 步、无效调用 3 次、反思 1 次；compile() 没有持久 checkpoint。"], 19)
    d.save("03-agent-graph.svg")


def intent():
    d = Diagram("04", "问题理解：先确定规则，再按需要调用模型", "模型分类不产生授权；日期、范围、订单号与场次号最终仍由代码绑定来源。", 1370)
    d.box(65, 200, 430, "① 规范化 + 规则解析", ["中文同义表达 / 北京时间日期", "保留用户编号与明确片名", "构造 QuestionPlan 与槽位"], "blue")
    d.box(585, 200, 430, "② 预检与澄清", ["无效日期 / 越界写操作", "缺关键 ID / 含糊日期", "不能猜，需用户补条件"], "gold")
    d.box(1105, 200, 430, "③ L0 确定性路由", ["问候 / 明确订单号与场次号", "明确单片资料 / 日期场次", "命中且安全 → 直接计划"], "teal")
    d.arrow([(495, 280), (585, 280)])
    d.arrow([(1015, 280), (1105, 280)], "预检可继续", (1015, 260))
    d.box(1105, 490, 430, "④ 可选本地 fastText", ["默认关闭；已验证模型才加载", "hash + manifest + 九标签", "高置信且与规则一致才接纳"], "teal")
    d.box(585, 490, 430, "⑤ B 组可选 GLM L1", ["单任务、适用问题才尝试", "320 tokens / 默认 6 秒 / 单并发", "接受阈值默认 0.90"], "purple")
    d.box(65, 490, 430, "⑥ Qwen 结构化兜底", ["复杂 / 上下文 / 未通过分类", "受约束 JSON，最多 1,000 输出", "理解调用还有 15 秒期限"], "purple")
    d.arrow([(1320, 365), (1320, 490)], "未命中", (1335, 430))
    d.arrow([(1105, 570), (1015, 570)], "未接纳", (1015, 550))
    d.arrow([(585, 570), (495, 570)], "A 组跳过 / B 组未通过", (290, 455))
    d.box(65, 795, 430, "⑦ 代码重新验证", ["还原规则日期 / 范围 / 片名", "编号只能来自用户可靠来源", "低置信 / 缺槽位 → 澄清"], "gold")
    d.box(585, 795, 430, "⑧ tasks + 代码选 route", ["单任务完整高置信 → Simple", "多个任务 / 依赖 / 不确定 → ReAct", "chat / unsupported → 直接响应"], "blue")
    d.box(1105, 795, 430, "A/B：按用户会话稳定分组", ["A：L0 + Qwen + 校验", "B：增加 GLM L1，默认 50%", "关 A/B 当前为全 B；可强制组别"], "gray")
    d.arrow([(280, 655), (280, 795)])
    d.arrow([(1105, 350), (1060, 350), (1060, 720), (380, 720), (380, 795)], "任一层已接纳 → 跳过后续模型", (530, 705), True)
    d.arrow([(1250, 655), (1250, 720), (1060, 720)], dashed=True)
    d.arrow([(800, 655), (800, 720)], dashed=True)
    d.arrow([(495, 875), (585, 875)])
    d.note(1090, "接纳不等于盲信：模型输出还要通过业务约束", ["GLM 字段须在原问题中有依据，不得扩展任务、改范围、伪造 ID；429 冷却 30 秒，超时冷却 10 秒。", "本地分类 / GLM / Qwen 理解均不能直接查库；最终输出 QuestionPlan 后才能进入受预算约束的工具执行。", "catalog 是资料；showing 是上映属性；scheduled 是真实排期；bookable 是此刻能买，不能互相替代。"])
    d.save("04-intent.svg")


def tools():
    d = Diagram("05", "工具执行：模型提议，代码约束，Java 查询", "大模型不持 MySQL 凭证，不接受任意 SQL；模型也不能选择订单所属用户。", 1370)
    d.box(65, 200, 430, "模型 / Simple 提议", ["search_movies / screenings", "query_seats / query_order", "policy / recommend / ask_user"], "purple")
    d.box(585, 200, 430, "调用前校验", ["白名单 + extra=forbid schema", "任务 / 日期 / 查询范围固定", "订单与场次 ID 追溯来源"], "gold")
    d.box(1105, 200, 430, "执行前控制", ["调用数 / 重复 / 无进展 / 超时", "从可信 state 注入 userId", "ask_user 只追问，不查库"], "blue")
    d.arrow([(495, 280), (585, 280)])
    d.arrow([(1015, 280), (1105, 280)])
    d.box(1105, 485, 430, "MCP · 四个查询", ["独立连接 / initialize / tools/call", "内部 token + X-AI-User-ID", "stateless / Host 检查 / 只读接口"], "teal")
    d.box(585, 485, 430, "Java HTTP → 固定 SQL", ["movies / screenings / order", "座位走现有业务座位接口", "WHERE order_no=? AND user_id=?"], "gold")
    d.box(65, 485, 430, "查询返回契约", ["MCP structuredContent data/error", "结果类型 / 日期 / 范围校验", "订单号与 owner 再次比对"], "blue")
    d.arrow([(1320, 365), (1320, 485)])
    d.arrow([(1105, 565), (1015, 565)])
    d.arrow([(585, 565), (495, 565)])
    d.box(65, 790, 430, "可信 observation", ["校验后才进入 ToolMessage", "截断标志 / 来源 / task_id", "任务进度更新，再决策或 draft"], "teal")
    d.box(585, 790, 430, "本地适配 · 两个业务工具", ["policy → 当前政策 + 知识检索", "recommend → Java 关键词查询", "不经 MCP；同样受图的执行控制"], "gold")
    d.box(1105, 790, 430, "不提供的工具", ["下单 / 锁座 / 支付 / 退款", "修改业务 / 删影片 / 查他人订单", "需前往正常页面按权限操作"], "red")
    d.arrow([(280, 650), (280, 790)])
    d.arrow([(1200, 365), (1065, 365), (1065, 750), (800, 750), (800, 790)], "policy / recommend", (815, 735), True)
    d.arrow([(800, 790), (800, 700), (350, 700), (350, 650)], "同样校验返回", (560, 690), True)
    d.note(1090, "来源限制与实时规则", ["订单号来自用户消息；场次编号来自用户明确输入或本轮已验证结果；不能从助手旧回答猜测。", "can_refund 由 Java 按订单状态、验票、当前时间、启用政策计算；通用政策不能替代本人订单资格。", "工具 readOnlyHint 是描述，真正边界是白名单、受控参数、固定 HTTP / SQL 和部署内网权限。"])
    d.save("05-tools.svg")


def memory():
    d = Diagram("06", "记忆：短期历史、图内状态、长期偏好各司其职", "MySQL 是长期记忆权威；Chroma 是可重建投影，删除与版本校验以 Java 为准。", 1510)
    d.box(65, 200, 430, "短期 · Redis / Dify", ["Redis 每通道最多 40 条消息", "Agent 接收最多 10 条有效历史", "Dify 自己的云端 conversation"], "blue")
    d.box(585, 200, 430, "本轮 · LangGraph state", ["tasks / observations / budget", "工具消息 / evidence / 结束原因", "无持久 checkpoint，不能断点续跑"], "purple")
    d.box(1105, 200, 430, "长期 · 用户确认偏好", ["记住… → suggestion → 用户确认", "Java API 写入；每人最多 200 条", "非自动把每轮对话写入画像"], "teal")
    d.group(40, 445, 1520, 380, "写入路径：异步、可重试、最终一致", "gold")
    d.box(65, 510, 430, "① Java 同一事务", ["ai_user_memory + outbox", "content / category / version", "修改与删除使用乐观锁"], "gold")
    d.box(585, 510, 430, "② Memory worker", ["claim ≤10 / SKIP LOCKED", "每记忆按序；租约 5 分钟", "成功 ack；失败延迟 30 秒重试"], "blue")
    d.box(1105, 510, 430, "③ BGE → Chroma", ["本地 bge-small-zh-v1.5 / CPU", "归一化向量 / cosine", "upsert 当前版本 / delete 墓碑"], "teal")
    d.arrow([(1320, 365), (1320, 420), (520, 420), (520, 490), (280, 490), (280, 510)])
    d.arrow([(495, 590), (585, 590)])
    d.arrow([(1015, 590), (1105, 590)])
    d.text(70, 760, ["worker 跳过已被新版本替代的事件；确认必须匹配当前有效 leaseToken。"], 19, True)
    d.group(40, 865, 1520, 365, "召回路径：先过滤，再向权威库核验", "teal")
    d.box(65, 935, 430, "④ 推荐 / 显式问记忆", ["Java 先查 ACTIVE 记忆", "问题加前缀生成查询向量", "普通订单查询不普遍注入偏好"], "blue")
    d.box(585, 935, 430, "⑤ Chroma 候选", ["user_id + channel=AGENT 过滤", "最多 5 条 id + version", "向量查询预算约 4 秒"], "teal")
    d.box(1105, 935, 430, "⑥ Java verify", ["owner + ACTIVE + version", "返回当前权威内容", "过期 / 删除 / 他人记忆被排除"], "gold")
    d.arrow([(495, 1015), (585, 1015)])
    d.arrow([(1015, 1015), (1105, 1015)])
    d.text(70, 1180, ["Chroma 失败或无有效候选 → SQL 最近记忆；整个记忆链路失败 → 不带偏好继续普通查询。"], 19, True)
    d.note(1270, "记忆的用途边界", ["长期记忆是确认偏好；票价、场次、退票资格仍走实时业务查询。用户删除后即使旧向量仍在也无法通过 verify。", "重置聊天只清短期会话，不删除长期记忆；Chroma 不是所有影片 / 订单 / 政策的统一数据库。"])
    d.save("06-memory.svg")


def streaming():
    d = Diagram("07", "SSE 时序：完成、取消与反馈如何闭环", "实时 Agent 的状态可持续输出；事实正文校验后统一输出，网关持久化成功后才发 complete。", 1510)
    centers = [170, 485, 800, 1115, 1430]
    headers = ["前端", "AI 网关", "Java / Redis", "Agent / Dify", "模型 / MCP"]
    for x, label in zip(centers, headers, strict=True):
        d.box(x - 125, 190, 250, label, [], "gray", 70)
        d.parts.append(f"<line x1='{x}' y1='270' x2='{x}' y2='1190' stroke='#bac6d5' stroke-dasharray='5 7'/>")

    def msg(source, target, y, label, dashed=False):
        d.arrow([(centers[source], y), (centers[target], y)], label, (min(centers[source], centers[target]) + 15, y - 12), dashed)

    msg(0, 2, 325, "Agent：申请 handoff（已登录 + sessionId）")
    msg(0, 1, 405, "POST chat + 三个身份 / 会话头")
    msg(1, 2, 475, "核验 token / 归属 / 限流 / 租约")
    msg(1, 0, 545, "messageId / status（开始上游调用前）")
    msg(1, 2, 615, "Agent：resolve credential 并取可信 owner")
    msg(1, 3, 685, "Agent /ai/live 或 Dify /chat-messages")
    msg(3, 4, 755, "理解 / 工具查询 / 校验 / 反思")
    msg(3, 1, 825, "status / context / delta / 上游 complete")
    msg(1, 0, 895, "status / normalized_question / delta")
    msg(1, 2, 965, "finish：快照 + 历史 + 释放租约")
    msg(1, 0, 1035, "成功才发 complete；否则 error")
    msg(0, 1, 1120, "反馈 messageId + rating；再次验权", True)
    d.box(50, 1230, 720, "中断不是成功", ["error 直接失败；EOF 无 complete 提示回答未完成。", "停止：前端 abort + 网关取消；Dify 额外 stop task。", "已生成但 Redis 保存失败也不能发送成功。"], "red")
    d.box(830, 1230, 720, "反馈独立持久化", ["先 Java 落库；Dify 再同步 feedbacks。", "失败保留本地记录与 FAILED / PENDING 状态。", "Agent 反馈不用同步 Dify；快照 2 小时窗口。"], "teal")
    d.save("07-streaming.svg")


def tracing():
    d = Diagram("08", "追踪与排错：从消息关联到节点、模型与工具", "LangSmith 与本地 trace 只收摘要 / 白名单元数据；这不代表聊天或模型链路没有处理原文。", 1430)
    d.box(65, 200, 430, "① 网关消息关联", ["messageId / provider / stage", "Agent 上游 trace UUID 写日志", "不把私有 trace 详情直接发浏览器"], "blue")
    d.box(585, 200, 430, "② Agent 每轮根 span", ["cinema.agent.live / chat", "用户会话 hash / root trace_id", "节点 → 模型 / 工具子 span"], "purple")
    d.box(1105, 200, 430, "③ MetadataOnlyClient", ["拦截 SDK create / update / batch", "清洗 input / output / error", "固定字段、计数、版本和来源摘要"], "gold")
    d.arrow([(495, 280), (585, 280)], "关联", (505, 260))
    d.arrow([(1015, 280), (1105, 280)])
    d.box(1105, 500, 430, "④ LangSmith 云端", ["节点耗时 / 模型 / 工具 / 错误", "local / test / preprod 显式开启", "启用不等于权限与上传已验证"], "purple")
    d.box(585, 500, 430, "⑤ 本地用户会话归档", ["langsmith(tracing)/日期/用户会话", "session.json + traces.jsonl", "SQLite 索引关联延迟回调"], "teal")
    d.box(65, 500, 430, "⑥ 定位失败发生阶段", ["理解 → 决策 → MCP / Java", "→ 反思 → 流完成 → 持久化", "区分错误码、阶段、状态与耗时"], "blue")
    d.arrow([(1320, 365), (1320, 500)])
    d.arrow([(1200, 365), (1200, 435), (800, 435), (800, 500)], "清洗后的同一类事件", (810, 420))
    d.arrow([(585, 580), (495, 580)], "排查", (510, 560))
    d.box(65, 815, 720, "目录示例（用户 42 / hash 为示例）", ["2026_10_12/", "  42_2026_10_12_14_24_a1b2c3d4e5f6/", "    session.json · traces.jsonl", "会话首次目录固定，跨日 / 重启仍归原会话。"], "teal")
    d.box(830, 815, 720, "质量反馈与评估（另一条链路）", ["点赞 / 点踩 → Java 持久反馈 → 后台处理", "缺槽位 → 补充成功 → 脱敏 silver 待审核样本", "evaluation/：golden / A-B / workflow / rerank", "历史报告不等于本次重新验证或线上质量保证。"], "gold")
    d.note(1140, "数据边界", ["追踪不保留完整问题、prompt、SQL、工具行或凭证；本地会话清单含 userId，云端会话用 hash 关联。", "模型可能收到问题 / 历史 / 业务观察；Redis 问答、MySQL 反馈与记忆可以含正文，不能与追踪脱敏混为一谈。", "排错先看 HTTP / error / complete，再关联网关日志与 trace；health UP 只证明进程存活与配置摘要。"])
    d.save("08-tracing.svg")


MODULE_PURPOSES = {
    "main": "FastAPI 入口、模型与工具组装、/ai/live 与兼容接口、特殊记忆分支。",
    "agent_budget": "整轮模型次数、token 预留 / 对账、期限与熔断包装。",
    "clarification_feedback": "脱敏补槽样本 SQLite 收集与待审核质量标记。",
    "failures": "异常归类、安全日志、固定用户提示和追踪失败事件。",
    "glm_router": "GLM L1 模型配置、适用性、结构化预测校验、并发和冷却。",
    "intent": "QuestionPlan、同义化、日期 / ID 规则、结构化理解与最终槽位校验。",
    "intent_classifier": "可选 fastText 加载门槛、hash / 清单验证与置信分类。",
    "intent_routing": "预检、L0 / 本地分类路径、理解层与槽位摘要。",
    "java_client": "内部 token HTTP 客户端，复用 Java 的业务接口。",
    "mcp_client": "带可信身份的独立 MCP session 与四个查询工具调用。",
    "mcp_server": "私网 Streamable HTTP MCP Server、工具 schema、Java 适配。",
    "memory": "用户记忆建议、BGE 嵌入、Chroma 投影 / 召回、Java 权威再验证。",
    "memory_runtime": "本地 Chroma 与 memory worker 启动器。",
    "memory_worker": "MySQL outbox 租约任务消费、版本检查、索引与确认。",
    "model_config": "Qwen 服务端密钥加载与 ChatOpenAI 参数。",
    "policy_retrieval": "本地 Markdown / Java 知识分块、关键词召回与合并去重。",
    "provision_memory_model": "固定版本 BGE 模型提前获取 / 本地部署。",
    "query_answers": "影片 / 排期答案、结果契约与来源语义格式化。",
    "query_semantics": "查询域、政策种类、日期 / 范围等语义辅助。",
    "react_agent": "八节点 LangGraph、Simple / ReAct、工具执行、事实块、反思与响应。",
    "react_tools": "模型可见工具 schema、参数来源 / 查询范围 / 返回结果校验。",
    "reflection": "结构化反思结果与仅基于已有事实块的受限修订。",
    "reranker": "DashScope 重排配置、限流、响应校验和关键词候选回退。",
    "rule_verifier": "确定的 Simple 查询事实验证，减少额外模型调用。",
    "task_progress": "子任务构建、完成判定、依赖与下一步调用、执行路由。",
    "tracing": "LangSmith 元数据清洗、根 / 工具追踪、本地用户会话 JSONL 归档。",
    "versions": "提示词加载、规则 / prompt hash、稳定 A/B 分组和版本摘要。",
}


def module_index():
    lines = [
        "# AI 源码定位索引", "", "生成日期：2026-10-12；行号对应本次文档生成时的工作区。源码以后修改时行号可能变化。", "",
        "这是源码导航，完整逻辑见 [README](README.md)，图见 [SVG 图册](index.html)。不含密钥、运行日志和环境配置实际值。", "",
        "代码链接适用于本项目目录；独立分享文档包时只包含说明与图册，不包含业务源码。", "",
    ]
    for folder, title in [(AI / "app", "内部 Agent / MCP / 记忆"), (GATEWAY / "app", "独立 AI 网关")]:
        lines.extend([f"## {title}", ""])
        for path in sorted(folder.glob("*.py")):
            if path.name == "__init__.py":
                continue
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source)
            relative = path.relative_to(ROOT).as_posix()
            purpose = MODULE_PURPOSES.get(path.stem, ast.get_docstring(tree) or "模块入口。")
            if folder.parent == GATEWAY:
                purpose = {
                    "main": "网关 FastAPI 入口、身份与会话、两通道转发、停止与重置、完成后持久化、反馈。",
                    "store": "Redis 会话 / 历史 / 绑定 / 活动指针、Lua 租约 / 限流 / 取消 / 反馈锁。",
                    "feedback": "消息快照、服务端可信反馈、Java 落库与 Dify 同步状态。",
                    "protocol": "统一 SSE 编码及上游 SSE 分帧读取。",
                    "config": "服务地址、服务端 key 文件加载、Redis 与并发配置。",
                }.get(path.stem, purpose)
            lines.extend([f"### `{path.name}`", "", purpose, "", f"源码：[打开文件](../../{relative})", ""])
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(f"- `{node.name}` — 第 {node.lineno} 行。")
                    if isinstance(node, ast.ClassDef):
                        for method in node.body:
                            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                lines.append(f"  - `{method.name}`：第 {method.lineno} 行。")
            lines.append("")
    lines.extend(["## 前端", ""])
    frontend = {
        "src/chat/CinemaAssistant.tsx": "两通道聊天组件、session 连接、发问、凭证、事件、停止 / 重置与记忆建议。",
        "src/chat/chatTransport.ts": "三请求头、通道 URL、fetch SSE 分帧、complete / error 与登录失效。",
        "src/chat/MessageFeedback.tsx": "点赞 / 点踩、原因、补充文字提交。",
        "src/chat/UserMemories.tsx": "确认后长期记忆的用户管理。",
        "src/chat/messageId.ts": "消息标识处理。",
        "src/chat/assistant.css": "聊天 UI 样式。",
        "src/admin/AiFeedbackAdmin.tsx": "管理端反馈查询 / 处理。",
        "src/auth/client.ts": "请求认证与 token 失效传播。",
        "vite.config.ts": "React 插件、5173 开发服务和同源 API / 网关代理。",
    }
    for relative, purpose in frontend.items():
        path = ROOT / "cinema-ticketing-frontend" / relative
        if path.is_file():
            lines.append(f"- [{relative}](../../cinema-ticketing-frontend/{relative})：{purpose}")
    lines.extend(["", "## Java 权威业务 / 身份 / 记忆 / 反馈", ""])
    java = ROOT / "cinema-ticketing-backend/src/main/java/com/cinema/ticketing"
    files = [
        "controller/AccountSecurityController.java", "controller/InternalAiController.java",
        "controller/AiHandoffController.java", "controller/AiMemoryController.java",
        "controller/AiFeedbackController.java", "controller/AiGatewayController.java",
        "service/AuthService.java", "service/AiMovieQueryService.java", "service/AiHandoffService.java",
        "service/AiMemoryService.java", "service/AiFeedbackService.java", "service/AiGatewayService.java",
        "config/AiMemorySchemaInitializer.java", "config/AiFeedbackSchemaInitializer.java",
        "common/SellableScreenings.java",
    ]
    for relative in files:
        path = java / relative
        if path.is_file():
            lines.append(f"- [{relative}](../../{path.relative_to(ROOT).as_posix()})")
    lines.extend(["", "## 提示词、知识和版本", ""])
    for pattern in ["prompts/**/*.md", "prompts/**/*.txt", "config/*.json", "knowledge/*.md"]:
        for path in sorted(AI.glob(pattern)):
            lines.append(f"- [{path.relative_to(AI).as_posix()}](../../{path.relative_to(ROOT).as_posix()})")
    lines.extend(["", "## 评估辅助代码", "", "这些文件是开发 / 评估工具，不会因为存在就自动在生产链路执行。本文未运行它们。", ""])
    for path in sorted((AI / "evaluation").glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        purpose = (ast.get_docstring(tree) or "评估辅助模块。").splitlines()[0]
        lines.append(f"- [{path.name}](../../{path.relative_to(ROOT).as_posix()})：{purpose}")
    lines.extend(["", "## 部署与依赖", ""])
    for relative in [
        "cinema-ticketing-backend/start-ai-local.ps1", "cinema-ticketing-backend/stop-ai-local.ps1",
        "cinema-ticketing-backend/docker-compose.yml", "cinema-ticketing-backend/nginx/nginx.conf",
        "cinema-ticketing-backend/cinema-ai/requirements.txt", "cinema-ticketing-backend/cinema-ai/Dockerfile",
        "cinema-ticketing-backend/cinema-ai-gateway/requirements.txt", "cinema-ticketing-backend/cinema-ai-gateway/Dockerfile",
        "cinema-ticketing-backend/cinema-ai/.env.example", "cinema-ticketing-backend/cinema-ai-gateway/.env.example",
    ]:
        if (ROOT / relative).is_file():
            lines.append(f"- [{relative}](../../{relative})")
    (HERE / "source-index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def viewer():
    diagrams = [
        ("01-system.svg", "01 / 系统全貌", "服务、部署边界与数据职责"),
        ("02-gateway.svg", "02 / AI 网关", "身份、会话、并发、取消与完成"),
        ("03-agent-graph.svg", "03 / Agent 图与边", "八个节点、条件路径与受控回边"),
        ("04-intent.svg", "04 / 意图识别", "规则、L0、fastText、GLM 与 Qwen"),
        ("05-tools.svg", "05 / 工具与 SQL", "参数约束、MCP、Java、结果校验"),
        ("06-memory.svg", "06 / 记忆", "短期、图状态、长期与向量投影"),
        ("07-streaming.svg", "07 / SSE 与反馈", "请求时序、成功语义与失败"),
        ("08-tracing.svg", "08 / 追踪", "关联、归档、排错与数据边界"),
    ]
    source = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>影院 AI 实现 · SVG 图册</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#eef2f6;color:#203047;font:15px/1.6 'Microsoft YaHei',sans-serif}header{height:90px;padding:17px 28px;background:#13283b;color:#fff;display:flex;align-items:center;justify-content:space-between}h1{font-size:23px;margin:0}header p{margin:1px 0;color:#b9cbd9;font-size:13px}header a{color:#d7f3ec;margin-left:20px;text-decoration:none}.layout{display:grid;grid-template-columns:265px minmax(0,1fr);height:calc(100vh - 90px)}aside{background:#fff;border-right:1px solid #d9e0e8;padding:20px 14px;overflow:auto}button{font:inherit;cursor:pointer}nav button{display:block;width:100%;text-align:left;border:0;border-radius:8px;background:transparent;padding:13px 12px;color:#203047;margin-bottom:5px}nav button small{display:block;color:#617189;font-size:11px;margin-top:2px}nav button.active{background:#e2f3ee;box-shadow:inset 3px 0 #167564}aside footer{margin:25px 12px;color:#718095;font-size:12px}main{min-width:0;display:flex;flex-direction:column}.toolbar{height:60px;display:flex;align-items:center;gap:10px;padding:10px 24px;background:#f8fafc;border-bottom:1px solid #d9e0e8}.toolbar strong{margin-right:auto;font-size:14px}.toolbar button,.toolbar a{background:#fff;border:1px solid #d5dee7;padding:5px 12px;border-radius:6px;color:#28445b;text-decoration:none;font-size:13px}.viewport{overflow:auto;flex:1;padding:24px}.paper{width:100%;min-width:650px;box-shadow:0 8px 32px #10253a14;background:white}.paper img{display:block;width:100%;height:auto}#zoomLabel{min-width:45px;text-align:center;color:#617189;font-size:13px}@media(max-width:800px){.layout{grid-template-columns:1fr;height:auto}aside{padding:8px}nav{display:flex;overflow:auto}nav button{min-width:180px}aside footer{display:none}main{height:80vh}header{padding:14px;height:auto}.toolbar{padding:10px;flex-wrap:wrap;height:auto}.viewport{padding:12px}.paper{min-width:580px}header a{margin-left:8px}}
</style></head><body><header><div><h1>影院 AI 实现 · SVG 图册</h1><p>依据当前代码 · 2026-10-12 · 八张独立矢量图</p></div><div><a href="README.md" target="_blank">完整说明 ↗</a><a href="source-index.md" target="_blank">源码索引 ↗</a></div></header><div class="layout"><aside><nav id="nav"></nav><footer>默认配置不等于当前运行状态。<br>图中数据仅为机制与格式示例。<br>原始 SVG 可缩放、导出或编辑。</footer></aside><main><div class="toolbar"><strong id="current"></strong><button id="minus" aria-label="缩小">−</button><span id="zoomLabel">适宽</span><button id="plus" aria-label="放大">+</button><button id="fit">适宽</button><a id="original" target="_blank">打开 SVG ↗</a><a id="download" download>下载</a></div><div class="viewport" id="viewport"><div class="paper" id="paper"><img id="diagram" alt="影院 AI 实现图"></div></div></main></div>
<script>
const diagrams=DATA;let selected=0,zoom=1;const nav=document.getElementById('nav'),paper=document.getElementById('paper');
function scale(){paper.style.width=(zoom*100)+'%';document.getElementById('zoomLabel').textContent=zoom===1?'适宽':Math.round(zoom*100)+'%'}
function show(i){selected=i;const [file,title,desc]=diagrams[i];document.getElementById('diagram').src=file;document.getElementById('diagram').alt=title+'：'+desc;document.getElementById('current').textContent=title;document.getElementById('original').href=file;document.getElementById('download').href=file;document.querySelectorAll('nav button').forEach((b,j)=>b.classList.toggle('active',i===j));document.getElementById('viewport').scrollTo(0,0);zoom=1;scale();location.hash=String(i+1)}
diagrams.forEach(([file,title,desc],i)=>{const b=document.createElement('button');b.append(document.createTextNode(title));const s=document.createElement('small');s.textContent=desc;b.append(s);b.onclick=()=>show(i);nav.append(b)});
document.getElementById('plus').onclick=()=>{zoom=Math.min(3,zoom+.25);scale()};document.getElementById('minus').onclick=()=>{zoom=Math.max(.5,zoom-.25);scale()};document.getElementById('fit').onclick=()=>{zoom=1;scale()};const initial=parseInt(location.hash.slice(1),10)-1;show(initial>=0&&initial<diagrams.length?initial:0);
</script></body></html>""".replace("DATA", json.dumps(diagrams, ensure_ascii=False))
    source = source.replace('href="README.md"', 'href="implementation.html"').replace('href="source-index.md"', 'href="source-index.html"')
    (HERE / "index.html").write_text(source, encoding="utf-8")


def readable_documents():
    """Use an already installed Markdown renderer for optional offline HTML copies."""
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        print("markdown_it unavailable: Markdown and SVG deliverables remain usable.")
        return
    for filename, output, title in [
        ("README.md", "implementation.html", "影院 AI 完整实现说明"),
        ("source-index.md", "source-index.html", "AI 源码定位索引"),
    ]:
        body = MarkdownIt("commonmark", {"html": False}).render((HERE / filename).read_text(encoding="utf-8"))
        headings = []

        def heading(match):
            index = len(headings) + 1
            headings.append((index, match.group(1)))
            return f'<h2 id="section-{index}">{match.group(1)}</h2>'

        body = re.sub(r"<h2>(.*?)</h2>", heading, body)
        toc = "".join(f'<a href="#section-{index}">{label}</a>' for index, label in headings)
        page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TITLE</title><style>
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:25px}body{margin:0;color:#25374b;background:#f3f6f9;font:16px/1.95 'Microsoft YaHei',sans-serif}aside{position:fixed;inset:0 auto 0 0;width:290px;background:#142a3e;color:#d5e0ea;padding:24px;overflow:auto}aside strong{font-size:20px;display:block;margin-bottom:15px}aside a{display:block;color:#c5d7e4;text-decoration:none;font-size:13px;padding:6px 0}aside .toplink{color:#a2e4cd;font-size:15px;margin-bottom:15px}main{margin-left:290px;padding:40px 55px 80px}article{max-width:1040px;margin:0 auto;background:#fff;padding:40px 54px;border:1px solid #e1e7ed}h1{font-size:30px;color:#142a3e;margin-top:0}h2{font-size:23px;margin-top:48px;padding-top:20px;border-top:1px solid #dce6ec;color:#175d51}h3{font-size:18px;margin-top:28px}a{color:#176b94;text-underline-offset:3px}pre{padding:18px 22px;background:#eff4f7;border-radius:6px;overflow:auto;font:13px/1.8 Consolas,monospace}code{font-family:Consolas,monospace;font-size:.9em;background:#edf3f6;padding:2px 4px;border-radius:3px}pre code{padding:0;background:none}blockquote{border-left:3px solid #167564;margin:20px 0;padding:5px 18px;background:#edf7f3;font-size:14px;color:#46655d}li{margin:7px 0}strong{color:#172e45}aside strong{color:white}@media(max-width:900px){aside{position:static;width:auto;max-height:220px}main{margin:0;padding:15px}article{padding:22px}}@media print{aside{display:none}main{margin:0;padding:0}article{border:0;padding:0;max-width:none}h2{break-after:avoid}pre{white-space:pre-wrap}}
</style></head><body><aside><strong>TITLE</strong><a class="toplink" href="index.html">← SVG 图册</a>TOC</aside><main><article>BODY</article></main></body></html>"""
        page = page.replace("TITLE", esc(title)).replace("TOC", toc).replace("BODY", body)
        page = page.replace('href="source-index.md"', 'href="source-index.html"')
        (HERE / output).write_text(page, encoding="utf-8")


def main():
    for build in (system, gateway, graph, intent, tools, memory, streaming, tracing):
        build()
    module_index()
    readable_documents()
    viewer()
    print("Generated 8 SVGs, source-index.md and index.html; no service calls.")


if __name__ == "__main__":
    main()
