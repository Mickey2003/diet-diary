import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    target: 'es2018',
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/') ||
            id.includes('node_modules/react-router-dom/') ||
            id.includes('node_modules/react-router/')
          ) {
            return 'react';
          }
          if (
            id.includes('node_modules/antd/') ||
            id.includes('node_modules/@ant-design/') ||
            id.includes('node_modules/rc-')
          ) {
            return 'antd';
          }
          if (
            id.includes('node_modules/echarts/') ||
            id.includes('node_modules/echarts-for-react/') ||
            id.includes('node_modules/zrender/')
          ) {
            return 'echarts';
          }
          if (id.includes('node_modules/@zxing/')) {
            return 'zxing';
          }
          if (id.includes('node_modules/dayjs/')) {
            return 'dayjs';
          }
        },
      },
    },
  },
});
