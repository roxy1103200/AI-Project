import test from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { compileComponent } from "./component-loader.mjs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const componentFile = fileURLToPath(new URL("../src/chat/CinemaAssistant.tsx", import.meta.url));
const { default: CinemaAssistant } = await import(await compileComponent(componentFile));
const props = { onLogin() {}, request: async () => [] };

function renderAssistant({ pending = false, token } = {}) {
  const previousStorage = globalThis.sessionStorage;
  globalThis.sessionStorage = { getItem: () => pending ? "1" : null };
  try { return renderToStaticMarkup(React.createElement(CinemaAssistant, { ...props, token })); }
  finally {
    if (previousStorage === undefined) delete globalThis.sessionStorage;
    else globalThis.sessionStorage = previousStorage;
  }
}

test("closed assistants render two distinct accessible launchers without mounting a dialog", () => {
  const html = renderAssistant();
  assert.match(html, /aria-label="打开规则问答"/);
  assert.match(html, /aria-label="打开智能 Agent"/);
  assert.equal((html.match(/aria-expanded="false"/g) ?? []).length, 2);
  assert.doesNotMatch(html, /role="dialog"/);
});

test("resuming Agent login renders only its dialog with matching active launcher", () => {
  const html = renderAssistant({ pending: true, token: "test-token" });
  assert.equal((html.match(/role="dialog"/g) ?? []).length, 1);
  assert.match(html, /role="dialog" aria-label="智能 Agent"/);
  assert.match(html, /agent-launcher is-active/);
  assert.doesNotMatch(html, /dify-launcher is-active|class="assistant-panel dify-panel"/);
  assert.match(html, /assistant-memory-entry[^>]*aria-expanded="false"/);
  assert.doesNotMatch(html, /class="assistant-memory-drawer"/);
  assert.match(html, /只读查询/);
});

test("a pending login flag alone cannot expose the authenticated Agent window", () => {
  const html = renderAssistant({ pending: true });
  assert.doesNotMatch(html, /role="dialog"|assistant-memory-entry/);
});
