import { useEffect, useState } from "react";

type Props = {
  deadline?: string | null;
  canRefund?: boolean;
  reason?: string;
  serverTime?: string;
  receivedAt?: number;
  busy: boolean;
  onRefund: () => void;
};

export default function RefundControl({ deadline, canRefund, reason, serverTime, receivedAt, busy, onRefund }: Props) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const offset = serverTime && receivedAt ? new Date(`${serverTime}+08:00`).getTime() - receivedAt : 0;
  const deadlineTime = deadline ? new Date(`${deadline}+08:00`).getTime() : NaN;
  const expired = Number.isFinite(deadlineTime) && now + offset >= deadlineTime;
  const allowed = canRefund === true && Number.isFinite(deadlineTime) && !expired;
  const note = expired ? "已超过退票截止时间" : !allowed ? reason || "退票规则暂不可用" : "";
  return <>
    <button className={!allowed ? "refund-disabled" : ""} type="button" disabled={busy || !allowed} title={note || "申请退票"} onClick={() => {
      if (allowed && Date.now() + offset < deadlineTime) onRefund();
      else setNow(Date.now());
    }}>申请退票</button>
    <span className="refund-note">{note}{deadline ? `${note ? " · " : ""}退票截止：${deadline.replace("T", " ").slice(0, 16)}（北京时间）` : ""}</span>
  </>;
}
