import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const modules = new Map();

async function compileComponent(file) {
  if (modules.has(file)) return modules.get(file);
  const source = await readFile(file, "utf8");
  let code = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
  }).outputText.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const imports = [...code.matchAll(/from\s+["']([^"']+)["']/g)];
  for (const [, specifier] of imports) {
    let destination;
    if (specifier.startsWith(".")) {
      const base = resolve(dirname(file), specifier);
      let dependency;
      for (const extension of [".tsx", ".ts"]) {
        try { await readFile(base + extension); dependency = base + extension; break; }
        catch (error) { if (error.code !== "ENOENT") throw error; }
      }
      assert.ok(dependency, `Cannot resolve ${specifier}`);
      destination = await compileComponent(dependency);
    } else destination = pathToFileURL(require.resolve(specifier)).href;
    code = code.replaceAll(`"${specifier}"`, JSON.stringify(destination));
  }
  const url = `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
  modules.set(file, url);
  return url;
}

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
