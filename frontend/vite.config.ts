import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: same-origin `/api` and `/ws` avoid CORS when using localhost vs 127.0.0.1.
// Use 127.0.0.1 (not "localhost") so Node connects via IPv4; uvicorn defaults to 127.0.0.1,
// and resolving "localhost" often hits ::1 first → ECONNREFUSED → browser sees 502.
const backend = process.env.VITE_DEV_BACKEND ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend, ws: true, changeOrigin: true },
    },
  },
})
