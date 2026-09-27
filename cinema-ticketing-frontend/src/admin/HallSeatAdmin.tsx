import { useEffect, useMemo, useState, type FormEvent } from "react";
import type { ApiRequest } from "./movie-save";
import "./hall-seat.css";

type Cinema = { id: number; name: string; status?: string | null };
type Hall = { id: number; cinema_id: number; cinema_name: string; name: string; row_count: number; column_count: number; hall_type: string; status: string; seat_count: number; screening_count: number };
type Seat = { id: number; row_no: number; column_no: number; seat_code: string; seat_type: string; status: string; has_orders: boolean | number };
type HallForm = { id?: number; cinemaId: number; name: string; rows: number; columns: number; type: string; status: string };
type SeatForm = { id?: number; row: number; column: number; code: string; type: string; status: string };
type Props = { view: "halls" | "seats"; cinemas: Cinema[]; token: string; request: ApiRequest; onRefresh: () => Promise<void>; onSeats: () => void };
const hallTypes: Record<string,string> = { STANDARD: "标准", IMAX: "IMAX", DOLBY: "杜比" };
const seatTypes: Record<string,string> = { STANDARD: "标准", VIP: "VIP", COUPLE: "情侣" };

export default function HallSeatAdmin({ view, cinemas, token, request, onRefresh, onSeats }: Props) {
  const [cinemaId, setCinemaId] = useState("");
  const [halls, setHalls] = useState<Hall[]>([]);
  const [hallId, setHallId] = useState("");
  const [seats, setSeats] = useState<Seat[]>([]);
  const [layout, setLayout] = useState<Hall | null>(null);
  const [hallForm, setHallForm] = useState<HallForm | null>(null);
  const [seatForm, setSeatForm] = useState<SeatForm | null>(null);
  const [selection, setSelection] = useState<number[]>([]);
  const [confirmation, setConfirmation] = useState<{ label: string; path: string } | null>(null);
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    request<Hall[]>(`/api/admin/halls${cinemaId ? `?cinemaId=${cinemaId}` : ""}`, { signal: abort.signal }, token)
      .then((data) => { if (!abort.signal.aborted) { setHalls(data); setHallId((old) => data.some((hall) => String(hall.id) === old) ? old : String(data[0]?.id ?? "")); } })
      .catch((cause) => { if (!abort.signal.aborted) { setHalls([]); setError(cause instanceof Error ? cause.message : "影厅读取失败"); } })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [cinemaId, reload, token, request]);
  useEffect(() => {
    setSeatForm(null); setSelection([]); setLayout(null); setSeats([]);
    if (view !== "seats" || !hallId) return;
    const abort = new AbortController(); setLoading(true); setError("");
    request<{ hall: Hall; seats: Seat[] }>(`/api/admin/halls/${hallId}/seats`, { signal: abort.signal }, token)
      .then((data) => { if (!abort.signal.aborted) { setLayout(data.hall); setSeats(data.seats); } })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "座位读取失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [hallId, view, reload, token, request]);
  useEffect(() => { setConfirmation(null); setHallForm(null); setSeatForm(null); setNotice(""); }, [view, cinemaId, hallId]);
  const grid = useMemo(() => new Map(seats.map((seat) => [`${seat.row_no}:${seat.column_no}`, seat])), [seats]);

  async function mutate(path: string, method: string, body?: object, success = "已保存") {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await request<{ added?: number }>(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) }, token);
      setHallForm(null); setSeatForm(null); setConfirmation(null); setSelection([]); setReload((value) => value + 1);
      setNotice(result?.added != null ? `已补充 ${result.added} 个座位，现有座位编号和状态已保留。` : success);
      try { await onRefresh(); } catch { setNotice(`${success}；首页数据刷新失败，可稍后刷新。`); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setBusy(false); }
  }
  function saveHall(event: FormEvent) { event.preventDefault(); if (!hallForm) return; const { id, ...body } = hallForm; void mutate(`/api/admin/halls${id ? `/${id}` : ""}`, id ? "PUT" : "POST", body, id ? "影厅已更新" : "影厅和初始座位已创建"); }
  function saveSeat(event: FormEvent) { event.preventDefault(); if (!seatForm) return; const { id, ...body } = seatForm; void mutate(`/api/admin/halls/${hallId}/seats${id ? `/${id}` : ""}`, id ? "PUT" : "POST", body); }
  function editSeat(seat: Seat) { setSeatForm({ id: seat.id, row: seat.row_no, column: seat.column_no, code: seat.seat_code, type: seat.seat_type, status: seat.status }); }
  return <section className="content-width hall-seat-admin"><div className="section-heading"><div><p className="eyebrow">{view === "halls" ? "SCREEN MANAGEMENT" : "SEAT MANAGEMENT"}</p><h2>{view === "halls" ? "影厅管理" : "座位管理"}</h2></div><div className="hall-seat-actions"><button type="button" className="secondary-button" disabled={busy || loading} onClick={() => setReload((value) => value + 1)}>刷新</button>{view === "halls" && <button type="button" className="primary-button" disabled={busy || !cinemas.length} onClick={() => setHallForm({ cinemaId: Number(cinemaId) || cinemas[0].id, name: "", rows: 8, columns: 12, type: "STANDARD", status: "ACTIVE" })}>新增影厅</button>}</div></div>
    <p className="section-note">{view === "halls" ? "新增影厅自动创建座位。已有排期不能改变影院或尺寸，有未结束排期不能停用。" : "选择座位可批量启用或停用，并在右侧编辑。订单关联座位保留编号和位置，锁座中的位置暂不能修改。"}</p>
    <div className="hall-seat-filters"><label>影院<select disabled={busy} value={cinemaId} onChange={(event) => setCinemaId(event.target.value)}><option value="">全部影院</option>{cinemas.map((cinema) => <option key={cinema.id} value={cinema.id}>{cinema.name}</option>)}</select></label>{view === "seats" && <label>影厅<select value={hallId} disabled={busy || !halls.length} onChange={(event) => setHallId(event.target.value)}>{halls.map((hall) => <option key={hall.id} value={hall.id}>{hall.cinema_name} / {hall.name}</option>)}</select></label>}</div>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="hall-seat-error">{error}</p>}
    {confirmation && <div className="hall-seat-confirm" role="alert"><span>确认删除「{confirmation.label}」？关联订单或排期的数据会被保护。</span><button type="button" disabled={busy} onClick={() => void mutate(confirmation.path, "DELETE", undefined, "已删除")}>确认删除</button><button type="button" disabled={busy} onClick={() => setConfirmation(null)}>取消</button></div>}
    {hallForm && <form className="hall-seat-editor" onSubmit={saveHall}><h3>{hallForm.id ? "编辑影厅" : "新建影厅"}</h3><div className="hall-seat-fields"><label>所属影院<select value={hallForm.cinemaId} disabled={busy} onChange={(event) => setHallForm({ ...hallForm, cinemaId: Number(event.target.value) })}>{cinemas.map((cinema) => <option key={cinema.id} value={cinema.id}>{cinema.name}</option>)}</select></label><label>影厅名称<input required maxLength={64} disabled={busy} value={hallForm.name} onChange={(event) => setHallForm({ ...hallForm, name: event.target.value })} /></label>{(["rows", "columns"] as const).map((field) => <label key={field}>{field === "rows" ? "排数" : "每排列数"}<input required type="number" min={1} max={40} step={1} disabled={busy} value={hallForm[field]} onChange={(event) => setHallForm({ ...hallForm, [field]: Number(event.target.value) })} /></label>)}<label>影厅类型<select value={hallForm.type} disabled={busy} onChange={(event) => setHallForm({ ...hallForm, type: event.target.value })}>{Object.entries(hallTypes).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>状态<select value={hallForm.status} disabled={busy} onChange={(event) => setHallForm({ ...hallForm, status: event.target.value })}><option value="ACTIVE">启用</option><option value="INACTIVE">停用</option></select></label></div><small>缩小无排期影厅的尺寸会移除超出新边界的未使用座位；扩大后可到座位管理补齐空位。</small><div className="hall-seat-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setHallForm(null)}>取消</button><button type="submit" className="primary-button" disabled={busy}>保存影厅</button></div></form>}
    {view === "halls" ? loading ? <p role="status">正在读取影厅…</p> : <div className="hall-admin-list">{halls.map((hall) => <article key={hall.id}><div><span>{hall.cinema_name}</span><h3>{hall.name}</h3><p>{hallTypes[hall.hall_type] || hall.hall_type} · {hall.row_count} 排 × {hall.column_count} 列 · {hall.seat_count} 个座位 · {hall.status === "ACTIVE" ? "启用" : "停用"}</p></div><div className="hall-seat-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setHallForm({ id: hall.id, cinemaId: hall.cinema_id, name: hall.name, rows: hall.row_count, columns: hall.column_count, type: hall.hall_type, status: hall.status })}>编辑</button><button type="button" className="secondary-button" disabled={busy} onClick={() => { setHallId(String(hall.id)); onSeats(); }}>管理座位</button><button type="button" className="text-button" disabled={busy || Number(hall.screening_count) > 0} title={Number(hall.screening_count) > 0 ? "有关联排期，无法删除" : "删除影厅及未使用座位"} onClick={() => setConfirmation({ label: hall.name, path: `/api/admin/halls/${hall.id}` })}>删除</button></div></article>)}{!halls.length && <p>当前影院没有影厅，请新增影厅。</p>}</div> : <>
      {layout && <><div className="seat-admin-toolbar"><span>{seats.filter((seat) => seat.status === "AVAILABLE").length} 可用 / {seats.length} 座位 · 已选 {selection.length}</span><div className="hall-seat-actions"><button type="button" className="secondary-button" disabled={busy || loading || !selection.length} onClick={() => void mutate(`/api/admin/halls/${hallId}/seats/batch`, "PUT", { ids: selection, status: "AVAILABLE" })}>启用所选</button><button type="button" className="secondary-button" disabled={busy || loading || !selection.length} onClick={() => void mutate(`/api/admin/halls/${hallId}/seats/batch`, "PUT", { ids: selection, status: "DISABLED" })}>停用所选</button><button type="button" className="secondary-button" disabled={busy || loading} onClick={() => { setSelection([]); setSeatForm(null); }}>清除选择</button><button type="button" className="secondary-button" disabled={busy || loading} onClick={() => void mutate(`/api/admin/halls/${hallId}/seats/fill`, "POST")}>补齐空位</button></div></div><div className="seat-admin-workspace"><div className="seat-admin-map"><div className="seat-admin-screen">银幕方向</div><div className="seat-admin-scroll"><div className="seat-admin-grid" style={{ gridTemplateColumns: `repeat(${layout.column_count}, 42px)` }}>{Array.from({ length: layout.row_count }, (_,row) => Array.from({ length: layout.column_count }, (_,column) => {
        const key = `${row+1}:${column+1}`, seat = grid.get(key);
        return <button key={key} type="button" disabled={busy || loading} className={`${seat ? seat.status === "AVAILABLE" ? "available" : "disabled-seat" : "missing"} ${seat && selection.includes(seat.id) ? "selected" : ""}`} aria-pressed={seat ? selection.includes(seat.id) : false} aria-label={`${row+1} 排 ${column+1} 座，${seat?.seat_code || "空位"}，${seat?.status === "AVAILABLE" ? "可用" : seat ? "停用" : "点击新增"}`} title={seat ? `${seat.seat_code} · ${seatTypes[seat.seat_type] || seat.seat_type}` : "空位：点击创建"} onClick={() => { if (seat) { setSelection((old) => old.includes(seat.id) ? old.filter((id) => id !== seat.id) : [...old,seat.id]); editSeat(seat); } else setSeatForm({ row: row+1, column: column+1, code: `R${row+1}C${column+1}`, type: "STANDARD", status: "AVAILABLE" }); }} onDoubleClick={() => { if (seat) editSeat(seat); }}>{seat ? `${row+1}-${column+1}` : "+"}</button>;
      }))}</div></div><p className="seat-admin-legend"><span>□ 可用</span><span>▧ 停用</span><span>■ 已选</span><span>＋ 缺失位置</span></p></div>
      {seatForm ? <form className="seat-admin-inspector" onSubmit={saveSeat}><h3>{seatForm.id ? "编辑座位" : "新增座位"}</h3><div className="hall-seat-fields">{(["row","column"] as const).map((field) => <label key={field}>{field === "row" ? "排" : "列"}<input required min={1} max={field === "row" ? layout.row_count : layout.column_count} step={1} type="number" disabled={busy} value={seatForm[field]} onChange={(event) => setSeatForm({ ...seatForm,[field]:Number(event.target.value) })} /></label>)}<label>座位编号<input required maxLength={32} disabled={busy} value={seatForm.code} onChange={(event) => setSeatForm({ ...seatForm,code:event.target.value })} /></label><label>类型<select disabled={busy} value={seatForm.type} onChange={(event) => setSeatForm({ ...seatForm,type:event.target.value })}>{Object.entries(seatTypes).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>状态<select disabled={busy} value={seatForm.status} onChange={(event) => setSeatForm({ ...seatForm,status:event.target.value })}><option value="AVAILABLE">可用</option><option value="DISABLED">停用</option></select></label></div><small>座位类型只作标识，票价仍由场次决定。</small><div className="hall-seat-actions"><button className="primary-button" disabled={busy} type="submit">保存座位</button>{seatForm.id && <button className="text-button" disabled={busy || !!seats.find((seat) => seat.id === seatForm.id)?.has_orders} type="button" onClick={() => setConfirmation({ label: seatForm.code, path: `/api/admin/halls/${hallId}/seats/${seatForm.id}` })}>删除</button>}</div></form> : <aside className="seat-admin-inspector"><h3>选择一个位置</h3><p>点击现有座位查看并修改编号、类型或状态；点击空位创建座位。</p></aside>}</div></>}
      {loading && <p role="status">正在读取布局…</p>}{!loading && !hallId && <p>请先创建影厅，再维护座位。</p>}
    </>}
  </section>;
}
