import type { IncomingMessage, ServerResponse } from "http";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 后端未启动时避免控制台只有 ECONNREFUSED，浏览器里能看到明确提示 */
function apiProxyError(
  err: NodeJS.ErrnoException,
  _req: IncomingMessage,
  res: ServerResponse | import("socket").Socket
) {
  const code = err.code ?? "";
  const hint =
    code === "ECONNREFUSED"
      ? "请先启动后端：在 backend 目录运行 .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 3000"
      : `代理错误 (${code}): ${err.message}\n若正在保存后端代码，多为热重载断连，稍后刷新即可。`;
  if ("writeHead" in res && typeof res.writeHead === "function" && !res.headersSent) {
    res.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
    res.end(`ProManager /api 代理: ${hint}\n`);
  }
}

const apiProxy = {
  target: "http://127.0.0.1:3000",
  changeOrigin: true,
  timeout: 120_000,
  proxyTimeout: 120_000,
  configure(proxy: import("http-proxy").default) {
    proxy.on("error", apiProxyError);
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3008,
    proxy: { "/api": apiProxy },
  },
  // `npm run preview` 默认不代理，会导致 /api 打到静态服务而 500/404
  preview: {
    port: 3008,
    proxy: { "/api": apiProxy },
  },
});
