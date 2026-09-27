import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ApiRequest } from "../admin/movie-save";
import ReviewInteractions from "./ReviewInteractions";
import { isTrue, reviewStatusLabels, reviewTime, type OwnReply, type Review } from "./review-business";
import "./reviews.css";

type OwnReview = { id: number; rating: number; content: string; status: string; moderation_note: string; publiclyVisible: boolean | number };
type Reviews = { reviewCount: number; averageRating: number | string | null; reviews: Review[]; ownReview?: OwnReview | null; ownReplies?: OwnReply[]; page: number; canReview: boolean; eligibilityReason: string };
type Props = { movieId: number; token?: string; userId?: number; request: ApiRequest; onLogin: () => void; onChanged: () => Promise<void> };

export default function MovieReviews({ movieId, token, userId, request, onLogin, onChanged }: Props) {
  const [data, setData] = useState<Reviews | null>(null);
  const [page, setPage] = useState(1);
  const [rating, setRating] = useState(0);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  const ownLoaded = useRef(false);
  useEffect(() => { ownLoaded.current = false; setRating(0); setContent(""); setPage(1); setData(null); setMessage(""); }, [movieId, token]);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true); setError("");
    request<Reviews>(`/api/movies/${movieId}/reviews?page=${page}`, { signal: abort.signal }, token)
      .then((value) => {
        if (abort.signal.aborted) return;
        setData(value);
        if (!ownLoaded.current) { setRating(value.ownReview?.rating ?? 0); setContent(value.ownReview?.content ?? ""); ownLoaded.current = true; }
      })
      .catch((failure: unknown) => { if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : "评价读取失败"); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [movieId, token, page, request, version]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!token || busy || !data?.canReview) return;
    if (rating < 1 || !content.trim()) { setMessage("请选择星级并填写评论。"); return; }
    setBusy(true); setMessage("");
    try {
      await request(`/api/movies/${movieId}/reviews`, { method: "PUT", body: JSON.stringify({ rating, content: content.trim() }) }, token);
      setPage(1); setVersion((value) => value + 1); setMessage("评价已提交，审核通过后公开并计入评分；修改后需重新审核。");
      try { await onChanged(); } catch { setMessage("评价已提交待审核，片单评分刷新失败，请稍后刷新。"); }
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "评价保存失败"); }
    finally { setBusy(false); }
  }
  async function removeReply(reply: OwnReply) {
    if (!token || busy) return;
    setBusy(true); setMessage("");
    try { await request(`/api/movies/${movieId}/reviews/${reply.review_id}/replies/${reply.id}`, { method: "DELETE" }, token); setVersion((value) => value + 1); setMessage("回复已删除。"); }
    catch (failure) { setMessage(failure instanceof Error ? failure.message : "删除回复失败"); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!token || busy) return;
    setBusy(true); setMessage("");
    try {
      await request(`/api/movies/${movieId}/reviews`, { method: "DELETE" }, token);
      setRating(0); setContent(""); setPage(1); setVersion((value) => value + 1); setMessage("评价已删除。");
      try { await onChanged(); } catch { setMessage("评价已删除，片单评分刷新失败，请稍后刷新。"); }
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "删除失败"); }
    finally { setBusy(false); }
  }
  return <section className="movie-reviews" aria-labelledby="reviews-title">
    <div className="reviews-heading"><h3 id="reviews-title">观众评论与评分</h3><span>{data && data.reviewCount > 0 ? `★ ${Number(data.averageRating).toFixed(1)} / 5 · ${data.reviewCount} 条评价` : "暂无评分"}</span></div>
    <div className="review-action-row"><small>购票且场次结束或已验票后可评价，审核通过后公开。</small><button className="text-button" type="button" disabled={loading || busy} onClick={() => setVersion((value) => value + 1)}>刷新评论</button></div>
    {data?.ownReview && <div className="review-own-status"><strong>我的影评 · {reviewStatusLabels[data.ownReview.status]}</strong>{data.ownReview.moderation_note && <p>处理说明：{data.ownReview.moderation_note}</p>}{data.ownReview.status === "APPROVED" && !isTrue(data.ownReview.publiclyVisible) && <p>已通过审核，当前观影资格不满足，暂不公开。</p>}{(!data.canReview || data.ownReview.status === "HIDDEN") && <p>{"★".repeat(data.ownReview.rating)} · {data.ownReview.content}</p>}</div>}
    {token && data?.canReview && data.ownReview?.status !== "HIDDEN" ? <form className="review-form" onSubmit={(event) => void save(event)}>
      <div className="review-stars" role="group" aria-label="选择评分">{[1, 2, 3, 4, 5].map((star) => <button key={star} type="button" disabled={busy} aria-label={`${star} 星`} aria-pressed={rating === star} className={star <= rating ? "chosen" : ""} onClick={() => setRating(star)}>★</button>)}<span>{rating ? `${rating} / 5` : "选择星级"}</span></div>
      <label><span className="sr-only">影片评论</span><textarea required maxLength={1000} rows={3} disabled={busy} value={content} onChange={(event) => setContent(event.target.value)} placeholder="分享你的观影感受（最多 1000 字）" /></label>
      <div className="review-form-actions"><small>观影资格已验证 · 每部影片一条 · 修改后重新审核。</small>{data?.ownReview && <button className="text-button" disabled={busy} type="button" onClick={() => void remove()}>删除我的评价</button>}<button className="secondary-button" disabled={busy} type="submit">{busy ? "处理中…" : data?.ownReview ? "修改并提交审核" : "提交影评审核"}</button></div>
    </form> : token ? <div className="review-login"><p>{loading ? "正在确认观影资格…" : data?.ownReview?.status === "HIDDEN" ? "影评已被隐藏，请联系影院处理。" : data?.eligibilityReason || "暂时无法确认观影资格，请刷新重试。"}</p>{data?.ownReview && <button className="text-button" disabled={busy} type="button" onClick={() => void remove()}>删除我的评价</button>}</div> : <p className="review-login">登录并购票，场次结束或验票后可以评分和评论。<button className="text-button" type="button" onClick={onLogin}>登录</button></p>}
    {data?.ownReplies && data.ownReplies.length > 0 && <details className="review-my-replies"><summary>我的回复 · 最近 {data.ownReplies.length} 条</summary>{data.ownReplies.map((reply) => <div key={reply.id} className="review-reply-item"><small>{reviewStatusLabels[reply.status]}{!isTrue(reply.parent_visible) ? " · 原影评未公开" : ""} · {reviewTime(reply.updated_at)}</small><p>{reply.content}</p>{reply.moderation_note && <p>处理说明：{reply.moderation_note}</p>}<button className="text-button" type="button" disabled={busy} onClick={() => void removeReply(reply)}>删除我的回复</button></div>)}</details>}
    {message && <p className="review-message" role="status">{message}</p>}
    {loading ? <p role="status">正在读取评价…</p> : error ? <p role="alert">{error}<button type="button" className="text-button" onClick={() => setVersion((value) => value + 1)}>重试</button></p> : data?.reviews.length ? <div className="review-list">{data.reviews.map((review) => <article key={review.id}><div><strong>{review.username}</strong><span>{"★".repeat(review.rating)}{"☆".repeat(5 - review.rating)}</span><time>{reviewTime(review.updated_at)}</time></div><p>{review.content}</p><ReviewInteractions movieId={movieId} review={review} request={request} token={token} userId={userId} onLogin={onLogin} /></article>)}</div> : <p className="review-empty">还没有公开评价，通过审核的影评会展示在这里。</p>}
    {data && data.reviewCount > 10 && <div className="review-pagination"><button className="text-button" disabled={page === 1 || loading} type="button" onClick={() => setPage((value) => value - 1)}>上一页</button><span>{page} / {Math.ceil(data.reviewCount / 10)}</span><button className="text-button" disabled={page * 10 >= data.reviewCount || loading} type="button" onClick={() => setPage((value) => value + 1)}>下一页</button></div>}
  </section>;
}
