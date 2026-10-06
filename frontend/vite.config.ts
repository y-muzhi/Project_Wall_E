import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
const api=process.env.WALLE_API_URL??'http://127.0.0.1:8000';
if(!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(api)||Number(new URL(api).port)>65535)throw Error('WALLE_API_URL must identify the local API server.');
export default defineConfig({plugins:[react()],server:{host:'127.0.0.1',port:5173,strictPort:true,proxy:{'/api':{target:api}}},preview:{host:'127.0.0.1',port:5173,strictPort:true,proxy:{'/api':{target:api}}},build:{outDir:'dist',emptyOutDir:true}});
