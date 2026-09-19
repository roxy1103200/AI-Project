# 影院售票系统：传统 Java 后端 + AI Agent 完整开发方案

## 1. 项目定位与亮点

这是一个适合大三/大四求职实习的综合项目：先用传统 Java 后端完成稳定的影院售票业务，再使用 LangChain 与 LangGraph 增加 AI Agent 能力。

项目亮点：

- Spring Boot + MyBatis + MySQL 完成核心业务。
- Redis 实现缓存、座位锁定、幂等与限流。
- RabbitMQ 实现订单超时取消、异步通知和削峰。
- 解决高并发选座、重复下单、重复支付回调等问题。
- LangChain 实现 RAG、Tool Calling 和会话管理。
- LangGraph 实现 Agent 状态流转和多节点工作流。
- Docker + Nginx 完成完整部署。

推荐架构为“模块化单体 Java 服务 + 独立 Python AI 服务”，先保证传统业务闭环，再逐步增加 AI 能力。

## 2. 完整业务模块

### 用户端

- 注册、登录、退出。
- 影片浏览、分类筛选、详情查看。
- 影院查询、影厅查询、场次查询。
- 座位图查看、选座、锁座。
- 模拟支付、订单查询、电子票查看。
- 退票申请和退票规则校验。
- AI 影院智能助手。

### 管理端

- 用户管理。
- 影片、类型、演员管理。
- 影院、影厅、座位布局管理。
- 场次排片管理。
- 订单、退款、操作日志查询。
- 退票规则和 AI 知识库文档管理。

### AI 能力

- 电影问答。
- 场次查询。
- 订单查询。
- 退票规则问答。
- 电影推荐及推荐理由解释。
- 多轮会话和参数澄清。

## 3. 系统架构与组件职责

```text
Web / Mobile
    |
  Nginx
    |
Spring Boot API
    |-- 用户、影片、影院、场次、座位、订单、支付
    |
    |-- MySQL：最终事实数据
    |-- Redis：缓存、短期锁座、幂等、限流
    |-- RabbitMQ：异步消息、超时取消、通知

LangChain + LangGraph AI Service
    |-- RAG 知识库
    |-- 业务工具调用
    |-- Agent 状态图
    |-- HTTP / MCP 调用 Java 内部 API
```

- Nginx：反向代理、静态资源、统一入口、基础限流。
- Spring Boot：核心业务、鉴权、事务、状态机和数据校验。
- MyBatis：持久化和复杂查询。
- MySQL：用户、影片、影院、场次、订单等最终数据。
- Redis：热点缓存、座位短锁、请求幂等、Token、限流。
- RabbitMQ：订单事件、延迟取消、出票、通知、失败重试。
- LangChain：模型、Prompt、RAG、Retriever、Tools。
- LangGraph：意图路由、澄清、工具执行、结果校验和回复。
- Docker：统一启动所有基础设施与业务服务。

## 4. 数据库核心表设计

### `user`

`id`、`username`、`password_hash`、`phone`、`role`、`status`、`created_at`。

### `movie`

`id`、`title`、`description`、`duration`、`release_date`、`director`、`actors`、`genre`、`status`。

### `cinema`

`id`、`name`、`address`、`phone`、`status`。

### `hall`

`id`、`cinema_id`、`name`、`row_count`、`column_count`、`hall_type`。

### `seat`

`id`、`hall_id`、`row_no`、`column_no`、`seat_code`、`seat_type`、`status`。

### `screening`

`id`、`movie_id`、`hall_id`、`start_time`、`end_time`、`price`、`status`。

### `ticket_order`

`id`、`order_no`、`user_id`、`screening_id`、`total_amount`、`status`、`expire_at`、`paid_at`。

### `order_item`

`id`、`order_id`、`seat_id`、`price`、`ticket_status`。

### `refund_record`

`id`、`order_id`、`amount`、`reason`、`status`、`created_at`。

### `knowledge_document`

`id`、`title`、`content`、`version`、`enabled`、`created_at`。

关系：影院 1:N 影厅，影厅 1:N 座位；影片 1:N 场次；用户 1:N 订单；订单 1:N 订单明细。

建议索引：

- `screening(movie_id, start_time)`。
- `screening(hall_id, start_time)`。
- `ticket_order(user_id, created_at)`。
- `ticket_order(order_no)` 唯一索引。
- `order_item(order_id, seat_id)` 唯一索引。
- 幂等请求号唯一索引。

## 5. Redis 使用场景

```text
movie:detail:{movieId}
screening:detail:{screeningId}
screening:seats:{screeningId}
seat:lock:{screeningId}:{seatId}
order:idempotent:{userId}:{requestId}
user:token:{token}
rate_limit:ai:{userId}
```

座位锁定建议使用 Redis Lua 脚本，原子完成“检查锁是否存在、校验持有者、写入锁、设置 TTL”。锁定时间建议为 5 分钟，锁值包含 `userId` 或 `orderNo`。

Redis 只负责短期占用和快速失败，MySQL 负责订单最终事实。释放锁时必须校验锁的持有者，避免误删其他用户的锁。

## 6. RabbitMQ 异步消息

建议消息：

- `order.delay.cancel`：订单延迟取消。
- `order.cancel`：订单取消事件。
- `order.paid`：支付成功事件。
- `ticket.issued`：出票事件。
- `notification.email`：邮件通知。
- `notification.sms`：短信通知。

超时取消流程：

1. 创建待支付订单。
2. 发送带 TTL 的延迟消息。
3. 消息进入死信交换机。
4. 取消消费者收到消息。
5. 再次查询订单状态。
6. 只有订单仍为 `UNPAID` 时才取消。
7. 释放 Redis 座位锁。
8. 更新订单为 `CANCELLED`。

消费者需要具备手动 ACK、幂等、重试、死信队列和失败日志。

## 7. 购票核心链路与一致性

```text
查询场次 -> 查询座位 -> Redis 原子锁座 -> 创建待支付订单
-> 模拟支付 -> 订单 PAID -> 出票
                         |
                    超时未支付
                         v
                 RabbitMQ 取消并释放锁
```

推荐订单状态：

```text
UNPAID -> PAID -> ISSUED
   |                 |
   v                 v
CANCELLED       REFUNDING -> REFUNDED
```

并发与一致性措施：

- Redis Lua 防止多个用户同时锁定同一座位。
- 请求号和唯一索引防止重复下单。
- 支付回调使用订单号和支付流水号幂等。
- 状态机禁止 `PAID -> CANCELLED` 等非法转换。
- 超时取消前重新查询订单状态。
- 订单、订单明细、出票记录在事务中更新。
- 退票前校验开场时间和退票规则。

建议接口：

```text
POST /api/auth/register
POST /api/auth/login
GET  /api/movies
GET  /api/cinemas/{id}/screenings
GET  /api/screenings/{id}/seats
POST /api/orders/lock-seats
POST /api/orders
POST /api/orders/{orderNo}/pay
GET  /api/orders/{orderNo}
POST /api/orders/{orderNo}/refund
```

## 8. AI 模块设计

### AI 影院助手

支持查询上映影片、影院场次、本人订单、订单状态、退票规则、购票须知，并支持电影推荐和推荐理由解释。

### LangChain 组件

- Chat Model。
- Prompt Template。
- Tool Calling。
- Retriever。
- 文档切分和 Embedding。
- 会话记忆。
- 结构化输出。

### LangGraph 状态图

```text
START
  -> 意图识别
  -> 参数完整性检查
     -> 缺参数：澄清节点
     -> 规则问题：RAG 节点
     -> 查询问题：工具调用节点
     -> 推荐问题：推荐节点
  -> 结果校验
  -> 回复生成
  -> END
```

Agent State：

```python
{
    "session_id": "...",
    "user_id": "...",
    "intent": "...",
    "slots": {},
    "messages": [],
    "tool_calls": [],
    "retrieved_docs": [],
    "auth_scope": {},
    "result": {},
    "error": None
}
```

业务工具：

```text
search_movies
search_screenings
query_order
query_ticket_policy
recommend_movies
check_refund_eligibility
```

安全边界：Agent 不直接访问数据库，不直接修改订单。下单、支付、退票等写操作必须调用 Java API，由 Java 后端负责鉴权、参数校验、幂等、事务和状态机。

RAG 知识库内容可以包括购票须知、退票规则、会员规则、影厅说明、优惠政策和客服 FAQ。回答时返回规则版本或来源；检索不到内容时明确说明，不能编造政策。

## 9. AI 与 Java 集成

优先使用 HTTP：

```text
POST /api/ai/chat
POST /api/ai/stream
```

AI 服务调用 Java 内部 API：

```text
GET  /internal/movies
GET  /internal/screenings
GET  /internal/orders/{orderNo}
GET  /internal/refund-policy
POST /internal/recommendations
```

请求应携带 `userId`、`sessionId` 和用户问题。后续可将这些内部能力封装为 MCP Tools，LangGraph Agent 作为 MCP Client；HTTP 仍作为稳定基础接口保留。

## 10. Docker 与 Nginx

Docker Compose 服务：

```text
mysql
redis
rabbitmq
cinema-api
cinema-ai
nginx
```

Nginx 路由：

```text
/api/* -> cinema-api:8080
/ai/*  -> cinema-ai:8000
/      -> 前端静态资源
```

部署步骤：编写 Dockerfile，配置环境变量，初始化数据库，启动 MySQL/Redis/RabbitMQ，启动 Java 与 AI 服务，配置 Nginx，最后通过 Swagger 和接口测试验收。

## 11. 分阶段开发路线

### 阶段一：基础工程

完成 Spring Boot、MyBatis、MySQL、统一响应、全局异常、参数校验、日志、Swagger 和 Docker 基础环境。

### 阶段二：传统业务

完成用户、影片、影院、影厅、座位、场次、订单查询和管理端 CRUD。

### 阶段三：购票闭环

完成座位查询、Redis 锁座、订单、模拟支付、出票、退票、幂等和订单状态机。

### 阶段四：消息与并发

完成 RabbitMQ、延迟取消、死信队列、消费者幂等、失败重试和并发测试。

### 阶段五：部署优化

完成 Docker Compose、Nginx、缓存优化、SQL 索引、接口限流和日志监控。

### 阶段六：AI 助手

完成 LangChain、RAG、场次/订单/规则工具和 Java HTTP 集成。

### 阶段七：LangGraph Agent

完成意图路由、参数澄清、工具调用、结果校验、错误兜底和多轮会话。

## 12. 必须做与进阶可选

### 必须做

- 用户登录。
- 影片、影院、影厅、场次。
- 座位布局。
- Redis 锁座。
- 订单和模拟支付。
- RabbitMQ 超时取消。
- Docker 和 Nginx。
- 一个可用的 AI Agent。
- 至少一个 RAG 能力。
- 至少三个业务工具调用。

### 进阶可选

- 真实支付。
- 微服务拆分。
- 分布式事务。
- Elasticsearch。
- 复杂推荐模型。
- 多 Agent 协作。
- 语音助手。
- 多模态海报分析。
- 大规模向量数据库集群。

## 13. 简历项目描述与面试亮点

### 简历描述

独立设计并实现基于 Spring Boot、MyBatis、MySQL、Redis、RabbitMQ 的影院售票系统，完成影片、影院、场次、座位、订单、模拟支付和退票等业务闭环；使用 Redis Lua 脚本实现高并发场景下的原子锁座，结合请求幂等、订单状态机和 RabbitMQ 延迟消息实现订单超时取消与异常补偿；基于 LangChain + LangGraph 构建影院智能 Agent，支持场次查询、订单查询、退票规则 RAG 问答和电影推荐，通过 HTTP 与 Java 后端完成工具调用集成，并使用 Docker + Nginx 完成部署。

### 面试重点

- 为什么座位锁放在 Redis？
- 如何防止重复下单？
- 支付回调如何幂等？
- RabbitMQ 重复消费怎么办？
- Redis、MySQL、RabbitMQ 如何分工？
- Agent 如何进行用户鉴权？
- RAG 如何减少幻觉？
- 为什么 Agent 不能直接操作数据库？
- 如何控制 AI 服务的响应时间和调用成本？

## 14. 最终推荐的项目边界

先完成“单体 Java 后端 + Redis 锁座 + RabbitMQ 超时取消 + Docker 部署”，再加入“独立 AI 服务 + LangChain RAG + LangGraph Agent”。不要一开始就做微服务、真实支付、复杂推荐和多 Agent，否则容易导致传统业务没有真正做扎实。
