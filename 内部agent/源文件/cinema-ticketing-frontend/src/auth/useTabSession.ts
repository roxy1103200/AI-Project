import { useEffect, useRef, useState } from "react";
import { AUTH_INVALID, ApiError, apiRequest } from "./client";

export type LoginPayload = { token: string; userId: number; username: string; role: string; expiresInSeconds: number };
export type StoredSession = LoginPayload & { expiresAt: number };
type Identity = Omit<LoginPayload, "token">;
const STORAGE_KEY = "cinema-auth";

function clearChatBindings() {
  for (const key of Object.keys(sessionStorage)) {
    if (key.startsWith("cinema-ai-binding:")) sessionStorage.removeItem(key);
  }
}

function readCandidate(): StoredSession | null {
  // Shared legacy login cannot be safely attributed to either tab.
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem("cinema-auth-token");
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "null") as StoredSession | null;
    if (value?.token && value.expiresAt > Date.now()) return value;
  } catch { /* Ignore a damaged local candidate; identity still requires the server. */ }
  sessionStorage.removeItem(STORAGE_KEY);
  return null;
}

function persist(token: string, identity: Identity): StoredSession {
  if (!["ADMIN", "USER"].includes(identity.role) || identity.expiresInSeconds <= 0) throw new Error("服务端登录身份无效");
  const value = { ...identity, token, expiresAt: Date.now() + identity.expiresInSeconds * 1000 };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  return value;
}

export function useTabSession() {
  const [session, setSession] = useState<StoredSession | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const generation = useRef(0);
  const operation = useRef<AbortController | null>(null);
  const currentToken = useRef<string | null>(null);

  function clear() {
    generation.current++;
    operation.current?.abort();
    currentToken.current = null;
    sessionStorage.removeItem(STORAGE_KEY);
    clearChatBindings();
    sessionStorage.removeItem("cinema-ai-handoff-pending");
    sessionStorage.removeItem("cinema-agent-login-pending");
    setSession(null); setChecking(false); setError("");
  }

  useEffect(() => {
    const candidate = readCandidate();
    const version = ++generation.current;
    const abort = new AbortController(); operation.current = abort;
    currentToken.current = candidate?.token ?? null;
    setChecking(true); setError("");
    if (!candidate) { setChecking(false); return () => abort.abort(); }
    void apiRequest<Identity>("/api/auth/me", { signal: abort.signal }, candidate.token).then((identity) => {
      if (generation.current === version) setSession(persist(candidate.token, identity));
    }).catch((cause) => {
      if (generation.current !== version || abort.signal.aborted) return;
      if (cause instanceof ApiError && cause.status === 401) clear();
      else setError(cause instanceof Error ? cause.message : "身份核验失败");
    }).finally(() => { if (generation.current === version) setChecking(false); });
    return () => abort.abort();
  }, [retry]);

  useEffect(() => {
    const invalid = (event: Event) => {
      if ((event as CustomEvent<string>).detail === currentToken.current) clear();
    };
    window.addEventListener(AUTH_INVALID, invalid);
    return () => { window.removeEventListener(AUTH_INVALID, invalid); operation.current?.abort(); };
  }, []);

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(clear, Math.max(0, session.expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [session]);

  async function signIn(username: string, password: string): Promise<void> {
    const version = ++generation.current;
    operation.current?.abort();
    const abort = new AbortController(); operation.current = abort;
    const payload = await apiRequest<LoginPayload>("/api/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }), signal: abort.signal,
    });
    if (generation.current !== version) throw new DOMException("登录已取消", "AbortError");
    const verified = persist(payload.token, payload);
    clearChatBindings();
    currentToken.current = payload.token;
    setSession(verified); setError(""); setChecking(false);
  }

  function signOut() {
    const token = currentToken.current;
    clear();
    if (token) void apiRequest("/api/auth/logout", { method: "POST" }, token).catch(() => undefined);
  }

  return { session, checking, error, signIn, signOut, forgetSession: clear, retry: () => setRetry((value) => value + 1) };
}
