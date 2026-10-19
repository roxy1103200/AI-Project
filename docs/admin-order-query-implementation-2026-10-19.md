# 管理端按订单号查询：实现与验证

## 交付内容

沿用已创建的 `AdminOrderQueryController`，补齐 `AdminOrderQueryService` 与显式 `AdminOrderDetail` DTO。管理端「票务服务 → 订单查询」入口为 `/admin/orders`，可直接使用 `/admin/orders?orderNo=完整订单号`，从详情跳转验票会携带订单号并自动读取原验票接口。

详情包含购票账号、影片场次、逐票成交价与验票记录、本地支付单、收款流水、全部退款记录、当前验票/退票资格、配置与核对异常、已有时间证据组成的事件列表。金额使用两位小数字符串；时间包含时区，页面统一显示北京时间。影片、影院和影厅信息来自当前关联资料，不代表购票时的历史快照。

不会因查询、刷新或深链接进入而取消订单、退款、发起支付宝查单、清除 Redis 锁或领取任务租约。页面保留前往原验票/支付核对模块的入口，实际交易操作仍由原业务接口重新校验。

## 接口

`GET /api/admin/orders/{orderNo}`，请求头 `X-Auth-Token`。复用 `AuthService.requireAdmin` 检查持久化账号角色与会话版本，不接受客户端提供的用户编号作为授权依据。

- 200：`ApiResponse<AdminOrderDetail>`，包含 `order/customer/screening/tickets/payment/receipts/refunds/eligibility/diagnostics/events/dataWarnings/serverTime/timeZone`。
- 400：空白、超过 64 字符或包含控制字符。合法首尾空格被去除，SQL 使用绑定参数精确匹配。
- 401：缺失、失效或已撤销的登录；403：无管理员权限。
- 404：主订单不存在；关联历史资料缺失保留主订单和资料提示。
- 500：数据库等服务故障，不能伪装成订单不存在。

响应设置 `Cache-Control: no-store`。不返回手机号、密码、收银台凭证、租约标识、密钥或完整支付身份。APPID 和商户编号仅显示末四位。配置比对只针对配置可用时的在途支付宝支付单；不适用或配置不足返回 `UNKNOWN`。

聚合读取使用 `REPEATABLE_READ` 只读事务。主订单精确匹配现有 `order_no` 唯一索引，明细、流水、退款分开读取以避免一对多 JOIN 放大金额。没有数据库迁移。

## 状态口径

- `UNPAID + CLOSING`：尚未确认取消，不能推断座位已释放或渠道未扣款。
- `REFUNDING + PENDING/UNKNOWN`：影票暂不可用，不能宣称退款失败或已经到账。
- `CANCELLED + SUCCESS + LATE_PAYMENT`：保留取消、实际收款和补偿退款三类事实；补偿确认后显示退款已确认。
- 无独立渠道支付单的历史 MOCK 收款：读取原收款流水，不能伪装成真实支付宝交易。
- `UNKNOWN` 退款达到 8 次且没有后续计划：提示前往原核对模块；支付关单不套用退款重试上限。
- 未知订单状态、收款证据与订单状态矛盾：展示原始值及核对提示，不自动修正。
- 事件仅使用已有时间；到期时间不是取消时间，收银台发放不是付款成功。

验票资格复用抽出的 `TicketCheckInPolicy`，保留开场前 15 分钟至放映结束前的窗口。退票口径复用 `OrderStatusSummary`，修正缺失场次时间时误报超过截止时间的问题。实际验票写入和退款流程保持原有校验。

## 自动验证

2026-10-19：后端选定的 10 个测试类共 **56 项通过**，前端完整现有测试集 **28 项通过**；前端 TypeScript/Vite 构建与后端 Maven 打包通过。

后端测试包括本次新增的 `AdminOrderQueryServiceTest`（H2 隔离库，19 项）、`AdminOrderQueryControllerTest`（6 项）、`TicketCheckInPolicyTest`（2 项），以及原有订单状态、登录权限、下单核心流程、参数校验、订单对账、退票规则、管理接口契约回归。前端新增请求竞态、时间格式、查询参数和真实组件服务端渲染测试；组件加载器与原助手渲染测试共用。

执行命令：

```powershell
# cinema-ticketing-backend
mvn.cmd -q "-Dtest=AdminOrderQueryServiceTest,AdminOrderQueryControllerTest,TicketCheckInPolicyTest,OrderStatusSummaryTest,AuthServiceTest,OrderServiceCoreFlowTest,OrderServiceValidationTest,OrderReconciliationJobTest,RefundPolicyConsistencyTest,ManagementApiContractTest" test
mvn.cmd -q -DskipTests package
# cinema-ticketing-frontend
npm.cmd test
npm.cmd run build
```

## 原方案 36 点验收记录

「通过」指对应隔离自动测试及代码核对通过，不代表已部署线上验收；「部分」和「未执行」不能视为通过。

- A01 部分：接口缺失登录 401/no-store 通过；旧账号详情清理由 workspace key 与中止请求实现，未做浏览器登录切换验收。
- A02 通过：普通用户正确订单号仍 403，查询服务不被调用。
- A03 部分：管理员鉴权先于专用查询，聚合不按登录用户过滤；真实管理员跨账号端到端未执行。
- A04 部分：控制器拒绝撤销/降权的鉴权结果，复用已有会话校验；真实账号降权端到端未执行。
- A05 通过：空白、超长、控制字符、去空格和 SQL 注入样式输入。
- A06 通过：404 与数据库故障 500 分开。
- B01 通过：未发起支付订单，无支付和退款记录。
- B02 通过：多座成交价和总额精确，多个退款不放大票项。
- B03 通过：部分验票、验票人/首次时间及剩余票资格。
- B04 通过：未收款取消与不可验票。
- B05 通过：普通退款确认、失效票项、不可验票。
- B06 部分：归档影片仍可查询；过期历史场次的浏览器展示未单独执行。
- C01 通过：关单待确认，不虚构取消事件。
- C02 通过：退款处理中不可用。
- C03 通过：UNKNOWN 保持结果待核对。
- C04 通过：取消、成功收款、迟到付款补偿同时展示。
- C05 通过：补偿退款已确认，不允许重复申请。
- C06 通过：未知订单状态和未支付却已有成功收款均提示核对，不修改状态。
- D01 通过：配置不一致、完整身份与敏感字段不出现在 JSON、查询不修改 APPID。
- D02 通过：无渠道支付单的 MOCK 历史流水。
- D03 通过：渠道错误从本地读取，服务没有渠道客户端依赖。
- D04 通过：空退款列表、多条历史退款独立展示。
- D05 通过：退款耗尽提示；支付单无 8 次耗尽判断。
- D06 通过：匹配、不匹配、配置不完整、已结束支付不参与配置比对。
- E01 部分：表单提交、当前订单刷新、输入变化清空旧结果均实现；按钮和回车实际浏览器交互未执行。
- E02 通过：请求生命周期测试覆盖 A 晚于 B 返回，旧成功与错误被忽略。
- E03 部分：中止/换号逻辑和原会话隔离测试通过；浏览器切模块、登出验收未执行。
- E04 部分：复制只绑定点击，失败提示手动选中订单号；实际剪贴板权限环境未执行。
- E05 部分：查询参数编解码、路径解析、验票预填渲染通过；浏览器前进后退和 effect 自动读取未端到端执行。
- E06 未执行：已实现响应式、长编号换行与语义表单，尚未进行 320px/桌面截图和键盘实测。
- F01 部分：真实事务代理的只读标志、REPEATABLE_READ 及同一记录重复读通过；H2 与 MySQL 跨表快照行为不同，未将 H2 测试当作 MySQL 并发状态切换验收。
- F02 通过：查询调用均为显式 SELECT，无 FOR UPDATE，无渠道/Redis/消息依赖，状态与配置不被修改。
- F03 部分：两位金额精度、TIMESTAMP 瞬时值转换、DATETIME 本地时区与前端北京时间通过；MySQL 实际连接时区组合未新增集成实测。
- F04 通过：主订单存在但账号、场次、座位关联缺失时保留详情和提示。
- F05 部分：SQL 精确匹配，schema 存在唯一索引，订单页面不加载全量运营数据；未执行生产 MySQL EXPLAIN。
- F06 通过：事件只使用真实时间字段，未虚构取消、付款、退款事件。

浏览器验收此前被自动审批拒绝，返回原因是所选模型容量已满；没有绕过该限制。因此此交付不宣称浏览器视觉与端到端验收完成。

## 发布状态

已生成前端 `dist` 与后端 `target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar`。没有重启原服务、部署、改动真实客户订单或触发支付退款。部署时需先更新后端再更新前端，之后进行上述浏览器及 MySQL 验收；运行中的旧后端不会仅因源代码修改就出现新接口。
