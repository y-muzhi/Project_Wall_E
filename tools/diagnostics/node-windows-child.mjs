// Isolated transport/runtime reproducer: no application DB, credentials or model calls.
import {createServer, request} from 'node:http';
import {once} from 'node:events';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
const [mode,root,outDir]=process.argv.slice(2);
if(mode==='fetch-exit') {
  const response=await fetch(process.env.WALLE_DIAGNOSTIC_URL); await response.text();
  console.log(JSON.stringify({completed:true,node:process.version}));
  // Deliberately exercise upstream's abrupt teardown reproducer.
  process.exit(0);
}
let server;
if(mode==='http') {
  server=createServer((incoming,outgoing)=>{
    const proxy=request(process.env.WALLE_DIAGNOSTIC_URL+incoming.url, {method:incoming.method}, response=>response.pipe(outgoing));
    proxy.on('error',()=>{if(!outgoing.headersSent)outgoing.writeHead(502);outgoing.end();});
    incoming.on('aborted',()=>proxy.destroy());outgoing.on('close',()=>proxy.destroy());incoming.pipe(proxy);
  });server.listen(0,'127.0.0.1');await once(server,'listening');
} else {
  process.env.WALLE_PROBE_API_URL=process.env.WALLE_DIAGNOSTIC_URL;
  const {createServer:dev,preview}=await import(pathToFileURL(resolve(root,'frontend/node_modules/vite/dist/node/index.js')).href);
  const common={root:resolve(root,'frontend'),configFile:resolve(root,'frontend/tests/browser/api-vite.config.ts'),logLevel:'error'};
  const instance= mode==='preview'?await preview({...common,build:{outDir},preview:{port:0,host:'127.0.0.1'}}):await dev({...common,server:{port:0,host:'127.0.0.1'}});
  if(mode==='dev')await instance.listen();server=instance.httpServer;
  process.stdin.once('data',async()=>{await instance.close();process.stdin.destroy();console.log(JSON.stringify({closed:true}));});
}
console.log(JSON.stringify({ready:true,url:`http://127.0.0.1:${server.address().port}`,node:process.version,mode}));
if(mode==='http')process.stdin.once('data',()=>{server.closeAllConnections();server.close(()=>{process.stdin.destroy();console.log(JSON.stringify({closed:true}));});});
