import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

// Transpile the real transport with the project's compiler; stub only the unrelated login event.
const source = await readFile(new URL("../src/chat/chatTransport.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const authStub = "data:text/javascript," + encodeURIComponent("export function invalidateToken(token) { globalThis.revokedToken = token; };");
const transport = compiled.replace('"../auth/client"', JSON.stringify(authStub));
const { bindingStorageKey, gatewayRequest, streamChat } = await import("data:text/javascript;base64," + Buffer.from(transport).toString("base64"));

test("tab bindings separate both provider and account", () => {
  const keys = [bindingStorageKey("dify"), bindingStorageKey("agent"), bindingStorageKey("dify", 2), bindingStorageKey("agent", 2), bindingStorageKey("agent", 9)];
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(keys.every((key) => key !== "cinema-ai-binding:2"));
});

test("session, reset, stop and feedback target only their selected provider", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, headers: init.headers });
    return new Response(JSON.stringify({ ok: true }), { headers: { "Content-Type": "application/json" } });
  };
  try {
    for (const channel of ["dify", "agent"]) {
      for (const path of ["session", "reset", "stop", "feedback"]) {
        await gatewayRequest(path, {}, { channel, bindingKey: `${channel}-binding`, sessionId: `${channel}-chat` });
      }
    }
    assert.deepEqual(calls.map((call) => call.url), ["dify", "agent"].flatMap((channel) => ["session", "reset", "stop", "feedback"].map((path) => `/ai-gateway/${channel}/${path}`)));
    assert.equal(calls[0].headers.get("X-AI-Session"), "dify-binding");
    assert.equal(calls[4].headers.get("X-AI-Conversation"), "agent-chat");
  } finally { globalThis.fetch = originalFetch; }
});

test("SSE requests use independent routes without a mode-switch field", async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return new Response('data: {"type":"delta","text":"reply"}\n\ndata: {"type":"complete"}\n\n', { headers: { "Content-Type": "text/event-stream" } });
  };
  try {
    for (const channel of ["dify", "agent"]) {
      const packets = [];
      await streamChat({ sessionId: `${channel}-chat`, question: `${channel}-question` }, new AbortController().signal,
        (packet) => packets.push(packet), { channel, bindingKey: `${channel}-binding` });
      assert.equal(packets[1].type, "complete");
    }
    assert.deepEqual(calls.map((call) => call.url), ["/ai-gateway/dify/chat", "/ai-gateway/agent/chat"]);
    assert.ok(calls.every((call) => !("mode" in call.body)));
  } finally { globalThis.fetch = originalFetch; }
});

test("revoked sessions clear the matching login for HTTP and active stream failures", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.revokedToken = undefined;
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "expired" }), { status: 401, headers: { "X-Auth-Expired": "1" } });
    await assert.rejects(gatewayRequest("session", {}, { channel: "agent", bindingKey: "test", token: "matching-token" }));
    assert.equal(globalThis.revokedToken, "matching-token");
    globalThis.revokedToken = undefined;
    globalThis.fetch = async () => new Response('data: {"type":"error","code":"auth_expired","message":"expired"}\n\n');
    await assert.rejects(streamChat({}, new AbortController().signal, () => {}, { channel: "agent", bindingKey: "test", token: "stream-token" }));
    assert.equal(globalThis.revokedToken, "stream-token");
    globalThis.revokedToken = undefined;
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "temporarily unavailable" }), { status: 503 });
    await assert.rejects(gatewayRequest("session", {}, { channel: "agent", bindingKey: "test", token: "keep-token" }));
    assert.equal(globalThis.revokedToken, undefined);
  } finally { globalThis.fetch = originalFetch; delete globalThis.revokedToken; }
});
