# 影院项目 AI 完整实现说明

> 代码梳理日期：2026-10-12。本文依据当前工作区的实际实现，解释前端聊天、独立 AI 网关、内部 Agent、MCP、Java 业务接口、记忆、反馈和追踪。配置值均指**代码默认值或示例配置**，不代表运行进程已经加载该配置；没有调用在线模型、检查云端工作流或执行业务测试。

## 阅读入口

- [打开 SVG 图册](index.html)：八张图，可切换、缩放、打开原始 SVG。
- [打开排版后的完整说明](implementation.html)：带目录，可离线阅读或由浏览器打印。
- [01 服务总览](01-system.svg)
- [02 网关与身份会话](02-gateway.svg)
- [03 Agent 节点与边](03-agent-graph.svg)
- [04 分层意图识别](04-intent.svg)
- [05 工具、MCP 与 Java 数据查询](05-tools.svg)
- [06 长短期记忆](06-memory.svg)
- [07 SSE 请求时序与反馈](07-streaming.svg)
- [08 追踪与排错](08-tracing.svg)
- [源码索引](source-index.md)：逐个列出 Agent / 网关 Python 模块及主要函数、Java 与前端入口。

## 1. 先建立整体认识

这个项目的 AI 不是一个独立拥有数据库读写权限的“大模型聊天程序”，而是多个职责明确的服务协作：

1. **前端聊天界面**负责展示、发送问题、接收事件、停止回答、重置会话、反馈和用户确认记忆。
2. **独立 AI 网关**负责浏览器入口、身份核验、会话归属、Dify 云端 API 调用、内部 Agent 转发、Redis 历史、并发与取消控制、统一 SSE 协议和反馈落库。
3. **内部 Agent**负责理解自然语言、规范化问题、构建查询任务、选择 Simple / ReAct 路线、调工具、校验结果、组织事实答案、反思检查以及调用用户记忆。
4. **MCP 查询服务**把四种只读业务查询封装成标准工具，通过内部 HTTP 与 Agent 通信。
5. **Java 服务**负责登录身份、临时转接凭证、业务规则、固定 SQL、本人订单归属、记忆的权威记录和后台反馈管理。
6. **Redis / MySQL / Chroma / 本地追踪文件**分别承担短期会话协调、业务与记忆权威数据、向量检索投影、追踪归档。
7. **Dify / Qwen / GLM / DashScope Rerank / LangSmith**分别提供云端知识问答、复杂理解与决策、可选轻量分类、规则片段重排、可选追踪。

### 1.1 当前实现与早期设想的区别

- 当前前端实际上是 **React + TypeScript + Vite**，虽然历史对话中曾称为 Vue。依据 `vite.config.ts` 的 React 插件和 `src/chat/*.tsx`。
- Dify 和实时 Agent 是**两个独立聊天通道**，有独立的绑定、历史、会话和请求路由。
- 当前代码没有实现“Dify 自动判断失败后自动转接 Agent”，也没有自动把 Dify 完整历史转给 Agent。用户打开实时 Agent 后，会为 Agent 自己的会话申请临时凭证。
- 浏览器不直接调用 Dify 官方 API。API Key 保留在服务端，由网关代为调用。
- Agent 已经具有 LangGraph、分层理解、任务跟踪、工具边界、结果契约、反思和 Chroma 记忆，已超过最初的“LLM 包装 Java 查询”形态。
- 网关会话已经迁移到 Redis。只有旧兼容 `/ai/chat` 和 `/ai/stream` 路径仍使用 Agent 进程内历史字典。
- Agent 不会直接生成任意 SQL，也不持有 MySQL 连接；SQL 在 Java 的固定查询代码中执行。
- 当前实时 Agent 正文是在事实与校验完成后通过一个 `delta` 返回。实时的是状态与事件通道，不能据此认为正文逐 token 输出。

## 2. 父目录、服务与端口

### 2.1 实际运行代码

```text
AI-Project/
├─ cinema-ticketing-frontend/
│  └─ src/
│     ├─ chat/                    聊天、反馈、长期记忆 UI
│     ├─ auth/                    标签页登录态、身份失效处理
│     └─ admin/AiFeedbackAdmin.tsx 后台 AI 反馈处理
├─ cinema-ticketing-backend/
│  ├─ cinema-ai/
│  │  ├─ app/                     内部 Agent + MCP + 记忆 worker
│  │  ├─ prompts/v1/              版本化模型提示词
│  │  ├─ config/agent_versions.json A/B 分组配置
│  │  ├─ knowledge/               本地票务知识 Markdown
│  │  └─ evaluation/              评估、审计、分类器训练工具
│  ├─ cinema-ai-gateway/app/       独立公开聊天网关
│  ├─ src/main/java/.../           Java 业务、鉴权、反馈、记忆接口
│  ├─ data/                       本地 Chroma、嵌入模型、澄清反馈等
│  ├─ target/                     本地 AI 服务启动日志
│  ├─ nginx/nginx.conf             生产同源代理与 SSE 配置
│  └─ start-ai-local.ps1           本地 AI 相关进程启动器
├─ API/                           服务端凭证文件，不进入浏览器
├─ langsmith(tracing)/             按日期与用户会话归档的追踪
├─ docs/ai-implementation/         本说明与 SVG 图册
└─ 内部agent/源文件/               历史源码副本，不是当前启动入口
```

### 2.2 本地进程

- 前端开发服务器：`5173`，`/api` 代理到 Java，`/ai-gateway` 代理到 Python 网关。
- Java 业务服务：`8080`，连接业务 MySQL、Redis 等基础设施。
- Agent：`8000`，入口 `app.main:app`。
- AI 网关：`8010`，入口网关自己的 `app.main:app`。
- MCP：`8020`，入口 `app.mcp_server:app`，协议地址 `/mcp`。
- Chroma：本地 `8030`，持久化目录 `cinema-ticketing-backend/data/chroma`。
- memory worker：独立后台进程，无 HTTP 端口。

`start-ai-local.ps1 -Service all` 当前选择五项：Chroma → MCP → Agent → Gateway → Memory worker。它不会替代 Java、前端、MySQL、Redis 等服务的启动。MCP 启动后会检查健康端点再继续；其他进程启动不等于全链路已经可用。

**Compose 与本地端口不同：** Compose 内网 Chroma 使用 `chroma:8000`；这不与另一个容器里的 Agent `:8000` 冲突。本地运行时才使用 Chroma `8030`。Compose 不把 MCP / Agent / Chroma 当成浏览器直接访问的公共接口。

### 2.3 两个名字相近的“网关”

- Python `cinema-ai-gateway/`：前端当前聊天的主要入口，负责 Dify、实时 Agent、Redis 会话、SSE、反馈。
- Java `AiGatewayService.java`：保留的兼容适配器，提供 `/api/ai/chat`、`/api/ai/stream`，调用 Agent `/ai/chat`、`/ai/stream`。它不是当前聊天界面调用的独立网关。

## 3. 一次问题从输入到回答的全过程

以“明天《某电影》有什么场次，顺便看看还有哪些座位”为例；电影名仅为示例，不代表数据库有该记录。

1. 前端取得当前标签页已核验的登录 token，连接 `agent/session`，获得 `sessionId` 与 `bindingKey`。
2. 前端向 Java `/api/ai/handoff` 申请与该 Agent 会话绑定的临时凭证。
3. 前端向网关 `/ai-gateway/agent/chat` 发 `{sessionId, question, credential}`，请求头携带标签页 token 与会话绑定。
4. 网关请求 Java 核验登录，再用 Redis 检查绑定、会话归属、当前活动会话。
5. 网关检查问题长度、速率、该会话是否正在回答、全局并发上限，取得分布式租约。
6. 网关到 Java 解析转接凭证，要求用户、会话、`cinema:read` 范围全部吻合。
7. 网关读取 Agent 通道最近的有效历史，最多十条、每条最多两千字符，发送给内部 `/ai/live`。
8. Agent 做规则预检、同义化、日期解析，必要时调用分类模型或 Qwen，得到受约束的 `QuestionPlan`。
9. 根据多个查询任务或依赖关系选择 ReAct：先查场次，再决定能否查座位。
10. Agent 工具参数经过白名单、实体来源与范围校验后，通过 MCP 查询 Java。
11. Java 用固定 SQL 返回真实场次；Agent 校验返回值与日期、范围等契约是否匹配。
12. 若只有一个可确定场次，继续查座位；若多个场次且用户没选，要求用户选择，不能猜编号。
13. Agent 依据查询事实生成答案块，进行规则校验或一次模型反思。
14. Agent 发状态、上下文和正文事件；网关保存快照和历史、释放租约后才发 `complete`。
15. 前端收到 `complete` 才认为本轮正常完成；后续“有帮助 / 没帮助”使用服务端生成的 `messageId` 提交。

这条链路中，LLM 可以理解问题、建议工具、检查答案；**用户身份、查询范围、订单归属和最终事实不能仅靠模型判断**。

## 4. 前端聊天实现

### 4.1 界面组件

- `CinemaAssistant.tsx`：承载 Dify 与 Agent 两套聊天实例；连接、历史恢复、发送、停止、重试、重置、记忆建议确认。
- `chatTransport.ts`：统一请求头、通道 URL、POST 流解析、错误与完成判断。
- `MessageFeedback.tsx`：点赞、点踩、原因与文字补充。
- `UserMemories.tsx`：长期记忆的查看、新增、修改、删除。
- `messageId.ts`：消息 ID 的处理。
- `assistant.css`：聊天面板及反馈样式。
- `AiFeedbackAdmin.tsx`：管理员筛选与处理用户反馈。

### 4.2 标签页隔离

登录信息使用 `sessionStorage`；聊天绑定也使用：

```text
cinema-ai-binding:<dify|agent>:<userId|guest>
```

请求采用 `credentials: "omit"`，不依赖浏览器共享 Cookie 识别聊天身份。使用：

- `X-Auth-Token`：当前标签页的登录凭证。
- `X-AI-Session`：服务端生成的随机绑定键。
- `X-AI-Conversation`：当前会话 UUID。

账号切换会取消旧请求、清理当前聊天状态，使用请求代次阻止旧响应覆盖新账号页面。登录失效需后端返回明确标志或流内 `auth_expired`，前端才作相应失效处理。

**标签页账号隔离不等于每个标签页都有独立账号聊天历史。** 当前 Redis 设计是每个账号、每个通道一个活动会话，因此同一账号多个设备可以恢复同一通道历史，也会受到同会话单请求限制。

### 4.3 为什么不是 EventSource

聊天要提交 JSON 和自定义鉴权头，因此前端使用 `fetch(POST)` + `ReadableStream` + `TextDecoder` 读取 SSE 帧。

解析器支持 UTF-8 字符跨网络块、帧跨网络块、多行 `data:`、空行分隔、`[DONE]` 忽略，并限制残余缓冲长度。收到 `error` 立即进入失败；连接结束没有 `complete` 则提示连接中断，防止“没有完整答案却显示成功”。

### 4.4 重置、停止与重试的差异

- 停止：取消当前生成，不等于清空历史；前端中断读取，同时调用网关停止接口。
- 重置：只换掉当前通道的会话与短期历史，不会删除用户长期记忆，也不会删除 Java 中已提交的反馈。
- 重试：创建新的一轮执行；原失败记录与新回答不能用同一个结果成功状态混淆。
- 实时 Agent 凭证有效期十分钟，临近到期时刷新；`handoff_expired` 会清理旧凭证。

## 5. AI 网关：入口与安全边界

### 5.1 接口

通道路径由服务端固定为 `dify` 或 `agent`：

```text
GET  /ai-gateway/{channel}/session
POST /ai-gateway/{channel}/chat
POST /ai-gateway/{channel}/stop
POST /ai-gateway/{channel}/reset
POST /ai-gateway/{channel}/feedback
```

`ChatRequest` 只接受会话 UUID、问题和可选临时凭证；问题长度一至两千字符。浏览器没有权力指定 `userId`、上游 Dify `conversation_id` 或 Agent 的工具参数。

### 5.2 身份核验流程

1. 先检查请求来源提示，拒绝明确 `sec-fetch-site: cross-site` 的请求。这是附加防线，不能解释为完整的所有跨站风险防护。
2. 如果有 token，网关调用 Java `/internal/ai/auth/resolve`，由 Java 验证当前登录和账号，返回用户 ID、角色、有效期。
3. 验证 Redis 绑定对应的 token 是否**正好等于本次请求的 token**，不能用 Redis 中旧 token 替代遗漏的请求凭证。
4. 验证会话 owner 与当前用户一致、会话 UUID 匹配、账号的活动会话指针仍有效。
5. Agent 还要求已登录及有效转接凭证；Dify 支持匿名会话。

鉴权服务不可用时返回 503，Redis 不可用也拒绝继续，避免在无法证明归属时放行私人会话。虽然配置中保留 `AI_AUTH_REDIS_URL`，当前身份权威核验实际走 Java HTTP，不是网关直接信任一个用户 ID。

### 5.3 临时转接凭证

Java `AiHandoffService` 根据当前登录用户签发七十二字符随机凭证，Redis 保存原登录 token 与会话 ID，有效十分钟。

网关请求 `/internal/ai/handoff/resolve` 后还检查：

- `sessionId` 等于当前 Agent 聊天会话。
- `userId` 等于网关核验的 owner。
- `scope` 为 `cinema:read`。

解析时 Java 再验证原登录态，因此登出或撤销后不能仅靠旧凭证继续查询。凭证在有效期内可重复解析，不是一次性消费令牌。

### 5.4 连接池与私网调用

网关启动创建两套共享异步 HTTP 连接池：外部调用池与内部服务池。内部池设置 `trust_env=False`，避免本机代理环境影响 Java / Agent 私网地址。默认连接超时五秒，HTTP 超时九十秒，连接数与网关并发上限相适配。服务启动会确认 Redis 可连接。

## 6. Redis 会话、并发和取消

### 6.1 会话持久化

Redis 分别使用 `ai:gateway:dify:` 与 `ai:gateway:agent:` 命名空间，保存：

- 会话与 owner、上游会话 ID、上游任务 ID。
- 标签页随机绑定键与 token 绑定。
- 账号活动会话指针。
- 最近用户 / 助手消息。
- 生成租约、取消标记、滚动限流计数。
- 两小时消息快照、反馈状态与反馈锁。

默认匿名会话一天，账号会话滑动三十天；绑定键一天。历史最多四十条消息，不是四十轮对话。每通道会话容量上限两千；消息快照每通道上限一千、TTL 两小时。

历史中保存问题和回答正文，因此“LangSmith 脱敏”**不等于整个系统不保存原文**。

### 6.2 多实例如何协作

新建账号会话使用 Redis `NX` 竞争活动指针；并发创建时保留获胜的会话。取得租约、限流、更新上游 ID、保存历史和释放锁使用 Lua 等原子操作，防止多个 worker 同时认为自己拥有执行权。

- 每个会话同一时间只允许一个生成。
- 所有网关实例、两个通道共享全局生成容量，默认十六，配置允许一至一百二十八。
- 生成租约一百二十秒，用于 worker 崩溃后的自动恢复；正常网关整轮超时九十秒。
- 释放时比较租约 token，迟到的老请求不能释放新请求的租约。
- 重置也需要独占操作；同账号其他设备持有的旧活动会话会失效，需要重新连接。

**多实例共享的前提是连接同一个 Redis 并使用同一个命名空间。** Redis 持久化、容量、清理策略、网络可用性仍决定实际恢复能力。

### 6.3 限流与取消

- 聊天：每会话每分钟十二次。
- 反馈：每会话每分钟二十次。
- 重置：每绑定每分钟五次。
- 流期间取消监测约每零点五秒一次；有登录用户时约每两秒再次向 Java 核验身份。

停止把当前租约标记为取消。Dify 额外调用其任务停止接口；Agent 通过取消内部 HTTP 流传播中断。远端已经受理的模型调用是否立即停止或不再计费，不能由本地取消机制保证。

### 6.4 完成后才发送成功

网关先观察上游事件，把 `complete` 暂存；在 `finally` 中保存快照和历史、释放租约，再按成功状态给浏览器发 `complete`。生成完成但保存失败，也不能假装会话已持久化成功。

## 7. Dify 通道

### 7.1 如何调用云端 Chatbot

网关向 Dify `POST /chat-messages`，使用服务端 Bearer API Key，提交：

```json
{
  "inputs": {},
  "query": "用户问题",
  "response_mode": "streaming",
  "user": "cinema-<网关会话UUID>",
  "conversation_id": "此前由Dify返回并由网关保存的会话ID"
}
```

`user` 使用会话标识，不直接传业务用户 ID。Dify 持有自己云端会话上下文；网关只保存其返回的会话与任务 ID，并把上游事件转为统一前端协议。

### 7.2 事件转换

- Dify `message` / `agent_message` → 前端 `delta`。
- `message_replace` → `replace`。
- `message_end` → 检查答案非空后确认上游完成。
- `error` → 固定错误分类与安全提示。
- 兼容最终答案是 `{ "answer": "..." }` JSON 的情况，提取 answer 替换展示。

答案长度上限四万字符；未完成时在清理阶段尽力停止 Dify 任务。API Key 存在仅说明已配置，不能证明 Dify 应用权限、额度、网络或工作流已正常。

### 7.3 当前代码无法说明的部分

Dify 内部的知识库、提示词、模型、工作流节点、召回参数由云端应用配置决定，不在本地源码中。本文没有把它们虚构成已实现的节点。

“Dify 承担大多数问答”能减少多少 Java 压力，取决于用户实际选择通道和 Dify 命中率；当前没有自动流量分配器，也没有实测命中率结论。

## 8. 内部 Agent 的三个入口

### 8.1 当前网站入口 `/ai/live`

只接受内部凭证，网关发送可信 `user_id`、会话 ID、当前问题和最多十条有效历史。历史来自网关 Redis，不接受浏览器伪造历史。

正常查询执行 `LangGraph.astream(..., stream_mode="custom")`，向网关输出状态、上下文、正文、错误与完成事件。最外层执行上限八十秒。

两条特殊路径直接在此入口处理：

- “记住……”：产生待确认的 `memory_suggestion`，不立即写库，也不进入通用图。
- “记得我 / 我的偏好 / 我的记忆”等显式记忆查询：读取记忆并回答，不进入通用查询图。

### 8.2 兼容入口 `/ai/chat`

返回结构化 JSON，包含答案、意图、数据、来源、执行计数和结束原因。它的历史使用进程内 `self.sessions[user:session]`，保留最近十条消息；不同 Agent worker 不共享、重启会丢失，字典的会话键没有实现统一 TTL / 总容量回收。

### 8.3 兼容入口 `/ai/stream`

先执行同一套结构化聊天，再通过 SSE 发一个结果和 `[DONE]`。它不是当前网站的 `/ai/live`，也不等于逐 token 流式生成。

### 8.4 健康检查

`/health` 返回进程状态与追踪配置摘要。它不完整探测 MCP、Java、Qwen、Chroma、Dify 等依赖，看到 UP 不能直接得出所有问答可用。

## 9. 问题理解、同义化与意图路由

### 9.1 九类意图

`movies`、`screenings`、`seats`、`order`、`refund`、`policy`、`recommend`、`chat`、`unsupported`。

意图与槽位一起形成受约束的 `QuestionPlan`，包括规范化问题、片名、影院、日期、查询范围、订单号、场次编号、偏好、置信度、澄清问题等。不会生成可执行 SQL 或授权用户 ID。

### 9.2 分层流程

1. **规则解析与预检**：日期按北京时间处理，保留原始订单标识，识别同义表达和明确槽位；无效日期、越界写操作、缺失关键编号等先处理。
2. **L0 规则快速路径**：问候、明确订单号、明确场次号、典型电影字段、明确日期场次等可以直接路由，无须调用模型。
3. **可选本地 fastText**：默认关闭。只有模型文件存在、SHA256 与评估清单相符、`deployment_approved=true`、九标签完整、置信度达阈值且符合规则约束时才接纳。
4. **可选 GLM L1**：只在 B 组、功能开启、模型可用且问题符合资格时调用。它负责高频单任务的结构化分类，不负责执行查询。
5. **Qwen 结构化理解兜底**：复杂、上下文依赖、多任务或分类未通过时调用，限制 JSON 输出与时限。
6. **代码再校验**：重新绑定规则解析出的日期、范围、明确片名和用户提供的订单号 / 场次号；低置信度或缺条件则追问。

分类模型说“这是订单查询”并不能产生订单号；模型说“查询用户 2”也不会改变当前认证用户。

### 9.3 A/B 机制

分组对 `experiment + userId + sessionId` 做 SHA256，取百分桶，默认 A/B 各一半：

- A：L0 + Qwen 兜底 + 校验 / 反思。
- B：L0 + GLM L1 + Qwen 兜底 + 校验 / 反思。

服务端允许强制 A/B 以评估或回滚。关闭 A/B 时当前实现走全 B，不应解释为关闭 GLM。GLM 自己的开关、密钥与资格检查仍生效。

### 9.4 GLM 的控制

- 默认模型 `glm-4.7-flash`，默认接受阈值 0.90，最低不低于 0.85。
- 最多输出 320 tokens，默认六秒期限，关闭 thinking，不自动重试。
- 每事件循环一次仅一个分类请求；忙时跳过，避免排队拖慢主链路。
- 429 后冷却三十秒；超时后冷却十秒。
- 发给 GLM 前屏蔽符合格式的订单号，但不是对所有个人信息进行通用匿名化。
- 片名、影院等字段必须能在问题中找到依据；不能改变已有范围、凭空补充编号或扩大查询任务。

### 9.5 同义化的边界

同义化用于把“啥片 / 电影有哪些”“能买 / 可订购”等表达归到业务槽位，不是随意改写用户要求。特别是：

- `catalog`：影片资料目录。
- `showing`：上映中的影片属性判断。
- `scheduled`：存在真实发布排期，按日期查询，可包含当天已开场或未开售场次。
- `bookable`：现在可订购，还要满足售票时间窗、影片周期、未开场等服务端规则。

**上映、已排期、当前可买是三个不同条件。** 不能用目录影片列表回答“明天哪些影片有排期”，也不能把全部排期称为可购票场次。

## 10. LangGraph 节点和边

### 10.1 八个节点

1. `prepare`：创建整轮预算、理解问题、构建 tasks、选择 simple / react、必要时读取推荐偏好、建立模型消息与版本信息。
2. `clarify`：缺条件时给出明确追问。
3. `simple`：用代码从单个已校验任务生成工具调用，不让模型再决定调用哪个工具。
4. `agent`：ReAct 决策，模型接收任务进度与已校验观察，用原生 tool calling 提议下一步；必要时有代码兜底任务。
5. `tools`：参数校验、预算检查、注入身份、执行、返回契约校验、记录 observation 与任务进度。
6. `draft`：把每个有效 observation 转成事实答案块，再拼接草稿。
7. `reflect`：优先规则验证，否则最多一次结构化模型反思；必要时回到 agent 补充尚未完成的查询。
8. `respond`：输出可信答案、追问、未完成说明或安全错误；记录执行上下文。

### 10.2 精确边关系

```text
START → prepare
prepare → clarify | simple | agent | respond
clarify → respond
simple → tools | draft | respond
agent  → tools | draft | respond
tools  → agent | draft | respond
draft  → reflect
reflect → agent | respond
respond → END
```

`prepare → respond` 包括问候和熔断等直接响应；`tools → agent` 用于 ReAct，`tools → draft` 用于 Simple；节点发现已有答案、错误或熔断时可以提前转 `respond`。

图通过 `graph.compile()` 构建，没有接 LangGraph checkpoint 存储。可跨请求恢复的是网关历史和业务记忆，不是中途工具循环的持久断点。

### 10.3 Simple 与 ReAct 怎么选

单任务、条件完整、置信度足够高时走 Simple。多意图、多订单、多片名、场次到座位依赖、不确定条件等走 ReAct 或追问。Simple 并非“换一个模型”，而是减少不必要的模型决策。

### 10.4 任务与进度

`task_progress.py` 把用户要求分解为可检查任务，追踪 pending / done / empty / blocked 等状态，决定下一个代码可执行调用。空结果是合法查询结果，但不能包装成找到记录；还有待完成任务时，也不能只因模型说“完成”就结束为全部成功。

ReAct 一次决策最多处理两个工具提议；超出部分计为无效。重复“工具名 + 排序参数”会被识别；连续没有进展会终止，避免循环烧 token。

## 11. 工具调用、MCP 和 Java SQL

### 11.1 工具全集

- `search_movies`：资料、上映、排期影片，支持片名、日期、影院、范围和分页。
- `search_screenings`：真实排期或当前可订购场次，返回编号、时间、影厅、价格。
- `query_seats`：指定真实场次的座位快照，区分 AVAILABLE / LOCKED / SOLD 等；不锁座。
- `query_order`：当前登录用户本人的订单、票、实时退票资格。
- `query_ticket_policy`：规则检索、当前启用退票政策及来源。
- `recommend_movies`：依据明确偏好或已确认记忆查询推荐候选。
- `ask_user`：控制工具，缺少真实条件时向用户提问，不执行业务查询。

前四个走 MCP；规则与推荐在 Agent 的本地工具适配中调用 Java。没有锁座、创建订单、付款、退款、删影片、管理他人订单等模型工具。

### 11.2 调用前的五层检查

1. 工具名必须在白名单。
2. Pydantic schema 禁止额外字段，例如模型传 `userId` 会被拒绝。
3. 工具查询范围、日期和当前 task 参数必须与已验证用户要求一致。
4. 订单号只允许来自用户消息；不能来自助手猜测。场次 ID 必须由用户明确提供或来自**本轮**已验证场次结果。
5. 查询关键词必须来自用户要求、已确认记忆或本轮结果，不能凭空改影院、片名或偏好。

### 11.3 MCP 协议路径

```text
LangGraph tools
 → CinemaMcpClient.call_tool
 → MCP initialize + tools/call（Streamable HTTP）
 → MCP /mcp
 → Java 固定 HTTP 接口
 → JdbcTemplate 参数化查询
 → structuredContent {data: ...} / {error: ...}
 → Agent validate_result
 → observation / ToolMessage
```

客户端每轮创建独立连接，以请求头绑定内部凭证和可信 `X-AI-User-ID`，不会把身份写进模型参数。MCP 是 stateless HTTP，启用 Host / DNS rebinding 检查与内部 token 中间件。

工具 `readOnlyHint` 是协议描述；真正的只读边界还依赖白名单、固定接口和 Java 的实际实现，不能只靠这个提示字段保证。

### 11.4 工具对应 Java 接口

```text
search_movies     → GET /internal/movies
                    GET /internal/movies/query（带范围/分页等条件时）
search_screenings → GET /internal/screenings
query_seats       → GET /api/screenings/{id}/seats
query_order       → GET /internal/orders/{orderNo}?userId=<服务端绑定身份>
ticket_policy     → GET /internal/refund-policy
                    GET /internal/knowledge/search
recommend_movies  → POST /internal/recommendations
```

### 11.5 SQL 的真实位置

`InternalAiController.java`、`AiMovieQueryService.java` 等 Java 代码构建 SQL。用户输入作为 `?` 参数绑定；动态拼接的查询条件由服务端选择，模型没有传 SQL 字符串的入口。

本人订单最终条件包含：

```sql
WHERE o.order_no = ? AND o.user_id = ?
```

即便猜中别人的订单号，也不能在当前身份下返回他人订单。Agent 还会检查返回订单号与 user_id 是否匹配，作为第二层结果边界。

电影查询排除 OFFLINE / ARCHIVED，排期要求有效影院、影厅和发布场次；影片分页先去重再附排期摘要，避免热门影片挤掉其他影片。场次查询最多五十条；摘要可能截断，答案应保留“不完整”的含义。

### 11.6 退票结果为什么要实时查

订单退票资格由 Java 用订单状态、当前时间、启用政策截止分钟数、验票状态计算。当前逻辑要求已出票、没有票验票入场、政策可用，且当前时间严格早于退票截止时刻。

通用“开场前 N 分钟可退”的知识只能解释规则；某张订单能不能退，以 `query_order` 返回 `can_refund`、`refund_reason`、`refund_deadline` 为准。Agent 不会代用户执行退款。

### 11.7 推荐当前的能力边界

推荐工具可以利用确认偏好，但 Java 当前主要是按 genre / title / actors 的关键词 SQL 查询并返回有限候选；不能描述成已经实现协同过滤、深度推荐或全站行为画像。

## 12. 答案生成、规则验证与反思

### 12.1 数据不能直接当模型可信观察

工具执行后先检查返回类型、必须字段、查询范围、日期和订单归属等契约。校验失败产生 `query_contract_mismatch` 或业务鉴权错误，不能继续把不匹配数据喂给模型并宣称是用户请求的结果。

向模型展示 observation 时有长度限制，截断结果带 `truncated` 标志。订单、座位等事实不是任由模型补齐的自由文本。

### 12.2 草稿是事实格式化

`draft` 不调用模型写一篇自由答案。它逐个格式化已验证 observation，形成 evidence_blocks。上映 / 排期回答、订单字段、座位统计、政策文本等有专门格式化逻辑。

### 12.3 反思不是另一个无限 Agent

- 对确定的单任务、规范事实结果，`rule_verifier.py` 可以直接验证，跳过额外模型费用。
- 复杂或不确定情况最多调用一次 Qwen，要求结构化 JSON，检查漏任务、无证据结论和建议动作。
- 反思本身不能调用工具。
- 需要补任务时由代码检查后回 ReAct，不是由反思输出任意调用。
- `grounded_revision` 只允许选取、排序已经存在的完整事实块，不允许随意重写业务事实。
- 反思失败、拒绝或预算用尽时，用已确认事实与限制说明收尾，不伪造“通过审核”。

## 13. 模型与整轮预算

### 13.1 默认模型分工

- Qwen `qwen3.7-flash`：复杂理解、ReAct 工具决策、结构化反思；默认温度 0、thinking 关闭、模型客户端不自动重试。
- GLM `glm-4.7-flash`：B 组可选意图分类。
- DashScope `qwen3.7-text-rerank`：公开票务知识片段的重排。
- 本地 BGE：用户记忆向量化，不是聊天模型。
- Dify：实际使用哪种模型取决于云端应用配置，本地代码无法证明。

模型名称来自代码 / 示例默认设置，可能被环境变量覆盖。API 文件只由服务端读取，本文不复制密钥内容。

### 13.2 整轮限制

- 业务工具调用：默认四次，硬上限八次。
- 无效工具调用：默认三次，硬上限三次。
- ReAct 决策步数：默认五步，硬上限五步。
- 模型调用：默认八次，硬上限八次，包含理解、GLM、决策、反思。
- Simple 模型调用默认最多两次；GLM 已尝试且又进入兜底时有受总上限约束的额外一次空间。
- tokens：默认 32,768，配置硬上限 131,072。
- 图内预算期限：默认六十五秒，硬上限七十秒。
- 外层 Agent 请求：八十秒；网关：九十秒；生成租约：一百二十秒。
- 反思：最多一次，不能通过提高步数变成无限反思。

### 13.3 预算怎样实现

`RequestBudget` 为每次图执行独立创建，`BudgetedModel` 包装不同阶段模型调用：发请求前检查剩余时间、调用次数、输入与最大输出预留；返回后用模型提供的 usage 纠正。

输入预估保守按序列化 UTF-8 字节计算并计入工具 schema。模型没有返回 usage 时保留保守预留，并标记 `usage_missing_calls`，因此这些数字不能直接当云端账单精确 token 数。

单次模型通常至多二十秒并受整轮剩余期限限制；理解另有十五秒约束；GLM 默认六秒；工具执行通常最多十五秒并受预算约束。超过限制熔断，禁止继续调用。

**Rerank 是独立 HTTP 请求，其费用不在 LangChain ChatModel 的 token 计数里。** 整轮仍受工具 / 外层期限约束，不能把 chat token 预算当整个 AI 账单总额。

## 14. 票务知识检索与 Rerank

### 14.1 这条路径与 Chroma 记忆不同

票务知识当前使用：

1. `knowledge/*.md` 本地 Markdown。
2. Java 数据库 `knowledge_document` 搜索结果。
3. 当前启用 `refund_policy` 的权威政策。
4. 本地关键词召回、合并去重、可选云端重排。

并没有把所有电影、订单、票务知识都写到 Chroma 中。Chroma 当前承载的是用户长期记忆。

### 14.2 分块和重排

文本分块默认五百字符、重叠八十，优先按段落和中文标点切分，保留 source、version、chunk_id。关键词召回按中文字符和英文词等交集排序，合并数据库片段后最多三十个候选。

默认 Rerank 取前四个，五秒上限，并发四；只发送所提供的公开政策片段，不把订单、座位记录或私人记忆当作重排文档。查询文本本身仍会发给重排提供方，不应声称完全没有用户文本出网。

缺密钥、超时、网络错误、非法响应、返回索引越界等情况回到已有候选顺序前四个，不让重排故障阻断基础政策解释。纯退票政策问题可直接走权威政策与关键词候选，跳过云端重排。

## 15. 记忆机制：三种不同的“记住”

### 15.1 短期对话历史

网站聊天由网关 Redis 保留最近四十条，Agent 使用其中最多十条有效消息。Dify 还有云端 `conversation_id` 关联的上下文。两通道的短期历史互不混用。

这些历史帮助回答“那明天呢”之类上下文问题，不等于长期偏好，也不是永久保存所有对话。

### 15.2 Agent 图内状态

每次执行的 tasks、observations、budget、工具消息只服务本轮调用。未接 checkpoint，进程中断不能从中途工具节点续跑。

### 15.3 长期用户记忆

MySQL `ai_user_memory` 是权威记录；Chroma `agent_user_memory_v1` 是可重建的向量投影。范围固定为 AGENT，类别：GENERAL / GENRE / CINEMA / SEAT / HABIT。

- 每用户最多两百条 ACTIVE 记忆。
- 每条内容最多五百字符。
- “记住我喜欢科幻”只产生建议，用户确认后由 Java 创建；也可在记忆管理界面显式新增。
- 修改 / 删除使用版本号做乐观锁，过期版本返回冲突。
- 删除使用 DELETED 标记与递增版本，再异步清理向量。
- 并非每轮自动总结、自动写入用户画像；模型没有任意记忆写工具。

### 15.4 写入与异步索引

Java 在同一个事务更新记忆并写 `ai_memory_index_outbox`。Memory worker 每次最多领取十项，MySQL `FOR UPDATE SKIP LOCKED` 防重复领取，同一记忆事件按顺序处理；租约五分钟，失败三十秒后重试。

worker 读取当前行与事件版本：旧事件已被新版本替代时跳过旧投影；当前事件成功写 / 删 Chroma 后才确认。确认必须匹配 leaseToken 且租约未过期，迟到 worker 不能覆盖新租约。

这样 MySQL 提交后就有恢复索引的任务，不必让前端等待向量化。索引是最终一致，并不保证保存的瞬间就已进入向量库。

### 15.5 向量模型

- 模型：`BAAI/bge-small-zh-v1.5`，固定模型获取 revision。
- 本地 CPU，归一化向量；查询文本加检索前缀，存储内容不加。
- SentenceTransformer 按本地模型目录加载，`local_files_only=True`，不会在用户请求时临时联网下载。
- Chroma 使用 cosine 距离，显式传入 embedding，不依赖 Chroma 默认远程嵌入函数。
- 编码在线程池串行执行，避免阻塞异步事件循环和重复初始化。

### 15.6 召回与二次校验

1. 先向 Java 查该用户当前 ACTIVE 记忆；没有就结束。
2. Chroma 按 `user_id + channel=AGENT` 过滤，向量取最多五条候选。
3. 只把候选 ID 与 version 发给 Java `/internal/ai/memories/verify`。
4. Java 再检查 owner、ACTIVE、当前 version，返回权威内容。
5. 向量库失败、未命中有效结果时退回 SQL 最近记忆；整个记忆服务失败则不带记忆继续普通查询。

删除记忆即使向量尚未清理，也会在 Java 校验时被排除；旧版本不能越过权威校验。

自动背景召回目前主要用于**电影推荐**；显式“我的记忆”请求也会召回。没有把用户偏好无差别加入每个订单或座位查询。

### 15.7 三种数据源不能互换

- 订单能否退：查 Java 当前业务数据。
- 用户爱看哪类电影：查确认的用户记忆。
- 退票制度是什么：查当前政策与知识来源。

不能把用户记忆中的旧票价、旧时间当作实时业务事实，也不能用公共知识替代订单归属核验。

## 16. 反馈、后台处理与澄清样本

### 16.1 点赞 / 点踩链路

服务端为每个生成保存 Snapshot，绑定消息 ID、会话、通道、用户、问题、回答、失败情况、意图和有限上下文。

用户反馈时前端只提交 messageId、like / dislike / null、固定原因与最多五百字符的补充。网关重新验身份、会话、消息归属、可反馈状态，再加分布式反馈锁。

它不会信任前端上传的一份任意问题 / 回答 / 用户 ID 当作真实聊天记录。

### 16.2 两个存储层

- Redis 快照保存两小时，回答截取最多八千字符并标识截断；流式展示上限四万字符。
- 用户明确反馈时才写入 Java 持久反馈记录。不是每条聊天自动写后台反馈表。

快照过期后反馈可能返回 410，恢复历史也会去掉无可用快照的反馈消息 ID。后台看到的是已提交的反馈，不是无限期在线查看每个用户所有对话。

### 16.3 Dify 反馈同步

先把本地反馈存到 Java，再用服务端保存的 Dify 消息 ID 调用 `/messages/{id}/feedbacks`，最后写同步状态。

- Agent：NOT_APPLICABLE。
- Dify：PENDING → SYNCED 或 FAILED；没有有效上游消息 ID 时 UNAVAILABLE。
- Dify 同步失败不抹掉已经保存的本地反馈。
- 当前没有完整的持久异步重试队列自动修复所有 PENDING / FAILED，不应把状态字段当作已实现自动补偿。

### 16.4 另一个反馈机制：补槽澄清样本

`clarification_feedback.py` 在“缺订单号 / 日期 / 场次号 → 用户补充 → 查询验证成功”的情况下收集脱敏样本，存入独立 SQLite。

样本标记 `silver`、`requires_review=true`，只作为待审核数据，不能自动当作可靠黄金标签或立即训练上线。本地数据库会包含脱敏后的问题 / 回复，因此与 LangSmith 的 metadata-only 机制不同。

## 17. LangSmith 与本地追踪

### 17.1 开启条件

同时满足：`LANGSMITH_TRACING=true`、允许的本地 / 测试 / 预发环境、有效服务端配置，才创建追踪客户端。默认运行环境按 production 处理，避免无意开启。

支持 US 默认 endpoint、自定义配置和组织密钥需要的 Workspace ID。配置成功只代表客户端已创建，权限、网络和云端写入是否成功还需要实际请求证据。

### 17.2 能看什么

- 每轮根 trace 与父子 span 关系。
- LangGraph 节点执行、模型调用、工具调用和耗时。
- 固定错误码、发生阶段、HTTP 状态、结束原因。
- Simple / ReAct、A/B、提示词 / 规则指纹、槽位存在性摘要。
- 模型调用次数、工具次数、反思次数、token usage 或保守预留。

输出使用 `MetadataOnlyClient` 对 SDK 的写入路径统一清洗，包括原生图 / 模型回调，避免仅手写工具 span 脱敏、自动回调却上传原文。

### 17.3 本地归档组织

```text
langsmith(tracing)/
├─ .archive-index.sqlite3
└─ 2026_10_12/
   └─ 42_2026_10_12_14_24_a1b2c3d4e5f6/
      ├─ session.json
      └─ traces.jsonl
```

上例用户 42 与 hash 仅为格式示例。分钟使用 `_`，Windows 文件夹不能使用时间中的 `:`。同一分钟多个会话用 session hash 区分。

会话首次追踪时确定目录；同一会话后续多轮、跨日、进程重启仍归该会话首次目录，因此第二天仍可能写入前一天的会话目录。这是**按会话聚合**，不是每轮都重新按当天拆分。

SQLite 索引保存 session_ref 与目录、trace_id 与会话关系，支持延迟 SDK 回调归档；写入通过线程锁与 SQLite 事务协调多个 Agent 进程。

JSONL 每行是已清洗 span 的创建 / 更新事件，有 trace_id、run_id、parent_run_id、时间、名称、摘要、允许 metadata、固定错误码。不是原始 prompt / 问答 / SQL / 工具行明细的全集。

### 17.4 隐私边界要分开看

- LangSmith 和本地 traces：只允许摘要与白名单 metadata，业务正文与凭证不上传；云端会话关联使用 hash，本地 session.json 含用户 ID。
- 模型理解与决策：为了完成查询，会读取问题、有限历史以及必要工具观察，可能包含业务字段；不能把 LangSmith 脱敏误解为模型也没收到它们。
- Dify：会收到用户发给 Dify 的问题，并保留它自己的云端会话。
- Redis：保存短期问答正文。
- MySQL AI 反馈：保存用户主动反馈对应的问题 / 回答等。
- MySQL / Chroma 记忆：保存用户确认的偏好内容。

追踪失败会记录安全日志，尽量不阻断业务回答；关闭追踪也意味着当前这种本地 LangSmith 归档路径不会照常生成所有 span，不是独立永久开启的全量审计系统。

## 18. “回答未完成”如何定位

### 18.1 这是界面结果，不是唯一根因

可能发生在：

- 请求尚未开始：登录失效、旧会话、绑定不匹配、凭证到期、限流、忙碌。
- 调用 Dify / Agent：不可达、上游 4xx / 5xx、SSE 提前 EOF。
- Agent：模型鉴权失败、模型权限 / 地域错误、429、超时、工具网络错误、MCP 未启动、Java 内部 token 不一致、结果契约不一致。
- 预算：模型次数 / token / 步数 / 工具次数耗尽。
- 返回阶段：用户停止、切换账号、网络断开、代理缓冲 / 超时、Redis 持久化失败。

某些预算终止会返回已确认事实与未完成说明，属于业务层部分完成；如果通道最终完整发送并持久化，SSE 仍可以 `complete`。**协议完成与用户所有任务完成不是同一概念**，需要结合 stop_reason / pending_tasks 理解。

### 18.2 推荐排查顺序

1. 先看浏览器请求通道和返回：是 HTTP 拒绝，还是流内 error，还是缺 complete？
2. 看 Gateway 日志的 messageId、provider、stage、错误类型 / 状态。
3. Agent 分支关联 trace_id，查看该用户会话归档或 LangSmith 的节点耗时。
4. 判断卡在理解、模型决策、MCP、Java 查询、反思还是持久化。
5. 401 / 403 区分登录凭证、内部服务凭证、模型凭证、LangSmith 凭证，不能把它们当同一种密钥错误。
6. 若是 query_contract_mismatch，先比对服务版本和返回字段 / 范围；不要通过关掉校验掩盖不匹配。
7. 若只有 health UP 而实际请求失败，继续查依赖和权限，不以进程活着代替链路健康。

日志通常在 `cinema-ticketing-backend/target/ai-<service>-stderr.log` / stdout.log。图册 08 标出了追踪关联路径。本文未对当前运行故障作诊断结论。

## 19. 对后端压力的实际影响

### 19.1 已经减少的工作

- FAQ 在 Dify 云端完成，不必每次调内部业务查询工具。
- SSE 连接与 Dify 流转发由 Python 网关承接，减少 Java 直接持有这些聊天连接。
- L0、Simple 和规则验证减少云端模型调用与循环。
- Redis 会话、连接池、全局并发、速率和预算限制减少无序放大。
- 记忆向量化异步完成，不挡住 Java 记忆保存事务。

### 19.2 仍然落到 Java 的工作

- 网关登录核验和流期间身份复核。
- Agent 转接凭证核验。
- 影片、场次、座位、订单、政策和推荐的实际查询。
- 记忆写入、召回二次校验、索引任务领取 / 确认。
- 点赞 / 点踩持久化及后台管理。

因此它把流式连接与 FAQ 负担分散了，但不会让真实业务查询消失。默认十六个同时登录的长流，在流中身份复核阶段理论上约每两秒每流一请求，即约八次 / 秒，加上其他操作；这是按代码周期推算的上限量级示例，不是压测结果。

同一业务问题使用 ReAct 可能产生多次 Java 查询；降低复杂度要依赖清晰范围、工具预算、索引和业务查询性能。当前不能仅靠“接了 Dify”保证数据库压力一定很小。

## 20. 已实现边界与仍需注意的限制

以下是当前代码的能力边界，不是本次提出或执行的改造：

- 没有自动 Dify → Agent 失败转接和历史迁移。
- 不提供模型执行交易或后台管理写操作。
- 网站 Agent 不支持逐 token 正文输出；状态通道与最终正文策略不同。
- LangGraph 未配置持久 checkpoint，兼容 JSON 接口的内存会话不适合无额外处理的多实例恢复。
- 记忆索引最终一致，模型文件需预先部署；默认 SQL 回退不是语义最优召回。
- 同账号同通道共享活动会话，重置会影响其他设备旧会话。
- 点踩 Dify 同步存在状态记录，但未实现完整自动补偿队列。
- 反馈快照有两小时窗口与容量限制，不能保证无限期反馈旧消息。
- 配置模板、Docker Compose、本地启动进程可能使用不同环境变量；修改模板不会自动更新正在运行的进程。
- gateway ready / Agent health 不等于依赖健康、付费模型可用或追踪写入成功。
- 当前工具权限依赖受信内网与共享内部凭证；浏览器不能访问私网服务是部署边界的一部分。
- 既有评估脚本与历史报告有参考价值，不代表这次已重新运行或证明当前线上质量。

## 21. 配置定位与阅读顺序

不要把密钥放进 `VITE_*`。服务端环境变量优先于文件加载；本文只指向配置项，不展示任何实际密钥。

### 网关配置

`cinema-ai-gateway/.env.example`：DIFY_API_BASE_URL、DIFY_API_KEY_FILE、JAVA_API_URL、AGENT_API_URL、AI_INTERNAL_TOKEN、AI_REDIS_URL、AI_REDIS_PREFIX、AI_MAX_STREAMS、AI_GATEWAY_WORKERS。

### Agent 配置

`cinema-ai/.env.example`：`QWEN_MODEL / KEY_FILE / BASE_URL`、`GLM_L1_*`、`AGENT_L0_ENABLED`、`INTENT_L1_*`、`AGENT_AB_*`、`AGENT_MAX_*`、`AGENT_TIMEOUT_SECONDS`、`AGENT_RULE_VERIFIER_ENABLED`、`RERANK_*`、`MEMORY_*`、`CHROMA_*`、`LANGSMITH_*`、`AI_ENVIRONMENT`、`CINEMA_MCP_URL`。

### 推荐阅读路线

1. 图 01 和本说明 1–3：知道系统有哪些服务。
2. 前端 `CinemaAssistant.tsx` + `chatTransport.ts`：知道浏览器发什么。
3. 网关 `main.py` + `store.py`：知道身份、历史、并发和完成语义。
4. Agent `main.py` + `react_agent.py`：知道入口与图。
5. `intent.py` / `intent_routing.py` / `glm_router.py`：知道如何理解用户。
6. `react_tools.py` / MCP / Java：知道数据从哪里来以及谁能查。
7. `task_progress.py` / `agent_budget.py` / `rule_verifier.py` / `reflection.py`：知道怎样保证有限执行与有据回答。
8. `memory.py` / worker / `AiMemoryService.java`：知道长期记忆如何存取。
9. `tracing.py` / feedback / evaluation：知道如何观测、回收问题和评估。

## 22. 一句话概括

**前端组织会话，网关守住身份与流量，Agent 把自然语言变成有限的只读查询计划，MCP 提供受约束工具，Java 执行权威业务查询，答案经过事实校验后返回；Redis 支持短期历史与协调，MySQL + Chroma 支持确认后的长期记忆，反馈和 LangSmith 支持后续排查。**

## 23. 协议与数据结构细节

### 23.1 容易混淆的各类标识

- **登录 token**：证明当前业务登录身份，Java 负责验证和撤销。
- **bindingKey**：随机会话绑定键，前端放在标签页 sessionStorage；需要同时匹配本次 token 和会话。
- **sessionId**：网关聊天 UUID，一次重置后会改变。
- **credential**：Java 签发的短期 Agent 转接凭证，与登录及会话绑定。
- **Dify conversation_id**：Dify 云端自己的历史标识，保存于网关服务端。
- **task_id**：Dify 当前生成任务标识，用于停止。
- **messageId**：网关为本次回答生成的 UUID，用于反馈与日志定位。
- **trace_id**：Agent 本轮追踪根 UUID；一次会话可以有很多轮 trace。
- **run_id / parent_run_id**：某个节点 / 模型 / 工具 span 与父级关系。
- **session_ref**：用户 ID 与会话 ID 的 hash，供追踪关联与目录索引。

这些标识用途不同，不能把某个 trace_id 当登录凭证，也不能拿 Dify conversation_id 直接请求本人订单。

### 23.2 浏览器到网关

示意结构，UUID、凭证和问题均为占位示例：

```http
POST /ai-gateway/agent/chat
Content-Type: application/json
X-Auth-Token: <当前标签页登录token>
X-AI-Session: <bindingKey>
X-AI-Conversation: <sessionId>

{
  "sessionId": "<会话UUID>",
  "question": "明天有哪些可以订购的场次？",
  "credential": "<Java签发的短期凭证>"
}
```

Dify 通道不允许混入 Agent 的 credential。浏览器不提交 user_id、SQL、历史消息或实际工具调用。

### 23.3 网关到 Agent

```json
{
  "user_id": 42,
  "session_id": "<Agent通道会话UUID>",
  "question": "明天有哪些可以订购的场次？",
  "history": [
    {"role": "user", "content": "之前的本通道问题"},
    {"role": "assistant", "content": "之前完整成功的本通道回答"}
  ]
}
```

42 只是示例。身份来自网关验证结果；即便 history 来自可信网关，其中的自然语言仍属于用户上下文，不能作为更高权限指令覆盖系统和工具约束。

### 23.4 发给浏览器的事件

每帧形式为 `data: <JSON>\n\n`：

```text
{"type":"message","messageId":"<本轮回答UUID>"}
{"type":"status","message":"正在理解你的问题…"}
{"type":"context","normalized_question":"规范化后的问题"}
{"type":"delta","text":"回答正文"}
{"type":"replace","text":"用于替换的最终正文"}
{"type":"memory_suggestion","content":"我喜欢科幻","category":"GENRE"}
{"type":"complete"}
```

上面是事件种类示意，单轮不一定包含全部事件，正常回答也不一定触发 replace 或 memory_suggestion。

失败例子：

```text
{"type":"error","code":"query_timeout","message":"实时查询超时，请稍后重试。"}
```

内部 Agent 的 `context` 远比浏览器的丰富，包含路由、预算、任务进度、版本与反思结果。网关目前仅保留有限字段进入 Snapshot，并主要向浏览器转发 normalized_question。**不能认为所有内部执行计数已完整展示于前端或后台反馈页。** 完整诊断还需要 Agent 追踪和内部结构化响应。

### 23.5 `AgentState` 按职责理解

- 身份与输入：user_id、session_id、question、messages。
- 理解结果：intent、entities、normalized_question、confidence、intent_source、requested_intents、clarification、needs_clarification。
- 任务与模型上下文：tasks、memories、agent_messages、pending_calls。
- 事实来源：observations、result、retrieved_docs、evidence_blocks。
- 草稿与校验：draft_answer、verified_answer、reflection_findings、reflection_status、reflection_resume。
- 进度与去重：seen_calls、tool_calls、tool_call_count、invalid_call_count、no_progress_count、step_count。
- 预算与终止：budget、model_call_count、token_usage、circuit_open、stop_reason、finish_reason、error、error_code、last_tool_error。
- 观测与版本：route、route_reason、slot_summary、understanding_layer、preflight_reason、runtime_version、l1_status、l1_duration_ms、l1_attempted。

状态里的字符串不会自动成为授权。例如 entities 中描述的片名可用于查询；user_id 必须由受信请求入口设置。

### 23.6 `ChatResponse` 有哪些诊断信息

兼容 JSON 接口会提供：

```text
answer / intent / data / sources / tool_calls
route / route_reason / stop_reason / circuit_open
step_count / tool_call_count / invalid_call_count
model_call_count / reflection_call_count / reflection_status
token_usage / pending_tasks / slot_summary
understanding_layer / preflight_reason
runtime_version / l1_status / l1_duration_ms / l1_attempted
```

单查询 data 通常保留原数据结构；退款问题可形成 order / orders 与 policy 组合；多个观察可能返回 results。调用方应按响应契约解释，不能对所有意图假定同一种 data 形状。

## 24. 六种常见问题的执行示例

以下用于解释路径，具体是否走 L0 / 模型由文本、历史、配置和分组决定，未实际执行这些示例。

### A. “你好”

规则识别 chat → prepare → respond → 固定能力介绍。通常不需要业务工具或模型查询，回答会说明可查影片、场次、本人订单与退票资格。

### B. “明天有哪些已排期电影”

规范化明天的北京时间日期 → movies + movie_scope=scheduled → 搜索真实排期影片 → Java 按日期取有发布场次的电影 → 保留摘要截断信息 → 校验与返回。

如果用户说“明天可以订购哪些场次”，则应是 screenings + bookable，范围发生变化；代码不能仅因两句都包含“明天”就把它们当成同一查询。

### C. “我的订单 OEXAMPLE123 能退吗”

订单号仅作示例。解析 refund 与用户显式订单号 → query_order → Java 当前身份 WHERE 约束 → 实时 can_refund / refund_reason → 返回截止时间和规则解释 → 提示到订单页操作。

若问“为什么不能退、手续费和到账如何算”，任务可能增加规则检索；没有来源的收费 / 到账时长不能靠常识编造。

### D. “明天某电影还有座位吗”

片名与日期有依据，但缺场次编号 → 搜索场次 → 单一可确定场次继续 query_seats，多候选则 ask_user → 用户下一轮明确场次后查询。

座位是当前快照；回答“有座”不表示已经锁住，最终售票仍需正常选座流程处理并发。

### E. “记住：我喜欢科幻，常去某影院”

`memory_proposal` 特殊分支 → 前端展示建议和保存按钮 → 用户确认 → Java 保存 + outbox → worker 向量索引。后续推荐可以召回这些偏好；这条输入本身不自动创建长期记录。

### F. “帮我推荐，然后查 A、B 两张订单”

多任务 → tasks → ReAct / 代码兜底按预算执行 → 每张订单分别验证归属 → 推荐使用明确偏好或确认记忆 → 多事实块 → 反思检查是否漏任务。

如果预算不足，返回已确认部分并说明剩余，不把第一张订单的状态套到第二张上。

## 25. 框架各自承担什么

### FastAPI / Uvicorn

提供 Agent 和网关 HTTP / SSE 服务。网关可以多个 worker，分布式共享靠 Redis，而不是 FastAPI 自动同步 Python 字典。

### LangChain Core / OpenAI 适配器

提供消息类型、结构化工具 schema、异步模型调用、Retriever / Document 等抽象；Qwen 与 GLM 使用兼容接口适配。是否可访问对应模型仍取决于真实账号、地域和权限。

### LangGraph

负责图状态、条件边、节点执行、custom 事件输出。预算、身份、业务权限、结果契约、持久化不是接上 LangGraph 自动获得的，都是本项目额外代码实现。

### MCP

提供标准工具发现 / 调用协议与结构化返回封装。本项目通过固定工具、请求头身份和 Java 业务实现建立安全约束。MCP 不替代登录或数据库权限。

### Chroma / Sentence Transformers

Chroma 负责向量候选检索；Sentence Transformers 加载 BGE 生成同一模型的存储与查询向量。Java MySQL 负责记忆归属和最新版本，两者一起组成长期记忆链路。

### LangSmith

负责追踪事件、父子 span 与耗时查看；本项目再增加元数据清洗、本地会话归档与 trace 关联。它不负责替 Agent 决策，也不会自动修复失败。

### 依赖锁定快照

源码 `requirements.txt` 当前声明：FastAPI 0.115.12、httpx 0.28.1、MCP 1.28.0、sse-starlette 2.2.1、langchain-core 0.3.58、langgraph 0.3.34、langchain-openai 0.3.16、langsmith 0.3.45、Pydantic 2.11.3、Uvicorn 0.34.2。

记忆相关声明 Chroma 1.5.9、sentence-transformers 6.1.0、torch 2.14.1、transformers 5.18.0；网关 Redis 客户端 5.2.1。这里是仓库依赖声明，未检查每个运行进程的实际安装版本。

## 26. 文档的维护与复用

本文是一次代码快照解释。以后增加自动转接、交易工具、持久 checkpoint 或新的记忆策略时，需要同时更新图中的边界和本说明，避免图比代码多出不存在的能力。

`build_diagrams.py` 只生成本目录的说明图、阅读页与源码索引，不会导入应用、读取 API 凭证或调用业务 / 模型服务。Markdown 和 SVG 是主要成果；排版 HTML 使用环境中已有的 Markdown 渲染库生成，读取页面不需要启动 Java、Agent、Dify 或联网。

SVG 保留文字和路径，可在浏览器放大或在支持 SVG 的工具里编辑。图册可从 `index.html` 直接打开，完整阅读页 `implementation.html` 也可离线打开。
