import { useEffect, useState, type FormEvent } from "react";
import { useScopedRequest } from "../auth/client";
import type { StoredSession } from "../auth/useTabSession";
import type { PaymentStatus } from "./payment";

const labels: Record<string, string> = {
  ISSUED: "支付已确认，电影票已出票", REFUNDING: "退款处理中，请稍后查看订单",
  REFUNDED: "退款已确认", CANCELLED: "订单已取消", UNPAID: "正在确认支付结果", PAID: "支付已确认，正在出票",
};

export default function PaymentResult({ session, signIn, navigate }: {
  session: StoredSession | null; signIn: (username: string, password: string) => Promise<void>; navigate: (path: string) => void;
}) {
  const request = useScopedRequest();
  const [orderNo] = useState(() => new URLSearchParams(window.location.search).get("orderNo") ?? "");
  const [status, setStatus] = useState<PaymentStatus | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const [waiting, setWaiting] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);

  useEffect(() => {
    // The signed return parameters are not used as evidence and are removed from browser history.
    window.history.replaceState(null, "", `/payment/result?orderNo=${encodeURIComponent(orderNo)}`);
    if (!session || !orderNo || orderNo.length > 64) return;
    const controller = new AbortController();
    let timer: number | undefined;
    let attempt = 0;
    setStatus(null); setError(""); setWaiting(true);
    async function poll() {
      try {
        const path = `/api/orders/${encodeURIComponent(orderNo)}/payment`;
        const value = await request<PaymentStatus>(attempt % 4 === 0 ? `${path}/sync` : path,
          { method: attempt % 4 === 0 ? "POST" : "GET", signal: controller.signal }, session!.token);
        if (controller.signal.aborted) return;
        setStatus(value); setError("");
        const finished = ["ISSUED", "REFUNDED"].includes(value.orderStatus)
          || (value.orderStatus === "CANCELLED" && !["PENDING", "UNKNOWN"].includes(value.refundStatus ?? ""));
        if (finished || ++attempt >= 60) { setWaiting(false); return; }
      } catch (cause) {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "暂时无法确认支付结果");
        if (++attempt >= 60) { setWaiting(false); return; }
      }
      timer = window.setTimeout(() => void poll(), 3000);
    }
    void poll();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [request, session, orderNo, version]);

  async function login(event: FormEvent) {
    event.preventDefault(); setSigningIn(true); setError("");
    try { await signIn(username, password); setPassword(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "登录失败"); }
    finally { setSigningIn(false); }
  }

  const refundPending = status && ["PENDING", "UNKNOWN"].includes(status.refundStatus ?? "");
  return <main className="admin-access"><section className="admin-access-card">
    <p className="eyebrow">CINEMA</p><h1>支付结果</h1>
    {!orderNo || orderNo.length > 64 ? <p role="alert">缺少有效订单号，请到“我的订单”查看。</p> : <>
      <p>订单号：{orderNo}</p>
      {!session ? <form onSubmit={(event) => void login(event)}>
        <p>请登录购票时使用的账号后查看结果。</p>
        <label>用户名<input required autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label>密码<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <button type="submit" className="primary-button" disabled={signingIn}>{signingIn ? "登录中…" : "登录并查看"}</button>
      </form> : <>
        <p role="status">{refundPending && status?.orderStatus === "CANCELLED" ? "已收款但无法完成出票，款项正在原路退回" : status ? labels[status.orderStatus] ?? "正在核对订单状态" : "正在读取订单结果…"}</p>
        {status?.orderStatus === "UNPAID" && <p>如果已付款，请等待确认，避免重复支付。离开页面后仍会继续核对。</p>}
        {status?.orderStatus === "REFUNDING" && <p>退款确认前电影票暂不可使用。</p>}
        {!waiting && status?.orderStatus === "UNPAID" && <p>暂未确认付款，请查看支付宝沙箱交易记录，或稍后刷新订单。</p>}
        <button type="button" className="secondary-button" disabled={waiting} onClick={() => setVersion((value) => value + 1)}>{waiting ? "正在核对…" : "重新查询"}</button>
      </>}
    </>}
    {error && <p role="alert">{error}</p>}
    <button type="button" className="secondary-button" onClick={() => navigate("/")}>返回影院查看订单</button>
  </section></main>;
}
