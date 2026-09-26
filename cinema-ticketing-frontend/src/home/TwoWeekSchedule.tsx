import { useEffect, useState } from "react";
import type { ApiRequest } from "../admin/movie-save";
import { dateAfter, wallString, wallTime } from "../admin/schedule-time";

type Movie = { id: number; title: string; duration?: number | null };
type Screening = { id: number; movie_id: number; hall_id: number; start_time: string; end_time: string; price: number | string; status: string; movie_title: string; duration: number; hall_name: string; cinema_id: number; cinema_name: string; can_book: number | boolean; sale_start_time?: string | null; sale_end_time?: string | null };
type Hall = { id: number; cinema_id: number; name: string };
type Cinema = { id: number; name: string };
type Props = { movies: Movie[]; halls: Hall[]; cinemas: Cinema[]; request: ApiRequest; onSelect: (screening: Screening) => void };

export default function TwoWeekSchedule({ movies, halls, cinemas, request, onSelect }: Props) {
  const [slots, setSlots] = useState<Screening[]>([]);
  const [today, setToday] = useState(() => wallString(Date.now()).slice(0, 10));
  const [selectedDay, setSelectedDay] = useState(today);
  const [cinemaId, setCinemaId] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const day = wallString(Date.now()).slice(0, 10);
        const value = await request<Screening[]>(`/api/screenings/schedule?from=${day}&to=${dateAfter(day, 14)}`);
        if (!mounted) return;
        setSlots(value); setError("");
        setToday(day); setSelectedDay((old) => old < day ? day : old);
      } catch (failure) { if (mounted) setError(failure instanceof Error ? failure.message : "排期读取失败"); }
      finally { if (mounted) setLoading(false); }
    };
    void load(); const timer = window.setInterval(() => void load(), 60000);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [request, version]);
  const hallById = new Map(halls.map((hall) => [hall.id, hall]));
  const cinemaById = new Map(cinemas.map((cinema) => [cinema.id, cinema]));
  const days = Array.from({ length: 14 }, (_, index) => dateAfter(today, index));
  const available = slots.filter((slot) => slot.status === "SCHEDULED" && wallTime(slot.start_time) > Date.now()
    && slot.start_time.slice(0, 10) >= today && slot.start_time.slice(0, 10) < dateAfter(today, 14)
    && (!cinemaId || (slot.cinema_id ?? hallById.get(slot.hall_id)?.cinema_id) === Number(cinemaId))).sort((a, b) => a.start_time.localeCompare(b.start_time));
  const daySlots = available.filter((slot) => slot.start_time.startsWith(selectedDay));
  const filmIds = [...new Set(daySlots.map((slot) => slot.movie_id))];
  return <section className="home-schedule content-width" id="schedule" aria-labelledby="schedule-title">
    <div className="section-heading"><div><p className="eyebrow">PLAN YOUR NEXT TWO WEEKS</p><h2 id="schedule-title">两周观影日程</h2></div><div className="schedule-home-tools"><label><span className="sr-only">选择影院</span><select value={cinemaId} onChange={(event) => setCinemaId(event.target.value)}><option value="">全部影院</option>{cinemas.map((cinema) => <option value={cinema.id} key={cinema.id}>{cinema.name}</option>)}</select></label><button className="text-button" type="button" onClick={() => { setLoading(true); setVersion((value) => value + 1); }}>刷新</button></div></div>
    <div className="schedule-date-strip" role="group" aria-label="未来十四天">{days.map((day, index) => <button type="button" key={day} aria-pressed={day === selectedDay} onClick={() => setSelectedDay(day)}><span>{index === 0 ? "今天" : new Intl.DateTimeFormat("zh-CN", { weekday: "short", timeZone: "Asia/Shanghai" }).format(new Date(`${day}T12:00:00+08:00`))}</span><strong>{day.slice(5).replace("-", "/")}</strong><small>{available.filter((slot) => slot.start_time.startsWith(day)).length} 场</small></button>)}</div>
    <p className="section-note">{selectedDay} · 北京时间 · {daySlots.length} 个已排场次 · {daySlots.filter((slot) => Boolean(slot.can_book)).length} 个可售</p>
    <p className="schedule-date-explanation">按开场日期显示；跨午夜的场次归属前一天。已排期但未到上架时间的影片也会展示。</p>
    {loading ? <p className="state-message">正在读取排期…</p> : error ? <p className="state-message" role="alert">{error}</p> : filmIds.length === 0 ? <div className="empty-state">当天暂无已排场次，试试其他日期。</div> : <div className="schedule-film-list">{filmIds.map((id) => {
      const movie = movies.find((item) => item.id === id);
      const filmSlots = daySlots.filter((slot) => slot.movie_id === id);
      const duration = filmSlots[0].duration ?? movie?.duration;
      return <article className="schedule-film-row" key={id}><div><h3>{filmSlots[0].movie_title || movie?.title || `影片 ${id}`}</h3><p>{duration ? `${duration} 分钟` : ""}</p></div><div className="schedule-session-list">{filmSlots.map((slot) => {
        const hall = hallById.get(slot.hall_id);
        const canBook = Boolean(slot.can_book) && (!slot.sale_start_time || wallTime(slot.sale_start_time) <= Date.now()) && (!slot.sale_end_time || wallTime(slot.sale_end_time) > Date.now());
        const filmEnd = wallString(wallTime(slot.start_time) + Number(duration) * 60000);
        const bookingLabel = canBook ? "选择座位" : slot.sale_start_time ? `${slot.sale_start_time.slice(5, 10).replace("-", "/")} ${slot.sale_start_time.slice(11, 16)} 开放购票` : "暂未开放购票";
        return <button key={slot.id} type="button" disabled={!canBook} title={bookingLabel} onClick={() => { if (canBook) onSelect(slot); }}><strong>{slot.start_time.slice(11, 16)}</strong><span>{slot.cinema_name || cinemaById.get(hall?.cinema_id ?? -1)?.name || "影院"} · {slot.hall_name || hall?.name || "影厅"}</span><span>放映结束 {filmEnd.slice(0, 10) !== selectedDay ? "次日 " : ""}{filmEnd.slice(11, 16)}</span><small>¥{Number(slot.price).toFixed(2)} · {bookingLabel}</small></button>;
      })}</div></article>;
    })}</div>}
  </section>;
}
