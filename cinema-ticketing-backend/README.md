# 影院售票系统后端

阶段一基础工程，基于 Spring Boot、MyBatis、MySQL、Redis、RabbitMQ、Nginx 和 OpenAPI。

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

数据库、服务端口和凭据均支持通过环境变量覆盖：`DB_URL`、`DB_USERNAME`、`DB_PASSWORD`、`SERVER_PORT`。
