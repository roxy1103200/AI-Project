# 影院售票系统后端

阶段一基础工程，基于 Spring Boot、MyBatis、MySQL、Redis、RabbitMQ 和 OpenAPI。

## 本地运行

1. 启动基础设施：`docker compose up -d`
2. 构建并启动服务：`mvn spring-boot:run`
3. 健康检查：`GET http://localhost:8080/api/health`
4. Swagger UI：`http://localhost:8080/swagger-ui.html`

数据库、服务端口和凭据均支持通过环境变量覆盖：`DB_URL`、`DB_USERNAME`、`DB_PASSWORD`、`SERVER_PORT`。
