import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileComponent } from "./component-loader.mjs";

const { default: OrderQueryAdmin, OrderDetails } = await import(await compileComponent(fileURLToPath(new URL("../src/admin/OrderQueryAdmin.tsx", import.meta.url))));
const { default: TicketCheckInAdmin } = await import(await compileComponent(fileURLToPath(new URL("../src/admin/TicketCheckInAdmin.tsx", import.meta.url))));
const noop = () => {};

function fixture() {
  return {
    order: { id: 1, orderNo: "ORDER-A9EC9EE9", status: "UNPAID", totalAmount: "79.90", ticketCount: 2, description: "正在核对并关闭支付交易，尚未确认取消" },
    customer: { id: 1, username: "customer" },
    screening: { movieTitle: "测试电影", cinemaName: "测试影院", hallName: "一号厅", durationMinutes: 120, status: "SCHEDULED" },
    tickets: [{ id: 1, seatId: 1, seatCode: "A1", price: "39.95", status: "VALID", checkedInAt: null }, { id: 2, seatId: 2, seatCode: "A2", price: "39.95", status: "VALID", checkedInAt: null }],
    payment: { status: "CLOSING", channel: "ALIPAY", environment: "SANDBOX", paymentNo: "PAY-1", amount: "79.90" },
    receipts: [], refunds: [], eligibility: { canCheckIn: false, canRefund: false, checkInReason: "只有已出票订单可以验票", refundReason: "尚未确认取消" },
    diagnostics: { configurationMatch: "MISMATCH", storedIdentity: { appId: "****3958", sellerId: "****1234" }, currentIdentity: { appId: "****6161", sellerId: "****1234" }, issues: [{ code: "CONFIG_MISMATCH", severity: "error", message: "支付配置不一致，需要管理员核对" }] },
    events: [{ type: "CREATED", label: "订单创建", at: "2026-10-19T10:00:00+08:00" }], dataWarnings: [], serverTime: "2026-10-19T10:00:00+08:00",
  };
}

function renderDetail(data) {
  return renderToStaticMarkup(React.createElement(OrderDetails, { data, refresh: noop, copy: noop, navigate: noop }));
}

test("empty lookup has a labelled form and no automatic business action", () => {
  let calls = 0;
  const html = renderToStaticMarkup(React.createElement(OrderQueryAdmin, { request: async () => { calls++; }, token: "admin", initialOrderNo: "", navigate: noop }));
  assert.match(html, /for="admin-order-number"/);
  assert.match(html, /从一个订单号开始/);
  assert.match(html, /type="submit"/);
  assert.equal(calls, 0);
});

test("closing shows independent facts, masked diagnostics and every seat without destructive controls", () => {
  const html = renderDetail(fixture());
  for (const text of ["待支付", "关单处理中", "尚未确认取消", "CONFIG_MISMATCH", "****3958", "A1", "A2", "79.90", "39.95", "当前不可验票", "这不等同于渠道已确认未扣款"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, />(取消订单|发起退款|强制关单|释放座位|立即查渠道)</);
});

test("late payment compensation renders cancelled order, successful receipt and pending refund together", () => {
  const data = fixture();
  data.order.status = "CANCELLED";
  data.payment.status = "SUCCESS";
  data.receipts = [{ paymentNo: "R-1", amount: "79.90", status: "SUCCESS", channel: "ALIPAY", environment: "SANDBOX" }];
  data.refunds = [{ id: 1, refundNo: "F-1", amount: "79.90", status: "UNKNOWN", reasonType: "LATE_PAYMENT", attempts: 8 }];
  const html = renderDetail(data);
  for (const text of ["订单 · 已取消", "支付 · 已确认收款", "退款 · 结果待核对", "迟到付款补偿退款", "F-1"]) assert.ok(html.includes(text), text);
});

test("missing historical associations remain renderable and raw unknown states remain visible", () => {
  const data = fixture();
  data.screening = { durationMinutes: null };
  data.customer.username = null;
  data.tickets[0].seatCode = null;
  data.order.status = "FUTURE_STATUS";
  data.payment = null; data.receipts = [{ paymentNo: "M-1", amount: "79.90", status: "SUCCESS", channel: "MOCK", environment: "MOCK" }];
  const html = renderDetail(data);
  for (const text of ["影片资料缺失", "历史账号资料缺失", "FUTURE_STATUS", "历史模拟支付", "M-1"]) assert.ok(html.includes(text), text);
});

test("ticket check-in accepts the linked order number while awaiting original lookup", () => {
  let calls = 0;
  const html = renderToStaticMarkup(React.createElement(TicketCheckInAdmin, { request: async () => { calls++; }, token: "admin", initialOrderNo: "ORDER-A9EC9EE9" }));
  assert.match(html, /value="ORDER-A9EC9EE9"/);
  assert.equal(calls, 0);
  assert.doesNotMatch(html, /确认所选电影票入场/);
});
