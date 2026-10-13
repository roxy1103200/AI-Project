# Agent 任务可靠性修复（2026-10-10）

## 当前状态

代码修复及真实复测已完成。虚拟机恢复后完成 96 次同版 rerank 开关对照、48 次排序专项，以及当前运行服务的 12 个退出检查。结果见 [当前服务与新评测](agent-runtime-evaluation-2026-10-10.md)。此前开发数据用于现有 Qwen 评测的授权继续适用。

正式测量前发现并修复模型将空日期传成字符串 `"None"` 导致三次重复参数拒绝的问题。内部 Agent 已重启加载修复；当前服务复查全部收到结束事件。固定问题集的关键事实验收不能等同完整语义审计或线上成功率。

## 已处理的问题

### 退票规则一致性

- 新增 `RefundPolicyText`，以业务实际使用的 `cutoff_minutes` 生成截止说明，并同步常见中文截止表达中的分钟数。
- 内部 AI 接口、管理端读取、管理端发布及订单错误说明使用同一个格式器。
- 旧记录在读取时归一化；新发布规则持久化归一化正文。没有修改现有开发库的截止数值或删除历史版本。
- 明确到达截止时间及之后不能退票，与订单服务的严格时间比较保持一致。
- Agent 回答使用实时数值，知识片段不能覆盖它；具体订单资格继续使用 `can_refund` 与 `refund_reason`。

### 多订单与无效日期

- 从用户文本独立提取 `order_nos`，保持 `order_no` 单值字段兼容，避免模型漏提编号导致误追问。
- 用户要求多个订单时逐一建立任务，查询权限继续由 Java 按登录用户校验。
- 无效日期直接说明具体日期不存在，不再降为泛化的“补充问题”。
- 日期来自用户当前要求或明确的追问继承，不采用模型猜测日期；补充订单号时保留退票资格意图。

### ReAct 完成检查

- 新增 `task_progress.py`：拆分影片资料、场次、座位、多个订单、推荐和规则查询；按已校验结果检查每项完成情况。
- 完成后立即停止，不再为了让模型输出“完成”增加一轮决策；同一批中剩余调用也会停止。
- 用户未要求的业务工具被拦截。推荐完成后无需继续查排期；空影片资料无需改范围重试。
- 模型提前结束时，可按清单补查尚未完成的任务；依赖不存在或多场次未选择时，保留空结果或追问。
- 第一场、前两场、逐场查询依据本轮真实场次结果解析，不能任意换成其他有效编号。
- 预算不足时列出未完成项；刚好用完预算但任务已完成时不显示“查询上限”提示。

### 参数约束与预算

- 参数按子任务应用：导演/片长资料查询使用 `catalog`，同一问题中的场次查询使用其日期和排期范围。
- 初次抽取的上映范围不再固定所有后续工具；来自用户或已校验结果的关键词可用于修正抽取。
- 业务调用预算默认 4 次；无效调用/重复调用独立最多 3 次。两项都有硬上限，保持重复请求和伪造身份拦截。
- `ask_user` 不消耗业务调用预算，已提供订单号/有效日期时不重复索要。
- 可选日期的空字符串、`None`、`null` 文本统一为 JSON null；用户明确提供的真实日期仍严格校验，不能被模型擦除或替换。

### 知识召回

- Java 不再用完整自然语言问题作单个 `LIKE`。
- 提取领域主题词、中文词组和英文词，统一退款/退票、买票/购票、付款/支付、选座/座位等表达。
- SQL 使用绑定参数，仅查询已发布文档，候选上限 60，标题与正文匹配排序后返回最多 20 篇。
- 后续仍执行原有切片、去重、候选限制与可关闭的云端 rerank。
- 这是有界词法召回，没有引入向量库；对复杂语义及大知识库的效果仍需真实数据验证。

## 独立评测维度

- `task_success_rate`：保持严格验收，要求工具链、关键事实和正常完成同时通过。
- `answer_correct_rate`：关键事实检查通过且正常完成，与工具链分开统计；需结合原始答复人工复核。
- `tool_correct_rate`：工具名称、参数、身份、允许顺序正确，并且没有无效调用。
- `extra_tool_task_rate`：至少一次多余实际业务调用的任务比例。
- `extra_tool_call_rate`：多余调用数 / 全部实际业务调用数。按允许方案作最大一一匹配，漏查和单纯顺序错误不当作多查。
- `rejected_task_rate`：发生参数拒绝或重复调用拒绝的任务比例，与多余业务调用分开。

保留 TTFT、完整耗时 P50/P95、聊天与重排调用、Token、成本和逐题原始轨迹。新增任务进度、参数拒绝原因、Java 源码与 JAR 哈希。历史严格原判和人工复核不覆盖。

## 本地验证

- Python 意图、ReAct、子任务、rerank、评测与 MCP 的 83 项针对性回归通过，包含本轮新增的空日期与明确日期约束检查。
- Java 34 项通过：规则格式 3、规则接口一致性 4、知识召回 4、订单核心流程 8、影片查询 10、管理接口 5。
- 召回包含 H2 实际 SQL 验证：自然语言可召回规则，草稿文档不进入结果。
- Python Ruff 检查、Java 打包、前端 TypeScript 构建、报告 JavaScript 语法及 5 个分组的执行检查通过。
- 订单回归中一处旧测试替身未匹配现有 SQL 的两个时间参数，已同步测试参数；没有改变锁座或订单创建业务。

## 生效与真实复测

Java 构建产物已用于隔离评测；当前 Java 接口的规则正文、数值和新知识召回均已核对。内部 Agent 已重启，原有模型与中间件配置沿用。未来源码改动仍需重建/重启对应服务。

本轮已完成以下复测流程；后续复用时更换输出目录，保留本轮原始记录：

```powershell
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\reliability-prepared-20261010 --prepare-only
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\reliability-rerank-ab-20261010 --manifest ..\target\agent-evaluation\reliability-prepared-20261010\cases.json --baseline-mode rerank-off --repeats 2
.venv\Scripts\python.exe -m evaluation.verify_snapshot ..\target\agent-evaluation\reliability-rerank-ab-20261010
.venv\Scripts\python.exe -m evaluation.rerank_focus --output ..\target\agent-evaluation\reliability-rerank-evidence-20261010 --prepare-only
.venv\Scripts\python.exe -m evaluation.rerank_focus --output ..\target\agent-evaluation\reliability-rerank-evidence-20261010
.venv\Scripts\python.exe -m evaluation.report ..\target\agent-evaluation\reliability-rerank-ab-20261010 --evidence-directory ..\target\agent-evaluation\reliability-rerank-evidence-20261010
```

端到端继续使用原 24 个问题模板，各版 2 轮，共 96 次；重新冻结当日真实业务事实和预期方案。规则排序专项继续 12 题、48 次，两版使用相同冻结候选。先完成端到端计时，再执行排序专项。

同版开关实验用于判断 rerank 当前收益；与 2026-10-09 的结果对比时，应披露修复、预算计数和业务快照变化，不能把跨日差值全部归因于 rerank。
