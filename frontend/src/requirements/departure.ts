export type DepartureState=Readonly<{phase:'IDLE'|'SAVING'|'WARNING'|'LEAVING';local_protected:boolean;error:string|null}>;
export interface DepartureDocument{prepareLeave():Promise<Readonly<{saved:boolean;local_protected:boolean}>>;continueAfterFailedLeave():boolean;}
/** Navigation permission is distinct from saving, cancellation and retirement.
 * An explicit failed-save departure never deletes either persistent draft. */
export class DetailDeparture{
 private value:DepartureState=Object.freeze({phase:'IDLE',local_protected:false,error:null});private closed=false;private next:(()=>void)|null=null;private pending:Promise<void>|null=null;private readonly listeners=new Set<()=>void>();private readonly document:DepartureDocument;
 constructor(document:DepartureDocument){this.document=document;}
 getSnapshot=():DepartureState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<DepartureState>){if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const listener of this.listeners)listener();}
 request(next:()=>void):Promise<void>{
  if(this.closed||this.value.phase!=='IDLE')return this.pending??Promise.resolve();this.next=next;this.publish({phase:'SAVING',error:null});
  const pending=Promise.resolve().then(()=>this.document.prepareLeave()).then(result=>{if(this.closed)return;if(result.saved)this.leave();else this.publish({phase:'WARNING',local_protected:result.local_protected,error:null});}).catch(()=>{this.publish({phase:'WARNING',local_protected:false,error:'保存结果尚未确认，当前内容仍保留，请先继续编辑或明确离开。'});}).finally(()=>{if(this.pending===pending)this.pending=null;});this.pending=pending;return pending;
 }
 continueEditing():boolean{if(this.closed||this.value.phase!=='WARNING')return false;if(!this.document.continueAfterFailedLeave()){this.publish({error:'编辑保护暂时无法解除，内容仍保留，请在本页读取最新状态后处理。'});return false;}this.next=null;this.publish({phase:'IDLE',error:null});return true;}
 confirmLeave():boolean{if(this.closed||this.value.phase!=='WARNING')return false;return this.leave();}
 private leave():boolean{const next=this.next;if(this.closed||!next)return false;this.next=null;this.publish({phase:'LEAVING',error:null});try{next();return true;}catch{this.next=next;this.publish({phase:'WARNING',error:'页面暂时无法离开，草稿仍保留，请继续编辑或重试离开。'});return false;}}
 dispose():void{this.closed=true;this.next=null;this.listeners.clear();}
}
