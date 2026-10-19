import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { compileComponent } from "./component-loader.mjs";

const { default: OrderCard } = await import(await compileComponent(fileURLToPath(new URL("../src/orders/OrderCard.tsx", import.meta.url))));
const noop = () => {};
function render(overrides = {}) {
  return renderToStaticMarkup(React.createElement(OrderCard, {
    orderNo: "O163C41B9TEST", title: "测试电影", showtime: "10月19日 19:30", venue: "测试影院 · 1号厅", amount: "79.90",
    status: "ISSUED", statusLabel: "已出票", expanded: false, onToggle: noop, onTicket: noop,
    children: React.createElement("div", { className: "order-card-detail" }, "A1 · A2"), ...overrides,
  }));
}

test("issued tickets have a primary action and details start collapsed with linked controls", () => {
  const html = render({ poster: "/api/movies/7/poster?v=0" });
  assert.match(html, /order-ticket-button is-primary/);
  assert.match(html, /查看电影票/);
  assert.match(html, /aria-expanded="false"/);
  const controlled = html.match(/aria-controls="([^"]+)"/)[1];
  assert.ok(html.includes(`id="${controlled}" hidden=""`));
  assert.doesNotMatch(html, /A1 · A2|订单号已复制/);
  assert.match(html, /loading="lazy"/);
  assert.match(html, /复制订单号 O163C41B9TEST/);
});

test("inactive orders keep a secondary seat action and a poster fallback", () => {
  for (const status of ["CANCELLED", "REFUNDED"]) {
    const html = render({ status, statusLabel: "已失效" });
    assert.match(html, /order-ticket-button is-muted/);
    assert.match(html, /查看座位/);
    assert.match(html, /暂无海报/);
    assert.doesNotMatch(html, /is-primary|查看电影票/);
  }
});

test("expanded details expose the supplied original business controls and SVG chevron", () => {
  const html = render({ expanded: true, status: "UNPAID", statusLabel: "关单处理中" });
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /收起订单详情/);
  assert.match(html, /A1 · A2/);
  assert.match(html, /关单处理中/);
  assert.match(html, /<svg/);
  assert.doesNotMatch(html, /详情 [↓↑]|is-primary/);
});
