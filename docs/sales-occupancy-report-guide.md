# 票务经营报表开发指南

本文是管理员销售与上座率报表的开发方案。2026-10-10 已完成三个阶段的本地源码实现，包括管理页面、销售/场次接口、容量快照和 CSV 导出；部署和使用步骤见 [经营报表：使用与升级](sales-reports.md)。以下保留设计依据，并同步最终采用的口径。

## 当前数据基础

核心事实分别保存在 `payment_transaction`、`refund_record`、`ticket_order`、`order_item` 和 `screening`：

- 支付金额和支付时间来自支付流水；每笔订单目前最多一条支付记录，支付流水状态为 `SUCCESS`。
- 退款金额和退款时间来自退款记录；当前退票是整单退款，一单写一条 `REFUNDED` 记录。当前记录是本系统内的业务退款，不代表真实支付渠道已经退回资金。
- 票数来自订单票项；下单时暂存为 `VALID`，支付出票后转为 `ISSUED`，退票后转为 `REFUNDED`。有效票统计还必须检查父订单状态为 `ISSUED`。
- 场次关联影片、影厅和影院；座位静态配置在 `seat` 表，`AVAILABLE` 表示当前可售，`DISABLED` 不可售。
- 已新增独立报表接口、管理页面、明细导出及 `screening_capacity_snapshot`。退款新增北京时间 `refunded_at` 字段，旧时间在升级时转换。

相关实现：[schema.sql](../cinema-ticketing-backend/src/main/resources/schema.sql)、[OrderService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/OrderService.java)、[TicketCheckInService.java](../cinema-ticketing-backend/src/main/java/com/cinema/ticketing/service/TicketCheckInService.java)。

## 先统一统计口径

建议将收入报表和场次运营报表分成两种日期口径，并在接口响应和页面上明确显示：

| 指标 | 日期口径 | 数据来源和建议定义 |
| --- | --- | --- |
| 已支付金额 | 支付日 | 汇总所选日期内 `payment_transaction.status='SUCCESS'` 的 `amount`，按 `paid_at` 归日。 |
| 退款金额 | 退款处理日 | 汇总所选日期内 `refund_record.status='REFUNDED'` 的 `amount`，按退款记录时间归日。它与支付金额是两个资金事件，因此窗口净额是“窗口内支付额 − 窗口内退款额”。 |
| 售出票数 | 支付日 | 统计支付时间落在窗口内的成功支付订单票项数，作为累计售出票数；即使之后退票，仍计入历史毛售出票数，退款票另由有效票数和退款金额反映。 |
| 有效票数 | 放映日 | 统计所选日期内场次、父订单为 `ISSUED` 且票项状态为 `ISSUED` 或兼容旧值 `VALID` 的票数。验票后仍属于有效票。 |
| 上座率 | 放映日 | `有效票数 / 该场次可售座位数`。座位数为 0 或容量未知时返回空值并标注原因，不能用 0% 混淆。 |
| 热门场次 | 放映日 | 逐场次展示有效票数和上座率；建议默认按有效票数降序、上座率降序排序，并提供排序依据。 |

收入指标中的支付日和退款处理日可能不同，这是对支付、退款流水按发生日核账的口径。页面不应把它误标为“按放映日期计算收入”。如果后续需要回答“某批支付订单最终退了多少钱”，那是按原支付订单归属的销售批次口径，应另加指标定义，不能与退款处理日金额混用。

所有日期参数和归日统一按**北京时间 `Asia/Shanghai`**。日期范围使用包含首尾日的用户语义，SQL 转为左闭右开区间 `[from 当日 00:00, to 次日 00:00)`，不要对索引时间列套 `DATE()`。当前 `payment_transaction.paid_at` 是应用写入的 `DATETIME`，退款 `created_at` 是数据库生成的 `TIMESTAMP`；聚合前必须按各自的存储时区规则转换到北京时间。先在本地和部署环境核对数据库时区与 JDBC 会话时区，避免退款日偏移一天。

当前前端以 `DEMO-{orderNo}` 作为支付流水号，尚无真实支付渠道。报表响应和页面应明确返回/显示 `dataMode: "SIMULATED"` 或等效“模拟支付数据”标识。不能仅靠前端隐藏标识；当前可以由后端统一标注。以后接入真实支付且数据混合时，应给支付记录增加持久化的支付模式/渠道字段。

## 上座率分母必须固定

直接用当前 `seat.status='AVAILABLE'` 的座位数作为历史分母会造成报表随影厅配置变化而变化。实现采用独立的 `screening_capacity_snapshot` 表，在首次成功锁座事务中、尚无订单时捕获容量，并通过影厅行锁与座位编辑串行化；锁座失败随事务回滚，成功后快照固定。直接创建订单路径也提供捕获兜底。

当前实现分母为捕获时状态为 `AVAILABLE` 的座位记录数；`DISABLED` 不计入。沿用当前订单规则，一个座位记录对应一张票，情侣座类型没有额外乘二规则。有未结束且已捕获容量的场次时禁止影厅座位布局/状态变化，已有快照的场次禁止修改或删除排期。未来若引入每场独立开放座位或一座多票规则，需升级为逐座位快照及新的计票规则。

已有订单且没有快照的历史场次保持“容量未知”，上座率返回 `null`，不使用当前影厅布局估算。范围内含未知容量时，整体上座率也返回 `null`；有快照的逐场比例仍展示。

## 建议接口

两个接口均要求管理员身份，在 Controller 中按项目现有模式调用 `AuthService.requireAdmin(token)`，使用 `X-Auth-Token`，返回 `ApiResponse`。请求参数校验和数据库查询放在独立 Service，不要只靠前端隐藏导航项。

### `GET /api/admin/reports/sales`

建议参数：

```text
from=2026-10-01&to=2026-10-07&cinemaId=1&movieId=12
```

已支持必填日期范围和可选影院、影片筛选，按日、影院、影片形成结果行。以下为 `ApiResponse.data` 的响应示例：

```json
{
  "metadata": {
    "from": "2026-10-01", "to": "2026-10-07",
    "dateBasis": { "paidAmount": "PAYMENT_DATE", "refundAmount": "REFUND_DATE", "grossTicketCount": "PAYMENT_DATE" },
    "timeZone": "Asia/Shanghai", "dataMode": "SIMULATED", "currency": "CNY",
    "generatedAt": "2026-10-10T12:00:00"
  },
  "summary": { "paidAmount": "120.00", "refundAmount": "20.00", "netAmount": "100.00", "grossTicketCount": 4 },
  "items": [
    { "date": "2026-10-01", "cinemaId": 1, "cinemaName": "示例影院", "movieId": 12,
      "movieTitle": "示例影片", "paidAmount": "120.00", "refundAmount": "20.00",
      "grossTicketCount": 4 }
  ]
}
```

金额使用 Java `BigDecimal` 和 MySQL `DECIMAL`，不要先转 `double`。金额按来源流水分别汇总：支付金额从支付表聚合，退款金额从退款表聚合，票数从支付订单与票项聚合。再按日期、影院和影片键合并结果。**不要把支付、退款、票项三张明细表直接一起联表后求和**：一笔支付连接多张票，再连接退款会重复放大金额。

### `GET /api/admin/reports/occupancy`

日期按场次开场日解释；结果以场次为行，并可提供按日期、影院、影片汇总。建议每场返回场次 ID、开场时间、影院/影片/影厅、有效票数、容量快照、上座率及容量来源。取消场次不纳入已排场次上座率；已过期但未取消的场次仍按历史场次计算。热门场次从这组逐场数据中排序生成。

两接口的可选筛选建议统一为 `cinemaId`、`movieId`。日期校验 `from <= to`，限制最大查询跨度（例如 31 天，具体由运营需求确认），并设置合理的默认范围和空结果结构。

## 前后端实现顺序

### 第一阶段：经营金额和售票数

1. 新建报告 Controller/Service 与 DTO；完成管理员校验和日期参数校验。
2. 新建 `/api/admin/reports/sales`，先按支付日、退款日分别查询已支付金额、退款金额、毛售出票数。
3. 建立管理员报表页面，在现有管理端导航增加“经营报表”；先提供一个日期范围控件、三项汇总卡片和按日/影院/影片分组的汇总表。
4. 页眉持续显示北京时间、各指标日期口径和“模拟支付数据”。无数据也显示明确的 0 与空状态。

### 第二阶段：场次运营指标

1. 定稿可售座位业务口径，增加容量快照字段/表及场次创建或开放销售时的快照流程。
2. 为旧场次确定估算/不展示策略，不把当前座位数静默用于精确历史报表。
3. 实现 `/api/admin/reports/occupancy`：逐场次返回有效票数、分母和上座率，再补影片/影院筛选及热门场次列表。
4. 锁定后台座位布局变更与场次容量快照的一致性，避免已售场次修改分母。

### 第三阶段：明细导出

增加按当前筛选导出明细的接口（例如 `/api/admin/reports/sales/export`），导出列至少包含统计口径日期、影院、影片、场次/订单号、支付流水金额与时间、退款金额与时间、票数和状态。只导出核账所需字段，不导出用户密码、电话等非必要个人信息。结果应限制时间范围、支持流式或分页生成；CSV 需 UTF-8（可加 BOM 适配 Excel），并处理以 `= + - @` 开头的文本，避免表格软件将其解释为公式。

建议实现位置：后端新增 `SalesReportController`、`SalesReportService`（金额/售票）、`OccupancyReportService`（场次/容量）；前端新增 `admin/SalesReportAdmin.tsx`；在 `App.tsx` 管理员快捷菜单中注册入口。查询继续使用参数化 SQL 与 `JdbcTemplate`，避免拼接用户输入。

## 对账与验收清单

- [ ] 指定范围内支付金额等于同一范围 `SUCCESS payment_transaction.amount` 之和；退款金额等于同一范围 `REFUNDED refund_record.amount` 之和。
- [ ] 窗口净额定义为窗口支付流水减窗口退款流水；测试跨日支付、次日退款，分别核对两日数据。
- [ ] 售出票数按成功支付订单统计，退款不从毛售出票数中倒扣；有效票数排除已退款、取消及未支付票项。
- [ ] 上座率分子为有效票数，分母为确认过口径的该场次容量快照；除法使用足够精度，页面格式化百分比。
- [ ] 取消场次、停用影院/影厅、停售影片的历史记录有确定处理规则，不能因当前状态而误删历史交易。
- [ ] 用一笔多座位订单验证金额只计一次、票数按票项计数；用退款订单验证退款只计一次、有效票正确减少。
- [ ] 用午夜前后、北京时间日期边界和数据库 `TIMESTAMP` 验证归日一致；校验起止日期均包含。
- [ ] 页面和导出标记模拟支付数据；普通用户访问两个接口均被拒绝；导出文件不含无关个人信息且不能触发表格公式。
- [ ] 大日期范围执行 `EXPLAIN`；必要时为 `payment_transaction(status, paid_at, order_id)`、`refund_record(status, created_at, order_id)` 补索引，并根据实际查询与数据量调整。

第一阶段范围建议严格保持为：一个日期范围、已支付金额、退款金额、毛售出票数。有效票、上座率、热门场次依赖容量口径和快照方案，放到第二阶段；导出按第三阶段实施。这样每一步都能先与原始支付/退款流水对账，再扩展到依赖运营定义的指标。
