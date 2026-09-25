import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';

const baseDir = 'E:/development/AI-Project/outputs/cinema-rag-values-2026-09-24';
const sourcePath = 'E:/development/AI-Project/deliverables/影院购退票与营业服务_RAG问答知识库.xlsx';
const outputPath = `${baseDir}/影院购退票与营业服务_RAG问答知识库_业务测试版.xlsx`;
const testConfig = '本问答表新增的本地业务测试配置，不来自真实影院或生产环境；仅用于 Dify/RAG 联调，正式对客前须由影院运营替换或确认。';
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const sheet = wb.worksheets.getItem('RAG问答库');
const rows = sheet.getRange('A1:F57').values;
const rowById = new Map(rows.slice(1).map((row, offset) => [row[0], offset + 1]));

const updates = {
  'PUR-009': [
    '本地演示环境使用模拟支付，不会实际扣款。如果测试支付后订单仍显示待支付，请先刷新订单，再用订单号和 paymentNo 核对；不要重复提交支付。当前演示客服号码为 010-00000001。',
    '项目实现值（联调可用）',
    '依据：README.md 的模拟支付说明；OrderService.pay；演示客服号码来自 seed-local-data.sql。号码仅为本地演示数据。',
  ],
  'PUR-012': [
    '当前售票项目只接入模拟支付流程，没有配置微信、支付宝、银行卡等真实支付渠道。测试时按页面提交 paymentNo；该操作用于推进订单状态，不会向真实支付机构扣款。',
    '项目实现值（联调可用）',
    '依据：README.md 的模拟支付说明；OrderController.pay、OrderService.pay。',
  ],
  'PUR-013': [
    '这是本地模拟支付流程，不会发生真实扣款。遇到失败或超时，先查询订单状态；如果订单仍为待支付，可按接口/页面提示重试一次。若订单已支付或已出票，不要重复支付；记录订单号和 paymentNo 交由测试人员核对。',
    '项目实现值（联调可用）',
    '依据：README.md 模拟支付流程；OrderService.pay 的订单状态与 paymentNo 幂等校验。',
  ],
  'REF-008': [
    'Dify 业务问答测试配置的到账口径为原支付路径 1–3 个工作日。注意：当前项目是模拟支付，退票接口成功后会立即把订单和票券状态记为 REFUNDED，但不会向银行或支付平台真实打款；1–3 个工作日仅是测试话术参数，不是已验证的线上到账承诺。',
    '测试业务值（非正式承诺）',
    testConfig + ' 项目当前仅同步更新模拟订单状态，未接入支付渠道退款；到账时限 1–3 个工作日是为问答联调指定的测试参数。',
  ],
  'REF-009': [
    '当前项目模拟退款按整笔订单全额退回：退款金额等于订单 total_amount（各张票价之和），系统不另扣退票手续费。单笔金额以该订单实际支付金额为准；本地种子场次票价示例为 39 元、45 元和 59 元/张。',
    '项目实现值（联调可用）',
    '依据：OrderService.refund 将 order.totalAmount 写入退款记录；seed-local-data.sql 中场次票价为 39.00、45.00、59.00 元。',
  ],
  'REF-010': [
    '当前项目退票手续费为 0 元，模拟退款全额记录为原订单 total_amount。此规则只描述本地项目实现；真实影院或支付渠道的手续费政策尚未接入。',
    '项目实现值（联调可用）',
    '依据：OrderService.refund 按订单 total_amount 创建退款记录，没有扣费计算；真实渠道未接入。',
  ],
  'REF-011': [
    '当前项目不支持一笔多座订单只退其中一张。退票接口以订单为单位，将该订单下全部票券状态改为 REFUNDED，并按整笔订单金额退款；只有整笔订单满足已出票及开场前 30 分钟截止规则时才可办理。',
    '项目实现值（联调可用）',
    '依据：OrderService.refund 按 order_id 更新全部 order_item，并记录 order.totalAmount；退款资格阈值为 30 分钟。',
  ],
  'REF-012': [
    '当前项目没有改签接口或改签规则，不能直接修改影片、场次或座位。需要更换时，应先按订单页检查原订单是否符合退票条件，再重新选择有余票的场次购票；新票价以新场次实时价格为准。',
    '项目实现值（联调可用）',
    '依据：README.md 当前 API 清单含购票、取消、支付和退票，没有改签接口；具体新场次及价格需实时查询。',
  ],
  'REF-013': [
    'Dify 业务问答测试配置：若影院取消场次，按原订单实付金额全额退款、手续费 0 元，测试到账口径为 1–3 个工作日。当前项目没有场次取消后的自动退款/补偿流程，模拟系统也不会真实打款；该问答值只用于测试，需由运营替换成正式流程。',
    '测试业务值（非正式政策）',
    testConfig + ' 退款到账测试值与人工处置话术不来自当前代码；当前项目未实现取消场次后的自动退款/补偿。',
  ],
  'CIN-001': [
    '星轶影城（演示店）的 Dify 测试营业时间为每日 09:00 开门、次日 00:30 停止营业；周末和节假日暂按同一时段。该时间是本知识库的测试配置，不代表真实门店公告。',
    '测试业务值（非正式营业公告）',
    testConfig + ' 演示影院名称来自 seed-local-data.sql；营业时段 09:00–次日 00:30 为本知识库新增的联调参数。',
  ],
  'CIN-002': [
    '本地种子数据中的影院为“星轶影城（演示店）”，地址是“演示市演示区演示路 1 号”。这是用于开发联调的演示地址，不是可导航的真实门店地址。',
    '演示种子数据（仅测试）',
    '依据：cinema-ticketing-backend/seed-local-data.sql 的 cinema 初始化记录；地址明确为演示数据。',
  ],
  'CIN-003': [
    '本地演示影城的测试联系电话是 010-00000001。该号码来自项目种子数据，是演示号码，不是影院真实客服电话；正式客服联系方式需替换后才能对客使用。',
    '演示种子数据（仅测试）',
    '依据：cinema-ticketing-backend/seed-local-data.sql 的 cinema 初始化记录；号码仅为演示数据。',
  ],
  'CIN-004': [
    '本知识库的节假日测试配置与平日相同：每日 09:00 开门、次日 00:30 停止营业，不额外缩短或延长。真实影院节假日安排尚未核实，不能将此测试时段作为官方公告。',
    '测试业务值（非正式营业公告）',
    testConfig + ' 节假日与平日采用相同时段是本知识库的测试参数，并非生产排班。',
  ],
  'CIN-005': [
    '当前项目的测试售票截止点为场次开始时刻：只要 start_time 晚于当前时间即可继续购票，开始时刻到达或已过就拒绝售票，相当于开场前 0 分钟停售。开场后能否入场属于另一项现场规则，项目没有配置。',
    '项目实现值（联调可用）',
    '依据：OrderService.screening 对 start_time.isAfter(LocalDateTime.now()) 的严格校验；该规则是停止售票时间，不等同检票时间。',
  ],
  'SHOW-001': [
    '演示种子场次共 4 场。以种子脚本执行日为 D：D+2 日 19:30《流浪地球 3》，1 号厅 IMAX，59 元；D+2 日 22:00《深海回响》，1 号厅 IMAX，45 元；D+3 日 14:00《长安夜行》，2 号厅标准厅，39 元；D+3 日 20:00《流浪地球 3》，2 号厅标准厅，39 元。D 会随数据库初始化日期变化；当天排片应以实时接口为准。',
    '演示种子排片（日期会滚动）',
    '依据：cinema-ticketing-backend/seed-local-data.sql 的 4 条 screening 记录；日期使用数据库 CURDATE()+2/+3，价格和影厅为实际种子值。',
  ],
  'SHOW-002': [
    '测试种子排片时间为：种子脚本执行后第 2 天 19:30《流浪地球 3》（1 号厅 IMAX）和 22:00《深海回响》（1 号厅 IMAX）；第 3 天 14:00《长安夜行》（2 号厅标准厅）和 20:00《流浪地球 3》（2 号厅标准厅）。具体年月日随数据库初始化日期滚动，查询用户当前场次时应优先调用实时排片接口。',
    '演示种子排片（日期会滚动）',
    '依据：cinema-ticketing-backend/seed-local-data.sql；start_time 使用 CURDATE() 相对日期。',
  ],
  'SHOW-003': [
    '本地演示场次票价：1 号厅 IMAX，《流浪地球 3》59 元/张，《深海回响》45 元/张；2 号厅标准厅，《长安夜行》39 元/张，《流浪地球 3》39 元/张。每单最多 6 张，因此对应整单示例金额最高分别为 354 元、270 元和 234 元；最终金额以实时订单为准。',
    '演示种子数据（仅测试）',
    '依据：seed-local-data.sql 的 screening.price；OrderService 每单最多 6 个座位并按场次票价计算 total_amount。',
  ],
  'SHOW-004': [
    '演示数据库中，1 号厅 IMAX 为 8 行 × 10 列，共 80 个座位；2 号厅标准厅为 6 行 × 8 列，共 48 个座位。这里是座位总容量，不代表当前余票数；已售和锁定状态必须查询实时座位接口。',
    '演示种子数据（容量固定，余票动态）',
    '依据：seed-local-data.sql 的 hall.row_count/column_count；OrderService.seats 返回动态可用状态。',
  ],
  'SHOW-006': [
    '当前演示排片的影厅对应关系：1 号厅 IMAX（80 座）安排《流浪地球 3》和《深海回响》；2 号厅标准厅（48 座）安排《长安夜行》和另一场《流浪地球 3》。单场具体影厅和时间请按实时场次或订单查询。',
    '演示种子数据（影厅容量固定）',
    '依据：seed-local-data.sql 的 hall 与 screening 记录；影厅容量由 row_count×column_count 计算。',
  ],
  'SHOW-007': [
    '本地种子影片片长：《流浪地球 3》128 分钟，《深海回响》106 分钟，《长安夜行》95 分钟。场次结束时间按片长计算；片前广告等候时长未包含在片长内。',
    '演示种子数据（仅测试）',
    '依据：cinema-ticketing-backend/seed-local-data.sql 中 movie.duration 与 screening.end_time。',
  ],
  'SHOW-008': [
    '当前演示种子数据没有影片年龄分级或儿童入场年龄字段，因此不能根据影片名称或类型推断“适合几岁”。Dify 测试时应回答“本测试数据未提供年龄分级”，并提示查询影院官方影片详情。',
    '项目数据未配置（应明确答未知）',
    '依据：schema.sql 的 movie 表字段及 seed-local-data.sql 影片记录均未配置年龄分级；不得自行补造适龄结论。',
  ],
  'SHOW-009': [
    'Dify 问答测试配置：开场后 15 分钟内可尝试入场，超过 15 分钟需联系前台确认；这只是联调用的模拟规则，当前项目没有检票接口，也不能据此保证真实影院放行。',
    '测试业务值（非正式入场政策）',
    testConfig + ' 开场后 15 分钟为本知识库新增的检索测试参数，代码未实现检票判断。',
  ],
  'SHOW-010': [
    '当前项目没有场次变更后的自动短信通知或自动改签流程。用户可重新查询实时排片并查看本人订单；如果影院手动调整场次，应联系测试客服 010-00000001 核对后续处理。该号码是演示号码。',
    '项目实现边界（联调可用）',
    '依据：README.md 当前功能和接口清单；项目没有场次变更通知/自动改签接口。测试联系方式来自 seed-local-data.sql。',
  ],
  'PRICE-001': [
    '当前项目未实现优惠券或会员折扣。Dify 测试基准按无优惠计算，即优惠金额 0 元、应付金额等于场次票价 × 座位数；测试场次票价为 39 元、45 元或 59 元/张。',
    '项目实现值（联调可用）',
    '依据：项目 schema 和购票接口没有优惠券/会员折扣字段或计算；价格来自 seed-local-data.sql。',
  ],
  'PRICE-002': [
    '当前项目没有优惠券和会员折扣功能，因此没有叠加规则；测试时所有优惠均按 0 元计算，应付金额直接按场次单价乘座位数。',
    '项目实现值（联调可用）',
    '依据：项目购票数据模型和 OrderService.createOrder 未实现优惠计算。',
  ],
  'PRICE-003': [
    '当前演示项目没有发票申请或开票接口，不能在系统内承诺开票或开票时效。若需要测试问答，可回答“当前演示版本暂不提供线上开票”，并将正式发票流程交由影院运营补充。',
    '项目实现边界（联调可用）',
    '依据：README.md 当前 API 清单及项目数据模型未包含发票功能。',
  ],
  'VEN-001': [
    'Dify 停车问答测试配置：凭当日电影票停车前 2 小时免费；超过部分按 5 元/小时计费，不足 1 小时按 1 小时计；24 小时内最高收取 30 元。该价格是虚构的本地测试参数，不代表演示影城或真实停车场收费。',
    '测试业务值（非正式收费公告）',
    testConfig + ' 停车收费参数为本知识库新增的测试值；项目代码和影院种子数据没有停车场信息。',
  ],
  'VEN-002': [
    '本地种子数据提供两个影厅：1 号厅 IMAX，8 行 × 10 列共 80 座；2 号厅标准厅，6 行 × 8 列共 48 座。种子数据没有 Wi-Fi、餐饮、卫生间或休息区等设施字段，相关设施不要自行推断。',
    '演示种子数据（设施信息部分未配置）',
    '依据：seed-local-data.sql 的 hall 初始化记录；其他顾客设施未在项目数据中维护。',
  ],
  'VEN-003': [
    'Dify 问答测试配置：允许携带密封饮用水；不允许携带外部餐食、酒精饮料或有强烈气味的食品入场。此为本地测试规则，真实影院请以现场公告为准。',
    '测试业务值（非正式入场政策）',
    testConfig + ' 外带食品规则为本知识库新增的模拟运营配置；项目代码未实现现场检查。',
  ],
  'VEN-004': [
    'Dify 失物招领测试流程：请在发现遗失后 7 日内拨打演示前台 010-00000001，提供观影日期、场次、影厅和物品特征；测试配置的物品保管期为 30 日。该号码及保管期仅供业务联调，不是实际影院承诺。',
    '测试业务值（非正式服务承诺）',
    testConfig + ' 联系电话来自演示种子数据；7 日联系时限和 30 日保管期是本知识库新增的测试参数。',
  ],
  'VEN-005': [
    '演示座位数据的 seat_type 全部为 STANDARD（普通座）。当前测试数据没有儿童座椅、情侣座或无障碍座位类别；可用座位仍需按指定场次查询实时座位图。',
    '演示种子数据（座位类型固定）',
    '依据：seed-local-data.sql 为所有种子座位写入 STANDARD；seat 查询以指定场次实时返回。',
  ],
};

for (const [id, values] of Object.entries(updates)) {
  const rowIndex = rowById.get(id);
  if (rowIndex === undefined) throw new Error(`Missing knowledge ID: ${id}`);
  rows[rowIndex][3] = values[0];
  rows[rowIndex][4] = values[1];
  rows[rowIndex][5] = values[2];
}

sheet.getRange('D2:F57').values = rows.slice(1).map(row => row.slice(3, 6));
wb.recalculate();

const preview = await wb.render({ sheetName: 'RAG问答库', autoCrop: 'all', scale: 0.7, format: 'png' });
await fs.writeFile(`${baseDir}/after_RAG问答库.png`, new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputPath);

const checked = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
const checkedSheet = checked.worksheets.getItem('RAG问答库');
const verifiedRows = checkedSheet.getRange('A1:F57').values;
const pending = verifiedRows.slice(1).filter(row => String(row[4]).includes('待影院') || String(row[4]).includes('待运营'));
const missingAnswers = verifiedRows.slice(1).filter(row => !String(row[3] ?? '').trim());
const checkIds = ['CIN-001', 'CIN-002', 'CIN-003', 'SHOW-001', 'SHOW-003', 'REF-001', 'REF-008', 'REF-009', 'VEN-001'];
const sample = verifiedRows.slice(1).filter(row => checkIds.includes(row[0])).map(row => ({ id: row[0], status: row[4], answer: row[3] }));
console.log(JSON.stringify({
  outputPath,
  sheet: checkedSheet.name,
  rows: verifiedRows.length - 1,
  updated: Object.keys(updates).length,
  pendingCount: pending.length,
  missingAnswerCount: missingAnswers.length,
  testOnlyConfigCount: verifiedRows.slice(1).filter(row => String(row[4]).includes('测试业务值')).length,
  sample,
}, null, 2));
if (pending.length || missingAnswers.length) throw new Error('Verification failed: unresolved pending rows or blank answers.');
