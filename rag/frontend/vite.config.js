import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The backend's ALLOWED_ORIGINS in backend/.env.example lists
    // localhost:5173, so keep this port unless you change both.
    port: 5173,
  },
})
