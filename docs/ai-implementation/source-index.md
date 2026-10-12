# AI 源码定位索引

生成日期：2026-10-12；行号对应本次文档生成时的工作区。源码以后修改时行号可能变化。

这是源码导航，完整逻辑见 [README](README.md)，图见 [SVG 图册](index.html)。不含密钥、运行日志和环境配置实际值。

代码链接适用于本项目目录；独立分享文档包时只包含说明与图册，不包含业务源码。

## 内部 Agent / MCP / 记忆

### `agent_budget.py`

整轮模型次数、token 预留 / 对账、期限与熔断包装。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/agent_budget.py)

- `configured_limit` — 第 11 行。
- `CircuitOpen` — 第 16 行。
- `RequestBudget` — 第 21 行。
  - `trip`：第 34 行。
  - `remaining_seconds`：第 39 行。
  - `reserve`：第 49 行。
  - `reconcile`：第 62 行。
  - `snapshot`：第 74 行。
- `BudgetedModel` — 第 88 行。
  - `__init__`：第 91 行。
  - `bind`：第 105 行。
  - `bind_tools`：第 111 行。
  - `ainvoke`：第 117 行。

### `clarification_feedback.py`

脱敏补槽样本 SQLite 收集与待审核质量标记。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/clarification_feedback.py)

- `deidentify` — 第 20 行。
- `filled_slots` — 第 34 行。
- `ClarificationFeedback` — 第 53 行。
  - `__init__`：第 56 行。
  - `connect`：第 59 行。
  - `record`：第 72 行。
- `record_feedback` — 第 150 行。

### `failures.py`

异常归类、安全日志、固定用户提示和追踪失败事件。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/failures.py)

- `CinemaQueryError` — 第 21 行。
  - `__init__`：第 25 行。
- `describe_failure` — 第 33 行。
- `_failure_details` — 第 68 行。

### `glm_router.py`

GLM L1 模型配置、适用性、结构化预测校验、并发和冷却。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/glm_router.py)

- `timeout_seconds` — 第 27 行。
- `GlmPrediction` — 第 32 行。
- `load_glm_key` — 第 49 行。
- `create_glm_model` — 第 67 行。
- `eligible` — 第 95 行。
- `apply_prediction` — 第 109 行。
- `classify` — 第 165 行。

### `intent.py`

QuestionPlan、同义化、日期 / ID 规则、结构化理解与最终槽位校验。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/intent.py)

- `QuestionPlan` — 第 73 行。
- `beijing_today` — 第 113 行。
- `explicit_date` — 第 120 行。
- `listing_kind` — 第 165 行。
- `general_listing` — 第 204 行。
- `normalize_question` — 第 310 行。
- `rule_plan` — 第 327 行。
- `understand` — 第 496 行。

### `intent_classifier.py`

可选 fastText 加载门槛、hash / 清单验证与置信分类。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/intent_classifier.py)

- `classifier_text` — 第 18 行。
- `load_classifier` — 第 26 行。
- `predict_intent` — 第 45 行。

### `intent_routing.py`

预检、L0 / 本地分类路径、理解层与槽位摘要。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/intent_routing.py)

- `preliminary_route` — 第 12 行。
- `slot_summary` — 第 83 行。

### `java_client.py`

内部 token HTTP 客户端，复用 Java 的业务接口。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/java_client.py)

- `JavaApiClient` — 第 15 行。
  - `__init__`：第 19 行。
  - `get`：第 33 行。
  - `post`：第 43 行。
  - `aclose`：第 53 行。

### `main.py`

FastAPI 入口、模型与工具组装、/ai/live 与兼容接口、特殊记忆分支。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/main.py)

- `create_tools` — 第 63 行。
- `ChatRequest` — 第 135 行。
- `HistoryMessage` — 第 147 行。
- `LiveChatRequest` — 第 157 行。
- `ChatResponse` — 第 165 行。
- `Assistant` — 第 200 行。
  - `__init__`：第 204 行。
  - `_call_tool`：第 243 行。
  - `chat`：第 257 行。
  - `_chat`：第 270 行。
  - `live`：第 320 行。
  - `_live`：第 337 行。
- `lifespan` — 第 412 行。
- `verify_internal_token` — 第 441 行。
- `health` — 第 452 行。
- `chat` — 第 461 行。
- `stream` — 第 470 行。
- `_live_event` — 第 487 行。
- `_business_answer` — 第 493 行。
- `_seat_answer` — 第 541 行。
- `live` — 第 566 行。
- `handle_http_error` — 第 595 行。

### `mcp_client.py`

带可信身份的独立 MCP session 与四个查询工具调用。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/mcp_client.py)

- `CinemaMcpClient` — 第 27 行。
  - `__init__`：第 31 行。
  - `call_tool`：第 38 行。

### `mcp_server.py`

私网 Streamable HTTP MCP Server、工具 schema、Java 适配。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/mcp_server.py)

- `tool_result` — 第 59 行。
- `InternalTokenMiddleware` — 第 73 行。
  - `__init__`：第 77 行。
  - `__call__`：第 84 行。
- `create_app` — 第 105 行。

### `memory.py`

用户记忆建议、BGE 嵌入、Chroma 投影 / 召回、Java 权威再验证。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/memory.py)

- `MemoryIndex` — 第 34 行。
  - `__init__`：第 38 行。
  - `connect`：第 50 行。
  - `_encode`：第 83 行。
  - `encode`：第 103 行。
  - `apply`：第 118 行。
- `UserMemory` — 第 156 行。
  - `__init__`：第 160 行。
  - `recall`：第 167 行。
- `memory_proposal` — 第 236 行。

### `memory_runtime.py`

本地 Chroma 与 memory worker 启动器。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/memory_runtime.py)

- `main` — 第 23 行。

### `memory_worker.py`

MySQL outbox 租约任务消费、版本检查、索引与确认。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/memory_worker.py)

- `process_job` — 第 20 行。
- `run` — 第 51 行。

### `model_config.py`

Qwen 服务端密钥加载与 ChatOpenAI 参数。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/model_config.py)

- `load_qwen_key` — 第 28 行。
- `create_model` — 第 61 行。

### `policy_retrieval.py`

本地 Markdown / Java 知识分块、关键词召回与合并去重。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/policy_retrieval.py)

- `keyword_terms` — 第 28 行。
- `split_documents` — 第 35 行。
- `KeywordRetriever` — 第 58 行。
  - `_get_relevant_documents`：第 67 行。
- `load_retriever` — 第 79 行。
- `policy_candidates` — 第 95 行。

### `provision_memory_model.py`

固定版本 BGE 模型提前获取 / 本地部署。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/provision_memory_model.py)


### `query_answers.py`

影片 / 排期答案、结果契约与来源语义格式化。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/query_answers.py)

- `valid_movie_result` — 第 13 行。
- `valid_screening_result` — 第 130 行。
- `movie_details` — 第 163 行。
- `movie_answer` — 第 186 行。
- `policy_answer` — 第 272 行。
- `screening_answer` — 第 291 行。

### `query_semantics.py`

查询域、政策种类、日期 / 范围等语义辅助。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/query_semantics.py)

- `prose` — 第 15 行。
- `movie_fields` — 第 20 行。
- `policy_kind` — 第 29 行。
- `query_domains` — 第 37 行。

### `react_agent.py`

八节点 LangGraph、Simple / ReAct、工具执行、事实块、反思与响应。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/react_agent.py)

- `AgentState` — 第 83 行。
- `initial_state` — 第 142 行。
- `emit_context` — 第 168 行。
- `response_data` — 第 206 行。
- `CinemaReAct` — 第 230 行。
  - `__init__`：第 234 行。
  - `prepare`：第 270 行。
  - `route_prepared`：第 348 行。
  - `clarify`：第 360 行。
  - `fallback_call`：第 365 行。
  - `agent`：第 469 行。
  - `tools`：第 521 行。
  - `factual_answer`：第 633 行。
  - `respond`：第 687 行。
  - `has_primary_evidence`：第 726 行。
  - `completion_note`：第 742 行。
  - `trip`：第 769 行。
  - `guard_step`：第 776 行。
  - `route_after_agent`：第 798 行。
  - `route_after_tools`：第 805 行。
  - `route_after_reflection`：第 812 行。
  - `simple`：第 816 行。
  - `draft`：第 831 行。
  - `reflect`：第 836 行。

### `react_tools.py`

模型可见工具 schema、参数来源 / 查询范围 / 返回结果校验。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/react_tools.py)

- `ToolArguments` — 第 31 行。
- `MovieArguments` — 第 39 行。
- `ScreeningArguments` — 第 62 行。
- `SeatArguments` — 第 81 行。
- `OrderArguments` — 第 89 行。
- `PolicyArguments` — 第 97 行。
- `RecommendationArguments` — 第 105 行。
- `ClarificationArguments` — 第 113 行。
- `validate_arguments` — 第 186 行。
- `validate_result` — 第 393 行。
- `observation_text` — 第 441 行。

### `reflection.py`

结构化反思结果与仅基于已有事实块的受限修订。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/reflection.py)

- `ReflectionResult` — 第 13 行。
- `grounded_revision` — 第 27 行。

### `reranker.py`

DashScope 重排配置、限流、响应校验和关键词候选回退。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/reranker.py)

- `RerankSettings` — 第 41 行。
  - `__post_init__`：第 58 行。
  - `from_env`：第 100 行。
- `_Rank` — 第 120 行。
- `_Output` — 第 128 行。
- `_Response` — 第 134 行。
- `DashScopeReranker` — 第 144 行。
  - `__init__`：第 148 行。
  - `rerank`：第 171 行。
  - `_request`：第 226 行。
  - `_select`：第 267 行。
  - `_log_fallback`：第 294 行。
  - `_log_success`：第 309 行。
  - `aclose`：第 333 行。

### `rule_verifier.py`

确定的 Simple 查询事实验证，减少额外模型调用。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/rule_verifier.py)

- `verify_simple` — 第 10 行。

### `task_progress.py`

子任务构建、完成判定、依赖与下一步调用、执行路由。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/task_progress.py)

- `build_tasks` — 第 22 行。
- `screening_rows` — 第 109 行。
- `progress` — 第 137 行。
- `is_complete` — 第 235 行。
- `next_call` — 第 244 行。
- `select_route` — 第 265 行。
- `matching_task` — 第 283 行。

### `tracing.py`

LangSmith 元数据清洗、根 / 工具追踪、本地用户会话 JSONL 归档。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/tracing.py)

- `SdkLogFilter` — 第 196 行。
  - `filter`：第 200 行。
- `_filter_sdk_logs` — 第 225 行。
- `load_langsmith_key` — 第 237 行。
- `_label` — 第 282 行。
- `summarize_payload` — 第 289 行。
- `_metadata` — 第 434 行。
- `_run_fields` — 第 463 行。
- `_archive_index` — 第 513 行。
- `_register_archive_session` — 第 545 行。
- `_archive_run` — 第 597 行。
- `MetadataOnlyClient` — 第 683 行。
  - `create_run`：第 687 行。
  - `update_run`：第 720 行。
  - `_insert_runtime_env`：第 740 行。
- `TraceTurn` — 第 752 行。
  - `observe`：第 772 行。
  - `finish`：第 801 行。
- `AgentTracing` — 第 843 行。
  - `__init__`：第 847 行。
  - `turn`：第 913 行。
  - `status`：第 1010 行。
  - `flush`：第 1025 行。
- `record_failure` — 第 1040 行。
- `current_trace_id` — 第 1078 行。
- `tool_span` — 第 1089 行。

### `versions.py`

提示词加载、规则 / prompt hash、稳定 A/B 分组和版本摘要。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai/app/versions.py)

- `prompt_bundle` — 第 33 行。
- `load_prompt` — 第 41 行。
- `fingerprints` — 第 49 行。
- `runtime_version` — 第 63 行。

## 独立 AI 网关

### `config.py`

服务地址、服务端 key 文件加载、Redis 与并发配置。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai-gateway/app/config.py)

- `load_dify_key` — 第 11 行。
- `local_redis_url` — 第 38 行。

### `feedback.py`

消息快照、服务端可信反馈、Java 落库与 Dify 同步状态。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai-gateway/app/feedback.py)

- `FeedbackInput` — 第 21 行。
- `Snapshot` — 第 31 行。
  - `observe`：第 48 行。
- `submit` — 第 71 行。

### `main.py`

网关 FastAPI 入口、身份与会话、两通道转发、停止与重置、完成后持久化、反馈。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai-gateway/app/main.py)

- `ChatRequest` — 第 33 行。
- `lifespan` — 第 42 行。
- `storage_failure` — 第 73 行。
- `same_site` — 第 79 行。
- `channel_store` — 第 85 行。
- `require_session` — 第 93 行。
- `session_info` — 第 107 行。
- `reset_session` — 第 133 行。
- `stop_dify` — 第 140 行。
- `stop` — 第 155 行。
- `dify_events` — 第 165 行。
- `agent_events` — 第 232 行。
- `describe_gateway_failure` — 第 335 行。
- `chat` — 第 371 行。
- `feedback` — 第 490 行。

### `protocol.py`

统一 SSE 编码及上游 SSE 分帧读取。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai-gateway/app/protocol.py)

- `event` — 第 10 行。
- `read_events` — 第 15 行。

### `store.py`

Redis 会话 / 历史 / 绑定 / 活动指针、Lua 租约 / 限流 / 取消 / 反馈锁。

源码：[打开文件](../../cinema-ticketing-backend/cinema-ai-gateway/app/store.py)

- `Session` — 第 64 行。
  - `ttl`：第 76 行。
- `ConversationStore` — 第 81 行。
  - `__init__`：第 84 行。
  - `key`：第 106 行。
  - `close`：第 110 行。
  - `identity`：第 116 行。
  - `load`：第 147 行。
  - `create`：第 159 行。
  - `discard`：第 176 行。
  - `bind`：第 183 行。
  - `open`：第 194 行。
  - `resolve`：第 238 行。
  - `touch`：第 259 行。
  - `reset`：第 280 行。
  - `rate`：第 307 行。
  - `acquire`：第 313 行。
  - `release`：第 338 行。
  - `busy`：第 342 行。
  - `update`：第 346 行。
  - `clear_task`：第 361 行。
  - `cancel`：第 370 行。
  - `cancelled`：第 376 行。
  - `save_snapshot`：第 380 行。
  - `snapshot`：第 397 行。
  - `finish`：第 402 行。
  - `history`：第 436 行。
  - `feedback_lock`：第 449 行。
  - `feedback_unlock`：第 456 行。

## 前端

- [src/chat/CinemaAssistant.tsx](../../cinema-ticketing-frontend/src/chat/CinemaAssistant.tsx)：两通道聊天组件、session 连接、发问、凭证、事件、停止 / 重置与记忆建议。
- [src/chat/chatTransport.ts](../../cinema-ticketing-frontend/src/chat/chatTransport.ts)：三请求头、通道 URL、fetch SSE 分帧、complete / error 与登录失效。
- [src/chat/MessageFeedback.tsx](../../cinema-ticketing-frontend/src/chat/MessageFeedback.tsx)：点赞 / 点踩、原因、补充文字提交。
- [src/chat/UserMemories.tsx](../../cinema-ticketing-frontend/src/chat/UserMemories.tsx)：确认后长期记忆的用户管理。
- [src/chat/messageId.ts](../../cinema-ticketing-frontend/src/chat/messageId.ts)：消息标识处理。
- [src/chat/assistant.css](../../cinema-ticketing-frontend/src/chat/assistant.css)：聊天 UI 样式。
- [src/admin/AiFeedbackAdmin.tsx](../../cinema-ticketing-frontend/src/admin/AiFeedbackAdmin.tsx)：管理端反馈查询 / 处理。
- [src/auth/client.ts](../../cinema-ticketing-frontend/src/auth/client.ts)：请求认证与 token 失效传播。
- [vite.config.ts](../../cinema-ticketing-frontend/vite.config.ts)：React 插件、5173 开发服务和同源 API / 网关代理。

## Java 权威业务 / 身份 / 记忆 / 反馈

- [controller/AccountSecurityController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AccountSecurityController.java)
- [controller/InternalAiController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/InternalAiController.java)
- [controller/AiHandoffController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiHandoffController.java)
- [controller/AiMemoryController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiMemoryController.java)
- [controller/AiFeedbackController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiFeedbackController.java)
- [controller/AiGatewayController.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiGatewayController.java)
- [service/AuthService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AuthService.java)
- [service/AiMovieQueryService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiMovieQueryService.java)
- [service/AiHandoffService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiHandoffService.java)
- [service/AiMemoryService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiMemoryService.java)
- [service/AiFeedbackService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiFeedbackService.java)
- [service/AiGatewayService.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiGatewayService.java)
- [config/AiMemorySchemaInitializer.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/config/AiMemorySchemaInitializer.java)
- [config/AiFeedbackSchemaInitializer.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/config/AiFeedbackSchemaInitializer.java)
- [common/SellableScreenings.java](../../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/common/SellableScreenings.java)

## 提示词、知识和版本

- [prompts/v1/decision.txt](../../cinema-ticketing-backend/cinema-ai/prompts/v1/decision.txt)
- [prompts/v1/glm_router.txt](../../cinema-ticketing-backend/cinema-ai/prompts/v1/glm_router.txt)
- [prompts/v1/reflection.txt](../../cinema-ticketing-backend/cinema-ai/prompts/v1/reflection.txt)
- [prompts/v1/understanding.txt](../../cinema-ticketing-backend/cinema-ai/prompts/v1/understanding.txt)
- [config/agent_versions.json](../../cinema-ticketing-backend/cinema-ai/config/agent_versions.json)
- [knowledge/cinema_faq.md](../../cinema-ticketing-backend/cinema-ai/knowledge/cinema_faq.md)
- [knowledge/purchase_guide.md](../../cinema-ticketing-backend/cinema-ai/knowledge/purchase_guide.md)
- [knowledge/refund_policy.md](../../cinema-ticketing-backend/cinema-ai/knowledge/refund_policy.md)

## 评估辅助代码

这些文件是开发 / 评估工具，不会因为存在就自动在生产链路执行。本文未运行它们。

- [ab_report.py](../../cinema-ticketing-backend/cinema-ai/evaluation/ab_report.py)：Compare pinned A/B exports; unlabelled live completion is not task accuracy.
- [build_golden.py](../../cinema-ticketing-backend/cinema-ai/evaluation/build_golden.py)：Freeze held-out cinema acceptance cases and preserve every clarification event.
- [eval_traces.py](../../cinema-ticketing-backend/cinema-ai/evaluation/eval_traces.py)：Summarize exported trace directories or scored trials without external requests.
- [export_clarifications.py](../../cinema-ticketing-backend/cinema-ai/evaluation/export_clarifications.py)：Export local deidentified slot feedback without invoking a model or training it.
- [glm_smoke.py](../../cinema-ticketing-backend/cinema-ai/evaluation/glm_smoke.py)：Four synthetic public-film questions: verify GLM routing without business data.
- [golden_bindings.py](../../cinema-ticketing-backend/cinema-ai/evaluation/golden_bindings.py)：Rebind held-out fixtures privately and force paired experiments in a local CLI.
- [live_cases.py](../../cinema-ticketing-backend/cinema-ai/evaluation/live_cases.py)：Freeze real development data and independently declare expected query tasks.
- [loop_audit.py](../../cinema-ticketing-backend/cinema-ai/evaluation/loop_audit.py)：Audit finite ReAct execution from recorded proposals and upstream business calls.
- [metrics.py](../../cinema-ticketing-backend/cinema-ai/evaluation/metrics.py)：Independent acceptance rules and descriptive statistics for Agent evaluation.
- [phrasing_cases.py](../../cinema-ticketing-backend/cinema-ai/evaluation/phrasing_cases.py)：Pair natural colloquial questions with fixed real-data gold cases.
- [phrasing_eval.py](../../cinema-ticketing-backend/cinema-ai/evaluation/phrasing_eval.py)：Measure intent, facts, and tool traces on paired formal and colloquial questions.
- [report.py](../../cinema-ticketing-backend/cinema-ai/evaluation/report.py)：Render measured results as a local, self-contained browser report.
- [rerank_focus.py](../../cinema-ticketing-backend/cinema-ai/evaluation/rerank_focus.py)：Measure evidence ranking on frozen real knowledge candidates, independently of Agent planning.
- [rerank_metrics.py](../../cinema-ticketing-backend/cinema-ai/evaluation/rerank_metrics.py)：Observe real reranking decisions, provider usage and fallback without changing ranking.
- [rescore_phrasing.py](../../cinema-ticketing-backend/cinema-ai/evaluation/rescore_phrasing.py)：Apply transparent scoring corrections to an already completed phrasing run.
- [review.py](../../cinema-ticketing-backend/cinema-ai/evaluation/review.py)：Apply explicit human adjudications while retaining all original automatic scores.
- [routing_audit.py](../../cinema-ticketing-backend/cinema-ai/evaluation/routing_audit.py)：Audit cheap routing against frozen gold plans without querying any provider.
- [run.py](../../cinema-ticketing-backend/cinema-ai/evaluation/run.py)：Compare real Qwen calls on current/previous workflows and real development queries.
- [runtime_check.py](../../cinema-ticketing-backend/cinema-ai/evaluation/runtime_check.py)：Inspect termination of the already running Agent using frozen real query cases.
- [train_intent_classifier.py](../../cinema-ticketing-backend/cinema-ai/evaluation/train_intent_classifier.py)：Train a local nine-intent classifier with scenario-isolated validation and test sets.
- [verify_snapshot.py](../../cinema-ticketing-backend/cinema-ai/evaluation/verify_snapshot.py)：Check that the live business facts still match the frozen scoring snapshot.
- [workflow_cases.py](../../cinema-ticketing-backend/cinema-ai/evaluation/workflow_cases.py)：Freeze 72 query scenarios, each with a standard and a conversational expression.
- [workflow_eval.py](../../cinema-ticketing-backend/cinema-ai/evaluation/workflow_eval.py)：Run 144 frozen real questions twice against the current workflow.

## 部署与依赖

- [cinema-ticketing-backend/start-ai-local.ps1](../../cinema-ticketing-backend/start-ai-local.ps1)
- [cinema-ticketing-backend/stop-ai-local.ps1](../../cinema-ticketing-backend/stop-ai-local.ps1)
- [cinema-ticketing-backend/docker-compose.yml](../../cinema-ticketing-backend/docker-compose.yml)
- [cinema-ticketing-backend/nginx/nginx.conf](../../cinema-ticketing-backend/nginx/nginx.conf)
- [cinema-ticketing-backend/cinema-ai/requirements.txt](../../cinema-ticketing-backend/cinema-ai/requirements.txt)
- [cinema-ticketing-backend/cinema-ai/Dockerfile](../../cinema-ticketing-backend/cinema-ai/Dockerfile)
- [cinema-ticketing-backend/cinema-ai-gateway/requirements.txt](../../cinema-ticketing-backend/cinema-ai-gateway/requirements.txt)
- [cinema-ticketing-backend/cinema-ai-gateway/Dockerfile](../../cinema-ticketing-backend/cinema-ai-gateway/Dockerfile)
- [cinema-ticketing-backend/cinema-ai/.env.example](../../cinema-ticketing-backend/cinema-ai/.env.example)
- [cinema-ticketing-backend/cinema-ai-gateway/.env.example](../../cinema-ticketing-backend/cinema-ai-gateway/.env.example)
