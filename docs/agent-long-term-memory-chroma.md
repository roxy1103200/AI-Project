# 内部 Agent 长期记忆接入方案：MySQL + Chroma

状态：**首期已实现并在本地启动验证（2026-10-06）**。MySQL 记忆管理、Chroma 索引工作进程、BGE 中文向量检索、Agent 偏好使用和“我的记忆”界面已接通。Dify 知识问答继续使用自己的会话，不读取这套记忆。以下原设计中的自动提议、开关和管理看板属于后续扩展，以文末“已实现与运行”说明为准。

## 目标与边界

登录观众可以让 Agent 跨会话记住稳定偏好，例如“喜欢科幻片”“通常选靠后的位置”。观众可以查看、修改、删除记忆。当前 Redis 聊天历史继续承接最近追问，最长闲置 30 天；长期记忆由 MySQL 保存，不因点击“新对话”而清空。

票价、实时场次、座位占用、订单状态、退票资格及规则版本每次仍通过现有只读业务工具查询。记忆只影响问题理解、推荐排序和表达习惯，不作为订单或票务事实的证据。匿名访客不建立长期记忆。

## 一次提问经过哪里

```text
浏览器的 Agent 窗口
  → 网关 /ai-gateway/agent/chat
  → Java 校验当前 Agent 凭证并返回可信 userId
  → 内部 Agent 用 userId + 固定渠道 agent 检索 Chroma 的候选记忆
  → Java 按 userId、记忆 ID 和版本复核 MySQL 有效记录
  → 内部 Agent 同时调用现有 MCP 票务工具，依据实时结果回答
```

Dify 路由不增加记忆读取或写入。前端和模型均不能提交可信 `userId`；沿用网关对当前登录与会话的校验。Agent 与 Chroma 的通信只在服务端内网进行。

## 存储分工

**MySQL 是权威数据。** 新建 `ai_user_memory`，建议字段：

| 字段 | 用途 |
| --- | --- |
| `id CHAR(36)` | 稳定 UUID，同时作为 Chroma 记录 ID |
| `user_id BIGINT` | 外键指向 `users.id`，服务端从登录获取 |
| `channel VARCHAR(8)` | 首期只允许 `AGENT` |
| `category VARCHAR(32)` | 如影片类型、影院、座位、观影习惯 |
| `content VARCHAR(500)` | 一条简短、可编辑的记忆事实 |
| `source_kind VARCHAR(24)`、`source_message_id CHAR(36) NULL` | 记录来源为手动填写或确认提议；原会话过期后不保证能展开原文 |
| `version INT`、`status VARCHAR(12)` | 更新版本和 `ACTIVE` / `DELETED` 状态 |
| `created_at`、`updated_at`、`deleted_at` | 管理、重建索引和删除审计 |

建立 `(user_id, channel, status, updated_at)` 索引。偏好可另设规范化 `memory_key`，同一用户更新“喜欢的类型”时修改原记录并递增版本，避免重复事实互相矛盾。账号删除时删除或匿名化关联记忆；密码、支付信息、订单号、手机号和实时查询结果不进入 `content`。

**Chroma 是可重建索引。** 建立 `agent_user_memory_v1` collection：`ids=[memory.id]`，`documents=[content]`，`metadatas` 至少含 `user_id`、`channel`、`version`、`category`。查询时强制 `user_id = 可信用户` 且 `channel = AGENT`，只取少量相近候选 ID；正式使用前再次向 Java 批量读取 MySQL，核对归属、`ACTIVE` 和版本。Java 不返回的候选一律丢弃。Chroma 故障时，仍可读取 MySQL 中最近的明确偏好；检索失败不影响票务查询。

**Redis 维持现状。** 最近 40 条聊天和本轮最多 10 条上下文继续保存在独立的 Agent Redis 命名空间。旧混合会话不导入长期记忆；新建记忆需要观众重新确认。

## 写入、更新与删除

1. 前端增加“我的记忆”面板，调用 Java 的 `GET/POST/PATCH/DELETE /api/ai/memories`。Java 使用已有 `X-Auth-Token` → `AuthService.requireUserId()` 校验身份，所有查询和修改都带服务端得出的 `user_id`；请求体不接受 `userId`。
2. 首期支持手动添加；观众说“记住我喜欢科幻片”时，Agent 可以返回一条**记忆提议**，前端让观众确认后再调用 Java 保存。不要把每轮完整对话或模型自行猜测的偏好自动写入。
3. Java 在同一个 MySQL 事务内写 `ai_user_memory` 和 `ai_memory_index_outbox`。后者保存 `memory_id`、`version`、`UPSERT/DELETE`、处理状态和重试时间。独立索引工作进程领取任务时先读取 MySQL 当前版本，跳过过时事件；有效任务生成向量并对 Chroma 按 ID `upsert`，或按 ID `delete`，成功后确认任务；失败可以重试。
4. 用户删除时先将 MySQL 记录标为 `DELETED`，立即从读取接口排除，再异步删除 Chroma 向量。即使索引暂时保留旧向量，Agent 的 MySQL 复核也不会让它进入回答。更新版本时同理拒绝旧索引结果。
5. 定期检查 MySQL 与 Chroma 的 ID/版本差异，并提供从 MySQL `ACTIVE` 记录重建索引的管理命令。Embedding 模型变化时使用新 collection（例如 `_v2`）重建并切换，避免不同维度的向量混入旧索引。

## 服务改动位置

- **Java 后端**：新增 `ai-user-memory-schema.sql`、对应的建表初始化或正式迁移、`AiMemoryController`、`AiMemoryService`；公开接口负责本人的记忆增删改查，内部接口负责已校验用户的批量复核及索引任务领取/确认。内部接口仅接受现有 `AI_INTERNAL_TOKEN`，且不向公网 Nginx 暴露。
- **Python 内部 Agent**：新增记忆检索模块，在 `/ai/live` 已取得可信 `user_id` 后读取 Chroma 候选和 Java 复核结果。向量化模块同时供检索和索引进程使用；现有电影、场次、座位、订单 MCP 工具及只读票务权限保持原规则。
- **索引进程**：单独运行 Python worker，消费 Java 的 MySQL outbox，避免多 Uvicorn worker 重复执行后台索引任务；领取时设置租约，到期可重试，按 `memory_id + version` 幂等处理。
- **前端**：在 Agent 窗口提供记忆管理入口及记忆提议确认操作。Dify 悬浮球不显示这套记忆。
- **部署**：Compose 新增仅内网可访问的 Chroma 服务和数据卷，以及索引 worker；Agent 连接 Chroma 的服务地址。Windows 本地运行可用 Docker 映射到另一个本机端口，避免与 Agent 的 8000 端口冲突。MySQL 与 Chroma 都纳入备份；索引仍可从 MySQL 重建。

## Embedding 与 Chroma 选型

首期建议用本地中文模型 [`BAAI/bge-small-zh-v1.5`](https://huggingface.co/BAAI/bge-small-zh-v1.5) 做向量化；其模型卡给出 512 维和 MIT 许可。写入和查询必须固定同一模型版本、预处理与向量维度。由 Agent/索引进程生成向量，通过 Chroma 的 `embeddings`、`query_embeddings` 接口提交，避免不同进程依赖各自的默认 Embedding 配置。模型文件预先准备在服务卷中，启动不依赖现场下载。

生产部署采用独立 Chroma 服务及 Python `AsyncHttpClient`，并固定测试过的服务镜像与客户端版本。确认所选镜像的实际持久化目录，显式开启持久化、挂载数据卷，执行“写入 → 重启容器 → 查询”的验收；Chroma 各镜像版本的数据目录不宜凭旧示例推测。只允许 Agent 与索引 worker 访问 Chroma 端口，不经 Nginx 暴露。Chroma 官方文档提供 [服务端客户端模式](https://docs.trychroma.com/production/chroma-server/client-server-mode)、[Python 客户端](https://docs.trychroma.com/reference/python) 和 [collection 查询、upsert、删除接口](https://docs.trychroma.com/reference/python/collection)。

## 验收顺序

1. 用户 A 保存记忆后，关闭并重开浏览器、新建 Agent 对话仍可使用；用户 B 和 Dify 均读不到。
2. 编辑“喜欢科幻片”为“不喜欢科幻片”后只使用新版；删除后立即不再进入 Agent 上下文，即使 Chroma 暂时不可用。
3. Chroma 重启后向量可查询；清空测试索引后可从 MySQL 重建，不丢失权威记忆。
4. “今天场次多少钱”“我的订单能否退票”仍按当次 MCP 查询结果回答，不用长期记忆作价格或资格依据。
5. 对索引超时、重复任务、乱序版本、账户切换、退出登录、过期凭证和其他用户记忆 ID 做隔离验证。

首个交付阶段建议只做“手动保存/确认提议 + 我的记忆 + 检索使用”；自动归纳多轮聊天在这一链路稳定后再加，并继续让用户控制是否保存。

## 已实现与运行（首期）

### 使用方式

1. 登录后打开右下角“智能 Agent”，点击“我的记忆”。支持分类添加、修改、删除，每个账号最多 200 条、每条最多 500 字。
2. 对 Agent 说“请记住：我喜欢科幻电影”，回答下方会出现“保存记忆”。点击确认才会写入 MySQL；普通聊天不会自动保存。
3. 点击“新对话”后，可以问“你记得我喜欢什么电影吗”。已有偏好也会作为回答背景；无明确类型的电影推荐会使用已保存的正向电影类型偏好。
4. 当轮明确要求优先；已删除、旧版本或其他用户的记忆不会作为背景使用。订单、场次、座位和票价仍由现有业务查询提供。

首期尚未实现普通对话自动提取候选、重复偏好合并、用户级停用开关、索引看板和排序学习。后端提供 `MEMORY_ENABLED=false` 总开关，关闭读取后仍可管理已保存的记录。

### 本地 Windows 启动

Java 21、Python 3.12；Chroma 固定 `1.5.9`，Sentence Transformers 固定 `6.1.0`。本次安装 CPU Torch `2.14.1+cpu`，依赖检查通过，未升级项目原有 FastAPI / Pydantic / LangChain 固定版本。

在 `cinema-ticketing-backend/cinema-ai` 中创建 `.env`（参考 `.env.example`），新增：

```dotenv
MEMORY_ENABLED=true
CHROMA_HOST=127.0.0.1
CHROMA_PORT=8030
CHROMA_SSL=false
MEMORY_MODEL_PATH=../data/models/bge-small-zh-v1.5
```

依赖安装和一次性下载模型（模型下载需要网络；日常提问只读取本地模型）：

```powershell
# 在 cinema-ticketing-backend/cinema-ai 下执行
uv pip install --python .venv/Scripts/python.exe torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.\.venv\Scripts\python.exe -m app.provision_memory_model
```

模型：`BAAI/bge-small-zh-v1.5`，512 维、归一化向量，固定 revision `7999e1d3359715c523056ef9478215996d62a620`。只有查询文本添加 BGE 中文检索前缀；写入文档不加。更换模型或预处理时必须重建整个 collection，不能混用向量。

重新构建并启动 Java，`AiMemorySchemaInitializer` 只执行独立 `ai-memory-schema.sql` 的建表语句，不重放业务种子数据。已有生产库也可以由 DBA 先执行该 SQL，然后配置 `ai.memory.initialize-schema=false`。

```powershell
# 在 cinema-ticketing-backend 下；已有服务先停止对应服务，避免重复占用端口
.\start-ai-local.ps1 -Service chroma
.\start-ai-local.ps1 -Service mcp
.\start-ai-local.ps1 -Service agent
.\start-ai-local.ps1 -Service gateway
.\start-ai-local.ps1 -Service memory
# 或在所有 AI 服务均停止时：.\start-ai-local.ps1 -Service all
```

停止支持同名 `-Service`。Chroma 只监听 `127.0.0.1:8030`，心跳地址 `http://127.0.0.1:8030/api/v2/heartbeat`；模型和索引分别位于 `cinema-ticketing-backend/data/models`、`data/chroma`，不放在 Maven `target` 中，避免 `mvn clean` 删除。索引任务日志为 `target/ai-memory-stderr.log`。索引工作进程不开放 HTTP 端口。

### 服务器 Compose

已扩展 `cinema-ticketing-backend/docker-compose.yml`：增加 Chroma、一次性模型准备服务和 memory-worker，持久化卷 `chroma-data` / `memory-model`。Chroma 不映射公网端口；Agent 和 worker 通过服务名访问，复用内部服务令牌。Dockerfile 安装 CPU Torch，避免服务器拉取 CUDA 运行库。

```bash
# 先按现有部署流程构建后端 JAR，配置服务器 .env 中的内部令牌和模型 API 信息
# 此命令启动 app profile 所有应用（包含长期记忆服务）
docker compose --profile app up -d --build
```

本次已验证本地 Windows 的完整链路；当前机器没有 Docker CLI，**尚未在 Ubuntu 服务器执行这次升级，也未实测 Compose 镜像**。

### 接口与索引恢复

- 用户接口：`GET/POST /api/ai/memories`，`PATCH /api/ai/memories/{id}`，`DELETE /api/ai/memories/{id}?version=N`。都需要 `X-Auth-Token`，归属只取登录用户；更新和删除需要当前版本，冲突返回 409。
- 内部接口：`/internal/ai/memories`、`/internal/ai/memories/verify`、`/internal/ai/memory-index/claim`、`/internal/ai/memory-index/{id}/ack`，需要 `X-Internal-Token`。
- 管理员重建：`POST /api/admin/ai-memory/reindex`，需要管理员的 `X-Auth-Token`。重新排队每条记忆最新的已完成事件，未完成任务继续正常重试。重建含删除标记。
- 每批领取最多 10 个任务，同一记忆按事件顺序领取；租约 5 分钟。失败 30 秒后重试，崩溃后租约到期自动恢复；迟到的确认不能覆盖新租约。worker 单任务限制 20 秒。
- 更新与 outbox 在同一 SQL 事务内；写入 Chroma 使用稳定 UUID 幂等 upsert/delete。过期版本任务跳过，后续最新事件继续同步。
- 索引未同步或不可用时读取 MySQL 当前偏好。Chroma 命中仍须通过 MySQL 的用户、渠道、有效状态和版本复核；Java 故障时本轮不使用记忆，继续普通票务查询。
- 删除使用 SQL 墓碑，立即停止参与检索，异步删除向量。墓碑仍保留原文；如果需要删除原文的隐私清除策略，后续另加定期清理任务。备份重点是 MySQL 的两张新增表；Chroma 可以由 MySQL 重建。

### 验证记录

- Java 7 项测试：真实 SQL + Spring 事务、跨用户访问、版本冲突、事务回滚、任务顺序、租约重领、重试和重建，以及接口认证和管理员权限。
- Python 5 项测试：真实 Chroma 的归属过滤、SQL 复核、更新/删除幂等、故障回退、过期事件跳过和失败重试；测试使用独立临时 collection 与合成向量，不依赖云模型。
- 实际 MySQL + 本地 512 维 BGE + Chroma HTTP + Agent：两个临时账号验证跨会话记住、用户隔离、修改立即生效、删除立即生效以及提议不自动落库。
- 页面实际验证“我的记忆”添加、修改及 Agent 确认保存入口；前端类型检查与生产构建通过。
- Agent / MCP 合计 17 项、网关 9 项、前端 9 项，加上新增 Java 7 项，共 42 项测试通过。Chroma 服务重启后两个实际 BGE 向量仍可读取；临时测试账号与记忆已清理。
- 管理员重建通过 SQL 事务测试及接口权限测试；本次未在本地真实管理员账号上执行。自动审批拒绝了临时账号提权的测试步骤，未实施该权限变更。

### 本地助手连接故障与后台启动

出现“助手连接失败”时先检查 8080 / 8000 / 8010 的监听状态。2026-10-06 排查发现前端和 MCP 存活，但后端、Agent 和网关进程已退出；恢复后，从 5173 代理入口验证两个登录会话均返回 200。

新增 `cinema-ticketing-backend/start-stack-background.ps1`，通过隐藏的独立 Windows 启动器拉起已构建的 Java 后端及缺失的 AI 服务，避免后台进程依附调用终端的任务生命周期。已有端口不会重复启动；仅用于本地 `local` 配置，不负责重新构建 JAR。

```powershell
# 在 cinema-ticketing-backend 下，指定实际 Java 21 路径
.\start-stack-background.ps1 -JavaPath 'D:\java\jdk21\bin\java.exe'
```

默认也支持 `JAVA_HOME` 或 PATH 中的 Java。启动日志为 `target/stack-startup.log`；AI 服务可继续用 `stop-ai-local.ps1 -Service ...` 停止。Java 后端需停止其已确认的本项目 JAR 进程。服务器使用 Compose 的服务管理，不使用此 Windows 脚本。
