import vue from '@vitejs/plugin-vue'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'
import Components from 'unplugin-vue-components/vite'
import { defineConfig } from 'vite'

// The dev server proxies the API to the FastAPI backend; in production the backend serves the built files itself.
export default defineConfig({
  plugins: [vue(), Components({ resolvers: [AntDesignVueResolver({ importStyle: false })], dts: false })],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  build: { chunkSizeWarningLimit: 2500 },
})
