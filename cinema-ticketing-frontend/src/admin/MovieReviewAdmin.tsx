import { useEffect, useState, type FormEvent } from "react";
import type { ApiRequest } from "./movie-save";
import { isTrue, reviewStatusLabels, reviewTime } from "../home/review-business";
import MovieReviewReports from "./MovieReviewReports";
import "./movie-reviews-admin.css";

type Content = {
  kind: string; id: number; review_id: number; user_id: number; username: string; movie_title: string; rating?: number;
  content: string; status: string; revision: number; moderation_note: string; updated_at: string; publicly_visible: boolean | number; open_reports: number;
};
type History = { id: number; from_status: string; to_status: string; note: string; admin_name: string | null; created_at: string; content_snapshot: string; target_revision: number };
type Listing = { items: Content[]; summary: { total: number; pending: number; hidden: number; openReports: number } };

function ContentCard({ item, request, token, onDone }: { item: Content; request: ApiRequest; token: string; onDone: (message: string) => void }) {
  const [note, setNote] = useState(item.moderation_note);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<History[] | null>(null);
  async function moderate(status: string) {
    setBusy(true); setError("");
    try {
      await request(`/api/admin/movie-reviews/${item.kind}/${item.id}`, { method: "PUT", body: JSON.stringify({ status, note: note.trim(), revision: item.revision }) }, token);
      onDone(`已${status === "APPROVED" ? "审核通过" : status === "REJECTED" ? "拒绝" : status === "HIDDEN" ? "隐藏" : "转回待审核"}该${item.kind === "REVIEW" ? "影评" : "回复"}。`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "审核失败"); }
    finally { setBusy(false); }
  }
  async function loadHistory() {
    setBusy(true); setError("");
    try { setHistory(await request<History[]>(`/api/admin/movie-reviews/${item.kind}/${item.id}/history`, {}, token)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "处理记录读取失败"); }
    finally { setBusy(false); }
  }
  return <article className="moderation-card">
    <header><div className="moderation-tags"><span>{reviewStatusLabels[item.status]}</span><span>{item.kind === "REVIEW" ? "影评" : "回复"} #{item.id}</span>{Number(item.open_reports) > 0 && <span className="warning">{item.open_reports} 条待处理举报</span>}</div><time>{reviewTime(item.updated_at)}</time></header>
    <h3>{item.movie_title}{item.rating != null ? ` · ${item.rating} 星` : ""}</h3><p className="moderation-meta">作者：{item.username}{item.kind === "REPLY" ? ` · 所属影评 #${item.review_id}` : ""} · {isTrue(item.publicly_visible) ? "公开展示中" : "未公开"}</p>
    {item.status === "APPROVED" && !isTrue(item.publicly_visible) && <p className="moderation-meta">审核已通过，作者观影资格或原影评公开状态不满足。</p>}
    <p className="moderation-body">{item.content}</p>
    <label>审核说明（通过可留空）<textarea rows={2} maxLength={1000} value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} placeholder="通过无需说明；拒绝或隐藏需填写 1～1000 字原因，原因会向作者展示" /></label>
    <p className="moderation-meta">通过无需最低字数；拒绝或隐藏至少填写 1 个非空白字。当前 {note.trim().length} / 1000 字。</p>
    <div className="moderation-actions">
      <button className="text-button" type="button" disabled={busy} onClick={() => void loadHistory()}>查看处理记录</button>
      {item.status !== "PENDING" && <button className="secondary-button" type="button" disabled={busy} onClick={() => void moderate("PENDING")}>转回待审核</button>}
      {item.status !== "REJECTED" && <button className="secondary-button" type="button" disabled={busy || !note.trim()} onClick={() => void moderate("REJECTED")}>拒绝</button>}
      {item.status !== "HIDDEN" && <button className="secondary-button" type="button" disabled={busy || !note.trim()} onClick={() => void moderate("HIDDEN")}>隐藏</button>}
      {item.status !== "APPROVED" && <button className="primary-button" type="button" disabled={busy} onClick={() => void moderate("APPROVED")}>{item.status === "HIDDEN" ? "恢复并通过审核" : "审核通过"}</button>}
    </div>
    {history && <div className="moderation-history"><h4>最近处理记录</h4>{history.length === 0 ? <p>尚无管理员处理记录。</p> : history.map((record) => <details key={record.id}><summary>{reviewTime(record.created_at)} · {record.admin_name || "管理员"} · {reviewStatusLabels[record.from_status]} → {reviewStatusLabels[record.to_status]}</summary><p>{record.note || "未填写说明"}</p><p>当时内容：{record.content_snapshot}</p></details>)}</div>}
    {error && <p role="alert">{error}</p>}
  </article>;
}

export default function MovieReviewAdmin({ request, token, onChanged }: { request: ApiRequest; token: string; onChanged: () => Promise<void> }) {
  const [tab, setTab] = useState("REVIEW");
  const [status, setStatus] = useState("PENDING");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (tab === "REPORTS") return;
    const abort = new AbortController(); setLoading(true); setError(""); setData(null);
    const params = new URLSearchParams({ kind: tab, status, query, page: String(page) });
    request<Listing>(`/api/admin/movie-reviews?${params}`, { signal: abort.signal }, token)
      .then((value) => { if (!abort.signal.aborted) setData(value); })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "影评读取失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [tab, status, query, page, version, request, token]);
  function search(event: FormEvent) { event.preventDefault(); setQuery(draft.trim()); setPage(1); }
  function done(value: string) {
    setMessage(value); setVersion((current) => current + 1);
    void onChanged().catch(() => setMessage(`${value} 片单评分刷新失败，请刷新首页。`));
  }
  return <section className="content-width movie-review-admin"><div className="section-heading"><div><p className="eyebrow">COMMUNITY MODERATION</p><h2>影评管理</h2></div></div><p className="section-note">核对内容后即可通过，不要求审核说明。存在辱骂、广告、违法违规等问题时，拒绝或隐藏并说明原因。隐藏影评后，其回复一并停止公开，评分同步排除；个人影评仍需观影资格，所有审核保留操作记录。</p>
    <div className="moderation-tabs" role="tablist" aria-label="影评管理分类">{Object.entries({ REVIEW: "影评审核", REPLY: "回复审核", REPORTS: "举报处理" }).map(([key, label]) => <button type="button" role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} key={key} onClick={() => { setTab(key); setPage(1); setMessage(""); }}>{label}</button>)}</div>
    {tab === "REPORTS" ? <MovieReviewReports request={request} token={token} onChanged={onChanged} /> : <>
      <form className="moderation-filters" onSubmit={search}><label>审核状态<select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">全部状态</option>{Object.entries(reviewStatusLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="moderation-search">影片 / 作者 / 内容<input maxLength={120} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="输入关键词" /></label><button className="secondary-button" type="submit">搜索</button><button className="text-button" type="button" disabled={loading} onClick={() => setVersion((value) => value + 1)}>刷新</button></form>
      {data && <div className="moderation-summary"><span>记录 {data.summary.total}</span><span>待审核 {data.summary.pending}</span><span>已隐藏 {data.summary.hidden}</span><span>待处理举报 {data.summary.openReports}</span></div>}
      {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}{loading && <p role="status">正在读取影评…</p>}
      {data?.items.map((item) => <ContentCard key={`${item.kind}:${item.id}:${item.revision}`} item={item} request={request} token={token} onDone={done} />)}
      {!loading && !error && data?.summary.total === 0 && <p className="moderation-empty">当前没有符合条件的内容。</p>}
      {data && <div className="moderation-actions"><button className="secondary-button" type="button" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(data.summary.total / 20))}</span><button className="secondary-button" type="button" disabled={loading || page * 20 >= data.summary.total} onClick={() => setPage(page + 1)}>下一页</button></div>}
    </>}
  </section>;
}
