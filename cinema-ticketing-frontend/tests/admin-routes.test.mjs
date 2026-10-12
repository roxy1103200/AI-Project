import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/admin/routes.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { ADMIN_PAGES, adminView, canOpenAdmin, isAdminPath } = await import("data:text/javascript;base64," + Buffer.from(compiled).toString("base64"));

test("management routes stay distinct from customer routes and similarly named paths", () => {
  for (const path of ["/", "/movies", "/accounts", "/administrator", "/admin-preview"]) assert.equal(isAdminPath(path), false);
  for (const path of ["/admin", "/admin/", "/admin/accounts", "/admin/unknown"]) assert.equal(isAdminPath(path), true);
});

test("every management module has a unique deep link and the root opens account management", () => {
  assert.equal(adminView("/admin"), "accounts");
  assert.equal(adminView("/admin/"), "accounts");
  assert.equal(new Set(ADMIN_PAGES.map((page) => page.id)).size, ADMIN_PAGES.length);
  for (const page of ADMIN_PAGES) {
    assert.equal(adminView(`/admin/${page.id}`), page.id);
    assert.equal(adminView(`/admin/${page.id}/`), page.id);
  }
});

test("unknown and nested management pages do not silently show an unrelated module", () => {
  for (const path of ["/admin/unknown", "/admin/accounts/extra", "/accounts", "/admin/accounts-old"]) assert.equal(adminView(path), null);
});

test("only the confirmed administrator role can open management", () => {
  assert.equal(canOpenAdmin("ADMIN"), true);
  for (const role of [undefined, "USER", "admin", "", "UNKNOWN"]) assert.equal(canOpenAdmin(role), false);
});
