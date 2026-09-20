# 影院售票系统后端

阶段一基础工程，基于 Spring Boot、MyBatis、MySQL、Redis、RabbitMQ、Nginx 和 OpenAPI。

运行环境：JDK 21、MySQL 8.0.44。项目显式锁定 MySQL Connector/J 8.0.33；该驱动适配 MySQL 8.0.x，避免本地开发环境因 Maven 依赖管理变化而产生版本差异。

## 本地启动

1. 启动基础设施：`docker compose up -d mysql redis rabbitmq`（首次启动会自动执行 `schema.sql`）
2. 构建并启动服务：`mvn spring-boot:run`
3. 健康检查：`GET http://localhost:8080/api/health`
4. Swagger UI：`http://localhost:8080/swagger-ui.html`

## Docker 启动

1. 先构建 JAR：`mvn clean package -DskipTests`
2. 启动完整入口：`docker compose up -d --build`
3. 通过 Nginx 访问：`GET http://localhost/api/health`

基础设施账号仅用于本地开发，生产环境必须通过环境变量替换。

## 第二阶段接口

通用资源接口支持 `users`、`movies`、`cinemas`、`halls`、`seats`、`screenings`：

- `GET /api/{resource}`：列表查询
- `GET /api/{resource}/{id}`：详情查询
- `POST /api/{resource}`：管理端新增
- `PUT /api/{resource}/{id}`：管理端全量更新
- `DELETE /api/{resource}/{id}`：管理端删除
- `GET /api/orders?userId={userId}`：订单列表
- `GET /api/orders/{orderNo}`：订单详情

写接口已要求 `X-Auth-Token`，只有登录后的 `ADMIN` 用户可以操作；注册接口为 `POST /api/auth/register`，登录接口为 `POST /api/auth/login`，退出接口为 `POST /api/auth/logout`。

用户列表和详情只返回脱敏字段，绝不返回 `password_hash`。密码使用 BCrypt 哈希保存。当前 token 存储在进程内存中，后续阶段会迁移到 Redis，并补充刷新、撤销和多实例共享能力。

持久化取舍：用户账户与鉴权查询已使用 MyBatis Mapper；通用后台资源 CRUD 暂时保留 JdbcTemplate 动态实现，以减少重复 Mapper 样板代码。后续若进入多条件查询和复杂事务，将按资源拆分为独立 Entity、Mapper、Service 层。

## 第三阶段购票闭环接口

- `GET /api/screenings/{screeningId}/seats`：查询场次座位和实时占用状态
- `POST /api/orders/lock-seats`：使用 Redis Lua 脚本原子锁座，锁定时间为 5 分钟
- `POST /api/orders`：创建待支付订单，`requestId` 用于请求幂等
- `POST /api/orders/{orderNo}/pay`：模拟支付并完成出票，订单状态变为 `ISSUED`
- `GET /api/orders/{orderNo}`：查询当前登录用户的订单详情
- `GET /api/orders`：查询当前用户订单，管理员可按 `userId` 查询
- `POST /api/orders/{orderNo}/refund`：校验开场时间后执行退票，状态变为 `REFUNDED`

订单状态流转为 `UNPAID -> ISSUED -> REFUNDED`；Redis 负责短期座位锁，MySQL 负责订单最终状态。RabbitMQ 超时取消属于第四阶段。

## 第四阶段消息与并发

- 订单创建事务提交后发送 `order.cancel.delay` 延迟消息
- 延迟队列过期后通过死信交换机进入 `order.cancel` 消费队列
- 取消消费者使用手动 ACK，最多重试 3 次，最终失败消息进入 `order.cancel.failed`
- `message_consume_record` 保证消费者幂等；订单取消使用 `UNPAID` 条件更新避免重复状态变更
- 订单保存 Redis 锁持有者，超时取消只释放对应用户的座位锁
- RabbitMQ 地址支持 `SPRING_RABBITMQ_HOST`、`SPRING_RABBITMQ_PORT`、`SPRING_RABBITMQ_USERNAME` 和 `SPRING_RABBITMQ_PASSWORD` 配置

## 第五阶段部署优化

- 影片、影院、影厅和场次等目录查询使用 Redis 缓存，写操作自动清理缓存，缓存 TTL 为 5 分钟；实时座位查询不使用缓存
- 所有 `/api/*` 请求默认按客户端 IP 限制为每分钟 120 次，可通过 `RATE_LIMIT_REQUESTS_PER_MINUTE` 调整
- `/actuator/health`、`/actuator/metrics` 和 `/actuator/prometheus` 提供健康检查与监控指标
- 请求自动生成 `X-Trace-Id`，日志记录请求路径、状态码和耗时
- Docker Compose 已配置 MySQL、Redis、RabbitMQ 健康检查和服务启动依赖；Nginx 负责反向代理、转发真实客户端 IP 和网关日志

## 第六阶段 AI 助手

新增独立 `cinema-ai` 服务，端口为 `8000`，通过 HTTP 调用 Java 内部业务接口，不直接访问数据库。

- `POST /api/ai/chat`：Java 鉴权后转发到 AI 服务
- `POST /api/ai/stream`：SSE 形式返回 AI 助手结果
- `POST /ai/chat`：AI 服务结构化问答
- `POST /ai/stream`：AI 服务流式问答
- 内置 LangChain Tools：影片查询、场次查询、订单查询、退票规则、电影推荐、退票资格
- 内置 RAG 知识库：购票须知、退票规则、影院 FAQ，回答携带来源和规则版本
- AI 只读调用 Java 内部接口，支付、退票等写操作仍由 Java 鉴权、事务和状态机负责

AI 服务支持 `OPENAI_API_KEY` 和 `OPENAI_MODEL`；未配置模型密钥时使用确定性意图路由和本地 RAG，仍可完成基础演示。

数据库、服务端口和凭据均支持通过环境变量覆盖：`DB_URL`、`DB_USERNAME`、`DB_PASSWORD`、`SERVER_PORT`、`AI_SERVICE_URL`、`AI_INTERNAL_TOKEN`。
