import { useEffect, useState, type FormEvent } from "react";
import type { ApiRequest } from "../admin/movie-save";
import { isTrue, reportReasonLabels, reviewStatusLabels, reviewTime, type Review } from "./review-business";

type AuthProps = { request: ApiRequest; token?: string; userId?: number; onLogin: () => void };
type Reply = { id: number; user_id: number; username: string; content: string; status: string; official: boolean | number; moderation_note?: string; updated_at: string };
type ReplyList = { items: Reply[]; total: number; page: number };

export function ReportButton({ path, request, token, onLogin }: { path: string } & Omit<AuthProps, "userId">) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("ABUSE");
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!token || busy) return;
    setBusy(true); setMessage("");
    try {
      await request(path, { method: "POST", body: JSON.stringify({ reason, content: content.trim() }) }, token);
      setOpen(false); setMessage("举报已提交。同一版本内容的重复举报只保留一条记录。"); setContent("");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "举报提交失败"); }
    finally { setBusy(false); }
  }
  return <div className="review-report">
    <button className="text-button" type="button" aria-expanded={open} disabled={busy} onClick={() => token ? setOpen(!open) : onLogin()}>举报</button>
    {open && <form onSubmit={(event) => void submit(event)} className="review-inline-form">
      <label>举报原因<select value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)}>{Object.entries(reportReasonLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>补充说明<textarea rows={2} maxLength={1000} required={reason === "OTHER"} disabled={busy} value={content} onChange={(event) => setContent(event.target.value)} placeholder="说明具体问题，便于管理员核实" /></label>
      <div className="review-action-row"><button type="button" className="text-button" disabled={busy} onClick={() => setOpen(false)}>取消</button><button className="secondary-button" disabled={busy} type="submit">{busy ? "提交中…" : "提交举报"}</button></div>
    </form>}
    {message && <p role="status" className="review-message">{message}</p>}
  </div>;
}

function Replies({ path, request, token, userId, onLogin }: { path: string } & AuthProps) {
  const [data, setData] = useState<ReplyList | null>(null);
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState(0);
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    const abort = new AbortController(); setLoading(true); setError("");
    request<ReplyList>(`${path}?page=${page}`, { signal: abort.signal }, token)
      .then((value) => { if (!abort.signal.aborted) setData(value); })
      .catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "回复读取失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [path, page, request, token, version]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!token || busy || !content.trim()) return;
    setBusy(true); setMessage("");
    try {
      await request(path, { method: "POST", body: JSON.stringify({ content: content.trim() }) }, token);
      setContent(""); setPage(1); setVersion((value) => value + 1); setMessage("回复已提交，审核通过后公开。可在我的回复中查看状态。");
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "回复失败"); }
    finally { setBusy(false); }
  }
  async function remove(id: number) {
    if (!token || busy) return;
    setBusy(true); setMessage("");
    try { await request(`${path}/${id}`, { method: "DELETE" }, token); setVersion((value) => value + 1); setMessage("回复已删除。"); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : "删除失败"); }
    finally { setBusy(false); }
  }
  return <section className="review-replies" aria-label="影评回复">
    <div className="review-action-row"><strong>回复讨论</strong><button className="text-button" disabled={loading} type="button" onClick={() => setVersion((value) => value + 1)}>刷新回复</button></div>
    {loading && <p role="status">正在读取回复…</p>}{error && <p role="alert">{error}</p>}
    {!error && data?.items.map((reply) => <div className="review-reply-item" key={reply.id}>
      <header><strong>{reply.username}</strong>{isTrue(reply.official) && <span className="review-badge">管理员</span>}<time>{reviewTime(reply.updated_at)}</time></header>
      {reply.status !== "APPROVED" && <small>{reviewStatusLabels[reply.status]} · 仅自己可见{reply.moderation_note ? ` · ${reply.moderation_note}` : ""}</small>}
      <p>{reply.content}</p>
      {reply.user_id === userId ? <button type="button" disabled={busy} className="text-button" onClick={() => void remove(reply.id)}>删除我的回复</button> : <ReportButton path={`${path}/${reply.id}/reports`} request={request} token={token} onLogin={onLogin} />}
    </div>)}
    {!loading && !error && data?.total === 0 && <p className="review-empty">还没有回复。</p>}
    {data && data.total > 10 && <div className="review-pagination"><button className="text-button" type="button" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {Math.ceil(data.total / 10)}</span><button className="text-button" type="button" disabled={loading || page * 10 >= data.total} onClick={() => setPage(page + 1)}>下一页</button></div>}
    {token ? <form className="review-inline-form" onSubmit={(event) => void submit(event)}><label>发表回复<textarea maxLength={1000} required rows={2} value={content} disabled={busy} onChange={(event) => setContent(event.target.value)} placeholder="文明讨论，回复不影响影片评分" /></label><div className="review-action-row"><small>回复需审核，每条影评最多保留 20 条本人回复。</small><button type="submit" className="secondary-button" disabled={busy || Boolean(error)}>{busy ? "提交中…" : "提交回复"}</button></div></form> : <button type="button" className="text-button" onClick={onLogin}>登录后参与讨论</button>}
    {message && <p className="review-message" role="status">{message}</p>}
  </section>;
}

export default function ReviewInteractions({ movieId, review, request, token, userId, onLogin }: { movieId: number; review: Review } & AuthProps) {
  const [liked, setLiked] = useState(isTrue(review.liked));
  const [likeCount, setLikeCount] = useState(Number(review.likeCount));
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const path = `/api/movies/${movieId}/reviews/${review.id}`;
  useEffect(() => { setLiked(isTrue(review.liked)); setLikeCount(Number(review.likeCount)); }, [review.liked, review.likeCount, token]);
  async function like() {
    if (!token) { onLogin(); return; }
    if (busy) return;
    setBusy(true); setError("");
    try { await request(`${path}/like`, { method: "PUT", body: JSON.stringify({ liked: !liked }) }, token); setLikeCount((value) => value + (liked ? -1 : 1)); setLiked(!liked); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "点赞失败"); }
    finally { setBusy(false); }
  }
  return <div className="review-interactions">
    <div className="review-action-row"><button type="button" className={`text-button${liked ? " liked" : ""}`} aria-pressed={liked} disabled={busy || review.user_id === userId} title={review.user_id === userId ? "不能给自己的影评点赞" : ""} onClick={() => void like()}>{liked ? "已点赞" : "点赞"} · {likeCount}</button><button type="button" className="text-button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "收起回复" : `回复 · ${review.replyCount}`}</button></div>
    {review.user_id !== userId && <ReportButton path={`${path}/reports`} request={request} token={token} onLogin={onLogin} />}
    {error && <p role="alert">{error}</p>}
    {open && <Replies path={`${path}/replies`} request={request} token={token} userId={userId} onLogin={onLogin} />}
  </div>;
}
