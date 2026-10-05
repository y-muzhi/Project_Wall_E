import { defineConfig } from 'vite';
const api = process.env.WALLE_PROBE_API_URL;
if (!api || !/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(api)) throw new Error('Actual isolated API URL required');
export default defineConfig({ server: { hmr: false, proxy: { '/api': { target: api } } } });
