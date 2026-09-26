import { useEffect, useState } from "react";
import HallScheduleCalendar from "./HallScheduleCalendar";
import type { ApiRequest } from "./movie-save";
import { endAfterDuration, wallTime, TURNOVER_MINUTES } from "./schedule-time";

export type DraftScreening = {
  id?: number;
  hall_id: string;
  start_time: string;
  end_time: string;
  price: string;
  status: string;
  has_orders?: boolean | number;
};

export type ScheduleHall = { id: number; cinema_id: number; name: string; status?: string };
export type ScheduleCinema = { id: number; name: string; status?: string };

type Props = {
  slots: DraftScreening[];
  halls: ScheduleHall[];
  cinemas: ScheduleCinema[];
  duration: number;
  loading: boolean;
  error: string;
  disabled: boolean;
  onChange: (slots: DraftScreening[]) => void;
  movieId?: number;
  movieTitle: string;
  saleStart: string;
  saleEnd: string;
  token: string;
  request: ApiRequest;
};

export default function MovieScheduleFields({ slots, halls, cinemas, duration, loading, error, disabled, onChange, movieId, movieTitle, saleStart, saleEnd, token, request }: Props) {
  const [view, setView] = useState<"list" | "calendar">("list");
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  useEffect(() => {
    const normalized = slots.map((slot) => {
      if (slot.has_orders || wallTime(slot.start_time) <= Date.now()) return slot;
      const end = endAfterDuration(slot.start_time, duration);
      return end && end !== slot.end_time ? { ...slot, end_time: end } : slot;
    });
    if (normalized.some((slot, index) => slot !== slots[index])) onChange(normalized);
  }, [duration, slots, onChange]);
  function change(index: number, values: Partial<DraftScreening>) {
    onChange(slots.map((slot, position) => position === index ? { ...slot, ...values } : slot));
  }
  const cinemaById = new Map(cinemas.map((cinema) => [cinema.id, cinema]));
  return (
    <section className="movie-admin-schedules wide" aria-label="放映场次与票价">
      <div className="movie-admin-schedule-heading"><h3>放映场次与票价</h3>
        <button type="button" disabled={disabled || loading || !!error} onClick={() => { setView("list"); setExpandedIndex(slots.length); onChange([...slots, { hall_id: "", start_time: "", end_time: "", price: "", status: "SCHEDULED" }]); }}>＋ 添加场次</button>
      </div>
      <p>影厅占用时长 = 影片片长 {duration > 0 ? `${duration} 分钟` : "（请填写）"} + {TURNOVER_MINUTES} 分钟周转。占用结束自动计算，下一场须在周转结束后开场。</p>
      <div className="schedule-view-tabs"><button type="button" aria-pressed={view === "list"} onClick={() => setView("list")}>场次列表 · {slots.length}</button><button type="button" aria-pressed={view === "calendar"} onClick={() => setView("calendar")}>影厅周期表</button></div>
      <div hidden={view !== "calendar"}>{!loading && !error && <HallScheduleCalendar slots={slots} halls={halls} cinemas={cinemas} movieId={movieId} movieTitle={movieTitle} duration={duration} saleStart={saleStart} saleEnd={saleEnd} token={token} request={request} disabled={disabled} onAdd={(slot) => { const next = [...slots, slot].sort((a, b) => (a.start_time || "9999").localeCompare(b.start_time || "9999")); onChange(next); setExpandedIndex(next.indexOf(slot)); setView("list"); }} />}</div>
      <div className="schedule-list-content" hidden={view !== "list"}>
      <button className="movie-admin-sort-slots" type="button" disabled={disabled || loading} onClick={() => { setExpandedIndex(null); onChange([...slots].sort((a, b) => (a.start_time || "9999").localeCompare(b.start_time || "9999"))); }}>按开场时间排序</button>
      {loading ? <p role="status">正在读取影厅与现有场次…</p> : error ? <p className="movie-admin-form-error" role="alert">{error}，请关闭编辑窗口后重新打开。</p> : slots.length === 0 ? <p>尚未排期。仅上架影片不会生成场次，添加场次后观众才可订购。</p> : null}
      {slots.map((slot, index) => {
        const locked = Boolean(slot.has_orders);
        const hall = halls.find((item) => String(item.id) === slot.hall_id);
        const expanded = expandedIndex === index;
        return <div className="schedule-list-item" key={slot.id ?? `new-${index}`}>
          <button className="schedule-list-summary" type="button" aria-expanded={expanded} onClick={() => setExpandedIndex(expanded ? null : index)}>
            <span><strong>{slot.start_time ? slot.start_time.replace("T", " ").slice(0, 16) : "待设置开场时间"}</strong><small>{hall ? `${cinemaById.get(hall.cinema_id)?.name ?? ""} · ${hall.name}` : "选择影厅"}</small></span>
            <span>{slot.price ? `¥${slot.price}` : "待设票价"}<small>{locked ? "已有订单" : slot.status === "CANCELLED" ? "已取消" : slot.id ? "已保存" : "新场次"}</small></span><span aria-hidden="true">{expanded ? "−" : "＋"}</span>
          </button>
          <fieldset hidden={!expanded} className="movie-admin-schedule-row" disabled={disabled || locked || loading}>
          <legend>{slot.id ? `场次 #${slot.id}` : `新场次 ${index + 1}`}{locked ? " · 已有订单，保留原排期" : ""}</legend>
          <label><span>影院 / 影厅 <b>*</b></span><select required value={slot.hall_id} onChange={(event) => change(index, { hall_id: event.target.value })}>
            <option value="">选择影厅</option>
            {halls.filter((hall) => String(hall.id) === slot.hall_id || (hall.status === "ACTIVE" && cinemaById.get(hall.cinema_id)?.status === "ACTIVE"))
              .map((hall) => <option key={hall.id} value={hall.id}>{cinemaById.get(hall.cinema_id)?.name ?? "影院"} / {hall.name}</option>)}
          </select></label>
          <label><span>票价（元） <b>*</b></span><input required type="number" min="0.01" max="99999999.99" step="0.01" value={slot.price} onChange={(event) => change(index, { price: event.target.value })} placeholder="例如 39.00" /></label>
          <label><span>开场时间 <b>*</b></span><input required type="datetime-local" step="1" value={slot.start_time} onChange={(event) => change(index, { start_time: event.target.value, end_time: endAfterDuration(event.target.value, duration) })} /></label>
          <label><span>占用结束（含 20 分钟周转）</span><input required readOnly type="datetime-local" step="1" value={slot.end_time} /><small>放映结束后预留清场及入场时间</small></label>
          <label><span>场次状态</span><select value={slot.status} onChange={(event) => change(index, { status: event.target.value })}><option value="SCHEDULED">开放售票</option><option value="CANCELLED">取消场次</option></select></label>
          {!locked && <button className="movie-admin-remove-slot" type="button" onClick={() => { setExpandedIndex(null); onChange(slots.filter((_, position) => position !== index)); }}>移除此场次</button>}
        </fieldset></div>;
      })}
      </div>
    </section>
  );
}
