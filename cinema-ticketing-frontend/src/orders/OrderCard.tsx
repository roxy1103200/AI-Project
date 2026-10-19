import { useId, useRef, useState, type ReactNode } from "react";

type Props = {
  orderNo: string;
  title: string;
  showtime: string;
  venue: string;
  amount: string;
  status: string;
  statusLabel: string;
  poster?: string;
  expanded: boolean;
  onToggle: () => void;
  onTicket: () => void;
  children: ReactNode;
};

export default function OrderCard({ orderNo, title, showtime, venue, amount, status, statusLabel,
  poster, expanded, onToggle, onTicket, children }: Props) {
  const detailsId = useId();
  const titleId = useId();
  const number = useRef<HTMLElement>(null);
  const [copyMessage, setCopyMessage] = useState("");
  const [failedPoster, setFailedPoster] = useState<string>();
  const issued = status === "ISSUED";
  const inactive = status === "CANCELLED" || status === "REFUNDED";

  async function copyNumber() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(orderNo);
      setCopyMessage("订单号已复制");
    } catch {
      setCopyMessage("请选中订单号手动复制");
      if (number.current) {
        const range = document.createRange();
        range.selectNodeContents(number.current);
        const selection = window.getSelection();
        selection?.removeAllRanges(); selection?.addRange(range);
      }
    }
  }

  return <article className="order-card" aria-labelledby={titleId}>
    <div className="order-card-main">
      <div className="order-card-poster" aria-hidden="true">
        {poster && failedPoster !== poster
          ? <img src={poster} alt="" width="84" height="126" loading="lazy" decoding="async" onError={() => setFailedPoster(poster)} />
          : <span>暂无海报</span>}
      </div>
      <div className="order-card-summary">
        <div className="order-card-title">
          <div className="order-card-heading"><h3 id={titleId}>{title}</h3><span className={`order-status status-${status.toLowerCase()}`}>{statusLabel}</span></div>
          <p className="order-card-showtime">{showtime}</p>
          {venue && <p className="order-card-venue">{venue}</p>}
        </div>
        <div className="order-card-side">
          <strong><span>订单金额</span>¥{amount}</strong>
          <button className={`order-ticket-button${issued ? " is-primary" : ""}${inactive ? " is-muted" : ""}`}
            type="button" onClick={onTicket}>{issued ? "查看电影票" : "查看座位"}</button>
        </div>
      </div>
    </div>
    <div className="order-card-footer">
      <button className="order-expand" type="button" aria-expanded={expanded} aria-controls={detailsId} onClick={onToggle}>
        {expanded ? "收起订单详情" : "查看订单详情"}
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      <div className="order-card-number"><code ref={number} title={orderNo}>{orderNo}</code>
        <button className="order-copy-button" type="button" aria-label={`复制订单号 ${orderNo}`} title="复制订单号" onClick={() => void copyNumber()}>
          <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></svg>
        </button>
      </div>
    </div>
    {copyMessage && <p className="order-copy-feedback" role="status">{copyMessage}</p>}
    <div id={detailsId} hidden={!expanded}>{expanded && children}</div>
  </article>;
}
