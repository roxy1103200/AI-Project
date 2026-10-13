import { useEffect, useState, type FormEvent } from "react";

type Request = <T>(path: string, init?: RequestInit, token?: string) => Promise<T>;
type Memory = { id: string; content: string; category: string; version: number };
export type MemoryProposal = { content: string; category: string };
const categories = { GENERAL: "一般偏好", GENRE: "电影类型", CINEMA: "影院", SEAT: "座位", HABIT: "观影习惯" };

/** Only the Agent mounts this panel. Java authenticates each operation. */
export default function UserMemories({ token, request, onClose }: { token: string; request: Request; onClose: () => void }) {
  const [items, setItems] = useState<Memory[]>([]);
  const [draft, setDraft] = useState<MemoryProposal>({ content: "", category: "GENERAL" });
  const [editing, setEditing] = useState<Memory | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function refresh(signal?: AbortSignal) {
    const rows = await request<Memory[]>("/api/ai/memories", { signal }, token);
    if (!signal?.aborted) setItems(rows);
  }
  useEffect(() => {
    const abort = new AbortController();
    setBusy(true);
    void refresh(abort.signal).catch((cause) => { if (!abort.signal.aborted) setError(cause instanceof Error ? cause.message : "记忆加载失败"); })
      .finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => abort.abort();
  }, [token]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !draft.content.trim()) return;
    setBusy(true); setError("");
    try {
      await request(`/api/ai/memories${editing ? `/${editing.id}` : ""}`, {
        method: editing ? "PATCH" : "POST", body: JSON.stringify({ ...draft, ...(editing ? { version: editing.version } : {}) }),
      }, token);
      setEditing(null); setShowEditor(false); setDraft({ content: "", category: "GENERAL" }); await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function remove(item: Memory) {
    setBusy(true); setError("");
    try {
      await request(`/api/ai/memories/${item.id}?version=${item.version}`, { method: "DELETE" }, token);
      if (editing?.id === item.id) { setEditing(null); setDraft({ content: "", category: "GENERAL" }); }
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "删除失败"); }
    finally { setBusy(false); }
  }
  return <section className="assistant-memories" aria-label="我的记忆">
    <header><h3>我的记忆</h3><button type="button" onClick={onClose}>返回聊天</button></header>
    <p>跨对话保存你的观影偏好，仅供智能 Agent 使用。新对话会保留记忆；删除后立即停止使用。</p>
    {items.length > 0 && !editing && <button type="button" onClick={() => setShowEditor(!showEditor)}>{showEditor ? "收起表单" : "添加记忆"}</button>}
    {(!items.length || editing || showEditor) && <form onSubmit={(event) => void save(event)}>
      <label>分类<select value={draft.category} disabled={busy} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>{editing ? "修改记忆" : "添加记忆"}<textarea required rows={3} maxLength={500} placeholder="例如：我偏好科幻电影，喜欢靠过道的座位" value={draft.content} disabled={busy} onChange={(event) => setDraft({ ...draft, content: event.target.value })}/></label>
      <div><button type="submit" disabled={busy || !draft.content.trim()}>{busy ? "处理中…" : "保存"}</button>{editing && <button type="button" disabled={busy} onClick={() => { setEditing(null); setDraft({ content: "", category: "GENERAL" }); }}>取消修改</button>}<button type="button" disabled={busy} onClick={() => { setBusy(true); void refresh().catch((cause) => setError(cause.message)).finally(() => setBusy(false)); }}>刷新</button></div>
    </form>}
    {error && <p role="alert">{error}</p>}
    {!busy && items.length === 0 && <p>还没有保存的记忆。</p>}
    <ul>{items.map((item) => <li key={item.id}><small>{categories[item.category as keyof typeof categories] ?? item.category}</small><p>{item.content}</p><button type="button" disabled={busy} onClick={() => { setEditing(item); setDraft({ content: item.content, category: item.category }); }}>修改</button><button type="button" disabled={busy} onClick={() => void remove(item)}>删除</button></li>)}</ul>
  </section>;
}

export function SaveMemory({ proposal, messageId, token, request }: { proposal: MemoryProposal; messageId?: string; token: string; request: Request }) {
  const [state, setState] = useState<"ready" | "saving" | "saved">("ready");
  const [error, setError] = useState("");
  async function save() {
    if (state !== "ready") return;
    setState("saving"); setError("");
    try {
      await request("/api/ai/memories", { method: "POST", body: JSON.stringify({ ...proposal, sourceMessageId: messageId }) }, token);
      setState("saved");
    } catch (cause) { setState("ready"); setError(cause instanceof Error ? cause.message : "保存失败"); }
  }
  return <div className="assistant-memory-proposal"><p>{proposal.content}</p><button type="button" disabled={state !== "ready"} onClick={() => void save()}>{state === "saved" ? "已保存记忆" : state === "saving" ? "保存中…" : "保存记忆"}</button>{error && <small role="alert">{error}</small>}</div>;
}
