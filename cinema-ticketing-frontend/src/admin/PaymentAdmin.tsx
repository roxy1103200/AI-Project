import { useEffect, useState } from "react";
import type { ApiRequest } from "./movie-save";

type Refund = { id: number; refund_no: string; order_no: string; status: string; attempts: number; last_error_code: string | null };
type Payment = { out_trade_no: string; order_no: string; status: string; last_error_code: string | null };
type Exceptions = { refunds: Refund[]; payments: Payment[] };

export default function PaymentAdmin({ request, token }: { request: ApiRequest; token: string }) {
  const [data, setData] = useState<Exceptions | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setError(""); setData(null);
    request<Exceptions>("/api/admin/payments/exceptions", { signal: controller.signal }, token)
      .then((value) => { if (!controller.signal.aborted) setData(value); })
      .catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "读取失败"); });
    return () => controller.abort();
  }, [request, token, version]);

  async function retry(id: number) {
    setBusy(id); setError(""); setNotice("");
    try {
      await request(`/api/admin/refunds/${id}/retry`, { method: "POST" }, token);
      setNotice("已重新核对原退款单，使用原退款流水号处理。请刷新查看渠道确认结果。");
      setVersion((value) => value + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "重试失败"); }
    finally { setBusy(null); }
  }

  return <section className="content-width">
    <div className="section-heading"><div><p className="eyebrow">PAYMENT RECONCILIATION</p><h2>支付与退款核对</h2></div>
      <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => setVersion((value) => value + 1)}>刷新</button></div>
    <p className="section-note">当前接入支付宝沙箱。渠道结果未确认时保留订单与退款记录；退款最多自动核对 8 次，之后需要人工排查。每类展示最近 100 条。</p>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {!data && !error && <p role="status">正在读取待核对记录…</p>}
    {data && <>
      <h3>待确认退款</h3>
      {!data.refunds.length && <p>暂无待确认退款。</p>}
      {data.refunds.map((refund) => <article className="order-card" key={refund.id}>
        <h4>订单 {refund.order_no}</h4><p>退款单：{refund.refund_no}</p>
        <p>{refund.status === "PENDING" ? "等待退款" : "渠道结果待确认"} · 已核对 {refund.attempts} 次{refund.last_error_code ? ` · ${refund.last_error_code}` : ""}</p>
        {refund.attempts >= 8 && <button type="button" className="secondary-button" disabled={busy !== null} onClick={() => void retry(refund.id)}>{busy === refund.id ? "核对中…" : "重新核对原退款单"}</button>}
      </article>)}
      <h3>支付核对异常</h3>
      {!data.payments.length && <p>暂无支付核对异常。</p>}
      {data.payments.map((payment) => <article className="order-card" key={payment.out_trade_no}>
        <h4>订单 {payment.order_no}</h4><p>支付单：{payment.out_trade_no}</p><p>{payment.status} · {payment.last_error_code}</p>
      </article>)}
    </>}
  </section>;
}
