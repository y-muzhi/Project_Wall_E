import {createRoot} from 'react-dom/client';
import {Crepe} from '@milkdown/crepe';
import {installSourceNodes} from './documents/source-nodes.ts';
import {ApiClient} from './api/client.ts';
import {WalleApi} from './api/walle.ts';
import {ApplicationRouter} from './application/router.ts';
import {Application} from './application/app.tsx';
import './shared/styles.css';

const container=document.getElementById('root')!;
async function start(){
 // A private parser context validates documents before any detail editor exists.
 // It is not a business document and is never displayed or persisted.
 const parserHost=document.createElement('div');parserHost.hidden=true;parserHost.inert=true;parserHost.setAttribute('aria-hidden','true');document.body.append(parserHost);
 const parser=new Crepe({root:parserHost,defaultValue:'',features:{[Crepe.Feature.CodeMirror]:false,[Crepe.Feature.ListItem]:false,[Crepe.Feature.LinkTooltip]:false,[Crepe.Feature.Cursor]:false,[Crepe.Feature.ImageBlock]:false,[Crepe.Feature.BlockEdit]:false,[Crepe.Feature.Toolbar]:false,[Crepe.Feature.Placeholder]:false,[Crepe.Feature.Table]:false,[Crepe.Feature.Latex]:false,[Crepe.Feature.TopBar]:false,[Crepe.Feature.AI]:false}});
 try{await installSourceNodes(parser);await parser.create();parser.setReadonly(true);
  const api=parser.editor.action(ctx=>new WalleApi(new ApiClient(),ctx));let storage:Storage|null=null;try{storage=window.sessionStorage;}catch{/* The history owner reports missing recovery storage. */}
  const router=new ApplicationRouter(api,{history:window.history,pathname:()=>location.pathname,scroll:()=>window.scrollY,scrollTop:()=>window.scrollTo(0,0),listen:listener=>{window.addEventListener('popstate',listener);return()=>window.removeEventListener('popstate',listener);}},storage);
  createRoot(container).render(<Application router={router}/>);
 }catch(error){await parser.destroy().catch(()=>undefined);parserHost.remove();throw error;}
}
void start().catch(error=>{console.error('WALL-E application initialization failed',error);container.replaceChildren();const message=document.createElement('p');message.setAttribute('role','alert');message.textContent='页面暂时无法加载，请重试。';const retry=document.createElement('button');retry.textContent='重新加载';retry.onclick=()=>location.reload();container.append(message,retry);});
