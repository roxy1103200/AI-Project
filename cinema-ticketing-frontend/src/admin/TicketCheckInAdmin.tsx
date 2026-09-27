import { useState, type FormEvent } from "react";
import type { ApiRequest } from "./movie-save";
import { reviewTime } from "../home/review-business";
import "./movie-reviews-admin.css";

type Ticket = { id: number; ticket_status: string; seat_code: string; checked_in_at: string | null };
type Order = { order_no: string; status: string; username: string; movie_title: string; cinema_name: string; hall_name: string; start_time: string; viewing_end_time: string; canCheckIn: boolean; checkInReason: string; items: Ticket[] };

export default function TicketCheckInAdmin({ request, token }: { request: ApiRequest; token: string }) {
  const [number, setNumber] = useState("");
  const [data, setData] = useState<Order | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function lookup(event: FormEvent) {
    event.preventDefault(); if (!number.trim() || busy) return;
    setBusy(true); setData(null); setError(""); setMessage(""); setSelected([]);
    try { setData(await request<Order>(`/api/admin/tickets/${encodeURIComponent(number.trim())}`, {}, token)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "订单查询失败"); }
    finally { setBusy(false); }
  }
  async function checkIn() {
    if (!data || busy || selected.length === 0) return;
    setBusy(true); setError(""); setMessage("");
    try {
      setData(await request<Order>(`/api/admin/tickets/${encodeURIComponent(data.order_no)}/check-in`, { method: "POST", body: JSON.stringify({ itemIds: selected }) }, token));
      setSelected([]); setMessage("所选电影票已验票入场，观众现在可以提交影评。该订单不再支持退票。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "验票失败"); }
    finally { setBusy(false); }
  }
  return <section className="content-width movie-review-admin"><div className="section-heading"><div><p className="eyebrow">TICKET CHECK IN</p><h2>验票入场</h2></div></div><p className="section-note">输入订单号核对影片、场次和座位，选择实际到场的电影票。验票开放时间为开场前 15 分钟至影片放映结束，重复验票不会覆盖首次记录。</p>
    <form className="moderation-filters" onSubmit={(event) => void lookup(event)}><label className="moderation-search">订单号<input required maxLength={64} value={number} disabled={busy} onChange={(event) => { setNumber(event.target.value); setData(null); setSelected([]); setMessage(""); }} placeholder="输入观众出示的订单号" /></label><button type="submit" className="secondary-button" disabled={busy}>{busy ? "处理中…" : "查询电影票"}</button></form>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {data && <article className="moderation-card"><h3>{data.movie_title}</h3><p>{data.cinema_name} · {data.hall_name}</p><p>开场 {reviewTime(data.start_time)} · 放映结束 {reviewTime(data.viewing_end_time)}（北京时间）</p><p className="moderation-meta">购票人：{data.username} · 订单：{data.order_no} · {data.status === "ISSUED" ? "已出票" : data.status === "REFUNDED" ? "已退票" : data.status === "CANCELLED" ? "已取消" : "未出票"}</p><p>{data.checkInReason}</p>
      <div className="check-in-tickets">{data.items.map((item) => <label className={item.checked_in_at ? "checked" : ""} key={item.id}><input type="checkbox" checked={selected.includes(item.id)} disabled={busy || !data.canCheckIn || Boolean(item.checked_in_at) || !["ISSUED", "VALID"].includes(item.ticket_status)} onChange={(event) => setSelected((value) => event.target.checked ? [...value, item.id] : value.filter((id) => id !== item.id))} /><strong>{item.seat_code}</strong><span>{item.checked_in_at ? `已验票 · ${reviewTime(item.checked_in_at)}` : ["ISSUED", "VALID"].includes(item.ticket_status) ? "待验票" : "电影票已失效"}</span></label>)}</div>
      <div className="moderation-actions"><span>已选 {selected.length} 张</span><button type="button" className="primary-button" disabled={busy || selected.length === 0 || !data.canCheckIn} onClick={() => void checkIn()}>确认所选电影票入场</button></div>
    </article>}
  </section>;
}
