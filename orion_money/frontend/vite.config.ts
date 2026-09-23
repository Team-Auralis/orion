import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies /api to the ORION FastAPI backend so the SPA never
// needs to know the backend address. The backend default is 127.0.0.1:8765
// (config api.port) — override with the ORION_API_TARGET env var if needed.
const apiTarget = process.env.ORION_API_TARGET ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});