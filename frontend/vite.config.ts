import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const projectRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig({
  root: projectRoot,
  base: process.env.GITHUB_ACTIONS ? '/professor-research-career-dashboard/' : '/',
  publicDir: fileURLToPath(new URL('../public', import.meta.url)),
  plugins: [react()],
  server: { watch: { useFsEvents: false, usePolling: true } },
  build: { outDir: fileURLToPath(new URL('../dist', import.meta.url)), emptyOutDir: true },
});
