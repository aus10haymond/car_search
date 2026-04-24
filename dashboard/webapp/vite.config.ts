import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // base must match the path where the portal is served in production
  base: '/portal/',
  server: {
    port: 5174,
    proxy: {
      // Forward all /portal API calls to the FastAPI backend in dev
      '/portal/auth': 'http://127.0.0.1:8000',
      '/portal/profiles': 'http://127.0.0.1:8000',
      '/portal/docs': 'http://127.0.0.1:8000',
      '/portal/settings': 'http://127.0.0.1:8000',
      '/portal/users': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: '../portal-dist',
    emptyOutDir: true,
  },
})
