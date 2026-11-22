import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 本地静态资源通过 e2s://app/ 加载，使用相对基路径保证离线可用。
export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
});
