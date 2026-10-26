/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  // En modo demo (GitHub Pages) el sitio vive bajo /panama-canal-tracker/ (ADR-0011).
  base: process.env.VITE_DEMO === 'true' ? '/panama-canal-tracker/' : '/',
  server: {
    // En desarrollo, la API va detrás del mismo origen que el frontend, como en producción: la
    // cookie del refresh y el `Origin` del WebSocket funcionan igual. El navegador sigue
    // enviando `Origin: http://localhost:5173`, que debe estar en `CORS_ORIGINS`.
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  build: {
    // Sin source maps públicos salvo decisión explícita (AGENTS.md §8.12).
    sourcemap: false,
    // MapLibre ocupa ~1 MB minificado y no se puede trocear; va en su propio chunk, cargado
    // después del login (App.tsx). El aviso sigue saltando si otro chunk crece de más.
    chunkSizeWarningLimit: 1100,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
  },
});
