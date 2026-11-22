import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: 'management',
  plugins: [react()],
  build: {
    outDir: '../dist-management',
    emptyOutDir: false,
  },
});
