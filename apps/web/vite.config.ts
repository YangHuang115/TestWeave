import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    // 端口唯一权威来源：环境变量 WEB_PORT / SERVER_PORT（缺省与 Makefile 一致）
    port: Number(process.env.WEB_PORT ?? 5173),
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.SERVER_PORT ?? 8000}`,
        ws: true,
      },
      "/health": `http://127.0.0.1:${process.env.SERVER_PORT ?? 8000}`,
    },
  },
});
