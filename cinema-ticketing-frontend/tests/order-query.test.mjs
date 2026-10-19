import test from "node:test";
import assert from "node:assert/strict";
import { OrderQueryRequest, orderQueryError, orderStateLabel, orderTime, paymentOrigin } from "../src/admin/order-query.ts";
import { orderNoFromSearch, adminView } from "../src/admin/routes.ts";

test("order numbers are exact identifiers with bounded length and no control characters", () => {
  for (const value of ["", "   ", "A".repeat(65), "A\u0000B", "A\u007fB"]) assert.ok(orderQueryError(value));
  assert.equal(orderQueryError("  ORDER-A9EC9EE9  "), null);
  assert.equal(orderQueryError("A".repeat(64)), null);
});

test("new requests supersede late replies even if the transport ignores abort", async () => {
  const requests = new OrderQueryRequest();
  const first = requests.begin();
  const second = requests.begin();
  assert.equal(first.signal.aborted, true);
  let displayed = "";
  await Promise.resolve().then(() => { if (second.current()) displayed = "B"; });
  await Promise.resolve().then(() => { if (first.current()) displayed = "A"; });
  assert.equal(displayed, "B");
  requests.cancel();
  assert.equal(second.current(), false);
  assert.equal(second.signal.aborted, true);
});

test("clear and unmount invalidate both pending successes and errors", () => {
  const requests = new OrderQueryRequest();
  const old = requests.begin(); requests.cancel();
  assert.equal(old.current(), false);
  const next = requests.begin();
  assert.equal(next.current(), true);
});

test("query links keep pathname distinct and preserve encoded full order numbers", () => {
  const number = "ORDER A/+?#&中文";
  const url = new URL(`/admin/orders?orderNo=${encodeURIComponent(number)}`, "https://cinema.test");
  assert.equal(adminView(url.pathname), "orders");
  assert.equal(orderNoFromSearch(url.search), number);
  assert.equal(orderNoFromSearch("?other=abc"), "");
  assert.equal(orderNoFromSearch("?orderNo=%20ORDER-A9EC9EE9%20"), "ORDER-A9EC9EE9");
  assert.equal(adminView("/admin/ticket-check-in"), "ticket-check-in");
});

test("pending payment and refund states stay distinct and unknown values remain visible", () => {
  assert.equal(orderStateLabel("CLOSING"), "关单处理中");
  assert.equal(orderStateLabel("UNKNOWN"), "结果待核对");
  assert.equal(orderStateLabel("REFUNDED"), "退款已确认");
  assert.match(orderStateLabel("FUTURE_STATE"), /FUTURE_STATE/);
  assert.equal(orderStateLabel(null), "未记录");
  assert.equal(paymentOrigin("MOCK", "MOCK"), "历史模拟支付 · 模拟");
});

test("dates display Shanghai time consistently regardless of client zone", () => {
  assert.equal(orderTime("2026-10-19T02:00:00Z"), orderTime("2026-10-19T10:00:00+08:00"));
  assert.match(orderTime("2026-10-19T02:00:00Z"), /10:00:00/);
  assert.equal(orderTime(null), "未记录");
  assert.equal(orderTime("invalid"), "时间资料待核对");
});
