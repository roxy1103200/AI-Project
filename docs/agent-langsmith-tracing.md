# 内部 Agent 的 LangSmith 追踪

内部 Agent 已接入 LangSmith，用于本地或预发环境定位“回答未完成”。追踪采用后台批量上报，LangSmith 不可用时不会中断影院问答。Dify 云端工作流不在这次追踪范围内。

## 开启与配置

密钥只放在 `API/langsmith.txt`，支持一行密钥或 `LANGSMITH_API_KEY=...`；也支持服务端环境变量 `LANGSMITH_API_KEY` 覆盖文件。不要放进前端配置。

在 `cinema-ticketing-backend/cinema-ai/.env` 中设置：

```dotenv
AI_ENVIRONMENT=local
LANGSMITH_TRACING=true
LANGSMITH_API_KEY_FILE=../../API/langsmith.txt
LANGSMITH_PROJECT=cinema-agent-local
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# 组织级服务密钥必须指定工作空间；工作空间级密钥可以不填。
LANGSMITH_WORKSPACE_ID=
```

当前本地 `.env` 已按 US 地址开启追踪。环境变量优先于 `.env`。允许的环境为 `local/development/dev/test/staging/preprod`；未配置环境时视为生产，生产环境即使设置 `LANGSMITH_TRACING=true` 也不会开启本模块的追踪。关闭时设置 `LANGSMITH_TRACING=false`。

本地追踪文件存放在项目根目录 `langsmith(tracing)/YYYY_MM_DD/`，按北京时间生成日期目录，例如 `langsmith(tracing)/2026_10_10/`。`traces.jsonl` 逐条追加 span 创建和结束事件，`verification.json` 保存最近一次云端链路验证结果。上传和落盘均只保留脱敏摘要。

修改配置后重启内部 Agent；首次应用这次代码改动也需要重启 AI 网关，用来记录追踪关联编号。Java、MCP 和前端无需因这次改动而重启。已有其他服务可继续运行，在项目根目录执行：

```powershell
./cinema-ticketing-backend/stop-ai-local.ps1 -Service agent
./cinema-ticketing-backend/start-ai-local.ps1 -Service agent
./cinema-ticketing-backend/stop-ai-local.ps1 -Service gateway
./cinema-ticketing-backend/start-ai-local.ps1 -Service gateway
```

Agent `/health` 的 `tracing.enabled` 只表示本地配置生效，不代表云端已经收到数据。需要通过下文的回读验证确认交付。

## 能看到什么

在 LangSmith 的 `cinema-agent-local` 项目中，每轮回答有一个 `cinema.agent.live` 或 `cinema.agent.chat` 根记录：

- LangGraph 实际执行的 `prepare/clarify/agent/tools/respond` 节点、执行顺序及耗时。
- LangChain 模型调用及耗时；供应商返回且能保留的 token 用量摘要。
- `tool.search_movies` 等具体工具调用，包括 MCP 查询与本地规则、推荐工具，及其耗时和失败状态。
- 最终状态 `completed/failed/interrupted`、稳定错误码，以及捕获后没有向上抛出的异常事件 `agent_failure`。
- 会话的散列关联标识，可以关联同一用户的同一会话，不上传原始用户 ID 或会话 ID。

当前采用 `metadata_only` 模式：不上传完整问题、历史、答案、工具参数、订单记录、业务结果、模型配置密钥或异常正文。只能看到字符数、条目数、受控意图和错误码等摘要。因此可以定位失败阶段与耗时，不能直接在 LangSmith 中阅读或回放原始对话。

## 定位“回答未完成”

1. 在 `cinema-ticketing-backend/target/ai-gateway-stderr.log` 查找发生时刻的 `message_id`。同一日志行会记录 Agent 返回的 `trace_id`。网关不会把内部追踪事件展示成聊天消息。
2. 在 LangSmith 中用该追踪 UUID 找到对应根记录，查看耗时最长或失败的节点、模型或工具。
3. 查看 `agent_failure` 事件的 `stage/exception_type/error_code/http_status`，与 `ai-agent-stderr.log` 中相同 `trace_id` 的失败日志对照。
4. `query_timeout` 表示整轮或查询超时；`interrupted` 表示停止/取消；`stream_incomplete` 表示流结束时没有正常完成或明确错误事件。`model_auth_failed/model_rate_limited/business_unavailable` 等沿用现有错误分类。

被捕获并成功降级的异常也会记录事件和失败次数，根记录仍可能是 `completed`。不能把“出现过异常”和“最终回答失败”混为一谈。完整退出服务时会尝试清空追踪队列；强制结束进程可能丢失未上传记录。

网关把 `trace_id` 保存在该回答的 Redis 反馈摘要中，保留时间沿用现有摘要 TTL；未新增 Java 数据表或后台追踪详情页。网关日志用于更长期的编号关联，需要按部署环境配置日志保留周期。

## 验证云端链路

在项目根目录执行：

```powershell
./cinema-ticketing-backend/cinema-ai/.venv/Scripts/python.exe ./cinema-ticketing-backend/cinema-ai/scripts/check_langsmith.py
```

脚本先核验云端项目访问权限，再上传一条成功和一条工具失败的合成追踪，回读所有后代节点，核对模型/工具/节点关系、最终错误码以及私有诊断文本没有上传。模型使用本地模拟实现，不调用 Qwen、Java、MCP 或数据库。

当天验证报告写入 `langsmith(tracing)/YYYY_MM_DD/verification.json`，与本地追踪追加日志 `traces.jsonl` 放在一起。只有 `verified=true` 才表示云端上传与回读都成功；失败报告只含阶段、异常类型和 HTTP 状态，不输出密钥或远端错误正文。

2026-10-10 已使用更新后的 US 密钥完成上传和回读验证：成功、工具失败两条追踪各含 8 个记录，节点、模型、工具耗时可读，失败根记录为 `business_unavailable`，私有诊断文本未上传。本地日归档记录了 32 个 span 生命周期事件。此次验证采用合成流程，实际 Qwen 问答需要在重启 Agent 和网关后继续观察。

US 接口返回 403 时，需要检查密钥权限、有效期、工作空间归属及工作空间 ID。尤其是组织级服务密钥，官方要求对工作空间资源发送 `X-Tenant-Id`；本项目会将 `LANGSMITH_WORKSPACE_ID` 转换为这个请求头，兼容目前固定的 SDK 版本。不能仅凭 403 断定密钥内容错误。参见 [LangSmith 密钥说明](https://docs.langchain.com/langsmith/create-account-api-key) 与 [组织和工作空间 API 鉴权](https://docs.langchain.com/langsmith/manage-organization-by-api)。

SDK 固定为 `langsmith==0.3.45`。输出过滤在 SDK 的创建、更新以及运行环境附加环节执行；升级 SDK 时需重新运行 `tests/test_tracing.py`，确认没有绕过过滤边界。日志中的 `LangSmith SDK event category=authentication/connection/...` 是脱敏后的上传诊断，不能作为回答本身成功或失败的判断依据。
