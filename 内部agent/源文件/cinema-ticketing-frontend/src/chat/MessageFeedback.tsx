import { useEffect, useRef, useState, type FormEvent } from "react";
import { gatewayRequest, type ChatContext } from "./chatTransport";

export const feedbackReasons = { misunderstood: "理解错误", irrelevant: "答非所问", inaccurate: "信息不准确", outdated: "信息过时", unresolved: "未解决问题", error: "服务异常", other: "其他" };
type Rating = "like" | "dislike" | null;
type Saved = { saved: boolean; providerSync: string; syncRecorded: boolean };

export default function MessageFeedback({ messageId, disabled, initial, context }: { messageId: string; disabled: boolean; context: ChatContext; initial?: { rating?: Rating; reason?: string | null; content?: string } }) {
  const [rating, setRating] = useState<Rating>(initial?.rating ?? null);
  const [reason, setReason] = useState(initial?.reason ?? "");
  const [content, setContent] = useState(initial?.content ?? "");
  const [details, setDetails] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState<Rating | undefined>(undefined);
  const lifetime = useRef(new AbortController());

  useEffect(() => {
    if (lifetime.current.signal.aborted) lifetime.current = new AbortController();
    const current = lifetime.current;
    return () => current.abort();
  }, []);

  useEffect(() => {
    setRating(initial?.rating ?? null); setReason(initial?.reason ?? ""); setContent(initial?.content ?? "");
    setNotice(""); setError(""); setRetry(undefined); setDetails(false);
  }, [messageId, initial?.rating, initial?.reason, initial?.content]);

  async function save(next: Rating) {
    if (saving || disabled) return;
    setSaving(true); setError(""); setNotice("");
    const abort = lifetime.current;
    try {
      const result = await gatewayRequest<Saved>("feedback", { method: "POST", headers: { "Content-Type": "application/json" },
        signal: abort.signal,
        body: JSON.stringify({ messageId, rating: next, reason: next === "dislike" ? reason || null : null, content: next === "dislike" ? content : "" }) }, context);
      setRating(next); setDetails(next === "dislike");
      const syncIssue = result.providerSync === "FAILED" || result.providerSync === "UNAVAILABLE" || !result.syncRecorded;
      setRetry(syncIssue ? next : undefined);
      setNotice(syncIssue ? "已保存到影院后台，云端反馈同步异常，可重试。" : next ? "感谢反馈，已保存。" : "已取消评价。");
    } catch (cause) { if (!abort.signal.aborted) { setRetry(next); setError(cause instanceof Error ? cause.message : "反馈保存失败"); } }
    finally { if (!abort.signal.aborted) setSaving(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void save("dislike"); }
  return <div className="assistant-feedback">
    <div className="assistant-feedback-actions" aria-label="评价这条回答">{(["like", "dislike"] as const).map((value) => <button key={value} type="button" aria-label={value === "like" ? "回答有帮助" : "回答没有帮助"} aria-pressed={rating === value} disabled={saving || disabled} onClick={() => void save(rating === value ? null : value)}>
      <svg className={value === "dislike" ? "thumb-down" : ""} viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10v11H3V10h4Zm0 0 5-8h2v6h5a2 2 0 0 1 2 2l-2 9a2 2 0 0 1-2 2H7" /></svg>{value === "like" ? "有帮助" : "没帮助"}</button>)}
      {rating === "dislike" && <button type="button" disabled={saving || disabled} onClick={() => setDetails(!details)}>{details ? "收起原因" : "补充原因"}</button>}
    </div>
    {details && <form className="assistant-feedback-form" onSubmit={submit}><label>哪里需要改进？<select value={reason} disabled={saving || disabled} onChange={(event) => setReason(event.target.value)}><option value="">选择原因（可选）</option>{Object.entries(feedbackReasons).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><textarea aria-label="补充反馈" rows={2} maxLength={500} value={content} disabled={saving || disabled} placeholder="可以补充你期望的回答，请勿填写密码或支付信息。" onChange={(event) => setContent(event.target.value)} /><button type="submit" disabled={saving || disabled}>{saving ? "保存中…" : "保存原因"}</button></form>}
    {notice && <small role="status">{notice}</small>}{error && <small role="alert">{error}</small>}
    {retry !== undefined && <button type="button" disabled={saving || disabled} onClick={() => { if (retry !== undefined) void save(retry); }}>重试反馈</button>}
  </div>;
}
