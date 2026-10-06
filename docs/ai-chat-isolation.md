# Dify 与内部 Agent 独立聊天

## 页面入口

- 首页右下角保留「智能 Agent」入口及原聊天窗口，用于电影、场次、座位、本人订单及退票规则查询。
- Agent 左侧新增圆形「Dify」小悬浮球，打开独立的知识问答窗口。
- 桌面宽度大于 900px 时，两个窗口可以同时并排打开。小屏幕保留并排入口，每次显示一个聊天窗口，关闭窗口不会清空另一助手的记录。
- Agent 需要登录，点击「登录后开始查询」打开登录弹窗，登录成功后自动打开 Agent。每轮查询由前端自动申请或刷新只读凭证。
- Dify 可匿名使用。未配置 Dify 密钥时，Dify 窗口提示尚未配置，Agent 仍可独立使用。
- 两个窗口各自发送问题、停止回答、恢复聊天、创建新对话和评价回答，不提供转接或上下文传递操作。

## 数据隔离

前端分别挂载两个固定渠道的客户端。它们只共享网站登录身份，不共享聊天状态。

- 独立的消息列表、输入草稿、错误提示、流式连接与停止控制器。
- 浏览器绑定分别保存为 `cinema-ai-binding:dify:<userId或guest>` 与 `cinema-ai-binding:agent:<userId或guest>`；不读取旧混合聊天绑定。
- 网关根据 URL 中的渠道选择服务和存储，不接受请求体中的模式选择来切换服务。
- Redis 聊天数据分别使用 `${AI_REDIS_PREFIX}dify:` 和 `${AI_REDIS_PREFIX}agent:` 前缀。
- 会话编号、浏览器绑定、账户当前会话指针、聊天历史、反馈摘要、反馈锁、生成锁、取消标记和渠道限流分别保存。
- Dify 云端会话编号与任务编号只由 Dify 通道使用。Agent 只接收 Agent 自身最近的历史。
- Dify 请求不带 Agent 凭证、Agent 问答历史或电影、座位、订单等业务查询结果。Agent 也不读取 Dify 问答历史。
- 将一个渠道的绑定、会话编号或消息编号用于另一个渠道，不能读取、清空、停止或评价原渠道的数据。
- 两个渠道仍使用同一个网关进程、Redis 服务与 Java 登录校验；全局生成并发额度共享以保护资源，不承载聊天内容。
- 用户明确提交的反馈仍进入原影院管理后台，按 `DIFY` / `AGENT` 来源区分。只有 Dify 回答反馈同步 Dify 云端，Agent 回答及反馈不会同步到 Dify。

## 接口

`channel` 仅允许 `dify` 或 `agent`。

- `GET /ai-gateway/{channel}/session`：获取或恢复该渠道的会话。
- `POST /ai-gateway/{channel}/chat`：在该渠道发送问题，返回 SSE。
- `POST /ai-gateway/{channel}/reset`：为该渠道创建新会话。
- `POST /ai-gateway/{channel}/stop`：停止该渠道当前回答。
- `POST /ai-gateway/{channel}/feedback`：提交该渠道回答的评价。

继续使用 `X-Auth-Token`、`X-AI-Session` 与 `X-AI-Conversation` 校验当前登录、浏览器绑定及期望会话。前端不提交可信用户 ID 或历史记录。

Java `/api/ai/handoff` 与内部 `/api/internal/ai/handoff/resolve` 保留原接口名称，当前仅用于 Agent 查询授权，不再表示 Dify 与 Agent 之间的聊天转接。凭证仍绑定当前登录与 Agent 会话，只有只读权限。

## 更新与旧记录

必须同时发布前端构建产物和新版 AI 网关，并重启网关、刷新页面。旧 `/ai-gateway/session`、`/chat` 等混合接口已移除；旧页面不能与新网关配套使用。Nginx 现有 `/ai-gateway/` 路径代理可以继续使用。

本次未修改 Java、内部 Agent、MCP 或数据库表结构，这些服务无需因本次拆分而迁移。模型密钥及其他环境变量沿用现有配置。

旧混合聊天记录不自动迁移到任一渠道，避免把旧 Dify 内容带入 Agent，或把旧业务数据带入 Dify。原 Redis 数据未删除，按既有保留时间自然过期；新入口从各自的独立历史开始。

## 验证

已使用一次性 Redis、模拟 Java/Dify/Agent 上游完成隔离集成测试，测试不调用真实模型或生产数据库。覆盖独立恢复、上下文隔离、跨渠道凭证拒绝、新对话、同时生成及停止、反馈来源、旧混合数据不导入等 8 项。

```powershell
cd E:/development/AI-Project/cinema-ticketing-backend/cinema-ai-gateway
../cinema-ai/.venv/Scripts/python.exe -m unittest discover -s tests -v
```

测试优先使用 `CINEMA_TEST_REDIS_URL`；未设置时启动一次性 Redis。在本机可使用 Maven 缓存中的 embedded-redis 1.4.3 Windows 二进制，其他环境可使用 PATH 中的 `redis-server`。测试仅清理自身随机前缀数据。

前端通道请求测试与现有消息编号、影片图片保存测试共 9 项；TypeScript 检查与生产构建均通过。

```powershell
cd E:/development/AI-Project/cinema-ticketing-frontend
npm test
npm run build
```

浏览器使用模拟上游与一次性 Redis 验证：登录后自动打开 Agent、两个入口及桌面窗口并排、分别发送问题、重置 Dify 后保留 Agent 记录、手机窗口切换、关闭再打开恢复各自记录。真实供应商模型及远程服务器部署需在发布环境验证。
