import { useCallback, useLayoutEffect, useRef } from "react";

export const AUTH_INVALID = "cinema-auth-invalid";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export function invalidateToken(token?: string) {
  if (token) window.dispatchEvent(new CustomEvent(AUTH_INVALID, { detail: token }));
}

export async function apiRequest<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (token) headers.set("X-Auth-Token", token);
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  const payload = await response.json().catch(() => null) as { code: number; message?: string; data: T } | null;
  init.signal?.throwIfAborted();
  if (response.status === 401 || payload?.code === 401) invalidateToken(token);
  if (!payload) throw new ApiError("服务暂时无法响应，请稍后重试", response.status);
  if (!response.ok || payload.code !== 0) throw new ApiError(payload.message ?? `请求失败（${response.status}）`, response.status);
  return payload.data;
}

/** Abort all requests and reject late results when the account workspace is removed. */
export function useScopedRequest() {
  const scope = useRef(new AbortController());
  useLayoutEffect(() => {
    // StrictMode replays effects; each mounted lifetime needs a fresh scope.
    if (scope.current.signal.aborted) scope.current = new AbortController();
    const current = scope.current;
    return () => current.abort();
  }, []);
  return useCallback(async <T,>(path: string, init: RequestInit = {}, token?: string): Promise<T> => {
    const current = scope.current;
    current.signal.throwIfAborted();
    const signal = init.signal ? AbortSignal.any([current.signal, init.signal]) : current.signal;
    const result = await apiRequest<T>(path, { ...init, signal }, token);
    current.signal.throwIfAborted();
    return result;
  }, []);
}
