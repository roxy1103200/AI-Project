import { useEffect, useRef, useState, type FormEvent } from "react";
import type { ApiRequest } from "../admin/movie-save";

type Review = { id: number; username?: string; rating: number; content: string; updated_at: string };
type Reviews = { reviewCount: number; averageRating: number | string | null; reviews: Review[]; ownReview?: Review | null; page: number };
type Props = { movieId: number; token?: string; request: ApiRequest; onLogin: () => void; onChanged: () => Promise<void> };

export default function MovieReviews({ movieId, token, request, onLogin, onChanged }: Props) {
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
    event.preventDefault(); if (!token || busy) return;
    if (rating < 1 || !content.trim()) { setMessage("请选择星级并填写评论。"); return; }
    setBusy(true); setMessage("");
    try {
      await request(`/api/movies/${movieId}/reviews`, { method: "PUT", body: JSON.stringify({ rating, content: content.trim() }) }, token);
      setPage(1); setVersion((value) => value + 1); setMessage("评价已保存。");
      try { await onChanged(); } catch { setMessage("评价已保存，片单评分刷新失败，请稍后刷新。"); }
    } catch (failure) { setMessage(failure instanceof Error ? failure.message : "评价保存失败"); }
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
    {token ? <form className="review-form" onSubmit={(event) => void save(event)}>
      <div className="review-stars" role="group" aria-label="选择评分">{[1, 2, 3, 4, 5].map((star) => <button key={star} type="button" disabled={busy} aria-label={`${star} 星`} aria-pressed={rating === star} className={star <= rating ? "chosen" : ""} onClick={() => setRating(star)}>★</button>)}<span>{rating ? `${rating} / 5` : "选择星级"}</span></div>
      <label><span className="sr-only">影片评论</span><textarea required maxLength={1000} rows={3} disabled={busy} value={content} onChange={(event) => setContent(event.target.value)} placeholder="分享你的观影感受（最多 1000 字）" /></label>
      <div className="review-form-actions"><small>每人每部影片一条评价，可随时修改。</small>{data?.ownReview && <button className="text-button" disabled={busy} type="button" onClick={() => void remove()}>删除我的评价</button>}<button className="secondary-button" disabled={busy} type="submit">{busy ? "处理中…" : data?.ownReview ? "更新评价" : "发表评价"}</button></div>
    </form> : <p className="review-login">登录后可以评分和评论。<button className="text-button" type="button" onClick={onLogin}>登录</button></p>}
    {message && <p className="review-message" role="status">{message}</p>}
    {loading ? <p role="status">正在读取评价…</p> : error ? <p role="alert">{error}<button type="button" className="text-button" onClick={() => setVersion((value) => value + 1)}>重试</button></p> : data?.reviews.length ? <div className="review-list">{data.reviews.map((review) => <article key={review.id}><div><strong>{review.username}</strong><span>{"★".repeat(review.rating)}{"☆".repeat(5 - review.rating)}</span><time>{review.updated_at.replace("T", " ").slice(0, 16)}</time></div><p>{review.content}</p></article>)}</div> : <p className="review-empty">还没有评价，写下第一条观影感受吧。</p>}
    {data && data.reviewCount > 10 && <div className="review-pagination"><button className="text-button" disabled={page === 1 || loading} type="button" onClick={() => setPage((value) => value - 1)}>上一页</button><span>{page} / {Math.ceil(data.reviewCount / 10)}</span><button className="text-button" disabled={page * 10 >= data.reviewCount || loading} type="button" onClick={() => setPage((value) => value + 1)}>下一页</button></div>}
  </section>;
}
