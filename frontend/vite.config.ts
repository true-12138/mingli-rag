import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把 /api 转给本地 FastAPI，前端代码里只写相对路径，
// 生产由 Nginx 把同样的前缀转给后端，不用改代码。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.MINGLI_API_ORIGIN || "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
