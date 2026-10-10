# 影院 Agent 真实模型对照评测

对照 `039085e` 的旧版网站聊天流程与当前 ReAct 的 `Assistant.live`，使用相同 Qwen 模型和真实开发 Java / MySQL / Redis。MCP 使用独立监听器和官方 SDK，Java 使用独立端口 18080；退出时关闭本次启动的服务。初始化建表、RabbitMQ 消费与过期订单清理在评测服务中关闭。

## 数据与外部服务

准备阶段只在本地读取数据并固化题库、业务快照。正式评测会把问题及工具返回的业务信息发送至项目配置的外部 Qwen 服务，包括选定开发账户的订单号、状态、金额、座位及退票信息。密钥和内部令牌只用于鉴权，不写入问题、记录或报告。

```powershell
cd E:\development\AI-Project\cinema-ticketing-backend\cinema-ai
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\prepared --prepare-only
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\measured --manifest ..\target\agent-evaluation\prepared\cases.json --repeats 2
.venv\Scripts\python.exe -m evaluation.report ..\target\agent-evaluation\measured
```

先验证数据准备，再进行完整测量。若中断，可用相同目录和参数继续，已持久化的任务不会再次收费执行。正式数据不能混入试跑结果。更换问题、模型或源码时使用新目录。

默认读取 `.env` 和现有 Qwen 配置。开发库默认地址 `192.168.100.133`；可用 `EVAL_DB_HOST`、`EVAL_DB_PASSWORD`、`EVAL_MYSQL_EXE`、`EVAL_JAVA_EXE`、`EVAL_JAVA_PORT` 覆盖。依赖现有 Java 构建产物和 MySQL CLI，不自动创建或修改业务数据。长期记忆在两版中均关闭，以隔离记忆检索和个人偏好对任务的影响。

规则与召回 Java 代码改动后必须先在后端重新构建：`mvn -DskipTests package`。评测使用独立 Java 进程加载该构建产物，不会自动让已运行的网站服务升级。

## 问题集与规则

24 个固定问题模板：12 道基础查询、6 道组合查询、4 道参数澄清、2 道身份/交易边界题。绑定数据后写出 `cases.json`，在任何计分模型调用前冻结。未来有效场次用于座位题；历史明确日期用于排期和票价题。数据中若只有一个未来场次，如实保留这一限制，不凭空制造多场次测试结果。

每版每题重复 2 次，合计 96 次任务。题序用固定随机种子打乱，同题新旧版本交替执行；并发数为 1。Qwen 温度、输出上限和思考模式沿用项目配置。当前 ReAct 固定 4 次实际业务调用、另限 3 次无效调用，二者分别留存；2026-10-09 的旧口径为 4 次工具尝试，跨日对比需披露这处实现变化。旧版直接加载 Git 保存的 `main.py`，不重写旧版决策逻辑。

- **任务成功率**：正确工具链、参数和身份、关键事实检查通过、SSE 正常结束，四项同时满足的任务数 / 全部任务数。失败和澄清均保留在分母中，同时提供各组结果。
- **工具链正确率**：整题的业务工具选择、参数、调用顺序及可信用户身份完全符合独立声明的允许方案，且没有被拒绝的模型调用尝试。允许多种等价查询路径；必要澄清与拒绝题的正确行为是不调用业务工具。
- **答案关键事实通过率**（`answer_correct_rate`）：声明的关键事实检查通过且正常结束的任务比例，独立于工具链；这是可复核的规则评分，不等于完整语义审计。正确纯数字座位数量在两版对称接受。
- **多余调用任务率**（`extra_tool_task_rate`）：至少一次不在允许工具方案中的实际业务调用的任务数 / 全部任务数。按工具名称、参数和身份作最大一一匹配，忽略顺序；漏查不会被误记为多查，顺序错误由工具链指标单独判定。
- **多余调用占比**（`extra_tool_call_rate`）：多余业务调用数 / 实际业务调用总数。另列无效调用任务率（`rejected_task_rate`），不将参数被拒与已经执行的多余查询混合。
- **首字时间**：从进入 `Assistant.live` 到第一条非空答复 `delta`；状态和上下文事件不算首字。没有答复的失败任务没有首字值，单独显示样本数。
- **完整耗时**：从同一入口到流结束或失败；主指标包含失败任务，另列成功任务耗时。P50/P95 使用排序后线性插值。计时不包含服务启动、预取判定数据、登录、网关和浏览器网络。
- **调用与 Token**：记录理解、工具决策和最终回复的全部 SDK 逻辑调用及异常；流式回复开启供应商 usage 返回。未返回 usage 的调用记为缺失，不能当成 0 Token。SDK 内部的 HTTP 重试不单独计为模型调用。
- **费用**：按供应商返回的输入、输出、缓存命中 Token，结合阿里云北京地域公开原价估算；这是估算费用，不是账单扣费。每次输入不超过 32K 时，输入/输出/缓存输入分别为 0.2/0.8/0.04 元/百万 Token，更长输入按阶梯处理。来源：[官方价格](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)，核对日期 2026-10-09。未返回 usage 或调用失败时，费用可能不完整；优惠、赠送额度和实际账单不在此估算中。

## 留存证据

所有输出保存在项目忽略的 `target/agent-evaluation/<run>` 下：

- `metadata.json`：代码版本、配置、题库与数据快照哈希。
- `cases.json`、`snapshot.json`：固定问题、独立预期方案及本地业务判定数据。
- `baseline_main.py`：本次实际运行的旧版本入口。
- `trials.jsonl`：逐题答复、实际业务工具轨迹、参数校验、Token、首字和完成时间。
- `summary.json`、`report.html`：整体及分组对照统计和可直接打开的报告。
- `review.json`、`reviewed_summary.json`：逐题人工复核的修正及原因、复核后的统计；不覆盖原始自动判定，也不再次调用模型。
- `stability.json`：评测后重读业务数据的核对；仅排除每次响应都变化的订单 `server_time`，其余影片、排期、座位、订单和规则字段完整比较。

原始自动判定保留在 `trials.jsonl` 与 `summary.json`。人工复核同时检查成功与失败样本，修正必须精确到问题、版本和轮次并写明原因；同一原则对两版同时适用。HTML 展示复核后的结果及原判，不通过改题或选择性重跑提高成绩。重新生成报告时会自动读取同目录的 `review.json`。

```powershell
.venv\Scripts\python.exe -m evaluation.verify_snapshot ..\target\agent-evaluation\measured
```

这些数据只能支持“固定开发业务问题集上的验收评测”。24 题的小样本 P95 不能作为线上 SLA，测试成功率不能称为生产用户成功率。自动事实规则只检查声明的关键事实，并非逐字语义审计；报告保留每题答复供复核。旧流程更快或更省费用时也应如实呈现。

## Rerank 同版开关对照

`--baseline-mode rerank-off` 在两个独立 Assistant 实例中运行同一份工作区源码，仅重排开关不同。会保存未提交的业务 Python 源码、知识文档和哈希，避免仅凭 HEAD 错认实际测量版本；不会修改项目 `.env` 或已有服务。

当前同时留存 Java 源码、JAR 哈希和逐题 `task_progress`、拒绝原因。历史原始评分不覆盖；重新生成报告会补算独立维度，人工修正及原判继续保留。评测后应运行 `evaluation.verify_snapshot` 核对业务事实稳定性。

```powershell
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\rerank-prepared --prepare-only
.venv\Scripts\python.exe -m evaluation.run --output ..\target\agent-evaluation\rerank-ab --manifest ..\target\agent-evaluation\rerank-prepared\cases.json --baseline-mode rerank-off --repeats 2
.venv\Scripts\python.exe -m evaluation.rerank_focus --output ..\target\agent-evaluation\rerank-evidence --prepare-only
.venv\Scripts\python.exe -m evaluation.rerank_focus --output ..\target\agent-evaluation\rerank-evidence
.venv\Scripts\python.exe -m evaluation.report ..\target\agent-evaluation\rerank-ab --evidence-directory ..\target\agent-evaluation\rerank-evidence
```

专项准备默认拥有并关闭独立 Java/MCP 服务，也可用 `--java-url` 复用可用 Java。云端排序专项在端到端计时结束后执行，使用已冻结的真实候选；不生成回答。候选相关性规则在首次计分重排前声明，10 道有答案题纳入 Top1/MRR/NDCG 分母，2 道无答案题单列。测量输出已有 `trials.jsonl` 时拒绝静默重复执行。

评测中的 `rerank_calls` 分别记录关闭、跳过、真实云端成功、回退，以及原生 usage、候选与来源、实际选中片段。报告按聊天和重排分别记账，并显示合计模型请求、Token 与估算费用。native usage 缺失不会当作免费调用。此处价格仅适用于本轮北京地域 `qwen3.7-text-rerank`。

## 当前运行服务与循环排查

`runtime_check` 直接请求已运行的内部 Agent，不启动替代实例、不重启业务服务，串行保存 SSE 事件、工具计数和任务进度。默认检查 8 道普通、组合、澄清问题，可用 `--case-ids` 选择已有题号。请求沿用项目 Qwen 配置；更换输出目录以保留已有诊断。

```powershell
.venv\Scripts\python.exe -m evaluation.runtime_check --manifest ..\target\agent-evaluation\prepared\cases.json --output ..\target\agent-evaluation\runtime-check
.venv\Scripts\python.exe -m evaluation.loop_audit ..\target\agent-evaluation\measured
.venv\Scripts\python.exe -m evaluation.report ..\target\agent-evaluation\measured --runtime-directory ..\target\agent-evaluation\runtime-check
```

`loop_audit` 离线统计同一请求内同参数工具的重复执行、模型重复提议、超时、决策轮数及预算越界，输出 `loop-audit.json`。相同工具查询两个不同订单/场次不会被算成重复。当前服务 SSE 不暴露完整工具参数，因此精确参数重复需结合仪表化的正式评测轨迹；收到 complete 与完整满足用户任务分开统计，预算题可能正常退出并返回部分结果。
