import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import OrderCard from "../../src/orders/OrderCard";
import "../../src/styles.css";

/** Isolated layout fixture: no authentication, order API or transaction actions. */
function Preview() {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [ticket, setTicket] = useState("");
  const samples = [
    { no: "OPREVIEW-ISSUED-163C41B9020261019", title: "星际穿越", status: "ISSUED", label: "已出票", amount: "79.90" },
    { no: "OPREVIEW-CANCELLED-79BC20520261019", title: "海上钢琴师", status: "CANCELLED", label: "已取消", amount: "39.95" },
    { no: "OPREVIEW-CLOSING-" + "A".repeat(40), title: "这是一部用于检查手机端长标题和状态标签排版的电影", status: "UNPAID", label: "关单处理中", amount: "12345.60" },
  ];
  return <main className="app-shell"><section className="orders-section content-width" style={{ paddingTop: 40 }}>
    <div className="section-heading"><div><p className="eyebrow">YOUR TICKETS</p><h2>我的订单</h2></div></div>
    {ticket && <p role="status">已选择查看：{ticket}</p>}
    <div className="order-list">{samples.map(sample => <OrderCard key={sample.no} orderNo={sample.no} title={sample.title}
      showtime="10月19日 周一 19:30" venue="城市影院 · 激光 IMAX 厅" amount={sample.amount} status={sample.status} statusLabel={sample.label}
      expanded={expanded === sample.no} onToggle={() => setExpanded(expanded === sample.no ? null : sample.no)} onTicket={() => setTicket(sample.title)}>
      <div className="order-card-detail"><div className="order-seat-list"><span>A1</span><span>A2</span></div><p className="refund-note">订单详情预览，所有交易操作均未连接。</p></div>
    </OrderCard>)}</div>
  </section></main>;
}

createRoot(document.getElementById("root")!).render(<Preview />);
