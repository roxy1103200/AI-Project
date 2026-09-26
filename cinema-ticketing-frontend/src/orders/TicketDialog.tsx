import { useEffect, useRef, useState } from "react";
import type { ApiRequest } from "../admin/movie-save";

type TicketSeat = { id: number; row_no: number; column_no: number; seat_code: string; is_order_seat: boolean | number; ticket_status?: string };
type Ticket = { orderNo: string; status: string; totalAmount: number | string; movieTitle: string; cinemaName: string; hallName: string; startTime: string; rowCount: number; columnCount: number; seats: TicketSeat[] };
const statusLabels: Record<string, string> = { UNPAID: "待支付", PAID: "已支付", ISSUED: "已出票", REFUNDED: "已退票", CANCELLED: "已取消" };

export default function TicketDialog({ orderNo, token, request, onClose }: { orderNo: string; token: string; request: ApiRequest; onClose: () => void }) {
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  const closeButton = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);
  useEffect(() => {
    let mounted = true;
    setLoading(true); setError(""); setTicket(null);
    request<Ticket>(`/api/orders/${encodeURIComponent(orderNo)}/seat-map`, {}, token)
      .then((value) => { if (mounted) setTicket(value); })
      .catch((failure: unknown) => { if (mounted) setError(failure instanceof Error ? failure.message : "电影票读取失败"); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [orderNo, token, request, version]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onCloseRef.current(); }
      if (event.key === "Tab") {
        const buttons = closeButton.current?.closest("section")?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
        if (!buttons?.length) return;
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => { document.removeEventListener("keydown", handleKey); previous?.focus(); };
  }, []);
  const rows = ticket ? Math.max(ticket.rowCount, ...ticket.seats.map((seat) => seat.row_no), 0) : 0;
  const columns = ticket ? Math.max(ticket.columnCount, ...ticket.seats.map((seat) => seat.column_no), 0) : 0;
  const ownSeats = ticket?.seats.filter((seat) => Boolean(seat.is_order_seat)) ?? [];
  return <div className="modal-backdrop ticket-backdrop" role="presentation" onClick={onClose}>
    <section className="ticket-dialog" role="dialog" aria-modal="true" aria-labelledby="ticket-title" onClick={(event) => event.stopPropagation()}>
      <button ref={closeButton} className="modal-close" type="button" aria-label="关闭电影票" onClick={onClose}>×</button>
      <p className="eyebrow">MY CINEMA TICKET</p><h2 id="ticket-title">{ticket?.status === "ISSUED" ? "电影票" : "订单座位"}</h2>
      {loading && <p role="status">正在读取电影票与座位…</p>}
      {error && <div className="ticket-error" role="alert"><p>{error}</p><button type="button" className="secondary-button" onClick={() => setVersion((value) => value + 1)}>重新读取</button></div>}
      {ticket && <>
        <div className="ticket-heading"><h3>{ticket.movieTitle}</h3><span className={`order-status status-${ticket.status.toLowerCase()}`}>{statusLabels[ticket.status] ?? ticket.status}</span></div>
        <p className="ticket-venue">{ticket.cinemaName} · {ticket.hallName}</p>
        <p className="ticket-time">{ticket.startTime.replace("T", " ").slice(0, 16)}（北京时间）</p>
        {ticket.status !== "ISSUED" && <p className="ticket-state-note">{ticket.status === "UNPAID" ? "订单尚未支付，座位图仅展示本订单所选位置。" : ticket.status === "PAID" ? "订单已支付，正在等待出票。" : "此订单已失效，座位图仅用于查看购票记录。"}</p>}
        <div className="seat-legend"><span><i className="legend-seat selected" />本订单座位</span><span><i className="legend-seat available" />其他座位位置</span></div>
        <div className="screen-label">银幕方向</div>
        <div className="ticket-seat-scroll"><div className="seat-map" aria-label="电影票座位位置图" style={{ minWidth: `${columns * 32 + 38}px` }}>
          {Array.from({ length: rows }, (_, index) => index + 1).map((row) => {
            const byColumn = new Map(ticket.seats.filter((seat) => seat.row_no === row).map((seat) => [seat.column_no, seat]));
            return <div className="seat-row" key={row}><span className="row-label">{row}排</span><div className="seat-row-grid" style={{ gridTemplateColumns: `repeat(${columns}, minmax(25px, 1fr))` }}>
              {Array.from({ length: columns }, (_, column) => {
                const seat = byColumn.get(column + 1);
                return seat ? <span key={seat.id} className={`ticket-seat${seat.is_order_seat ? " selected" : ""}`} role="img" aria-label={`${seat.row_no}排${seat.column_no}座${seat.is_order_seat ? "，本订单座位" : ""}`} title={`${seat.row_no}排${seat.column_no}座`}>{seat.column_no}</span> : <span className="seat-gap" key={`gap-${column}`} />;
              })}</div></div>;
          })}
        </div></div>
        <div className="ticket-seat-summary">{ownSeats.map((seat) => <strong key={seat.id}>{seat.row_no}排 {seat.column_no}座</strong>)}{ownSeats.length === 0 && <span>暂无座位记录</span>}</div>
        <p className="ticket-order-number">订单金额 ¥{Number(ticket.totalAmount).toFixed(2)} · 订单号 {ticket.orderNo}</p>
      </>}
    </section>
  </div>;
}
