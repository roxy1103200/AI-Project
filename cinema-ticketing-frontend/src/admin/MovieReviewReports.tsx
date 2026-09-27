import { useEffect, useState } from "react";
import type { ApiRequest } from "./movie-save";
import { reportReasonLabels, reviewStatusLabels, reviewTime } from "../home/review-business";

type Report = {
  id: number; target_kind: string; target_id: number; target_revision: number; current_revision: number; current_status: string;
  reporter_name: string; movie_title: string; reported_content: string; current_content: string; reason: string; content: string;
  status: string; resolution_note: string; created_at: string;
};
type Listing = { items: Report[]; total: number };
const statuses: Record<string, string> = { OPEN: "待处理", RESOLVED: "已处理", DISMISSED: "已驳回" };

function ReportCard({ item, request, token, onDone }: { item: Report; request: ApiRequest; token: string; onDone: (message: string) => void }) {
  const [note, setNote] = useState(item.resolution_note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function resolve(status: string, hideTarget: boolean) {
    setBusy(true); setError("");
    try {
      await request(`/api/admin/movie-reviews/reports/${item.id}`, { method: "PUT", body: JSON.stringify({ status, note: note.trim(), hideTarget, revision: item.current_revision }) }, token);
      onDone(hideTarget ? "内容已隐藏，举报已处理。" : status === "DISMISSED" ? "举报已驳回，处理记录已保留。" : "举报已标记处理，内容状态未变更。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "处理举报失败"); }
    finally { setBusy(false); }
  }
  return <article className="moderation-card">
    <header><div className="moderation-tags"><span>{statuses[item.status]}</span><span>{item.target_kind === "REVIEW" ? "影评" : "回复"} #{item.target_id}</span><span>{reviewStatusLabels[item.current_status]}</span></div><time>{reviewTime(item.created_at)}</time></header>
    <h3>{item.movie_title}</h3><p className="moderation-meta">举报人：{item.reporter_name} · {reportReasonLabels[item.reason] || item.reason}</p>
    <blockquote>{item.reported_content}</blockquote>{item.content && <p>举报说明：{item.content}</p>}
    {item.target_revision !== item.current_revision && <details><summary>被举报内容已有后续变化，查看当前内容</summary><p>{item.current_content}</p><small>隐藏操作将针对上面展示的当前内容。</small></details>}
    {item.status === "OPEN" ? <><label>处理说明<textarea value={note} maxLength={1000} rows={2} disabled={busy} onChange={(event) => setNote(event.target.value)} placeholder="说明核实结果，隐藏原因会向内容作者展示" /></label><div className="moderation-actions"><button type="button" className="secondary-button" disabled={busy || !note.trim()} onClick={() => void resolve("DISMISSED", false)}>驳回举报</button><button type="button" className="secondary-button" disabled={busy || !note.trim()} onClick={() => void resolve("RESOLVED", false)}>标记已处理</button><button type="button" className="primary-button" disabled={busy || !note.trim() || item.current_status === "HIDDEN"} onClick={() => void resolve("RESOLVED", true)}>{busy ? "处理中…" : "隐藏内容并处理举报"}</button></div></> : <p>处理说明：{item.resolution_note}</p>}
    {error && <p role="alert">{error}</p>}
  </article>;
}

export default function MovieReviewReports({ request, token, onChanged }: { request: ApiRequest; token: string; onChanged: () => Promise<void> }) {
  const [status, setStatus] = useState("OPEN");
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [data, setData] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError(""); setData(null);
    request<Listing>(`/api/admin/movie-reviews/reports?${new URLSearchParams({ status, page: String(page) })}`, { signal: abort.signal }, token)
      .then((value) => { if (!abort.signal.aborted) setData(value); })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "举报读取失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [request, token, status, page, version]);
  function done(value: string) {
    setMessage(value); setVersion((current) => current + 1);
    void onChanged().catch(() => setMessage(`${value} 片单评分刷新失败，请刷新首页。`));
  }
  return <><div className="moderation-filters"><label>举报状态<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">全部举报</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><button type="button" className="secondary-button" disabled={loading} onClick={() => setVersion((value) => value + 1)}>刷新举报</button></div>
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}{loading && <p role="status">正在读取举报…</p>}
    {data?.items.map((item) => <ReportCard key={`${item.id}:${version}`} item={item} request={request} token={token} onDone={done} />)}
    {!loading && !error && data?.total === 0 && <p className="moderation-empty">当前没有符合条件的举报。</p>}
    {data && <div className="moderation-actions"><button type="button" className="secondary-button" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(data.total / 20))} · {data.total} 条</span><button type="button" className="secondary-button" disabled={loading || page * 20 >= data.total} onClick={() => setPage(page + 1)}>下一页</button></div>}
  </>;
}
