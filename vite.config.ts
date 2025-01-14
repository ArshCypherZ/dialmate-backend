import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '0.0.0.0', // Bind to all network interfaces
    port: 5173, 
  },
});
