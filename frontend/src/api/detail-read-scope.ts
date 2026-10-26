/** Only in-flight reads in one detail lifetime. No resolved response cache and
 * no write deduplication. A command separates reads before and after its send. */
export class DetailReadScope {
 private epoch=0;private closed=false;private writes=0;private readonly waiters=new Set<()=>void>();
 private readonly pending=new Map<string,{controller:AbortController;consumers:Set<symbol>;promise:Promise<unknown>}>();
 get generation():number{return this.epoch;}
 beginWrite():void{this.writes++;this.invalidate();}
 endWrite():void{this.writes--;this.invalidate();if(this.writes===0){for(const resolve of this.waiters)resolve();this.waiters.clear();}}
 afterWrites():Promise<void>{if(this.closed)return Promise.reject(new DOMException('Read retired','AbortError'));return this.writes===0?Promise.resolve():new Promise(resolve=>this.waiters.add(resolve));}
 invalidate():void{this.epoch++;for(const job of this.pending.values())job.controller.abort();this.pending.clear();}
 dispose():void{this.closed=true;this.invalidate();for(const resolve of this.waiters)resolve();this.waiters.clear();}
 read<T>(key:string,signal:AbortSignal|undefined,load:(signal:AbortSignal)=>Promise<T>):Promise<T>{
  if(this.closed||signal?.aborted)return Promise.reject(new DOMException('Read retired','AbortError'));
  const epoch=this.epoch;let job=this.pending.get(key);
  if(!job){
   const controller=new AbortController(),consumers=new Set<symbol>();
   const promise=Promise.resolve().then(()=>{if(controller.signal.aborted)throw new DOMException('Read retired','AbortError');return load(controller.signal);});
   job={controller,consumers,promise};this.pending.set(key,job);
   const owned=job;void promise.finally(()=>{if(this.pending.get(key)===owned)this.pending.delete(key);}).catch(()=>undefined);
  }
  const owned=job,consumer=Symbol();owned.consumers.add(consumer);
  return new Promise<T>((resolve,reject)=>{
   let done=false;
   const release=()=>{signal?.removeEventListener('abort',abort);owned.consumers.delete(consumer);if(!owned.consumers.size&&this.pending.get(key)===owned){this.pending.delete(key);owned.controller.abort();}};
   const finish=(value:unknown,error:boolean)=>{if(done)return;done=true;release();if(error)reject(value);else resolve(value as T);};
   const abort=()=>finish(new DOMException('Read retired','AbortError'),true);
   signal?.addEventListener('abort',abort,{once:true});
   owned.promise.then(value=>{if(epoch!==this.epoch||this.closed||owned.controller.signal.aborted)abort();else finish(value,false);},error=>{if(epoch!==this.epoch||this.closed||owned.controller.signal.aborted)abort();else finish(error,true);});
  });
 }
}
