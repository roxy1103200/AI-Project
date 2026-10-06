import { useEffect, useRef, useState, type FormEvent } from "react";
import { bindingStorageKey, GatewayError, gatewayRequest, streamChat, type ChatChannel, type ChatContext } from "./chatTransport";
import { createMessageId } from "./messageId";
import MessageFeedback from "./MessageFeedback";
import "./assistant.css";

type Message = { id: string; role: "user" | "assistant"; content: string; mode: ChatChannel; failed?: boolean; messageId?: string; normalizedQuestion?: string; finished?: boolean; truncated?: boolean; feedback?: { rating?: "like" | "dislike" | null; reason?: string | null; content?: string } };
type SessionInfo = { channel: ChatChannel; sessionId: string; bindingKey: string; ready: boolean; accountBound: boolean; busy: boolean; messages: Message[] };
type Credential = { credential: string; expiresAt: string };
type Props = { token?: string; userId?: number; onLogin: () => void; request: <T>(path: string, init?: RequestInit, token?: string) => Promise<T> };
const AGENT_LOGIN_PENDING = "cinema-agent-login-pending";

/** Two independently mounted clients share login identity, never chat data. */
export default function CinemaAssistant(props: Props) {
  const [visible, setVisible] = useState({ dify: false, agent: Boolean(props.token && sessionStorage.getItem(AGENT_LOGIN_PENDING)) });
  const lastOpened = useRef<ChatChannel>("agent");
  function show(channel: ChatChannel, open: boolean) {
    if (open) lastOpened.current = channel;
    setVisible((current) => ({ ...current,
      ...(open && window.matchMedia("(max-width: 900px)").matches ? { dify: false, agent: false } : {}), [channel]: open }));
  }
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 900px)");
    const resize = () => {
      if (narrow.matches) setVisible((current) => current.dify && current.agent
        ? { dify: lastOpened.current === "dify", agent: lastOpened.current === "agent" } : current);
    };
    narrow.addEventListener("change", resize);
    return () => narrow.removeEventListener("change", resize);
  }, []);
  return <>
    <ChatAssistant {...props} channel="dify" open={visible.dify} onOpen={(open) => show("dify", open)} />
    <ChatAssistant {...props} channel="agent" open={visible.agent} onOpen={(open) => show("agent", open)} />
  </>;
}

function ChatAssistant({ token, userId, onLogin, request, channel, open, onOpen }: Props & { channel: ChatChannel; open: boolean; onOpen: (open: boolean) => void }) {
  const isAgent = channel === "agent";
  const name = isAgent ? "智能 Agent" : "Dify 知识问答";
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [credential, setCredential] = useState<Credential | null>(null);
  const [busy, setBusy] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const stream = useRef<AbortController | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const previousToken = useRef(token);
  const generation = useRef(0);
  const lifetime = useRef(new AbortController());
  const storageKey = bindingStorageKey(channel, userId);
  const context: ChatContext = { channel, bindingKey: info?.bindingKey ?? "", sessionId: info?.sessionId, token };

  async function connect() {
    if (isAgent && !token) return;
    const currentGeneration = ++generation.current;
    setConnecting(true); setError("");
    try {
      const value = await gatewayRequest<SessionInfo>("session", { signal: lifetime.current.signal }, {
        channel, bindingKey: sessionStorage.getItem(storageKey) ?? "", token,
      });
      if (currentGeneration !== generation.current) return;
      if (value.channel !== channel || value.messages.some((message) => message.mode !== channel)) throw new Error("助手会话不匹配，请重新连接");
      sessionStorage.setItem(storageKey, value.bindingKey);
      setInfo(value); setMessages(value.messages); setCredential(null);
      setStatus(value.busy ? "另一窗口或设备正在回答，结束后点击恢复聊天。" : value.messages.length ? "已恢复最近聊天。" : "");
      if (isAgent) sessionStorage.removeItem(AGENT_LOGIN_PENDING);
    } catch (cause) { if (currentGeneration === generation.current) setError(cause instanceof Error ? cause.message : "助手连接失败"); }
    finally { if (currentGeneration === generation.current) setConnecting(false); }
  }
  useEffect(() => {
    if (lifetime.current.signal.aborted) lifetime.current = new AbortController();
    return () => { generation.current++; lifetime.current.abort(); stream.current?.abort(); };
  }, []);
  useEffect(() => { if (open && !busy) void connect(); if (open) input.current?.focus(); }, [open]);
  useEffect(() => {
    if (previousToken.current === token) return;
    previousToken.current = token;
    generation.current++; stream.current?.abort(); stream.current = null;
    setBusy(false); setCredential(null); setInfo(null); setMessages([]); setQuestion(""); setError(""); setStatus("");
    if (open) void connect();
  }, [token]);
  useEffect(() => { if (open && !connecting && info) input.current?.focus(); }, [open, connecting, info]);
  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight }); }, [messages, status, error]);
  function close() { onOpen(false); launcher.current?.focus(); }
  function login() { sessionStorage.setItem(AGENT_LOGIN_PENDING, "1"); onOpen(false); onLogin(); }

  async function send(text = question) {
    const value = text.trim();
    if (!value || !info || busy || connecting || !info.ready || (isAgent && !token)) return;
    const currentGeneration = generation.current;
    const id = createMessageId();
    const abort = new AbortController(); stream.current = abort;
    setBusy(true); setError(""); setQuestion("");
    setMessages((current) => [...current.slice(-38), { id: createMessageId(), role: "user", content: value, mode: channel }, { id, role: "assistant", content: "", mode: channel }]);
    try {
      let activeCredential = credential;
      if (isAgent && (!activeCredential || Date.parse(activeCredential.expiresAt) - Date.now() < 15000)) {
        activeCredential = await request<Credential>("/api/ai/handoff", { method: "POST", signal: abort.signal, body: JSON.stringify({ sessionId: info.sessionId }) }, token);
        if (currentGeneration !== generation.current) return;
        abort.signal.throwIfAborted(); setCredential(activeCredential);
      }
      // Dify never receives Agent credentials, history, or business query results.
      await streamChat({ sessionId: info.sessionId, question: value, ...(isAgent ? { credential: activeCredential?.credential ?? "" } : {}) }, abort.signal, (packet) => {
        if (currentGeneration !== generation.current) return;
        if (packet.type === "message" || packet.type === "context") {
          setMessages((current) => current.map((message) => message.id === id ? { ...message,
            ...(packet.messageId ? { messageId: packet.messageId } : {}), ...(packet.normalized_question ? { normalizedQuestion: packet.normalized_question } : {}) } : message));
        } else if (packet.type === "delta" || packet.type === "replace") {
          setMessages((current) => current.map((message) => message.id === id ? { ...message, content: packet.type === "replace" ? packet.text ?? "" : message.content + (packet.text ?? "") } : message));
        } else if (packet.type === "status") setStatus(packet.message ?? "");
        else if (packet.type === "complete") { setMessages((current) => current.map((message) => message.id === id ? { ...message, finished: true } : message)); setStatus(""); }
        else if (packet.code === "handoff_expired") setCredential(null);
      }, context);
    } catch (cause) {
      if (currentGeneration !== generation.current) return;
      const stopped = abort.signal.aborted;
      const failureMessage = cause instanceof Error ? cause.message : "回答失败，请重试";
      if (cause instanceof GatewayError && cause.status === 409) setQuestion(value);
      if (cause instanceof GatewayError && cause.status === 401) { setInfo(null); setCredential(null); }
      setMessages((current) => current.map((message) => message.id === id ? { ...message, failed: true, finished: true, content: message.content || (stopped ? "已停止回答。" : failureMessage) } : message));
      setError(stopped ? "" : failureMessage); setStatus(stopped ? "已停止回答" : "");
    } finally { if (currentGeneration === generation.current) { setBusy(false); stream.current = null; input.current?.focus(); } }
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
      setInfo({ ...info, ...value }); setCredential(null); setMessages([]); setQuestion(""); setStatus("");
    } catch (cause) { if (currentGeneration === generation.current) setError(cause instanceof Error ? cause.message : "新对话创建失败"); }
    finally { if (currentGeneration === generation.current) setConnecting(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void send(); }
  const lastQuestion = [...messages].reverse().find((message) => message.role === "user")?.content;
  const canSend = Boolean(info?.ready && (!isAgent || token));
  const prompts = isAgent ? ["查询正在上映的电影", "查询明天的电影场次"] : ["怎么买票和选择座位？", "退票需要注意什么？"];
  return <>
    <button ref={launcher} type="button" className={`assistant-launcher ${isAgent ? "agent-launcher" : "dify-launcher"}`} aria-label={`打开${name}`} title={name} aria-expanded={open} aria-controls={`cinema-assistant-${channel}`} onClick={() => onOpen(!open)}>
      {isAgent ? <><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-6 3v-3a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="M7 9h10M7 13h6"/></svg><span>智能 Agent</span></> : <span>Dify</span>}
    </button>
    {open && <section id={`cinema-assistant-${channel}`} className={`assistant-panel ${channel}-panel`} role="dialog" aria-label={name} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); close(); } }}>
      <header className="assistant-header"><div><span className="assistant-eyebrow">{isAgent ? "CINEMA AGENT" : "DIFY KNOWLEDGE"}</span><h2>{isAgent ? "你的观影助手" : "Dify 知识问答"}</h2></div><button type="button" aria-label={`关闭${name}`} onClick={close}>×</button></header>
      <div className="assistant-mode"><span><i />{isAgent ? "智能 Agent · 实时查询" : "Dify · 常见问题"}</span><div className="assistant-session-actions"><button type="button" disabled={busy || connecting || (isAgent && !token)} onClick={() => void connect()}>恢复聊天</button><button type="button" title={`仅清空${name}的当前会话`} disabled={busy || connecting || !info} onClick={() => void reset()}>新对话</button></div></div>
      <div className="assistant-transcript" ref={scroll} role="log" aria-label={`${name}聊天记录`} aria-live="polite" aria-relevant="additions">
        {messages.length === 0 && <div className="assistant-welcome"><span className="assistant-welcome-mark">{isAgent ? "C /" : "D /"}</span><h3>{isAgent ? "查询你的观影安排" : "了解购票与观影"}</h3><p>{isAgent ? "查询电影、实时场次、座位和本人订单。提供订单号，还可以查看当前退票资格。" : "购票流程、观影须知与常见问题，都可以在这里咨询。"}</p>
          {isAgent && !token ? <button type="button" className="assistant-login" onClick={login}>登录后开始查询 →</button> : <div className="assistant-prompts">{prompts.map((text) => <button key={text} type="button" disabled={busy || connecting || !canSend} onClick={() => void send(text)}>{text}<span>↗</span></button>)}</div>}
        </div>}
        {messages.map((message) => <article key={message.id} className={`assistant-message ${message.role}${message.failed ? " incomplete" : ""}`}><span>{message.role === "user" ? "你" : name}</span>
          {message.normalizedQuestion && <details className="assistant-understanding"><summary>理解后的问题</summary><p>{message.normalizedQuestion}</p></details>}
          <p>{message.content || "正在准备回答…"}</p>{message.failed && <small>回答未完成</small>}{message.truncated && <small>较长回答仅恢复前 8000 字。</small>}
          {message.role === "assistant" && message.messageId && message.finished && <MessageFeedback messageId={message.messageId} initial={message.feedback} disabled={busy || connecting} context={context} />}
        </article>)}
        {status && <p className="assistant-status" role="status">{status}</p>}
        {error && <div className="assistant-error" role="alert"><p>{error}</p>{info && lastQuestion && <button type="button" disabled={busy || connecting} onClick={() => void send(lastQuestion)}>重试问题</button>}{!info && <button type="button" disabled={connecting} onClick={() => void connect()}>重新连接</button>}</div>}
        {info && !info.ready && <p className="assistant-status">Dify 知识问答尚未配置，请稍后再试。</p>}
      </div>
      <div className="assistant-handoff"><span>{isAgent ? "只读查询，不执行购票或退款" : "购票流程与观影常见问题"}</span></div>
      <form className="assistant-composer" onSubmit={submit}><label className="sr-only" htmlFor={`assistant-question-${channel}`}>输入你的问题</label><textarea ref={input} id={`assistant-question-${channel}`} value={question} maxLength={2000} rows={2} placeholder={isAgent ? token ? "请输入订单号或想查询的场次…" : "请先登录后查询…" : "输入你的观影问题…"} disabled={connecting || !canSend} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); if (!busy) void send(); } }} />
        {busy ? <button type="button" onClick={stop}>停止</button> : <button type="submit" disabled={!question.trim() || connecting || !canSend} aria-label={`发送${name}问题`}>发送 ↗</button>}</form>
    </section>}
  </>;
}
