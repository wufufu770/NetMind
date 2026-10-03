import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发期把 /api 与 /ws 代理到后端，这样开发与生产的请求形状一致：
// 都是同源相对路径。此前前端写死 `http://localhost:8000`，
// 于是「构建产物里烤进了 localhost」，换个访问地址就指错地方。
const backend = process.env.VITE_BACKEND_ORIGIN || 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend, ws: true, changeOrigin: true },
    },
  },
});
