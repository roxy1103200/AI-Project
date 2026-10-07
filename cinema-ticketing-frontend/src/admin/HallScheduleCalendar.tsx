import { useEffect, useState } from "react";
import type { ApiRequest } from "./movie-save";
import type { DraftScreening, ScheduleHall, ScheduleCinema } from "./MovieScheduleFields";
import { dateAfter, endAfterDuration, wallString, wallTime, TURNOVER_MINUTES } from "./schedule-time";

type ScheduledSlot = { id: number; movie_id: number; hall_id: number; title: string; start_time: string; film_end_time: string; occupied_end_time: string; price: number | string };
type Occupancy = { key: string; hallId: number; start: number; filmEnd: number; end: number; title: string; draft: boolean; price: string };
type Props = {
  slots: DraftScreening[]; halls: ScheduleHall[]; cinemas: ScheduleCinema[];
  movieId?: number; movieTitle: string; duration: number; saleStart: string; saleEnd: string;
  token: string; request: ApiRequest; disabled: boolean; onAdd: (slot: DraftScreening) => void;
};

export default function HallScheduleCalendar({ slots, halls, cinemas, movieId, movieTitle, duration, saleStart, saleEnd, token, request, disabled, onAdd }: Props) {
  const [from, setFrom] = useState(() => wallString(Date.now()).slice(0, 10));
  const [days, setDays] = useState(7);
  const [hallFilter, setHallFilter] = useState(() => String(halls.find((hall) => hall.status === "ACTIVE")?.id ?? ""));
  const [dayStart, setDayStart] = useState("09:00");
  const [dayEnd, setDayEnd] = useState("23:59");
  const [rows, setRows] = useState<ScheduledSlot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!from) return;
    let mounted = true;
    setLoading(true); setError("");
    request<ScheduledSlot[]>(`/api/halls/schedule?from=${from}&to=${dateAfter(from, days)}`, {}, token)
      .then((result) => { if (mounted) setRows(result); })
      .catch((failure: unknown) => { if (mounted) setError(failure instanceof Error ? failure.message : "排期读取失败"); })
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, [from, days, token, request, version]);
  const cinemaById = new Map(cinemas.map((cinema) => [cinema.id, cinema]));
  const visibleHalls = halls.filter((hall) => (!hallFilter || String(hall.id) === hallFilter)
    && hall.status === "ACTIVE" && cinemaById.get(hall.cinema_id)?.status === "ACTIVE");
  const occupancy: Occupancy[] = rows.filter((row) => row.movie_id !== movieId).map((row) => ({
    key: `saved-${row.id}`, hallId: row.hall_id, start: wallTime(row.start_time), filmEnd: wallTime(row.film_end_time),
    end: wallTime(row.occupied_end_time), title: row.title, draft: false, price: String(row.price),
  }));
  slots.forEach((slot, index) => {
    const start = wallTime(slot.start_time);
    if (slot.status !== "SCHEDULED" || !slot.hall_id || !Number.isFinite(start)) return;
    const filmEnd = start + duration * 60000;
    const end = Math.max(wallTime(slot.end_time) || 0, filmEnd + TURNOVER_MINUTES * 60000);
    occupancy.push({ key: `draft-${slot.id ?? index}`, hallId: Number(slot.hall_id), start, filmEnd, end, title: movieTitle || "当前影片", draft: true, price: slot.price });
  });
  occupancy.sort((a, b) => a.start - b.start);
  const dates = from ? Array.from({ length: days }, (_, index) => dateAfter(from, index)) : [];

  function firstGap(hallId: number, date: string): number | null {
    if (!Number.isInteger(duration) || duration <= 0 || !dayStart || !dayEnd || dayEnd <= dayStart) return null;
    const length = (duration + TURNOVER_MINUTES) * 60000;
    let candidate = Math.max(wallTime(`${date}T${dayStart}`), Math.ceil((Date.now() + 60000) / 300000) * 300000);
    if (saleStart) candidate = Math.max(candidate, wallTime(saleStart));
    let limit = wallTime(`${date}T${dayEnd}`);
    if (saleEnd) limit = Math.min(limit, wallTime(saleEnd));
    for (const event of occupancy.filter((event) => event.hallId === hallId)) {
      if (event.end <= candidate) continue;
      if (candidate + length <= event.start) break;
      candidate = Math.max(candidate, event.end);
    }
    return candidate + length <= limit ? candidate : null;
  }
  return <section className="hall-schedule-calendar" aria-label="影厅排期周期表">
    <div className="movie-admin-schedule-heading"><h3>影厅排期周期表</h3><button type="button" disabled={loading || disabled} onClick={() => setVersion((value) => value + 1)}>刷新排期</button></div>
    <div className="hall-schedule-controls">
      <label><span>周期开始日期</span><input type="date" required value={from} onChange={(event) => setFrom(event.target.value)} /></label>
      <label><span>查看周期</span><select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={7}>7 天</option><option value={14}>14 天</option><option value={28}>28 天</option></select></label>
      <label><span>影厅</span><select value={hallFilter} onChange={(event) => setHallFilter(event.target.value)}><option value="">所有影厅</option>{halls.map((hall) => <option key={hall.id} value={hall.id}>{cinemaById.get(hall.cinema_id)?.name} / {hall.name}</option>)}</select></label>
    </div>
    <details className="calendar-options"><summary>可排片时段 · {dayStart}–{dayEnd}</summary><div className="hall-schedule-controls">
      <label><span>时段开始</span><input type="time" value={dayStart} onChange={(event) => setDayStart(event.target.value)} /></label>
      <label><span>时段结束</span><input type="time" value={dayEnd} onChange={(event) => setDayEnd(event.target.value)} /></label>
    </div></details>
    <p>当前编辑场次已叠加；点击空档添加。时间范围包含 20 分钟周转。跨午夜场次会在次日显示占用，购票日程按开场日期显示。</p>
    {loading ? <p role="status">正在读取影厅排期…</p> : error ? <p role="alert" className="movie-admin-form-error">{error}</p> : <div className="hall-schedule-scroll"><table className="hall-schedule-table">
      <thead><tr><th scope="col">影院 / 影厅</th>{dates.map((date) => <th scope="col" key={date}>{date.slice(5)}<small>{new Intl.DateTimeFormat("zh-CN", { weekday: "short", timeZone: "Asia/Shanghai" }).format(new Date(`${date}T00:00:00+08:00`))}</small></th>)}</tr></thead>
      <tbody>{visibleHalls.map((hall) => <tr key={hall.id}><th scope="row">{cinemaById.get(hall.cinema_id)?.name}<small>{hall.name}</small></th>{dates.map((date) => {
        const dayLo = wallTime(`${date}T00:00:00`), dayHi = wallTime(`${dateAfter(date, 1)}T00:00:00`);
        const events = occupancy.filter((event) => event.hallId === hall.id && event.start < dayHi && event.end > dayLo);
        const gap = firstGap(hall.id, date);
        return <td key={date}>{events.map((event) => {
          const conflict = occupancy.some((other) => other.key !== event.key && other.hallId === event.hallId && other.start < event.end && other.end > event.start);
          return <article className={`calendar-slot${event.draft ? " is-draft" : ""}${conflict ? " has-conflict" : ""}`} key={event.key}>
          <strong title={event.title}>{event.title}</strong>{event.start < dayLo && <small>跨日占用 · 前日开场</small>}<span>{wallString(event.start).slice(0, 10) === date ? wallString(event.start).slice(11, 16) : wallString(event.start).slice(5, 16).replace("T", " ")}–{wallString(event.end).slice(0, 10) === date ? wallString(event.end).slice(11, 16) : wallString(event.end).slice(5, 16).replace("T", " ")}</span>
          <span>放映结束 {wallString(event.filmEnd).slice(11, 16)}</span>
          <small>{event.draft ? "当前编辑" : "已保存"} · ¥{event.price || "待设票价"}{conflict ? " · 时间冲突" : ""}</small>
        </article>; })}{gap !== null ? <button className="calendar-add-gap" type="button" disabled={disabled} onClick={() => {
          const start = wallString(gap);
          onAdd({ hall_id: String(hall.id), start_time: start, end_time: endAfterDuration(start, duration), price: "", status: "SCHEDULED" });
        }}>＋ {wallString(gap).slice(11, 16)} 空档</button> : <span className="calendar-no-gap">{duration > 0 ? "时段内无可用空档" : "先填写影片片长"}</span>}</td>;
      })}</tr>)}</tbody>
    </table>{visibleHalls.length === 0 && <p>没有符合条件的营业影厅。</p>}</div>}
  </section>;
}
