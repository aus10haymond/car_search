import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ping':     BACKEND,
      '/profiles': BACKEND,
      '/runs':     BACKEND,
      '/history':  BACKEND,
      '/setup':    BACKEND,
      '/settings': BACKEND,
      '/docs':     BACKEND,
    },
  },
})
