# 内部 Agent 源码备份

备份日期：2026-09-28。源仓库提交：`7c39c19e3e906d124b8c8d6c8f98a11d42d1eac7`。

本目录保存影院售票项目中**实际运行的内部 Agent 链路**及直接相关的集成文件。`源文件/` 下保留原项目相对路径，文件内容与备份时的源文件完全一致；阅读注释见 [注释说明.md](注释说明.md)。[文件清单.csv](文件清单.csv) 列出每个文件的大小和 SHA-256，可用于逐个核对。共备份 53 个文件。

## 运行链路

```text
浏览器 CinemaAssistant
  ├─ 常见问题 → /ai-gateway/chat → AI 网关 → Dify
  └─ 用户点击转接 → Java /api/ai/handoff 签发短期凭证
                     → /ai-gateway/chat（agent 模式）
                     → Java /internal/ai/handoff/resolve 校验身份与会话
                     → 内部 Agent /ai/live
                     → Java /internal/* 只读业务查询
                     → Agent / 网关 SSE → 浏览器
```

内部 Agent 负责理解问题、选择固定工具、查询实时业务数据并生成回复。网关负责会话、身份绑定、限流、流式转发与反馈；Java 负责登录校验、转接凭证和业务查询。订单归属由网关解析出的登录身份约束，模型输出不能自行指定身份或执行下单、支付、退款。

## 目录内容

- `源文件/cinema-ticketing-backend/cinema-ai/`：FastAPI、LangGraph、意图理解、Java 查询工具、Qwen 配置及本地知识文档。
- `源文件/cinema-ticketing-backend/cinema-ai-gateway/`：Dify 与内部 Agent 的统一网关、Redis 会话、SSE 协议和反馈处理。
- `源文件/cinema-ticketing-backend/src/main/`：Java 转接、内部只读接口、反馈接口、兼容接口及相关配置和数据库定义。
- `源文件/cinema-ticketing-frontend/`：聊天面板、前端 SSE 客户端、反馈界面、登录会话关联和开发代理配置。
- `源文件/cinema-ticketing-backend/start-ai-local.ps1`、`stop-ai-local.ps1`、`docker-compose.yml`、`nginx/nginx.conf`：本地启动与部署接线。
- `源文件/docs/`：当前配置说明与 Dify 转接方案说明。

其中 Java `AiGatewayController` / `AiGatewayService` 提供旧版 `/api/ai/chat`、`/api/ai/stream` 兼容接口；目前前端使用 `/ai-gateway/*`。这两条路径都已备份，并在注释中标明，避免恢复时误判入口。

## 备份边界与使用

这是**相关源码快照**，不是可独立启动的完整项目。Java 文件仍依赖原后端其他业务类和数据库；前端文件仍依赖原 React 项目。需要恢复时，先查看 `文件清单.csv` 和 `注释说明.md`，再将 `源文件/` 中对应文件复制回相同的项目相对路径，并按 [启动说明](源文件/docs/dify-agent-setup.md) 安装依赖及配置环境。

没有备份实际密钥、`API/`、`.env`、`application-local.yml`、虚拟环境、构建产物、日志或 Redis/MySQL 业务数据。两个 `.env.example` 仅为配置模板；`docker-compose.yml` 中的演示默认值也不能当作生产凭证。若要在另一台机器运行，需要单独提供环境配置、模型与 Dify 密钥以及基础服务。

原项目源码未因本次备份修改。说明文档与清单放在备份目录外层，确保 `源文件/` 内的内容可按 SHA-256 与原文件核对。
