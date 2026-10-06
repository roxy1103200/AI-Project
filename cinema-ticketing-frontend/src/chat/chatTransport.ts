import { invalidateToken } from "../auth/client";

export type ChatEvent = { type: string; text?: string; message?: string; code?: string; messageId?: string; normalized_question?: string };
export type ChatChannel = "dify" | "agent";
export type ChatContext = { channel: ChatChannel; bindingKey: string; sessionId?: string; token?: string };

/** Provider routes and tab bindings never fall back to the old mixed conversation. */
export function bindingStorageKey(channel: ChatChannel, userId?: number): string {
  return `cinema-ai-binding:${channel}:${userId ?? "guest"}`;
}

export function gatewayPath(channel: ChatChannel, path: string): string {
  return `/ai-gateway/${channel}/${path}`;
}

function contextHeaders(context: ChatContext, original?: HeadersInit): Headers {
  const headers = new Headers(original);
  if (context.bindingKey) headers.set("X-AI-Session", context.bindingKey);
  if (context.sessionId) headers.set("X-AI-Conversation", context.sessionId);
  if (context.token) headers.set("X-Auth-Token", context.token);
  return headers;
}

function checkLogin(response: Response, context: ChatContext) {
  if (response.status === 401 && response.headers.get("X-Auth-Expired") === "1") invalidateToken(context.token);
}

export class GatewayError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function gatewayRequest<T>(path: string, init: RequestInit, context: ChatContext): Promise<T> {
  const response = await fetch(gatewayPath(context.channel, path), { ...init, headers: contextHeaders(context, init.headers), credentials: "omit", cache: "no-store" });
  const payload = await response.json().catch(() => null);
  init.signal?.throwIfAborted();
  checkLogin(response, context);
  if (!response.ok) throw new GatewayError(typeof payload?.detail === "string" ? payload.detail : "助手连接失败，请稍后重试", response.status);
  return payload as T;
}

/** Parse complete SSE frames, including frames split across UTF-8 network chunks. */
export async function streamChat(body: object, signal: AbortSignal, onEvent: (event: ChatEvent) => void, context: ChatContext): Promise<void> {
  const response = await fetch(gatewayPath(context.channel, "chat"), {
    method: "POST", credentials: "omit", headers: contextHeaders(context, { "Content-Type": "application/json" }),
    body: JSON.stringify(body), signal,
  });
  signal.throwIfAborted();
  checkLogin(response, context);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new GatewayError(typeof payload?.detail === "string" ? payload.detail : "助手暂时无法响应，请稍后再试", response.status);
  }
  if (!response.body) throw new Error("浏览器无法接收流式回答");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let complete = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let boundary: RegExpExecArray | null;
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const raw = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
        if (!raw || raw === "[DONE]") continue;
        const packet = JSON.parse(raw) as ChatEvent;
        if (packet.type === "error") {
          onEvent(packet);
          throw new Error(packet.message ?? "回答失败，请稍后重试");
        }
        if (packet.type === "complete") complete = true;
        onEvent(packet);
      }
      if (buffer.length > 300000) throw new Error("回答数据过长，请重新提问");
      if (done) break;
    }
    if (!complete) throw new Error("回答连接中断，请重试");
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
