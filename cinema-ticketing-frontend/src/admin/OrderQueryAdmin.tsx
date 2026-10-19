import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { ApiRequest } from "./movie-save";
import { OrderQueryRequest, orderQueryError, orderStateLabel, orderTime, paymentOrigin, type AdminOrderDetail } from "./order-query";
import "./order-query.css";

type Props = { request: ApiRequest; token: string; initialOrderNo: string; navigate: (path: string) => void };

export default function OrderQueryAdmin({ request, token, initialOrderNo, navigate }: Props) {
  const [number, setNumber] = useState(initialOrderNo);
  const [data, setData] = useState<AdminOrderDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pending = useRef(new OrderQueryRequest());

  const lookup = useCallback(async (orderNo: string) => {
    const operation = pending.current.begin();
    setData(null); setNotice(""); setError("");
    const invalid = orderQueryError(orderNo);
    if (invalid) { setError(invalid); setBusy(false); return; }
    setBusy(true);
    try {
      const detail = await request<AdminOrderDetail>(`/api/admin/orders/${encodeURIComponent(orderNo.trim())}`, { signal: operation.signal }, token);
      if (operation.current()) setData(detail);
    } catch (cause) {
      if (operation.current()) setError(cause instanceof Error ? cause.message : "订单查询失败，请稍后重试");
    } finally { if (operation.current()) setBusy(false); }
  }, [request, token]);

  useEffect(() => {
    setNumber(initialOrderNo); setData(null); setError(""); setNotice(""); setBusy(false);
    if (initialOrderNo) void lookup(initialOrderNo);
    return () => pending.current.cancel();
  }, [initialOrderNo, lookup]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const invalid = orderQueryError(number);
    if (invalid) { pending.current.cancel(); setBusy(false); setData(null); setError(invalid); return; }
    const orderNo = number.trim();
    if (orderNo === initialOrderNo) void lookup(orderNo);
    else navigate(`/admin/orders?orderNo=${encodeURIComponent(orderNo)}`);
  }
  function clear() {
    pending.current.cancel(); setNumber(""); setData(null); setBusy(false); setError(""); setNotice("");
    if (initialOrderNo) navigate("/admin/orders");
  }
  function changeNumber(value: string) {
    pending.current.cancel(); setNumber(value); setData(null); setBusy(false); setError(""); setNotice("");
  }
  async function copyOrder() {
    if (!data) return;
    try {
      if (!navigator.clipboard) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(data.order.orderNo); setNotice("订单号已复制");
    } catch { setNotice("当前环境无法自动复制，请选中页面中的完整订单号复制。"); }
  }

  return <section className="order-query-admin" aria-labelledby="order-query-title">
    <div className="section-heading"><div><p className="eyebrow">ORDER LOOKUP</p><h2 id="order-query-title">订单查询</h2></div></div>
    <p className="section-note">按完整订单号查看订单、逐张电影票及支付退款记录。此页面只读取本系统记录，刷新不会发起渠道查单或交易操作。</p>
    <form className="order-query-search" onSubmit={submit}>
      <label htmlFor="admin-order-number">完整订单号<input id="admin-order-number" value={number} onChange={(event) => changeNumber(event.target.value)} placeholder="输入或粘贴订单号" autoComplete="off" spellCheck={false} aria-describedby={error ? "order-query-error" : undefined} /></label>
      <button type="submit" className="primary-button">{busy ? "重新查询" : "查询订单"}</button>
      <button type="button" className="secondary-button" onClick={clear}>清空</button>
    </form>
    {busy && <p role="status" className="order-query-note">正在读取订单详情…</p>}
    {error && <p id="order-query-error" role="alert" className="order-query-error">{error}</p>}
    {notice && <p role="status" className="order-query-note">{notice}</p>}
    {!data && !busy && !error && <div className="order-query-empty"><h3>从一个订单号开始</h3><p>查询后可查看每张影票、验票记录，以及订单当前的支付和退款情况。</p></div>}
    {data && <OrderDetails data={data} refresh={() => void lookup(data.order.orderNo)} copy={() => void copyOrder()} navigate={navigate} />}
  </section>;
}

export function OrderDetails({ data, refresh, copy, navigate }: {
  data: AdminOrderDetail; refresh: () => void; copy: () => void; navigate: (path: string) => void;
}) {
  return <>
      <header className="order-query-overview">
        <div><p className="order-query-caption">当前查询订单</p><h3>{data.screening.movieTitle ?? "影片资料缺失"}</h3><code>{data.order.orderNo}</code><p>{data.screening.cinemaName ?? "影院资料缺失"} · {data.screening.hallName ?? "影厅资料缺失"}</p></div>
        <div className="order-query-total"><strong>¥{data.order.totalAmount}</strong><span>{data.order.ticketCount} 张影票</span></div>
        <div className="order-query-badges"><Badge label="订单" value={data.order.status} /><Badge label="支付" value={data.payment?.status ?? (data.receipts.some(r => r.status === "SUCCESS") ? "SUCCESS" : "NOT_STARTED")} />{data.refunds.length > 0 && <Badge label="退款" value={data.refunds[data.refunds.length - 1].status} />}</div>
        <p className="order-query-description">{data.order.description}</p>
        <div className="order-query-actions"><button type="button" className="secondary-button" onClick={refresh}>刷新记录</button><button type="button" className="secondary-button" onClick={copy}>复制订单号</button><button type="button" className="secondary-button" onClick={() => navigate(`/admin/ticket-check-in?orderNo=${encodeURIComponent(data.order.orderNo)}`)}>前往验票</button><button type="button" className="text-button" onClick={() => navigate("/admin/payments")}>支付与退款核对 ↗</button></div>
      </header>
      {data.dataWarnings.map((warning) => <p className="order-query-warning" key={warning}>{warning}</p>)}
      {data.diagnostics.issues.map((issue, index) => <div role="status" className={`order-query-warning ${issue.severity}`} key={`${issue.code}-${index}`}><strong>{issue.message}</strong><details><summary>查看异常代码</summary><code>{issue.code}</code></details></div>)}
      <div className="order-query-grid">
        <div className="order-query-primary">
          <DetailCard title="订单与场次"><Facts rows={[
            ["购票账号", data.customer.username ?? "历史账号资料缺失"], ["用户编号", data.customer.id],
            ["创建时间", orderTime(data.order.createdAt)], ["支付截止", orderTime(data.order.expiresAt)],
            ["开场时间", orderTime(data.screening.startTime)], ["放映结束", orderTime(data.screening.viewingEndTime)],
            ["影片时长", data.screening.durationMinutes === null ? "资料缺失" : `${data.screening.durationMinutes} 分钟`], ["场次状态", orderStateLabel(data.screening.status)],
          ]} /></DetailCard>
          <DetailCard title="电影票明细"><p className="order-query-note">按成交时单价展示。验票状态以每张电影票的记录为准。</p><ul className="order-query-tickets">{data.tickets.map(ticket => <li key={ticket.id}>
            <div><strong>{ticket.seatCode ?? `座位 ${ticket.seatId ?? "资料缺失"}`}</strong><span>¥{ticket.price} · {orderStateLabel(ticket.status)}</span></div>
            <div><span>{ticket.checkedInAt ? `已验票 · ${orderTime(ticket.checkedInAt)}` : "未记录验票"}</span>{ticket.checkedInAt && <span>验票人：{ticket.checkedInByName ?? `账号 ${ticket.checkedInBy ?? "资料缺失"}`}</span>}</div>
          </li>)}</ul>{!data.tickets.length && <p className="order-query-note">未找到影票明细，请核对历史资料。</p>}</DetailCard>
          <DetailCard title="支付与收款记录">
            {data.payment ? <Facts rows={[["支付状态", orderStateLabel(data.payment.status)], ["渠道与环境", paymentOrigin(data.payment.channel, data.payment.environment)], ["商户支付单号", data.payment.paymentNo], ["渠道交易号", data.payment.tradeNo], ["支付单金额", `¥${data.payment.amount}`], ["收银台发放", orderTime(data.payment.checkoutIssuedAt)], ["申请关单", orderTime(data.payment.closeRequestedAt)], ["关单原因", data.payment.closeReason === "USER" ? "用户申请" : data.payment.closeReason === "EXPIRED" ? "订单超时" : data.payment.closeReason], ["本地确认收款", orderTime(data.payment.confirmedAt)]]} /> : <p className="order-query-note">没有独立渠道支付单；如为历史模拟支付，请以下方收款流水为准。</p>}
            {data.receipts.map(receipt => <div className="order-query-record" key={receipt.paymentNo}><strong>¥{receipt.amount} · {orderStateLabel(receipt.status)}</strong><Facts rows={[["收款流水", receipt.paymentNo], ["渠道交易号", receipt.tradeNo], ["渠道与环境", paymentOrigin(receipt.channel, receipt.environment)], ["付款时间", orderTime(receipt.paidAt)]]} /></div>)}
            {!data.receipts.length && <p className="order-query-note">本系统尚未记录成功收款；这不等同于渠道已确认未扣款。</p>}
          </DetailCard>
          <DetailCard title="退款记录">{!data.refunds.length && <p className="order-query-note">暂无退款记录。</p>}{data.refunds.map(refund => <div className="order-query-record" key={refund.id}><strong>¥{refund.amount} · {orderStateLabel(refund.status)}</strong><Facts rows={[["退款流水", refund.refundNo], ["退款类型", refund.reasonType === "LATE_PAYMENT" ? "迟到付款补偿退款" : refund.reasonType === "CUSTOMER" ? "用户退票" : refund.reasonType], ["原因", refund.reason], ["渠道与环境", paymentOrigin(refund.channel, refund.environment)], ["申请时间", orderTime(refund.requestedAt)], ["确认退款", orderTime(refund.refundedAt)], ["规则版本", refund.policyVersion], ["已核对次数", refund.attempts], ["下次计划核对", orderTime(refund.nextCheckAt)], ["最近错误代码", refund.lastErrorCode]]} /></div>)}</DetailCard>
        </div>
        <aside className="order-query-secondary" aria-label="资格与核对信息">
          <DetailCard title="当前服务资格"><div className="order-query-eligibility"><strong>{data.eligibility.canCheckIn ? "可前往验票" : "当前不可验票"}</strong><p>{data.eligibility.checkInReason}</p><strong>{data.eligibility.canRefund ? "当前可申请退票" : "当前不可申请退票"}</strong><p>{data.eligibility.refundReason}</p><span>退票截止：{orderTime(data.eligibility.refundDeadline)}</span></div><p className="order-query-note">按当前规则和服务器时间判断。实际验票与退款仍由原业务接口重新校验。</p></DetailCard>
          <DetailCard title="最近核对情况"><Facts rows={[["最近支付检查", orderTime(data.payment?.lastQueryAt ?? null)], ["下次计划检查", orderTime(data.payment?.nextCheckAt ?? null)], ["配置匹配", data.diagnostics.configurationMatch === "MATCH" ? "一致" : data.diagnostics.configurationMatch === "MISMATCH" ? "不一致，需要处理" : "未判断或不适用"]]} /><details className="order-query-technical"><summary>查看脱敏配置</summary><Facts rows={[["支付单应用", data.diagnostics.storedIdentity?.appId], ["当前应用", data.diagnostics.currentIdentity.appId], ["支付单商户", data.diagnostics.storedIdentity?.sellerId], ["当前商户", data.diagnostics.currentIdentity.sellerId]]} /></details><p className="order-query-note">这里展示本地已知记录。计划检查时间不保证实际执行时间。</p></DetailCard>
          <DetailCard title="已记录事件"><ol className="order-query-events">{data.events.map((event, index) => <li key={`${event.type}-${index}`}><span>{event.label}</span><time dateTime={event.at}>{orderTime(event.at)}</time></li>)}</ol>{!data.events.length && <p className="order-query-note">没有可展示的事件时间。</p>}<p className="order-query-note">仅展示已有时间记录。支付截止不是取消时间，收银台发放不代表付款成功。</p></DetailCard>
        </aside>
      </div>
      <p className="order-query-note">服务器记录时间：{orderTime(data.serverTime)} · 北京时间。影片、影院和影厅信息为当前关联资料。</p>
  </>;
}

function DetailCard({ title, children }: { title: string; children: ReactNode }) {
  return <section className="order-query-card"><h3>{title}</h3>{children}</section>;
}
function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="order-query-facts">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value === null || value === undefined || value === "" ? "未记录" : value}</dd></div>)}</dl>;
}
function Badge({ label, value }: { label: string; value: string }) {
  const pending = ["CLOSING", "REFUNDING", "UNKNOWN", "PENDING"].includes(value);
  return <span className={`order-query-badge${pending ? " pending" : ""}`}>{label} · {orderStateLabel(value)}</span>;
}
