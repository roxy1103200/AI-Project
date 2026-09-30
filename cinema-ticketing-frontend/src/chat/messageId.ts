/**
 * Create an ID for a locally rendered chat message.
 *
 * `crypto.randomUUID()` is unavailable on plain HTTP pages in some browsers.
 * These IDs are only React/message-list keys, so a timestamp plus a random
 * suffix is a safe fallback when the browser is not a secure context.
 */
export function createMessageId(randomUUID: (() => string) | null = defaultRandomUUID()): string {
  if (randomUUID) return randomUUID();
  return `message-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function defaultRandomUUID(): (() => string) | null {
  if (typeof globalThis.crypto?.randomUUID !== "function") return null;
  return globalThis.crypto.randomUUID.bind(globalThis.crypto);
}
