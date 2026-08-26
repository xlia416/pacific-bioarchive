import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 前端构建。把 API 基址与 Cognito 配置在 build 时用环境变量注入，
// 或在运行时通过 /config.js 覆盖（用作静态托管时部署脚本会写入）。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});