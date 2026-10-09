# 内部 Agent：阿里云 Rerank 接入与运行说明

## 已实现的范围

内部 Agent 的 `query_ticket_policy` 已接入 `qwen3.7-text-rerank`，用于规则知识问答。电影、场次、座位、订单的 MCP 查询，以及 Dify 问答和用户长期记忆，不进入这条重排链路。

执行顺序：

1. 并行读取本地规则知识、Java 已发布知识、Java 当前退票规则。
2. 本地关键词召回最多 20 个片段；Java 知识接口最多返回 10 篇文档，再切成片段。两类知识统一采用 500 字符切片、80 字符重叠。
3. 合并片段并按内容去重，以关键词相关程度排序，默认保留最多 30 个候选。
4. 将本轮问题和候选片段发送到百炼，按照返回的相关性分数排序，默认选前 4 个作为回答依据。
5. 把选中片段、对应来源和当前退票规则一起交给回答模型。

当前退票规则通过独立的 `policy` 字段保留，不参与重排和裁剪。知识片段保留来源、版本、数据库文档 ID（如有），并增加稳定的 `chunk_id`；云端重排成功后增加 `rerank_score`。来源与片段通过返回的候选索引对应，云端不能替换原始片段内容。

本地知识目录：`cinema-ticketing-backend/cinema-ai/knowledge/`，当前读取其中的 `cinema_faq.md`、`purchase_guide.md` 和 `refund_policy.md`。只读取该目录直接包含的 Markdown 文件，在 Agent 启动时加载；修改后需要重启 Agent。

## 配置与密钥

配置文件：`cinema-ticketing-backend/cinema-ai/.env`。本次已在本机文件中补充以下配置，示例同步到 `.env.example`：

```dotenv
RERANK_ENABLED=true
RERANK_MODEL=qwen3.7-text-rerank
RERANK_API_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank
RERANK_TOP_K=30
RERANK_TOP_N=4
RERANK_TIMEOUT_SECONDS=5
```

`TOP_K` 控制合并后发送的候选上限，`TOP_N` 控制返回片段数量，满足 `1 <= TOP_N <= TOP_K <= 50`。本地召回仍最多 20 个，调整 `TOP_K` 不会自动扩大本地召回。超时可配置为大于 0、最多 15 秒；非法限制会在启动时拒绝加载。

复用现有服务端密钥加载器：优先 `QWEN_API_KEY`，其次 `DASHSCOPE_API_KEY`，然后 `QWEN_API_KEY_FILE` 指定的文件。默认文件为 `API/qwen.txt`（相对 Agent 目录为 `../../API/qwen.txt`）。不需要新建独立的 Rerank 密钥，也不向前端下发密钥。

重排使用百炼原生 API，地址独立于聊天模型的 `QWEN_API_BASE_URL`。当前默认地址属于北京地域；密钥与接口地域需要匹配。也支持同地域业务空间专属域名，保留上述原生 API 路径。接口格式以[阿里云文本重排 API](https://help.aliyun.com/zh/model-studio/text-rerank-api)和[服务地址说明](https://help.aliyun.com/zh/model-studio/base-url)为准。

## 生效与连通检查

在后端目录执行，仅需重启内部 Agent：

```powershell
cd E:\development\AI-Project\cinema-ticketing-backend
.\stop-ai-local.ps1 -Service agent
.\start-ai-local.ps1 -Service agent
```

完整网站问答需要 Java、MCP 和网关已正常运行。本次改动不要求重新构建 Java 或前端。启动脚本加载 Agent 目录下的 `.env`，已有进程环境变量优先；修改配置后须重启。

可独立检查百炼连接，无须启动 Java 或 MCP：

```powershell
.\cinema-ai\.venv\Scripts\python.exe .\cinema-ai\scripts\check_rerank.py
```

该检查会真实调用一次付费模型，使用脚本内的三段公开测试文字，不读取业务知识或用户记忆。成功输出 `"status": "success"`，订单说明应排在第一位；回退输出 `"status": "fallback"` 并返回非零退出码。脚本同样读取 `.env`，关闭 Rerank 后该检查不会报告云端成功。

## 故障回退与日志

- 没有候选、只有一个候选或开关关闭时，不调用云端。
- 缺少密钥、网络失败、超时、HTTP 400/401/403/429/5xx 或响应格式错误时，整次回退到候选的关键词排序，取前 `TOP_N` 个；当前退票规则仍保留。
- 重排请求不自动重试，每个 Agent 进程最多同时发起 4 次重排；等待并发空位也计入默认 5 秒总超时。
- 检查返回索引是否越界、重复或缺失，以及分数是否合法；不使用部分错误结果。
- 不设置固定分数阈值，分数用于本次候选间排序，不用于跨问题比较。

日志位于 `cinema-ticketing-backend/target/ai-agent-stderr.log`：

```text
Rerank status=success model=... candidates=... selected=... elapsed_ms=... total_tokens=... request_id=...
Rerank status=fallback reason=http_429 candidates=... elapsed_ms=...
```

`reason` 可为 `missing_key`、`timeout`、`transport_error`、`http_401` 等 HTTP 状态，或 `invalid_key_or_response`。这些日志不输出密钥、问题、知识正文或上游响应正文。

需要关闭云端重排时，将 `.env` 中 `RERANK_ENABLED=false` 后重启 Agent。此时保留合并、切片、去重流程，按照关键词排序取前 `TOP_N` 个，不会恢复旧版无限追加数据库正文的行为。

## 验证记录与效果评估

本次开发验证：

- 重排组件与工具测试 13 项、ReAct 链路测试 17 项、MCP 回归测试 16 项，合计 46 项通过。
- 覆盖来源与索引映射、数据库切片、候选限制、并发限制、超时、限流、错误密钥、异常响应、取消请求和回退。
- ReAct 集成检查确认：模型收到的是重排选中的片段，同时保留实时退票规则和最终回答来源。
- 使用当前本机密钥真实调用 `qwen3.7-text-rerank`，收到 HTTP 200；公开示例的订单说明排在第一位。该次响应记录 `total_tokens=269`。

已完成同版本重排开关的 96 次真实业务任务对照，以及 12 题、48 次规则证据排序专项，详见 [2026-10-09 真实评测](agent-rerank-evaluation-2026-10-09.md)。小规模有答案专项的首位证据命中率由 90% 提升到 100%，端到端严格成功率未提升。发现实时规则正文与数值字段冲突、自然语言数据库知识召回为空等问题；建议先修复，再扩充至 50～100 个规则问题（近义表达、相似干扰、版本冲突、无答案）复测。

主要实现位置：`app/policy_retrieval.py`（候选构建）、`app/reranker.py`（百炼客户端和回退）、`app/main.py`（工具接入与资源关闭）、`scripts/check_rerank.py`（真实连通检查），均位于 `cinema-ticketing-backend/cinema-ai/` 下。
