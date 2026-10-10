import { useEffect, useRef, useState, type FormEvent } from "react";
import { invalidateToken } from "../auth/client";
import type { ApiRequest } from "./movie-save";
import "./sales-report.css";

type Choice = { id: number; name?: string; title?: string };
type Metadata = { from: string; to: string; timeZone: string; dataMode: string; generatedAt: string };
type SalesRow = { date: string; cinemaId: number; cinemaName: string; movieId: number; movieTitle: string; paidAmount: string; refundAmount: string; grossTicketCount: number };
type Sales = { metadata: Metadata; summary: { paidAmount: string; refundAmount: string; netAmount: string; grossTicketCount: number }; items: SalesRow[] };
type OccupancyRow = { screeningId: number; date: string; startTime: string; cinemaName: string; movieTitle: string; hallName: string; effectiveTicketCount: number; sellableSeatCount: number | null; capacitySource: string; occupancyRate: number | null };
type Occupancy = { metadata: Metadata; summary: { screeningCount: number; effectiveTicketCount: number; knownSellableSeatCount: number; unknownCapacityScreenings: number; occupancyRate: number | null }; items: OccupancyRow[]; popular: OccupancyRow[] };
type Filters = { from: string; to: string; cinemaId: string; movieId: string };
const money = (value: string) => new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value));
const rate = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const dateTime = (value: string) => value.replace("T", " ").slice(0, 16);

function initialFilters(): Filters {
  const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
  const start = new Date(`${today}T12:00:00+08:00`);
  start.setUTCDate(start.getUTCDate() - 6);
  return { from: new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(start), to: today, cinemaId: "", movieId: "" };
}

function query(filters: Filters) {
  const result = new URLSearchParams({ from: filters.from, to: filters.to });
  if (filters.cinemaId) result.set("cinemaId", filters.cinemaId);
  if (filters.movieId) result.set("movieId", filters.movieId);
  return result.toString();
}

function OccupancyTable({ rows, emptyText = "当前筛选范围内没有场次" }: { rows: OccupancyRow[]; emptyText?: string }) {
  return <div className="report-table-wrap"><table className="report-table"><thead><tr><th>场次 / 放映时间</th><th>影院 / 影厅</th><th>影片</th><th>有效票数</th><th>可售容量</th><th>上座率</th></tr></thead><tbody>
    {rows.map((row) => <tr key={row.screeningId}><td>#{row.screeningId}<small>{dateTime(row.startTime)}</small></td><td>{row.cinemaName}<small>{row.hallName}</small></td><td>{row.movieTitle}</td><td>{row.effectiveTicketCount}</td><td>{row.sellableSeatCount ?? "未知"}<small>{row.capacitySource === "UNKNOWN" ? "缺少历史快照" : "首次锁座快照"}</small></td><td>{rate(row.occupancyRate)}</td></tr>)}
    {!rows.length && <tr><td colSpan={6} className="report-empty">{emptyText}</td></tr>}
  </tbody></table></div>;
}

export default function SalesReportAdmin({ request, token, cinemas, movies }: {
  request: ApiRequest; token: string; cinemas: Choice[]; movies: Choice[];
}) {
  const [draft, setDraft] = useState<Filters>(initialFilters);
  const [applied, setApplied] = useState<Filters>(draft);
  const [sales, setSales] = useState<Sales | null>(null);
  const [occupancy, setOccupancy] = useState<Occupancy | null>(null);
  const [tab, setTab] = useState<"sales" | "occupancy">("sales");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [reload, setReload] = useState(0);
  const downloads = useRef<AbortController | null>(null);
  useEffect(() => () => downloads.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setExportError(""); setSales(null); setOccupancy(null);
    downloads.current?.abort(); setExporting(false);
    Promise.all([
      request<Sales>(`/api/admin/reports/sales?${query(applied)}`, { signal: controller.signal }, token),
      request<Occupancy>(`/api/admin/reports/occupancy?${query(applied)}`, { signal: controller.signal }, token),
    ]).then(([nextSales, nextOccupancy]) => {
      if (!controller.signal.aborted) { setSales(nextSales); setOccupancy(nextOccupancy); }
    }).catch((cause) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "报表读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [applied, reload, request, token]);

  function apply(event: FormEvent) {
    event.preventDefault();
    const days = (Date.parse(`${draft.to}T00:00:00+08:00`) - Date.parse(`${draft.from}T00:00:00+08:00`)) / 86400000;
    if (!Number.isFinite(days) || days < 0 || days >= 31) { setError("请选择有效日期范围，起止日期均包含，最多查询 31 天。"); return; }
    setApplied({ ...draft });
  }

  async function download() {
    const controller = new AbortController();
    downloads.current?.abort(); downloads.current = controller;
    setExporting(true); setExportError("");
    try {
      const response = await fetch(`/api/admin/reports/${tab}/export?${query(applied)}`, {
        headers: { "X-Auth-Token": token }, cache: "no-store", signal: controller.signal,
      });
      if (response.status === 401) invalidateToken(token);
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { message?: string } | null;
        throw new Error(payload?.message || "明细导出失败，请重试");
      }
      const blob = await response.blob();
      controller.signal.throwIfAborted();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `${tab}-${applied.from}-${applied.to}.csv`;
      link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      if (!controller.signal.aborted) setExportError(cause instanceof Error ? cause.message : "明细导出失败");
    } finally { if (!controller.signal.aborted) setExporting(false); }
  }

  return <section className="content-width sales-report-admin">
    <div className="section-heading"><div><p className="eyebrow">TICKETING REPORTS</p><h2>经营报表</h2></div><span className="report-simulation">模拟支付数据</span></div>
    <p className="section-note">所有日期均按北京时间统计。当前支付与退款为系统模拟记录。</p>
    <form className="report-filters" onSubmit={apply}>
      <label>开始日期<input type="date" required value={draft.from} onChange={(event) => setDraft({ ...draft, from: event.target.value })} /></label>
      <label>结束日期<input type="date" required value={draft.to} min={draft.from} onChange={(event) => setDraft({ ...draft, to: event.target.value })} /></label>
      <label>影院<select value={draft.cinemaId} onChange={(event) => setDraft({ ...draft, cinemaId: event.target.value })}><option value="">全部影院</option>{cinemas.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>影片<select value={draft.movieId} onChange={(event) => setDraft({ ...draft, movieId: event.target.value })}><option value="">全部影片</option>{movies.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      <button type="submit" className="primary-button">查询报表</button><button type="button" className="secondary-button" disabled={loading} onClick={() => setReload((value) => value + 1)}>刷新</button>
    </form>
    <div className="report-tabs" role="group" aria-label="报表类型"><button type="button" className={tab === "sales" ? "active" : ""} aria-pressed={tab === "sales"} onClick={() => setTab("sales")}>销售与退款</button><button type="button" className={tab === "occupancy" ? "active" : ""} aria-pressed={tab === "occupancy"} onClick={() => setTab("occupancy")}>场次与上座率</button></div>
    {error && <p role="alert" className="report-error">{error}</p>}
    {loading && <p role="status" className="report-state">正在汇总经营数据…</p>}
    {!loading && sales && occupancy && <>
      <div className="report-toolbar"><span>{applied.from} 至 {applied.to}（含首尾日） · 北京时间</span><button type="button" className="secondary-button" disabled={exporting} onClick={() => void download()}>{exporting ? "正在导出…" : "导出当前明细 CSV"}</button></div>
      {exportError && <p role="alert" className="report-error">{exportError}</p>}
      {tab === "sales" ? <>
        <div className="report-metrics" aria-label="销售汇总"><div><span>已支付金额 · 支付日</span><strong>{money(sales.summary.paidAmount)}</strong></div><div><span>退款金额 · 退款处理日</span><strong>{money(sales.summary.refundAmount)}</strong></div><div><span>毛售出票数 · 支付日</span><strong>{sales.summary.grossTicketCount}<small> 张</small></strong></div></div>
        <p className="report-explanation">窗口净额 {money(sales.summary.netAmount)} = 范围内支付金额 − 范围内退款金额。退款计入实际处理日，可能来自此前支付的订单；毛售出票数包含之后退票的票项。</p>
        <div className="report-table-wrap"><table className="report-table"><thead><tr><th>统计日期</th><th>影院</th><th>影片</th><th>已支付金额</th><th>退款金额</th><th>毛售出票数</th></tr></thead><tbody>{sales.items.map((row) => <tr key={`${row.date}:${row.cinemaId}:${row.movieId}`}><td>{row.date}</td><td>{row.cinemaName}</td><td>{row.movieTitle}</td><td>{money(row.paidAmount)}</td><td>{money(row.refundAmount)}</td><td>{row.grossTicketCount}</td></tr>)}{!sales.items.length && <tr><td colSpan={6} className="report-empty">当前日期范围内没有支付或退款记录</td></tr>}</tbody></table></div>
      </> : <>
        <div className="report-metrics" aria-label="场次汇总"><div><span>有效票数 · 放映日</span><strong>{occupancy.summary.effectiveTicketCount}<small> 张</small></strong></div><div><span>场次总数 · 放映日</span><strong>{occupancy.summary.screeningCount}</strong></div><div><span>整体上座率 · 可售容量加权</span><strong>{rate(occupancy.summary.occupancyRate)}</strong></div></div>
        <p className="report-explanation">上座率 = 有效票数 ÷ 场次可售容量；已验票仍计为有效票，不等同实际到场率。整体按容量加权，取消场次不纳入。<br />{occupancy.summary.unknownCapacityScreenings > 0 ? `${occupancy.summary.unknownCapacityScreenings} 个场次缺少历史容量快照，整体上座率暂不展示。` : "可售容量在首次锁座时固定，排除停用座位；每个座位记录计一张票。"}</p>
        <h3>热门场次 <small>按有效票数、上座率降序 · 前 10 场</small></h3><OccupancyTable rows={occupancy.popular} emptyText="当前筛选范围内没有已售票的热门场次" />
        <h3>全部场次</h3><OccupancyTable rows={occupancy.items} />
      </>}
      <p className="report-updated">销售数据生成于 {dateTime(sales.metadata.generatedAt)}；场次数据生成于 {dateTime(occupancy.metadata.generatedAt)}。刷新可获取最新支付、退款与出票状态。</p>
    </>}
  </section>;
}
