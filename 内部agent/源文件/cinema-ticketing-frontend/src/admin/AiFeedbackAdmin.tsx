import { useEffect, useState, type FormEvent } from "react";
import { feedbackReasons } from "../chat/MessageFeedback";
import type { ApiRequest } from "./movie-save";
import "./ai-feedback.css";

type Feedback = {
  id: number; provider: string; user_id: number | null; question: string; normalized_question: string; answer: string;
  intent: string; confidence: number | null; intent_source: string; entities_json: string; tool_calls_json: string;
  error_code: string; rating: string | null; reason: string | null; feedback_content: string;
  provider_sync_status: string; status: string; review_note: string; created_at: string; updated_at: string;
};
type Listing = { items: Feedback[]; summary: { total: number; likes: number; dislikes: number; unresolved: number; sync_issues: number } };
const intents: Record<string, string> = { chat: "问候与能力介绍", movies: "影片信息", screenings: "场次与票价", order: "本人订单", refund: "退票资格", policy: "票务规则", recommend: "影片推荐", unsupported: "待澄清" };
const syncLabels: Record<string, string> = { SYNCED: "已同步 Dify", FAILED: "Dify 同步失败", PENDING: "Dify 同步待确认", UNAVAILABLE: "缺少 Dify 消息编号", NOT_APPLICABLE: "内部 Agent 反馈" };
const sources: Record<string, string> = { rules: "规则", model: "模型", invalid_model_output: "模型格式异常，规则接管", model_unavailable: "模型不可用，规则接管" };
function date(value: string) { return value ? value.replace("T", " ").slice(0, 19) : "—"; }
function json(value: string) { try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; } }

function FeedbackCard({ item, request, token, refresh }: { item: Feedback; request: ApiRequest; token: string; refresh: () => void }) {
  const [note, setNote] = useState(item.review_note);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  async function review(status: string) {
    setSaving(true); setMessage("");
    try { await request(`/api/admin/ai-feedback/${item.id}`, { method: "PUT", body: JSON.stringify({ status, note }) }, token); refresh(); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : "处理失败"); }
    finally { setSaving(false); }
  }
  const reason = item.reason ? feedbackReasons[item.reason as keyof typeof feedbackReasons] : "未补充原因";
  return <article className="ai-feedback-card">
    <header><div className="ai-feedback-tags"><span className={item.rating === "dislike" ? "negative" : ""}>{item.rating === "dislike" ? "点踩" : item.rating === "like" ? "点赞" : "已撤回评价"}</span><span>{item.provider === "DIFY" ? "Dify 智能助手" : "内部 Agent"}</span><span>{item.status === "OPEN" ? "待处理" : "已处理"}</span></div><small>{date(item.updated_at)}</small></header>
    <h3>{item.question}</h3><p>{reason}{item.feedback_content ? ` · ${item.feedback_content}` : ""}</p>
    <details><summary>查看问题理解、回答和处理记录</summary>
      <dl><div><dt>归一化问题</dt><dd>{item.normalized_question || "Dify 管理的理解过程未通过 API 返回"}</dd></div>
        <div><dt>识别意图</dt><dd>{intents[item.intent] || item.intent || "Dify 未返回"}{item.confidence != null ? ` · 置信度 ${Math.round(Number(item.confidence) * 100)}%` : ""}{item.intent_source ? ` · ${sources[item.intent_source] || item.intent_source}` : ""}</dd></div>
        <div><dt>回答内容</dt><dd className="ai-feedback-answer">{item.answer || "未产生回答"}</dd></div>
        <div><dt>提取条件</dt><dd><pre>{json(item.entities_json)}</pre></dd></div><div><dt>查询工具</dt><dd><pre>{json(item.tool_calls_json)}</pre></dd></div>
        <div><dt>用户 / 异常</dt><dd>{item.user_id ? `用户 #${item.user_id}` : item.provider === "DIFY" ? "匿名 Dify 会话" : "未关联登录用户"}{item.error_code ? ` · ${item.error_code}` : " · 无错误码"}</dd></div>
        <div><dt>反馈同步</dt><dd>{syncLabels[item.provider_sync_status] || item.provider_sync_status}</dd></div><div><dt>首次反馈</dt><dd>{date(item.created_at)}</dd></div>
      </dl>
      <label>处理备注<textarea rows={2} maxLength={1000} value={note} disabled={saving} onChange={(event) => setNote(event.target.value)} placeholder="记录工作流、知识库或业务接口的改进措施" /></label>
      <div className="ai-feedback-review"><button type="button" className="secondary-button" disabled={saving} onClick={() => void review(item.status)}>保存备注</button><button type="button" className="primary-button" disabled={saving} onClick={() => void review(item.status === "OPEN" ? "RESOLVED" : "OPEN")}>{saving ? "保存中…" : item.status === "OPEN" ? "标记已处理" : "重新打开"}</button></div>
      {message && <p role="alert">{message}</p>}
    </details>
  </article>;
}

export default function AiFeedbackAdmin({ request, token }: { request: ApiRequest; token: string }) {
  const [provider, setProvider] = useState("");
  const [rating, setRating] = useState("dislike");
  const [status, setStatus] = useState("OPEN");
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError("");
    const filters = new URLSearchParams({ provider, rating, status, reason, query, page: String(page), size: "20" });
    request<Listing>(`/api/admin/ai-feedback?${filters}`, {}, token).then((value) => { if (active) setData(value); })
      .catch((cause) => { if (active) { setData(null); setError(cause instanceof Error ? cause.message : "反馈读取失败"); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [provider, rating, status, reason, query, page, reload, token, request]);
  function search(event: FormEvent) { event.preventDefault(); setPage(1); setQuery(draft.trim()); }
  const filters = [
    { label: "回答来源", value: provider, change: setProvider, choices: { "": "全部来源", DIFY: "Dify", AGENT: "内部 Agent" } },
    { label: "用户评价", value: rating, change: setRating, choices: { "": "全部评价", dislike: "点踩", like: "点赞" } },
    { label: "处理状态", value: status, change: setStatus, choices: { "": "全部状态", OPEN: "待处理", RESOLVED: "已处理" } },
    { label: "反馈原因", value: reason, change: setReason, choices: { "": "全部原因", ...feedbackReasons } },
  ];
  return <section className="content-width ai-feedback-admin"><div className="section-heading"><div><p className="eyebrow">ASSISTANT FEEDBACK</p><h2>AI 反馈</h2></div><button type="button" className="secondary-button" disabled={loading} onClick={() => setReload((value) => value + 1)}>刷新反馈</button></div>
    <p className="section-note">默认显示待处理点踩。展开记录可查看问题理解、原始回答及反馈原因，处理后保留记录。</p>
    <form className="ai-feedback-filters" onSubmit={search}>{filters.map((filter) => <label key={filter.label}>{filter.label}<select value={filter.value} onChange={(event) => { setPage(1); filter.change(event.target.value); }}>{Object.entries(filter.choices).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>)}<label className="ai-feedback-search">搜索问题 / 原因<input value={draft} maxLength={120} onChange={(event) => setDraft(event.target.value)} placeholder="输入关键词" /></label><button type="submit" className="secondary-button">搜索</button></form>
    {error && <p role="alert">{error}</p>}
    {data && <div className="ai-feedback-summary" aria-label="当前筛选范围统计"><span>记录 <strong>{data.summary.total}</strong></span><span>点踩 <strong>{data.summary.dislikes}</strong></span><span>点赞 <strong>{data.summary.likes}</strong></span><span>待处理 <strong>{data.summary.unresolved}</strong></span><span>同步异常 / 待确认 <strong>{data.summary.sync_issues}</strong></span></div>}
    {loading ? <p role="status">正在读取反馈…</p> : data?.items.length ? <div className="ai-feedback-list">{data.items.map((item) => <FeedbackCard key={`${item.id}:${item.updated_at}:${reload}`} item={item} request={request} token={token} refresh={() => setReload((value) => value + 1)} />)}</div> : !error && <div className="ai-feedback-empty"><h3>当前筛选条件下暂无反馈</h3><p>观众在聊天回答下提交点赞或点踩后，记录会出现在这里。</p></div>}
    {data && <footer className="ai-feedback-pagination"><button type="button" className="secondary-button" disabled={loading || page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页 · 共 {Math.max(1, Math.ceil(data.summary.total / 20))} 页</span><button type="button" className="secondary-button" disabled={loading || page * 20 >= data.summary.total} onClick={() => setPage(page + 1)}>下一页</button></footer>}
  </section>;
}
