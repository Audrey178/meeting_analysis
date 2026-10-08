import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Backend does have CORS middleware now (be/main.py, ALLOWED_ORIGINS
    // env var), but proxying same-origin in dev is still simpler than
    // configuring it just for local development.
    proxy: {
      '/health': 'http://localhost:8000',
      '/meetings': 'http://localhost:8000',
      '/v3': 'http://localhost:8000',
    },
  },
})
