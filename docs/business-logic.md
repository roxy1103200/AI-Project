# 影院售票系统：当前业务流程梳理

## 梳理口径

- 本文以当前工作树中的前后端代码、API 和数据库结构为已实现行为依据。
- 项目 README 和方案文档中的内容只有在代码中找到对应实现后，才记作已实现；其余内容列为规划或当前缺口。
- 已确认：记录现有 AI 接口和能力；新增 AI 功能留待后续梳理。
- 本文是当前实现地图。尚未由代码或用户确认的业务意图会标为待确认，不作为既定规则。

## 核心数据关系

- 影院包含影厅，影厅配置座位。
- 影片关联多个放映场次；每个场次属于一个影厅，并带有开场时间、结束时间、票价和状态。
- 观众创建订单；订单包含场次及所选座位项目。订单、支付记录、退款记录和电影票项目由数据库分别保存。

主要结构定义见 [schema.sql](../cinema-ticketing-backend/src/main/resources/schema.sql)。

## 观众购票流程

### 1. 浏览影片与场次

- 访客可以浏览影片、影院和场次；用户列表需要管理员身份。
- 影片列表根据影片状态、售票时间窗和是否存在有效未来场次，返回计算出的售票状态和评分汇总。
- 立即可订的场次要求：场次为已排定且开场时间在未来；影片状态允许销售；场次落在影片售票时间窗内；影院和影厅启用。
- 两周日程展示未来已排定的场次，即使售票尚未开放也会显示；接口返回是否可订，前端据此禁用未开放场次。
- 普通场次列表只返回当前可订的场次。影片详情中的选场入口从这个列表筛选。

当前代码接受影片状态 UPCOMING、ON_SHELF、ON_SHOW、OFFLINE；影片售票状态另行计算。ON_SHELF 和 ON_SHOW 在服务端可售判断中没有行为差异，后台编辑界面仅提供 UPCOMING、ON_SHELF、OFFLINE。两者的业务语义待确认，本文不把它们解释成不同业务阶段。

相关代码：[SellableScreenings.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/common/SellableScreenings.java)、[CatalogService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/CatalogService.java)、[TwoWeekSchedule.tsx](../cinema-ticketing-frontend/src/home/TwoWeekSchedule.tsx)。

### 2. 选座和锁座

1. 观众选择场次，读取该场次所属影厅的座位布局。
2. 座位显示状态分为可选、短期锁定和已有有效订单占用。
3. 登录后可一次选择最多 6 个座位。服务端使用 Redis 原子操作锁定所选座位，锁定时间为 5 分钟。
4. 锁座失败时，服务端拒绝继续下单；数据库订单状态仍会参与最终占座判断。

对应入口和规则见 [OrderController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/OrderController.java) 和 [OrderService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/OrderService.java)。

### 3. 创建、支付和出票

1. 锁座后，观众提交场次、座位和 requestId 创建订单。
2. 同一观众重试同一 requestId 时，服务端返回已创建的订单；金额由场次票价乘以座位数计算。
3. 新订单进入 UNPAID，有效期为 5 分钟。订单创建后会安排延迟取消消息。
4. 当前前端使用 DEMO-{orderNo} 作为支付流水号。后端记录模拟成功的支付，再把订单明细标记为已出票；没有调用真实支付渠道。
5. 同一订单以相同支付流水号重试可返回已有成功结果；冲突流水号会被拒绝。

在一次成功支付事务中，后端写入 PAID 后紧接着写入 ISSUED。因此用户成功收到响应时通常看到已出票状态，而不是一个长期停留的支付处理中状态。

### 4. 取消、超时和退票

- 观众只能主动取消未支付订单；取消后订单和座位项目标记为 CANCELLED，并按锁持有人释放 Redis 座位锁。
- 未支付订单到期时优先由 RabbitMQ 延迟消息取消；消费者对消息去重并有限重试。定时对账任务每分钟扫描过期未支付订单作为补偿。
- 只有 ISSUED 订单可以退票。当前退票按整笔订单处理：订单及所有座位项目转为 REFUNDED，并记录整单金额。
- 后端读取最新启用的退票规则，只有场次开场时间晚于“当前时间 + 截止分钟数”才接受退票。新库默认规则为开场前 30 分钟截止。
- 当前实现没有调用支付渠道执行实际资金退款；退款记录只表示本系统内的退款业务状态。
- 订单列表为用户本人提供退票截止时间、是否可退、原因和服务端时间，前端据此显示按钮状态；后端仍负责最终校验。

对应代码：[OrderService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/OrderService.java)、[OrderCancelConsumer.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/mq/OrderCancelConsumer.java)、[OrderReconciliationJob.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/OrderReconciliationJob.java)、[OrderQueryController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/OrderQueryController.java)。

### 5. 查看影票与评价影片

- 登录观众只能查看自己的订单、订单座位图和影票详情；管理员可按用户查询订单列表。
- 历史订单即使场次已开始或停售，仍可查看影厅座位图和本订单座位标记。
- 影片评价允许登录用户按影片提交 1 至 5 星和文字内容；每位用户每部影片一条，可修改或删除。
- 当前代码不检查评价者是否买过该影片的票。因此“仅购票观众可评价”不是已实现规则。

对应代码：[MovieReviewController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/MovieReviewController.java)、[TicketDialog.tsx](../cinema-ticketing-frontend/src/orders/TicketDialog.tsx)。

## 管理端流程

- 注册账户默认是 USER；管理员使用 ADMIN 角色。当前是全局管理员模型，没有影院级管理员或按影院隔离的权限。
- 影片编辑包含影片资料、售票时间窗、场次和海报。影片资料与一批场次在同一数据库事务里保存；海报随后单独上传或删除，因此图片操作失败时影片资料可能已经保存。
- 新增或调整场次要求开场在未来，影院与影厅启用，结束时间等于开场时间加影片片长和 20 分钟周转时间；影厅时段不可重叠，且未来场次须完整落在影片售票时间窗内。
- 场次只要关联过订单，就不能通过影片排期编辑流程修改或删除。当前没有已售场次取消后的统一停售、退款和观众通知流程。
- 影院可新增、修改和停用；有关联影厅的影院不能删除。
- 后端通用 API 支持影厅、座位等资源，但前端管理界面目前提供影片和影院管理，没有独立的影厅/座位管理页面。

对应代码：[MovieScheduleEditor.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/MovieScheduleEditor.java)、[CinemaService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/CinemaService.java)、[MovieAdmin.tsx](../cinema-ticketing-frontend/src/admin/MovieAdmin.tsx)、[CinemaAdmin.tsx](../cinema-ticketing-frontend/src/admin/CinemaAdmin.tsx)。

## 已有 AI 接口：当前范围

- Java 的 /api/ai/chat 和 /api/ai/stream 要求观众登录，并从已验证的会话中取得用户 ID。
- Java 网关使用内部服务凭证调用独立 Python AI 服务；Python 服务提供影片和场次查询、本人订单查询、退票规则与知识库检索、影片推荐及退票资格查询。
- 这些工具目前只读。下单、支付和退票仍由 Java 业务接口处理。
- 当前前端源码中没有 AI 对话入口；AI 服务能力存在于后端 API。
- 用户已确认新增 AI 功能留待后续。本节只记录当前已存在的后端能力。

对应代码：[AiGatewayController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiGatewayController.java)、[AiGatewayService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiGatewayService.java)、[main.py](../cinema-ticketing-backend/cinema-ai/app/main.py)、[InternalAiController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/InternalAiController.java)。

## 当前实现边界与核对项

以下描述现状或代码风险，不把它们扩展成用户尚未确认的业务目标：

1. **影片状态术语待确认**：服务端接受 ON_SHELF 和 ON_SHOW，但后台只允许设置 ON_SHELF，服务端售票判断将二者等同；售票状态另行计算。
2. **已售场次无法取消**：排期编辑器会拒绝修改或删除有关联订单的场次。当前没有管理员取消已售场次并批量退款的流程。
3. **通用场次 CRUD 校验差异**：管理员也可通过 /api/screenings 的通用新增、修改、删除接口操作场次；这些调用没有走影片编辑器里的场次重叠、售票时间窗和已有订单检查。后台界面使用的是影片编辑流程。
4. **退票规则缺少管理界面**：数据库有全局启用的退票规则，默认截止时间为 30 分钟；当前 API/后台界面没有修改该规则的入口。
5. **评价没有购票资格校验**：目前任何登录观众都能评价，不要求关联已出票订单。
6. **真实资金链路未实现**：当前支付使用演示流水号，退票只写本地业务记录。
7. **计划文档单独看待**：根目录 [cinema-ticketing-agent-solution.md](../cinema-ticketing-agent-solution.md) 是完整方案和可选方向；其中仅有方案描述、当前代码没有对应实现的内容不计入当前业务流程。

## 下一步待确认的业务术语

首先确认影片的 ON_SHELF 与 ON_SHOW 是否代表同一个“上映中”状态。确认后再将该术语写入根目录的 CONTEXT.md；其他实际规则若从代码已可直接核实，会作为现状记录，不要求用户重复提供代码事实。
