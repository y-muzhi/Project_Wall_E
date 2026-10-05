import { defineConfig } from 'vite';
const api = process.env.WALLE_PROBE_API_URL;
if (!api || !/^http:\/\/127\.0\.0\.1:[0-9]+$/.test(api)) throw new Error('Actual isolated API URL required');
// Verification owns an immutable source snapshot, with no live watch/WS cycle.
export default defineConfig({ server: { hmr: false, ws: false, watch: null, proxy: { '/api': { target: api } } },
  preview:{proxy:{'/api':{target:api}}},build:{emptyOutDir:false,rolldownOptions:{input:'tests/browser/api.html'}} });
