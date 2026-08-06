import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import AutoImport from "unplugin-auto-import/vite";
import checker from "vite-plugin-checker";
import * as lucide from "lucide-react";

// 只把 lucide 带 Icon 后缀的别名（MapIcon / FileIcon / StarIcon ...）纳入 auto-import。
// 这组名字由 lucide 官方 PR #2328 提供，天然不与 JS 全局 / DOM / React 导出撞名。
// 配合 src/vite-env.d.ts 里的 `declare module "lucide-react"` 重定向使用。
const lucideIconNames = Object.keys(lucide).filter(
  (k) => /^[A-Z]/.test(k) && k.endsWith("Icon")
);

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    AutoImport({
      dts: "auto-imports.d.ts",
      include: [/\.[tj]sx?$/],
      imports: [
        "react",
        { "lucide-react": lucideIconNames },
      ],
      eslintrc: { enabled: false },
    }),
    checker({
      typescript: {
        tsconfigPath: "tsconfig.app.json",
      },
      // HF Docker 下 enableBuild=true 触发 TS path 解析失败 (本地能 build, HF 不行)
      // 用 tsconfig 时的 baseUrl/paths 在 checker 子进程里读不到, 关掉 build 时检查
      // 开发时仍会检查 (npm run dev)
      enableBuild: false,
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    extensions: [".mjs", ".js", ".mts", ".ts", ".jsx", ".tsx", ".json"],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('react-dom') || id.includes('/react/') || id.includes('react-router')) {
              return 'vendor-react';
            }
            if (id.includes('@tanstack/react-query')) {
              return 'vendor-query';
            }
            if (id.includes('@radix-ui')) {
              return 'vendor-radix';
            }
            if (id.includes('lucide-react')) {
              return 'vendor-lucide';
            }
          }
        },
      },
    },
  },
  server: {
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8002",
        changeOrigin: true,
        // SSE: 禁用代理缓冲，确保流式响应即时转发
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes, req, res) => {
            const contentType = proxyRes.headers["content-type"] || "";
            if (contentType.startsWith("text/event-stream")) {
              // 禁用所有缓冲
              proxyRes.headers["x-accel-buffering"] = "no";
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["connection"] = "keep-alive";
              
              // 禁用压缩（压缩会缓冲）
              delete proxyRes.headers["content-encoding"];
              
              // 立即发送响应头
              if (res.flushHeaders) {
                res.flushHeaders();
              }
            }
          });
        },
      },
    },
  },
});
