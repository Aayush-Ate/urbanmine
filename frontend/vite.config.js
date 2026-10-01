import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// HTTPS=1 npm run dev -- --host  →  https://<mac-lan-ip>:5173 on your phone.
// HTTPS is what unlocks camera GPS tags + geolocation on mobile browsers.
const useHttps = process.env.HTTPS === '1'

export default defineConfig({
  plugins: [react(), ...(useHttps ? [basicSsl()] : [])],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000'
    }
  }
})
