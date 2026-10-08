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

影片状态使用 UPCOMING、ON_SHELF、OFFLINE。已确认 ON_SHELF 代表“上映中”；兼容旧 ON_SHOW，并在读写时归一化。影片售票状态另行计算。

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
- 影片评价要求登录且持有该影片的有效已出票电影票：订单 ISSUED、至少一张票项 ISSUED（兼容旧 VALID），并且所购场次已放映结束或该电影票已验票；取消的场次不提供资格。放映结束按开场加影片时长计算，不含影厅 20 分钟周转。管理员发表个人影评也适用该资格；未支付、取消、退票订单不计入。
- 每人每部影片一条影评，评分 1 至 5 星、文字必填且最多 1000 字。新建或修改后进入 PENDING，审核通过 APPROVED 后才公开；修改会使原评分暂时退出统计。作者可查看自己的审核状态和说明，自有影评始终可删除；HIDDEN 影评不能通过原地修改解除隐藏。
- 公开影评、评论数量、首页及详情页平均评分使用同一“审核通过且具备观影资格”条件。评分为五分制算术平均，保留一位小数；点赞与回复不影响评分。无资格记录保留，但不公开、不计评分；恢复资格仍须满足审核通过条件。升级前的旧影评保留正文，默认转为待审核。
- 登录账户可给他人的公开影评点赞或取消，一人一条点赞，重复 PUT 幂等，不能给自己点赞。点赞与影评记录关联，修改影评不会自动清空已有点赞。
- 登录账户可回复公开影评，无购票要求；回复需要 1～1000 字非空白正文，每人在每条影评最多保留 20 条，先审核再公开。管理员回复标记管理员身份，同样审核。作者可查看本人待审核、拒绝和隐藏回复并删除；影评隐藏或失去公开资格时，下属回复也停止公开。
- 登录账户可举报他人的公开影评或回复，原因包含辱骂、广告、剧透、违法违规、其他；其他原因必填说明。同一账户对同一版本重复举报幂等，新的版本可以再次举报。保存举报时的内容快照，不因作者修改而丢失举报依据。

对应代码：[MovieReviewService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/MovieReviewService.java)、[MovieReviewModerationService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/MovieReviewModerationService.java)、[MovieReviews.tsx](../cinema-ticketing-frontend/src/home/MovieReviews.tsx)、[TicketDialog.tsx](../cinema-ticketing-frontend/src/orders/TicketDialog.tsx)。详细入口与升级说明见 [影评与验票](movie-reviews.md)。

## 管理端流程

- 后台“影评管理”分为影评审核、回复审核、举报处理。可搜索影片/作者/正文、按审核状态筛选、通过/拒绝/隐藏/恢复/转回待审核；通过不要求说明，拒绝和隐藏须填写 1～1000 字非空白原因。管理员可以审核包括自己在内的内容。处理时检查内容版本，过期页面返回冲突；保留处理人、时间、内容快照、状态变化和说明。
- 举报可驳回、标记处理，或在同一事务内隐藏被举报内容并结案。结案说明必填，处理结果保留；举报本身不会自动隐藏内容或扣评分。
- 后台“验票入场”按订单号查询票和座位，管理员选择实际到场的票项验票。开放窗口为开场前 15 分钟至影片放映结束；仅限已出票有效票，记录首次验票时间和管理员，重复验票不覆盖记录。订单中任一票项已验票后整单不可退票，订单列表和 Agent 查询同步返回该条件。

- 注册账户默认是 USER；管理员使用 ADMIN 角色。当前是全局管理员模型，没有影院级管理员或按影院隔离的权限。
- 影片编辑包含影片资料、售票时间窗、场次和海报。影片资料与一批场次在同一数据库事务里保存；海报随后单独上传或删除，因此图片操作失败时影片资料可能已经保存。
- 新增或调整场次要求开场在未来，影院与影厅启用，结束时间等于开场时间加影片片长和 20 分钟周转时间；影厅时段不可重叠，且未来场次须完整落在影片售票时间窗内。
- 场次只要关联过订单，就不能通过影片排期编辑流程修改或删除。当前没有已售场次取消后的统一停售、退款和观众通知流程。
- 影院可新增、修改和停用；有关联影厅的影院不能删除。
- 后台管理下拉菜单提供独立“影厅管理”和“座位管理”。影厅支持按影院筛选、新增、编辑、停用与删除；新影厅自动生成座位，座位管理提供可视布局、单座位编号/位置/类型/状态编辑、创建与删除、批量启停和补齐缺失位置。
- 新管理接口统一为 /api/admin/halls；旧通用影厅/座位写接口拒绝绕过专用校验。已有排期不能改变影厅所属影院和尺寸，未结束排期不能停用影厅。有关联排期的影厅不能删除。
- 座位变更与下单共享数据库座位行锁；历史订单关联座位不能移动、重命名或删除，未结束场次的有效订单及 Redis 锁座阻止类型/状态变更。补齐空位保留现有座位 ID、编号、类型和状态。座位类型仅作标识，场次决定票价。

对应代码：[MovieScheduleEditor.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/MovieScheduleEditor.java)、[CinemaService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/CinemaService.java)、[MovieAdmin.tsx](../cinema-ticketing-frontend/src/admin/MovieAdmin.tsx)、[CinemaAdmin.tsx](../cinema-ticketing-frontend/src/admin/CinemaAdmin.tsx)。

## 已有 AI 接口：当前范围

- Java 的 /api/ai/chat 和 /api/ai/stream 要求观众登录，并从已验证的会话中取得用户 ID。
- Java 网关使用内部服务凭证调用独立 Python AI 服务；Python 服务提供影片和场次查询、本人订单查询、退票规则与知识库检索、影片推荐及退票资格查询。
- 这些工具目前只读。下单、支付和退票仍由 Java 业务接口处理。
- 前端 Dify 小悬浮球通过 `/ai-gateway/dify/` 调用 Dify 云端 Chatbot；普通问答与 SSE 不经过 Java。旁边的智能 Agent 使用独立窗口与 `/ai-gateway/agent/`，两者会话、历史、生成控制与反馈独立。
- Agent 查询时，Java 签发 10 分钟、绑定登录和 Agent 聊天会话的只读凭证。网关每轮核验凭证，调用内部 Agent `/ai/live`，业务工具仍由 Java 执行，模型回复直接由网关流回浏览器；Dify 历史不传入 Agent，Agent 查询结果不传入 Dify。
- 实时查询本人订单使用服务端身份，并返回当前退票规则计算的资格、截止时间和座位。没有通用 SQL 或自动交易工具。
- 内部 Agent 模型为 Qwen3.7 Flash（qwen3.7-flash），服务端读取 API/qwen.txt 密钥，通过百炼兼容接口调用。普通聊天与网站流式聊天共用 LangGraph ReAct 状态图：先结合最近 10 条上下文理解问题、提取并校验参数，缺少必要信息先追问；然后模型选择白名单只读工具，执行 MCP/Java/RAG 查询，将校验后的结果作为 ToolMessage 交回模型，继续查询或生成最终答复。每轮默认最多尝试 4 次工具调用，重复及不合法调用同样占用预算；身份由服务器注入，场次 ID 必须来自用户或本轮真实结果。模型不生成 SQL、不执行交易，内部规划不流向浏览器。问候走快速规则；未配置模型或工具选择失败时降级确定性查询，部分失败及预算不足明确说明。详见[Agent ReAct 流程](agent-react-flow.md)。
- 聊天回答支持点赞/点踩、可选原因与说明。网关按会话验证消息归属，仅在用户提交反馈时向 Java 保存原问题、归一化问题、意图/置信度/提取实体/查询工具、回答、异常码与评价。Dify 回答同步官方反馈接口，内部 Agent 反馈只保存在影院后台。管理员在“AI 反馈”中筛选、查看、备注和标记已处理；撤回评价保留本地记录但清空当前 rating。Dify 未通过 API 返回的意图不伪造。
- AI 网关会话、Dify 编号、最近 40 条聊天、反馈摘要、限流和生成锁存入共享 Redis。登录账户恢复最近 30 天内的当前聊天，匿名浏览器恢复最近 24 小时内的聊天；不自动合并匿名记录。用户可点击“恢复聊天”，账户切换只读取新账户的历史。内部 Agent 的上下文仅从 Agent 渠道服务器历史获取；Dify 与 Agent 的账户当前会话指针和 Redis 数据前缀分别保存，旧混合历史不自动导入。多个 worker/实例共享生成锁与额度，锁在进程异常后自动过期；普通问答不调用 Java，登录由共享 Redis 会话验证。
- 配置和已实现边界见 [dify-agent-setup.md](dify-agent-setup.md)。

对应代码：[AiGatewayController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/AiGatewayController.java)、[AiGatewayService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AiGatewayService.java)、[main.py](../cinema-ticketing-backend/cinema-ai/app/main.py)、[InternalAiController.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/controller/InternalAiController.java)。

## 当前实现边界与核对项

### 多用户鉴权核对（2026-09-27，代码审查）

- Java 登录生成独立随机 token，生产路径在 Redis 保存 userId/role，2 小时到期；多端登录各自持有 token，退出仅撤销当前 token。注册只创建 USER。登录信息保存在 sessionStorage，同一浏览器不同标签页可以分别登录；页面启动读取 token 候选并调用 /api/auth/me，服务端根据数据库确认账户状态、用户名和角色，返回剩余有效期，不延长登录寿命。核验完成前不显示管理菜单，暂时不可用可重试，401 清理当前标签身份。后台接口仍调用 requireAdmin。
- 订单查询、支付、取消、退票和座位详情都从 token 获取 userId，并在订单 SQL 检查归属；普通观众传其他 userId 查询订单列表仍只得到本人数据。管理员可以查询其他账户订单列表并验票，这是当前全局管理权限。
- 个人影评和回复的修改/删除按服务端 userId 限定；管理员审核独立检查 ADMIN 并记录操作人，审核不能代替观影资格。此次已移除未确认的“不能通过本人内容”限制，通过说明可省略，拒绝/隐藏原因必填；审核页面按 token 重新挂载，清理旧账户页面状态。
- 账号登录、退出或过期时，App 按 token 重建整个业务页面，清空订单、详情、购票/电影票弹窗、管理页面和聊天界面状态；统一请求作用域取消旧页面的请求，并在响应返回时再次检查取消状态。迟到的旧页面回调只能作用于已卸载实例。401 事件带原请求 token，只使当前匹配的标签会话失效；到期计时器也会清理身份。登录触发的 Agent 打开意图只在该标签保留到登录成功。
- AI 网关共享会话按 owner_id 隔离，使用 sessionStorage 保存的随机标签凭证，忽略原有共享 Cookie。建立会话时必须明确携带当前 token（匿名为空）；聊天、停止、重置和反馈同时携带 X-AI-Session、X-AI-Conversation 和当前 X-Auth-Token。网关逐次读取 Java 的 Redis 登录会话，检查绑定 token、账户归属、期望会话 ID 和当前账户会话；任何一项不匹配即拒绝，不自动用绑定中旧 token 代替请求 token，不自动切换到另一对话。聊天请求体 sessionId 和反馈消息归属另行校验；实时 Agent 凭证继续绑定 token、对话和只读范围，工具使用服务端身份查询个人订单。

仍需改造的实际缺口：

1. **旧权限与账户禁用的即时撤销。** /api/auth/me 会重新读取数据库角色和状态，更新当前 token 的缓存角色或撤销不可用账户的当前 token；尚未重新核验的其他 token 仍使用登录时角色。当前没有账户会话版本和按账户撤销全部会话机制。若要求数据库变更立即影响所有已登录设备，需要另行实现全账户撤销/版本校验；网关也应同步遵守。
2. **权限范围待扩展。** 当前 USER/ADMIN 是全局角色，管理员不按影院隔离，没有审核员、票务员等独立权限。若后续多个影院团队分别管理，需要在服务端增加权限点和影院范围，不能只拆分前端菜单。

本轮已采用用户确认的标签页独立方案，未迁移旧 localStorage 登录，更新后各标签需重新登录。刷新保留该标签会话，关闭标签后不保证保留；浏览器复制标签可能复制初始 sessionStorage，此后各标签独立。相同账户仍恢复服务端同一当前聊天，重置后其他设备必须重新连接；不同账户无法借共享 Cookie 操作彼此聊天。以上依据源码及编译检查，不表示已完成双账户并发或多设备运行验证。

对应代码：[AuthService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/AuthService.java)、[OrderService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/OrderService.java)、[App.tsx](../cinema-ticketing-frontend/src/App.tsx)、[store.py](../cinema-ticketing-backend/cinema-ai-gateway/app/store.py)、[main.py](../cinema-ticketing-backend/cinema-ai-gateway/app/main.py)。

以下描述现状或代码风险，不把它们扩展成用户尚未确认的业务目标：

1. **影片状态已确认**：ON_SHELF 统一代表“上映中”。兼容旧 ON_SHOW，读写接口将其归一为 ON_SHELF；售票状态仍独立计算。业务术语已记录于 CONTEXT.md。
2. **已售场次无法取消**：排期编辑器会拒绝修改或删除有关联订单的场次。当前没有管理员取消已售场次并批量退款的流程。
3. **场次校验统一**：/api/screenings 的新增、修改、删除均走影片排期编辑器，在事务中执行片长加 20 分钟、影厅营业、时间窗、重叠和关联订单检查。已有场次不能改换所属影片。
4. **退票规则可管理**：管理员通过后台“退票规则”和 /api/admin/refund-policy GET/PUT 管理全局截止分钟数及说明。保存生成新版本并保留历史版本，立即用于所有订单的后续退票资格判断；初始规则为开场前 30 分钟停止退票。
5. **评价已校验观影资格并审核**：有效购票且放映结束或已验票才可发表或修改，审核通过才公开及计分；已有后台影评/回复审核、举报处理、点赞和回复入口。
6. **真实资金链路未实现**：当前支付使用演示流水号，退票只写本地业务记录。
7. **计划文档单独看待**：根目录 [cinema-ticketing-agent-solution.md](../cinema-ticketing-agent-solution.md) 是完整方案和可选方向；其中仅有方案描述、当前代码没有对应实现的内容不计入当前业务流程。

## 仍需确认的业务规则及渠道

用户已确认上映中统一使用 ON_SHELF，影评需有效购票且放映结束或已验票，并添加后台审核与互动。管理员取消已售场次的退款范围，以及真实支付渠道和环境仍待确认。方案文档中的可选内容不计入当前实现。
