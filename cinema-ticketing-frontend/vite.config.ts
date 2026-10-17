import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
function sourceDigest(): string {
  const walk = (directory: string): string[] => readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? walk(join(directory, entry.name)) : [join(directory, entry.name)]);
  const paths = [...walk(join(root, "src")), join(root, "package.json"), join(root, "vite.config.ts")]
    .sort((left, right) => {
      const a = relative(root, left).replaceAll("\\", "/");
      const b = relative(root, right).replaceAll("\\", "/");
      return a < b ? -1 : a > b ? 1 : 0;
    });
  const hash = createHash("sha256");
  for (const path of paths) hash.update(relative(root, path).replaceAll("\\", "/")).update("\0").update(readFileSync(path));
  return hash.digest("hex");
}

const buildId = sourceDigest();
const builtAt = new Date().toISOString();
const metadata = () => ({ component: "frontend", build_id: buildId, built_at: builtAt,
  contracts: { sse: "cinema-sse-v1" }, workspace_changed: sourceDigest() !== buildId });

export default defineConfig({
  plugins: [react(), {
    name: "cinema-runtime-identity",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url?.split("?")[0] !== "/__cinema_runtime") return next();
        response.setHeader("Content-Type", "application/json"); response.setHeader("Cache-Control", "no-store");
        response.end(JSON.stringify(metadata()));
      });
    },
    transformIndexHtml() { return [{ tag: "meta", attrs: { name: "cinema-build", content: buildId }, injectTo: "head" }]; },
    generateBundle() { this.emitFile({ type: "asset", fileName: "runtime.json", source: JSON.stringify(metadata()) }); },
  }],
  server: {
    port: Number(process.env.CINEMA_WEB_PORT || 5173),
    proxy: {
      "/api": process.env.CINEMA_JAVA_PROXY || "http://localhost:8080",
      "/ai-gateway": process.env.CINEMA_GATEWAY_PROXY || "http://127.0.0.1:8010",
    },
  },
});

