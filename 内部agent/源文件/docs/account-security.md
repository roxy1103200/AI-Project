# T01：账户权限即时撤销与个人安全设置

实现日期：2026-10-07。

## 使用入口

- 登录后，右上角 **账户安全**：修改密码、退出全部设备（包括当前设备）。成功后清除当前标签页的身份、聊天绑定和 Agent 转接状态，重新登录。
- 管理员在管理菜单选择 **账户安全**：更改 USER/ADMIN 角色、启用/禁用账户、退出指定账户的全部设备。列表最多显示 500 个账户。
- 保存角色或状态变更自动撤销全部旧登录；不改变角色或状态的保存不会撤销。系统禁止移除最后一个可用管理员。
- 其他设备无需主动退出：旧登录在下一次受保护请求返回 401，页面随即清除该登录。正在生成的 AI 回答每两秒核验一次身份，发现失效后停止。

## 校验与存储规则

MySQL `users.session_version` 是持久化的账户会话版本。登录时 Redis `auth:session:{token}` 保存 `userId`、`role`、`sessionVersion`，登录寿命仍为两小时，身份核验不续期。

`AuthService.requireUserId`、`requireAdmin`、`isAdmin`、`current` 都检查真实账户是否存在、是否 ACTIVE、角色是否合法、角色是否仍与登录时一致，以及持久化会话版本是否匹配。MyBatis 身份读取禁止使用事务内查询缓存或二级缓存，避免同一事务中的再次校验读到旧身份。

修改密码在一个 SQL 更新中写入 BCrypt 密码摘要并递增会话版本；全部设备退出和管理员变更同样递增版本。旧 Redis 登录即使还在，也不能授权。数据库版本不会因 Redis 重启而丢失；过期登录由原有 TTL 自然清理。

密码修改要求验证当前密码，新密码至少 8 位且 UTF-8 编码不超过 72 字节，不能与原密码相同。版本条件阻止并发改密、撤销操作覆盖别人的更新。管理员变更使用账户版本冲突校验及管理员行锁，保留最后一个可用管理员。

AI 网关两个渠道的每次登录请求都调用 Java 内部身份接口，禁止仅凭 Redis 中的登录残留授权；Java 不可用或内部认证配置错误时返回 503，不回退到旧身份，也不会把暂时故障当作用户密码失效。匿名 Dify 请求继续按匿名会话规则处理。

Agent 转接凭证继续绑定原始登录 token，解析转接时由同一 `AuthService` 验证；版本失配后旧凭证返回 401，即使凭证自己的十分钟 TTL 尚未到期也不能继续查询。

撤销约束是下一次授权校验失效。已经通过授权并进入事务的业务操作不做强制回滚。正在生成的 AI 回答由网关定期中止，但不会撤回撤销前已传输的内容。

## 新增接口

所有公开接口使用当前标签页的 `X-Auth-Token`，不接受客户端指定个人操作的 userId。

- `POST /api/auth/logout-all`：本人全部设备退出，无请求体。
- `POST /api/auth/password`：请求体 `{"currentPassword":"…","newPassword":"…"}`，成功后包含当前登录的全部旧会话失效。
- `GET /api/admin/accounts`：管理员读取账户列表，不包含密码摘要。
- `PATCH /api/admin/accounts/{id}/access`：请求体 `{"role":"USER","status":"ACTIVE","sessionVersion":0}`，状态只接受 ACTIVE/DISABLED。
- `POST /api/admin/accounts/{id}/revoke-sessions`：请求体 `{"sessionVersion":0}`。
- `POST /internal/ai/auth/resolve`：网关携带 `X-Internal-Token`，请求体 `{"token":"…"}`；返回 `userId`、`username`、`role`、`expiresInSeconds`。用户 token 不放在 URL 中。

账户版本已被其他操作修改返回 409，刷新列表后再操作；撤销或失效的登录返回 401；有效普通用户访问管理接口返回 403。

## 数据库升级和发布顺序

1. 新库的 `schema.sql` 已包含 `session_version BIGINT NOT NULL DEFAULT 0`。
2. 旧库启动时通过 `AccountSecuritySchemaInitializer` 检查字段并补齐，只增添该字段，不重置已有账户。也可先手动执行 `cinema-ticketing-backend/migrations/20261007-account-session-version.sql`；该 SQL 用于尚未添加字段的库。
3. 手动完成升级且运行账户没有 ALTER 权限时，设置 `AUTH_INITIALIZE_SCHEMA=false`。默认 true。
4. **先升级全部 Java 后端实例，再升级网关并发布前端。** Java 与网关的 `AI_INTERNAL_TOKEN` 必须一致，网关的 `JAVA_API_URL` 必须指向升级后的 Java。
5. **第一次升级后，不包含 sessionVersion 的历史登录全部失效，需要重新登录。** 不把历史会话默认为版本 0，避免旧权限继续生效。

SQL 脚本或其他管理工具直接改角色、状态、密码时，也必须在同一个 UPDATE 中递增 `session_version`，以保证停用后再启用或改回旧角色不会恢复旧登录。业务内更改通过新接口自动实现该规则。

应用回退到旧身份逻辑会失去版本校验。回退前应停掉业务流量并撤销 Redis 中全部登录与转接凭证；保留新增字段不会破坏旧表结构，但旧代码不具备本功能。不要混用新旧 Java 实例提供身份校验。

## 验证结果

- Java：12 项账户安全集成测试、2 项原有 AuthService 测试通过。集成测试使用独立 H2（MySQL 模式）、真实 MyBatis mapper、Spring 事务和独立 Redis，无真实账户变更。
- 网关：12 项测试通过，包括两个渠道撤销后的读取、重置、聊天、反馈拒绝授权，禁用账户、Java 不可用时拒绝授权、生成过程中撤销及原有渠道隔离。
- 前端：10 项测试通过，验证 HTTP 和流式身份失效通知；TypeScript 检查与生产构建通过。后端 JAR 打包通过。
- 数据库升级：旧表增加版本、重复启动不重复添加字段、保留已有用户均通过隔离测试。

Java 选择性测试：`mvn -Dtest=AuthServiceTest,AccountSecurityIntegrationTest test`。本机 Windows JDK 21 的本地套接字目录过长时，额外指定 `-DargLine=-Djdk.net.unixdomain.tmpdir=<项目 target/sockets 的绝对路径>` 并先创建该目录；环境缺少 PROCESSOR_ARCHITECTURE 时补充 `AMD64`，供嵌入式 Redis 测试依赖识别系统。

网关测试：在 `cinema-ticketing-backend/cinema-ai-gateway` 使用项目 Python 执行 `-m unittest discover -s tests -v`。前端测试：在 `cinema-ticketing-frontend` 执行 `node --test tests/*.test.mjs`。

这些测试验证本地源码及隔离环境，不等于已部署或已验证远程服务器。
