import type {ReactNode} from 'react';
import {Icon} from './icon.tsx';

export type RecordListItem=Readonly<{id:number;title:ReactNode;metadata:ReactNode;description?:ReactNode;selected:boolean;disabled:boolean;label:string;open():void}>;
/** Presentation only: querying, pagination and business commands stay owned
 * by each caller. A row has one keyboard/click target and no nested controls. */
export function RecordList({title,total,loading,error,retry,retryDisabled,items,empty,filters,footer}:Readonly<{
 title:string;total:number|null;loading:boolean;error:string|null;retry():void;retryDisabled:boolean;
 items:readonly RecordListItem[];empty:ReactNode;filters?:ReactNode;footer?:ReactNode;
}>){
 return <section className="record-list" aria-label={title} aria-busy={loading}>
  <header className="record-list-heading"><h3>{title}</h3>{total!==null&&<span className="record-list-count">{total} 条</span>}<span className="read-status" role="status">{loading?'正在读取…':''}</span></header>
  {filters&&<div className="record-list-filters">{filters}</div>}
  {error&&<p className="inline-error" role="alert">{error} <button className="ui-button" type="button" disabled={retryDisabled} onClick={retry}>重试读取</button></p>}
  {items.length>0?<ol className="record-list-items">{items.map(item=><li key={item.id} data-record-id={item.id}><button type="button" className="record-list-item" aria-label={item.label} aria-pressed={item.selected} disabled={item.disabled} onClick={item.open}>
   <span className="record-item-heading"><span className="record-item-title">{item.title}</span><Icon name="right"/></span>
   <span className="record-item-metadata">{item.metadata}</span>{item.description&&<span className="record-item-description" title={typeof item.description==='string'?item.description:undefined}>{item.description}</span>}
  </button></li>)}</ol>:total!==null&&!loading&&!error&&<div className="record-list-empty">{empty}</div>}
  {footer&&<footer className="record-list-footer">{footer}</footer>}
 </section>;
}
