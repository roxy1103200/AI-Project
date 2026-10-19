import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import ts from "typescript";

const require = createRequire(import.meta.url);
const modules = new Map();

/** Load actual TSX components for server-render tests without a browser or CSS runtime. */
export async function compileComponent(file) {
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
      if (!dependency) throw new Error(`Cannot resolve ${specifier}`);
      destination = await compileComponent(dependency);
    } else destination = pathToFileURL(require.resolve(specifier)).href;
    code = code.replaceAll(`"${specifier}"`, JSON.stringify(destination));
  }
  const url = `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
  modules.set(file, url);
  return url;
}
