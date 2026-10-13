import { useEffect, useRef, useState, type FormEvent } from "react";
import { GatewayError, gatewayRequest, streamChat, type ChatContext } from "./chatTransport";
import "./assistant.css";
import MessageFeedback from "./MessageFeedback";

type Message = { id: string; role: "user" | "assistant"; content: string; mode: "dify" | "agent"; failed?: boolean; messageId?: string; normalizedQuestion?: string; finished?: boolean; truncated?: boolean; feedback?: { rating?: "like" | "dislike" | null; reason?: string | null; content?: string } };
type SessionInfo = { sessionId: string; bindingKey: string; difyReady: boolean; agentReadOnly: boolean; accountBound: boolean; busy: boolean; messages: Message[] };
type Credential = { credential: string; expiresAt: string };
type Props = {
  token?: string;
  userId?: number;
  onLogin: () => void;
  request: <T>(path: string, init?: RequestInit, token?: string) => Promise<T>;
};

export default function CinemaAssistant({ token, userId, onLogin, request }: Props) {
  const resumeHandoff = Boolean(token && sessionStorage.getItem("cinema-ai-handoff-pending"));
  const [open, setOpen] = useState(resumeHandoff);
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<"dify" | "agent">("dify");
  const [credential, setCredential] = useState<Credential | null>(null);
  const [busy, setBusy] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [suggested, setSuggested] = useState(false);
  const stream = useRef<AbortController | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const previousToken = useRef(token);
  const generation = useRef(0);
  const pendingHandoff = useRef(resumeHandoff);
  const lifetime = useRef(new AbortController());
  const bindingStorageKey = `cinema-ai-binding:${userId ?? "guest"}`;
  const context: ChatContext = { bindingKey: info?.bindingKey ?? "", sessionId: info?.sessionId, token };

  async function connect() {
    const currentGeneration = generation.current;
    setConnecting(true); setError("");
    try {
      const value = await gatewayRequest<SessionInfo>("session", { signal: lifetime.current.signal }, {
        bindingKey: sessionStorage.getItem(bindingStorageKey) ?? "", token,
      });
      if (currentGeneration !== generation.current) return;
      sessionStorage.setItem(bindingStorageKey, value.bindingKey);
      setInfo(value); setMessages(value.messages); setCredential(null); setMode("dify");
      setStatus(value.busy ? "另一窗口或设备正在回答，结束后点击恢复聊天。" : value.messages.length ? "已恢复最近聊天；查询实时业务可重新转接。" : "");
      if (pendingHandoff.current && token) {
        pendingHandoff.current = false; sessionStorage.removeItem("cinema-ai-handoff-pending"); await handoff(value);
      }
    } catch (cause) { if (currentGeneration === generation.current) setError(cause instanceof Error ? cause.message : "助手连接失败"); }
    finally { if (currentGeneration === generation.current) setConnecting(false); }
  }

  useEffect(() => {
    if (lifetime.current.signal.aborted) lifetime.current = new AbortController();
    return () => { generation.current++; lifetime.current.abort(); stream.current?.abort(); };
  }, []);

  useEffect(() => {
    if (open && !busy) void connect();
    if (open) input.current?.focus();
  }, [open]);

  useEffect(() => {
    if (previousToken.current === token) return;
    previousToken.current = token;
    if (!token) pendingHandoff.current = false;
    generation.current++;
    stream.current?.abort(); stream.current = null;
    setBusy(false); setCredential(null); setInfo(null); setMode("dify"); setMessages([]); setError(""); setStatus(""); setSuggested(false);
    // Restore only the newly verified account; logout never clears another device's history.
    if (open) void connect();
  }, [token]);

  useEffect(() => { if (open && !connecting && info) input.current?.focus(); }, [open, connecting, info]);

  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight }); }, [messages, status, error]);

  function close() { setOpen(false); launcher.current?.focus(); }

  async function handoff(restored?: SessionInfo) {
    const activeInfo = restored ?? info;
    if (!token) {
      pendingHandoff.current = true; sessionStorage.setItem("cinema-ai-handoff-pending", "1"); onLogin(); return;
    }
    if (!activeInfo || busy || (!restored && connecting)) return;
    setConnecting(true); setError("");
    const currentGeneration = generation.current;
    try {
      const ticket = await request<Credential>("/api/ai/handoff", {
        method: "POST", body: JSON.stringify({ sessionId: activeInfo.sessionId }),
      }, token);
      if (currentGeneration !== generation.current) return;
      setCredential(ticket); setMode("agent"); setSuggested(false);
      setStatus("已转接实时 Agent，继续输入问题即可查询。");
      input.current?.focus();
    } catch (cause) { if (currentGeneration === generation.current) setError(cause instanceof Error ? cause.message : "转接失败，请稍后重试"); }
    finally { if (currentGeneration === generation.current) setConnecting(false); }
  }

  async function send(text = question) {
    const value = text.trim();
    if (!value || !info || busy || connecting) return;
    const currentGeneration = generation.current;
    const id = crypto.randomUUID();
    const abort = new AbortController(); stream.current = abort;
    setBusy(true); setError(""); setSuggested(false); setQuestion("");
    setMessages((current) => [...current.slice(-38), { id: crypto.randomUUID(), role: "user", content: value, mode },
      { id, role: "assistant", content: "", mode }]);
    try {
      let activeCredential = credential;
      if (mode === "agent") {
        if (!token) throw new Error("请登录后重新转接实时 Agent");
        if (!activeCredential || Date.parse(activeCredential.expiresAt) - Date.now() < 15000) {
          activeCredential = await request<Credential>("/api/ai/handoff", {
            method: "POST", body: JSON.stringify({ sessionId: info.sessionId }),
          }, token);
          if (currentGeneration !== generation.current) return;
          setCredential(activeCredential);
        }
      }
      await streamChat({ sessionId: info.sessionId, question: value, mode, credential: activeCredential?.credential ?? "" }, abort.signal, (packet) => {
        if (currentGeneration !== generation.current) return;
        if (packet.type === "message" || packet.type === "context") {
          setMessages((current) => current.map((message) => message.id === id ? { ...message,
            ...(packet.messageId ? { messageId: packet.messageId } : {}),
            ...(packet.normalized_question ? { normalizedQuestion: packet.normalized_question } : {}) } : message));
        } else if (packet.type === "delta" || packet.type === "replace") {
          setMessages((current) => current.map((message) => message.id === id
            ? { ...message, content: packet.type === "replace" ? packet.text ?? "" : message.content + (packet.text ?? "") } : message));
        } else if (packet.type === "status") setStatus(packet.message ?? "");
        else if (packet.type === "complete") {
          setMessages((current) => current.map((message) => message.id === id ? { ...message, finished: true } : message));
          setSuggested(packet.handoffSuggested === true); setStatus("");
        }
        else if (packet.code === "handoff_expired") setCredential(null);
      }, context);
    } catch (cause) {
      if (currentGeneration !== generation.current) return;
      const stopped = abort.signal.aborted;
      const failureMessage = cause instanceof Error ? cause.message : "回答失败，请重试";
      if (cause instanceof GatewayError && cause.status === 409) setQuestion(value);
      if (cause instanceof GatewayError && cause.status === 401) { setInfo(null); setCredential(null); setMode("dify"); }
      setMessages((current) => current.map((message) => message.id === id
        ? { ...message, failed: true, finished: true, content: message.content || (stopped ? "已停止回答。" : failureMessage) } : message));
      setError(stopped ? "" : failureMessage);
      setStatus(stopped ? "已停止回答" : "");
    } finally {
      if (currentGeneration === generation.current) { setBusy(false); stream.current = null; input.current?.focus(); }
    }
  }

  function stop() {
    stream.current?.abort();
    if (info) void gatewayRequest("stop", { method: "POST", signal: lifetime.current.signal }, context).catch(() => undefined);
  }

  async function reset() {
    if (busy || connecting || !info) return;
    const currentGeneration = generation.current;
    setConnecting(true); setError("");
    try {
      const value = await gatewayRequest<{ sessionId: string }>("reset", { method: "POST", signal: lifetime.current.signal }, context);
      if (currentGeneration !== generation.current) return;
      setInfo({ ...info, ...value }); setCredential(null); setMode("dify"); setMessages([]); setSuggested(false); setStatus("");
    } catch (cause) { if (currentGeneration === generation.current) setError(cause instanceof Error ? cause.message : "新对话创建失败"); }
    finally { if (currentGeneration === generation.current) setConnecting(false); }
  }

  function submit(event: FormEvent) { event.preventDefault(); void send(); }
  const lastQuestion = [...messages].reverse().find((message) => message.role === "user")?.content;

  return <>
    <button ref={launcher} type="button" className="assistant-launcher" aria-label="打开影院助手" aria-expanded={open} aria-controls="cinema-assistant" onClick={() => setOpen(!open)}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-6 3v-3a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="M7 9h10M7 13h6"/></svg>
      <span>影院助手</span>
    </button>
    {open && <section id="cinema-assistant" className="assistant-panel" role="dialog" aria-label="影院助手" onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}>
      <header className="assistant-header"><div><span className="assistant-eyebrow">CINEMA CONCIERGE</span><h2>你的观影助手</h2></div><button type="button" aria-label="关闭影院助手" onClick={close}>×</button></header>
      <div className="assistant-mode"><span><i />{mode === "agent" ? "实时 Agent · 业务查询" : "智能助手 · 常见问题"}</span><div className="assistant-session-actions"><button type="button" disabled={busy || connecting} onClick={() => void connect()}>恢复聊天</button><button type="button" title="开始新对话，清空当前账户或匿名会话的最近聊天" disabled={busy || connecting || !info} onClick={() => void reset()}>新对话</button></div></div>
      <div className="assistant-transcript" ref={scroll} role="log" aria-label="聊天记录" aria-live="polite" aria-relevant="additions">
        {messages.length === 0 && <div className="assistant-welcome"><span className="assistant-welcome-mark">C /</span><h3>从一个问题开始</h3><p>购票流程、观影须知，可以先问智能助手。需要查询订单或实时场次时，选择下方转接。</p><div className="assistant-prompts">{["怎么买票和选择座位？", "退票需要注意什么？"].map((text) => <button key={text} type="button" disabled={busy || connecting || !info || (mode === "dify" && !info.difyReady)} onClick={() => void send(text)}>{text}<span>↗</span></button>)}</div></div>}
        {messages.map((message) => <article key={message.id} className={`assistant-message ${message.role}${message.failed ? " incomplete" : ""}`}><span>{message.role === "user" ? "你" : message.mode === "agent" ? "实时 Agent" : "智能助手"}</span>
          {message.normalizedQuestion && <details className="assistant-understanding"><summary>理解后的问题</summary><p>{message.normalizedQuestion}</p></details>}
          <p>{message.content || "正在准备回答…"}</p>{message.failed && <small>回答未完成</small>}{message.truncated && <small>较长回答仅恢复前 8000 字。</small>}
          {message.role === "assistant" && message.messageId && message.finished && <MessageFeedback messageId={message.messageId} initial={message.feedback} disabled={busy || connecting} context={context} />}
        </article>)}
        {status && <p className="assistant-status" role="status">{status}</p>}
        {suggested && mode === "dify" && <p className="assistant-status">建议转接实时 Agent 查询当前业务数据。</p>}
        {error && <div className="assistant-error" role="alert"><p>{error}</p>{info && lastQuestion && <button type="button" disabled={busy || connecting} onClick={() => void send(lastQuestion)}>重试问题</button>}{!info && <button type="button" disabled={connecting} onClick={() => void connect()}>重新连接</button>}</div>}
        {info && !info.difyReady && mode === "dify" && <p className="assistant-status">智能助手尚未配置，可登录后转接实时 Agent。</p>}
      </div>
      <div className="assistant-handoff">{mode === "dify" ? <><span>需要查订单或实时场次？</span><button type="button" disabled={busy || connecting || !info} onClick={() => void handoff()}>{token ? "转接实时 Agent →" : "登录并转接 →"}</button></>
        : <><span>当前可查询，不执行购票或退款</span><button type="button" disabled={busy || connecting} onClick={() => { setMode("dify"); setStatus(""); }}>返回智能助手</button></>}</div>
      <form className="assistant-composer" onSubmit={submit}><label className="sr-only" htmlFor="assistant-question">输入你的问题</label><textarea ref={input} id="assistant-question" value={question} maxLength={2000} rows={2} placeholder={mode === "agent" ? "请输入订单号或想查询的场次…" : "输入你的观影问题…"} disabled={connecting || !info} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!busy) void send(); } }} />
        {busy ? <button type="button" onClick={stop}>停止</button> : <button type="submit" disabled={!question.trim() || connecting || !info || (mode === "dify" && !info.difyReady)} aria-label="发送问题">发送 ↗</button>}</form>
    </section>}
  </>;
}
