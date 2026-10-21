import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// The dev server proxies the API to the FastAPI backend; in production the backend serves the built files itself.
export default defineConfig({
  plugins: [vue()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  build: { chunkSizeWarningLimit: 2500 },
})
