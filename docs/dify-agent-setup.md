# 方案 B：Dify Chatbot + 独立 AI 网关

已接入自定义聊天窗口；Dify 使用云端 Chatbot 官方 API。首页右下角“影院助手”是统一入口。

## 请求路径

- 常见问题：浏览器 → `/ai-gateway/chat` → Python 网关 → Dify 云端。此路径不访问 Java 或数据库。
- 手动转接：浏览器先向 Java `/api/ai/handoff` 申请凭证，再向网关发送问题。网关向 Java 校验凭证，调用内部 Agent `/ai/live`；电影、场次、座位、本人订单通过独立 MCP Server 查询 Java，规则 RAG 和推荐保留原工具。详见 [Cinema MCP 配置](cinema-mcp.md)。
- 回答由网关直接以 SSE 返回浏览器，Java 不转发模型长连接。
- 凭证有效期 10 分钟，绑定当前登录与聊天会话，只支持只读查询。每轮实时查询都会重新核验登录状态；退出登录后凭证失效。
- 前端不提交可信用户 ID。模型不生成 SQL；Java 工具使用固定 SQL 和参数查询本人订单、影片、场次、当前退票规则。

## 本地运行

Java 端口 8080；内部 Agent 端口 8000；网关端口 **8010**；MCP 端口 **8020**，协议地址 `http://127.0.0.1:8020/mcp`。8001 已被本机代理服务占用，保留该服务。

网关默认读取 `E:/development/AI-Project/API/dify.txt`，文件只放一行应用 API Key，也支持 `DIFY_API_KEY=...`。`API/` 与 `.env` 已加入 Git 忽略。也可以用服务端环境变量 `DIFY_API_KEY` 覆盖文件。

本次已创建 `cinema-ticketing-backend/cinema-ai/.venv` 并安装 Python 3.12 依赖。后续启动：

```powershell
cd E:/development/AI-Project/cinema-ticketing-backend
./start-ai-local.ps1
```

先启动 Java，再启动 AI。脚本后台依次启动 MCP、Agent 和网关进程，显示 PID；日志在 `cinema-ticketing-backend/target/ai-{mcp,agent,gateway}-{stdout,stderr}.log`。端口被占用时脚本会报错。可先运行 `./stop-ai-local.ps1`（全部）或 `./stop-ai-local.ps1 -Service gateway`（仅网关），随后对应运行 `./start-ai-local.ps1 -Service gateway`；`-Service mcp` 用于单独重启 MCP。仅启动 Agent 时需先启动 MCP 或配置已有 MCP 地址。脚本核实项目路径、端口和进程树，停止 supervisor 及 worker，不影响 Java、Vite 或本机代理。网关默认 2 个 worker，可用 AI_GATEWAY_WORKERS=1～8 调整。

新环境安装依赖（需 Python 3.12）：

```powershell
python -m venv cinema-ticketing-backend/cinema-ai/.venv
cinema-ticketing-backend/cinema-ai/.venv/Scripts/python.exe -m pip install -r cinema-ticketing-backend/cinema-ai/requirements.txt
```

网关可独立安装自己的 `requirements.txt`；本地脚本共用包含这些依赖的 Agent 虚拟环境，MCP、Agent、网关使用独立进程。

网关配置示例在 `cinema-ticketing-backend/cinema-ai-gateway/.env.example`。复制为同目录 `.env` 后，启动脚本通过 Uvicorn 加载。

内部 Agent 已切换为 **Qwen3.7 Flash**，模型 ID `qwen3.7-flash`，通过阿里云百炼兼容接口调用。服务端默认从 `API/qwen.txt` 读取一个密钥，支持纯密钥或附带标签的文本；环境变量 `QWEN_API_KEY` / `DASHSCOPE_API_KEY` 优先于文件。密钥文件仍由 Git 忽略。Docker 将该文件只读挂载到 Agent，网关不使用 Qwen 密钥。

配置示例见 `cinema-ticketing-backend/cinema-ai/.env.example`，可复制为同目录 `.env`：

- `QWEN_MODEL`：默认 `qwen3.7-flash`。
- `QWEN_API_BASE_URL`：默认北京兼容地址 `https://dashscope.aliyuncs.com/compatible-mode/v1`。其他地域的密钥须配置对应地域地址；可使用业务空间专属地址。详见 [阿里云兼容接口说明](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)。
- `QWEN_API_KEY_FILE`：相对 Agent 目录解析，默认 `../../API/qwen.txt`；也支持绝对路径。
- `QWEN_ENABLE_THINKING`：默认 `false`，用于票务查询直接回复，减少等待与推理 Token；见 [官方思考模式参数](https://help.aliyun.com/zh/model-studio/deep-thinking)。
- `QWEN_MAX_TOKENS`：默认 2048，上限 8192；请求超时 30 秒、最多一次自动重试。

配置密钥后 `/ai/live` 逐段发送模型输出；没有密钥时以模板显示真实查询结果。服务启动只初始化客户端，不自动发起收费生成请求。内部 Agent 新增结构化问题理解：归一化退钱/退票、排片/场次等同义说法，识别意图与实体，结合最近 10 条上下文解决追问；只允许固定工具，订单身份由网关注入。缺少订单号或低置信度先澄清，影片/影院关键词及北京时间日期传入参数化查询。问候使用快速规则，其他问题额外进行一次最多 15 秒、1000 输出 token 的理解调用，再根据真实查询结果生成回复；模型理解异常会在日志记录异常类型并回退保守规则。模型配置变更后重启内部 Agent 即可。

密钥读取保留点号、下划线和 Base64 常见符号，避免截断供应商的完整密钥。模型鉴权、权限、限流、超时和业务查询错误以稳定错误码和中文原因返回页面；服务端只记录失败阶段、异常类型和 HTTP 状态，不输出密钥或完整对话。简单问候及能力介绍不执行业务 SQL。

Java、网关、Agent 与 MCP 的 `AI_INTERNAL_TOKEN` 必须一致。本地默认匹配 Java 的 `local-internal-token`；修改后请同时设置四个服务。

## 聊天体验

- 默认由 Dify 回答，支持逐段显示、停止、错误重试、新对话。
- 用户点击“转接实时 Agent”；未登录时先打开登录弹窗，成功登录后完成转接。
- 转接后的问题携带最近 10 条、每条最多 2000 字的对话背景。背景只用于理解问题，不提供权限或覆盖业务事实。
- Agent 可查影片、场次、实时座位、本人订单和退票规则，不替用户下单、支付或退款。座位查询需明确场次编号，如“查询场次 12 的座位”。所有时区未标注的场次时间按北京时间解释。
- 返回智能助手时只继续 Dify 自己的会话；不会把实时 Agent 的订单回复发送给 Dify。退出或更换账户清空当前窗口记录。
- 订单号必须由用户提供。直接回答追问的订单号时，Agent 会根据上一条询问衔接。

## Dify 侧配合

当前 Chatbot 不要求额外输入变量，可直接使用 `/chat-messages`。密钥的配置读取已成功；尚未自动发起收费模型回答。

普通自然语言回答可直接流式展示。若希望 Dify 在回答末尾提示转接，可约定完整回答为 JSON：

```json
{"answer":"需要查询实时订单数据，请选择转接。","handoffSuggested":true}
```

这是本项目的可选协议，不是 Dify 默认响应字段。网关收到完成事件后解析它；推荐提示不会自动调用 Agent，仍由用户点击。用户也可以随时手动转接。建议普通问答先使用自然语言，待你完善 Dify 提示词后再开启结构化协议。

## 部署与当前边界

- Docker Compose 的 `app` profile 增加 `cinema-ai-gateway`，Nginx `/ai-gateway/` 直达网关并关闭缓冲。网关、Agent 不发布宿主机端口，内部端点不会从 Nginx 转发到公网。
- 云端 Dify 的调用采用服务端 Bearer Key、网关生成的独立 `user` 和会话 ID，遵循 [Dify Chat API](https://docs.dify.ai/en/api-reference/chat-messages/send-chat-message)。浏览器无法指定 Dify 会话 ID。
- 网关默认最多 16 条并发流，每个会话每分钟最多 12 次提问；总生成时间最多 90 秒，单回答最多 40000 字。每个会话只允许一条流。
- 网关会话已存入共享 Redis：所有 worker/实例共享会话、Dify 编号、聊天历史、反馈摘要、滑动限流、生成租约和全局并发额度。最多 2000 个聊天；匿名闲置 24 小时，登录账户闲置 30 天过期。默认 2 个 worker，不需要粘性会话。网关重启后可恢复既有 Redis 会话。部署仍需自行配置外部入口 IP 限流。
- 线上使用 HTTPS，替换演示内部凭证，并限制 Java 内部端点和 Agent 端口仅内网可达。页面登录及随机聊天绑定凭证保存在 sessionStorage；网关忽略旧共享 Cookie，浏览器请求使用 credentials=omit。AI_COOKIE_SECURE 为旧配置，当前不再签发用于鉴权的 Cookie。
- 现有 Java `/api/ai/chat`、`/api/ai/stream` 兼容保留；新前端不使用它们。旧 `/ai/stream` 仍是完整结果事件，新 `/ai/live` 提供进度和模型增量。
- 首期没有新增数据库缓存或通用 SQL 工具。减少 Java 问答流量靠 FAQ 分流；实时查询仍会产生业务请求与 SQL。
- 没有修改 Dify 工作流、开通真实支付或实现自动退款。

## 回答评价与后台处理

- 回答结束（包括错误回答）后可点赞/点踩，再选填点踩原因与最多 500 字说明。再次点击同一评价可撤回，反馈提交失败提供重试。
- Dify 同步采用官方 `POST /messages/{message_id}/feedbacks`，包括 `rating`（like/dislike/null）、原 Dify `user`、原因与说明。消息 ID 从服务端 SSE 获取，浏览器不能伪造回答内容或用户。参见 [Dify 官方 API 模板](https://github.com/langgenius/dify/blob/main/web/app/components/develop/template/template_chat.zh.mdx)。
- 先保存影院本地反馈，再同步 Dify。云端失败不会丢失本地记录；页面提示实际状态，后台记录 PENDING/SYNCED/FAILED/UNAVAILABLE。内部 Agent 反馈为 NOT_APPLICABLE，订单回答不会发往 Dify。当前重试由用户发起，没有后台自动同步队列。
- 共享 Redis 保留最近最多 1000 条反馈摘要、最多 8000 字/条、最长 2 小时（达到数量上限会提前淘汰）。反馈和提交锁可跨 worker；网关重启后仍可评价有效摘要。用户提交评价才写 Java/MySQL。新对话或过期后不能评价旧回答，已经保存的后台反馈仍保留。每会话每分钟最多 20 次反馈。
- 管理员从导航“AI 反馈”进入，默认显示待处理点踩；可按来源/评价/原因/处理状态/关键词筛选，展开查看原问题、归一化问题、意图、实体、查询工具、原始回答、异常、同步状态，保存备注及标记已处理/重新打开。该页面仅 ADMIN 可访问。Dify 的内部意图不在现有 SSE 合同中，后台对此显示未返回，不推测。
- 本次新增 Java API 和 `ai_message_feedback` 表，因此 **IDEA 中的 Java 服务也需要重启**，Python Agent 与网关也需重启；刷新前端后开始新对话、重新转接。
- Java 启动默认只执行 `src/main/resources/ai-feedback-schema.sql` 的 CREATE TABLE IF NOT EXISTS，不重跑影片种子。生产库可由运维预先执行该文件，并设置 `ai.feedback.initialize-schema=false`，应用账号无需 DDL 权限。既有表不自动变更。
- 普通聊天自动保存到 Redis，不写 Java/MySQL；后台显示用户明确提交的评价。撤回反馈保留本地业务记录，不提供逐次投票审计历史。

## 共享会话与跨设备恢复

- `AI_REDIS_URL` 指向共享会话 Redis（默认 redis://127.0.0.1:6379/0）；所有网关实例的 `AI_REDIS_PREFIX` 必须一致，默认 ai:gateway:。本地未设置 URL 时，且 Java 指向 localhost，读取被 Git 忽略的 Java application-local.yml 中 Redis 配置；不会打印连接凭证。Docker 使用 redis 服务的数据库 0。
- 网关直接读取 Java 的 `auth:session:<token>` 验证登录、用户和退出状态，普通 FAQ 与恢复会话无需调用 Java。`AI_AUTH_REDIS_URL` 默认同 AI_REDIS_URL；将 AI 数据放到另一数据库时，必须单独指向 Java 所使用的 Redis 数据库。网关身份绑定只保存在服务端，浏览器不指定 userId，生成模型也不提供身份。
- 打开助手或点击“恢复聊天”读取最近 40 条已结束的消息（完成、失败、用户停止均保存），每个回答最多保存前 8000 字，较长回答明确显示截断。同一登录账户在不同设备恢复同一当前聊天；默认回到 Dify，继续实时查询需使用本设备当前登录重新转接，不保存转接凭证。没有全量历史检索或恢复正在进行中的 SSE。
- 登录只恢复该账户当前会话，匿名记录不自动合并；退出/更换账户立即清空窗口、取消旧请求并清除本地聊天绑定。每次聊天、停止、重置和反馈均发送当前标签的 X-Auth-Token、X-AI-Session 随机绑定凭证及 X-AI-Conversation 期望会话 ID；缺失、过期、归属不匹配或旧对话均被拒绝，恢复需显式重新连接。其他标签/设备独立有效的登录不受退出影响。匿名聊天凭证仅保存在当前标签的 sessionStorage，不能跨设备识别匿名用户。会话建立响应含 bindingKey，需保密，不写 URL 或日志。
- 页面启动用 /api/auth/me 核验登录账户，菜单依据确认的角色显示；临时失败可重试，登录过期清理当前标签。发布后需重启 Java 和网关并刷新所有页面，旧 localStorage 登录不迁移，各标签重新登录。
- 网关到 Java/内部 Agent、内部 Agent 到 Java 均使用独立的 HTTP 客户端并设置 trust_env=false，直接连接配置的内部地址；这些调用不使用环境或 Windows 系统代理，避免本机服务被转发到代理后返回 502。Dify 云端请求仍使用独立云端客户端。网关失败日志仅记录 provider、固定 stage、异常类型和 HTTP 状态，不打印 token、URL 参数、对话或供应商响应正文。
- “新对话”清空当前会话的 Redis 最近聊天并切换账户指针，其他设备点击恢复后同步新会话；正在生成时拒绝重置。已保存的 MySQL 反馈不删除。生成锁默认 120 秒，回答预算 90 秒，进程崩溃后自动释放容量；有残留云端任务时下一轮先尝试停止。
- 普通聊天每会话每分钟 12 次、反馈 20 次、新对话每浏览器每分钟 5 次；全局同时生成最多 AI_MAX_STREAMS（默认16）。额度在 Redis 中共享，不会随 worker/实例数量翻倍。反馈同步锁也跨实例串行，防止点赞/撤回顺序被覆盖。
- 本地启动默认 `--workers 2`；Docker 默认 WEB_CONCURRENCY=2。多副本可执行 `docker compose --profile app up -d --scale cinema-ai-gateway=2`，网关已移除固定 container_name；扩缩容后重启 Nginx 刷新 Docker DNS 地址。所有实例必须共用 Dify 应用、密钥、Redis 和内部服务凭证。仅 `cinema-ai-gateway` 支持该扩展；其他已有固定名称服务不在本次扩容范围。
- Docker Redis 已开启 AOF（everysec）并挂载 redis-data 卷。既有虚拟机 Redis 部署需保留其持久化配置和磁盘；网关进程重启不会清理聊天，Redis 自身数据被清空或丢失仍会丢失恢复记录。客户端使用 [Redis 官方异步 Python 客户端接口](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)，依赖锁定 redis==5.2.1。当前 Lua 跨键事务面向单 Redis 主节点，不支持直接切换到 Redis Cluster。
- Redis 不可用时返回 503，不回退到各实例独立的内存会话。更新前只在旧网关进程中的记录没有可迁移持久副本，更新后产生的记录才具备共享恢复能力。
