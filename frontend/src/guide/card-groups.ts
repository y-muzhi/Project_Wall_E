import type {WalleApi} from '../api/walle.ts';
import type {Message} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import type {RequirementAiRead} from './read-owner.ts';
import {CardDrafts} from './card-drafts.ts';
import {InteractionCards} from './cards.ts';
export type CardSlot=Readonly<{message_id:number;owner:InteractionCards|null;loading:boolean;error:string|null}>;
export type CardGroupsState=Readonly<{slots:readonly CardSlot[];available:boolean;active:boolean;syncing:boolean;error:string|null;revision:number}>;
type Api=Pick<WalleApi,'getGuideRun'|'listMessages'|'prepareCardResponses'>;
type Actual=Readonly<{detail:DetailSnapshot;items:readonly Message[]}>;
const eligible=(message:Message)=>message.message_type==='INTERACTION_CARDS'&&message.structured_content!==null&&message.card_state!==null;
const signature=(actual:Actual)=>JSON.stringify([actual.detail.requirement,actual.detail.current.id,actual.detail.current.content_version,actual.detail.activity.kind,actual.detail.activity.kind==='GUIDE'?[actual.detail.activity.run.id,actual.detail.activity.run.status]:null,actual.items.filter(message=>eligible(message)||message.message_type==='CARD_RESPONSE')]);

/** Connects actual I35 windows to independently retained card owners. The
 * parent owns reads and Run receipts; this collection never inserts/reorders
 * messages, guesses expiration or replaces an UNKNOWN command on refresh. */
export class RequirementCardGroups{
 private value:CardGroupsState=Object.freeze({slots:[],available:false,active:true,syncing:false,error:null,revision:0});private readonly ai:RequirementAiRead;private readonly api:Api;private readonly drafts:CardDrafts;private readonly readActual:()=>Promise<DetailSnapshot>;private readonly adoptActual:(actual:DetailSnapshot)=>Promise<void>;private readonly receive:RequirementAiRead['receive'];private readonly refreshMessages:()=>Promise<void>;
 private readonly owners=new Map<number,InteractionCards>();private readonly releases=new Map<number,()=>void>();private readonly listeners=new Set<()=>void>();private readonly releaseAi:()=>void;private readonly releaseMessages:()=>void;
 private wanted:Actual|null=null;private completed:string|null=null;private pending:Promise<boolean>|undefined;private generation=0;private controller:AbortController|undefined;private closed=false;
 constructor(ai:RequirementAiRead,api:Api,drafts:CardDrafts,readActual:()=>Promise<DetailSnapshot>,adoptActual:(actual:DetailSnapshot)=>Promise<void>,receive:RequirementAiRead['receive']=ai.receive,refreshMessages:()=>Promise<void>=async()=>{if(!await ai.messages.refresh())throw Error('实际消息读取失败');}){this.ai=ai;this.api=api;this.drafts=drafts;this.readActual=readActual;this.adoptActual=adoptActual;this.receive=receive;this.refreshMessages=refreshMessages;this.releaseAi=ai.subscribe(()=>this.parentChanged());this.releaseMessages=ai.messages.subscribe(()=>this.parentChanged());this.parentChanged();}
 getSnapshot=():CardGroupsState=>this.value;subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
 private publish(changes:Partial<CardGroupsState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes,revision:this.value.revision+1});for(const listener of this.listeners)try{listener();}catch(error){console.error('WALL-E card group observer failed',error);}}
 private get enabled():boolean{return !this.closed&&this.value.available&&this.ai.getSnapshot().active&&this.ai.getSnapshot().visible;}
 private parentChanged():void{
  if(this.closed)return;const parent=this.ai.getSnapshot(),messages=this.ai.messages.getSnapshot();for(const [id,owner] of this.owners){owner.adoptDetail(parent.detail);owner.setAvailable(this.enabled&&Boolean(messages.items?.some(message=>message.id===id&&eligible(message)))&&!this.value.slots.find(slot=>slot.owner===owner)?.error);}
  if(!this.enabled){this.generation++;this.controller?.abort();return;}
  if(messages.loading||messages.error||messages.items===null)return;
  const actual={detail:parent.detail,items:messages.items};if(actual.items.some(message=>message.requirement_id!==parent.detail.requirement.id)){this.publish({error:'卡片消息所属需求异常，保留现有输入'});for(const owner of this.owners.values())owner.setAvailable(false);return;}
  this.wanted=actual;if(signature(actual)!==this.completed)void this.sync();
 }
 setAvailable(available:boolean):void{if(this.closed||available===this.value.available)return;this.publish({available});this.parentChanged();}
 get(message:number):CardSlot|null{return this.value.slots.find(slot=>slot.message_id===message)??null;}
 retry():Promise<boolean>{if(!this.enabled)return Promise.resolve(false);this.completed=null;return this.sync();}
 ready():Promise<boolean>{return this.pending??Promise.resolve(this.enabled&&this.value.error===null);}
 private sync():Promise<boolean>{
  if(!this.enabled||!this.wanted)return Promise.resolve(false);if(this.pending)return this.pending;const generation=this.generation,controller=new AbortController();this.controller=controller;const alive=()=>this.enabled&&generation===this.generation;
  const pending=Promise.resolve().then(async()=>{let success=true;
   while(alive()&&this.wanted&&signature(this.wanted)!==this.completed){
    const actual=this.wanted,key=signature(actual),cards=actual.items.filter(eligible),slots:CardSlot[]=[];success=true;
    for(const message of cards){
     if(!alive())return false;const retained=this.owners.get(message.id)??null;slots.push(Object.freeze({message_id:message.id,owner:retained,loading:true,error:null}));
    }
    this.publish({slots:Object.freeze([...slots]),syncing:true,error:null});
    for(let index=0;index<cards.length;index++){
     const message=cards[index]!;let owner=this.owners.get(message.id)??null;
     try{
      if(message.guide_run_id===null)throw Error('Card source Run missing');const run=(await this.api.getGuideRun(message.guide_run_id,controller.signal)).data;if(!alive())return false;
      // A newer parent/messages cohort supersedes this entire adoption.
      if(this.wanted!==actual&&signature(this.wanted!)!==key)break;
      if(run.id!==message.guide_run_id||run.requirement_id!==message.requirement_id)throw Error('Card source ownership');const replies=actual.items.filter(row=>row.message_type==='CARD_RESPONSE'&&row.reply_to_message_id===message.id);if(replies.length>1)throw Error('Duplicate actual card response');
      if(!owner){owner=new InteractionCards(message,run,actual.detail,this.api,this.drafts,this.readActual,this.adoptActual,this.receive,this.refreshMessages);this.owners.set(message.id,owner);this.releases.set(message.id,owner.subscribe(()=>this.publish({})));}
      owner.adopt(message,run,actual.detail,replies[0]??null);owner.setAvailable(this.enabled);slots[index]=Object.freeze({message_id:message.id,owner,loading:false,error:null});
     }catch{if(!alive())return false;success=false;owner?.setAvailable(false);slots[index]=Object.freeze({message_id:message.id,owner,loading:false,error:'原卡片运行或正式回答读取失败，现有输入仍保留'});}
     if(alive())this.publish({slots:Object.freeze([...slots])});
    }
    if(!alive())return false;if(this.wanted!==actual&&signature(this.wanted!)!==key)continue;
    this.completed=key;this.publish({slots:Object.freeze(slots),syncing:false,error:success?null:'部分卡片暂时无法读取，请重试'});
    // A damaged historical structure has no interactive slot. Retain its
    // in-memory original owner for recovery, but never expose stale controls.
    for(const [id,owner] of this.owners)if(!cards.some(message=>message.id===id))owner.setAvailable(false);
   }
   return success&&alive();
  }).catch(()=>{if(alive())this.publish({syncing:false,error:'卡片状态暂时无法同步，原输入仍保留'});return false;}).finally(()=>{if(this.pending===pending)this.pending=undefined;if(this.controller===controller)this.controller=undefined;if(!this.closed){this.publish({syncing:false});if(this.enabled&&generation!==this.generation&&this.wanted&&signature(this.wanted)!==this.completed)void this.sync();}});
  this.pending=pending;return pending;
 }
 dispose():void{if(this.closed)return;this.publish({active:false,available:false});this.closed=true;this.generation++;this.controller?.abort();this.releaseAi();this.releaseMessages();for(const release of this.releases.values())release();for(const owner of this.owners.values())owner.dispose();this.listeners.clear();}
}
