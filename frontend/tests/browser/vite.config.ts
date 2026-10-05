import { defineConfig } from 'vite';

// Verification must exercise one loaded code version for its whole session.
export default defineConfig({server: {hmr: false,ws:false,watch:null}});
