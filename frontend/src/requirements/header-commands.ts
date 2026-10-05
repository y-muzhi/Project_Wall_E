import {snapshotObject} from '../api/client.ts';
import type {WalleApi} from '../api/walle.ts';
import type {DetailSnapshot} from './detail-read.ts';
import {RequirementPropertyEdit} from './property-edit.ts';
import {RequirementLifecycle} from './lifecycle.ts';
import type {LifecycleOperation} from './lifecycle.ts';
import {ManualDraftStart} from '../documents/manual-start.ts';
import {detailPermissions} from './permissions.ts';

export type HeaderOwner='TITLE'|'MODE'|'LIFECYCLE'|'MANUAL';
export type HeaderCommandState=Readonly<{detail:DetailSnapshot;lifecycle:RequirementLifecycle|null;manual:ManualDraftStart|null;revision:number;lifecycle_generation:number;manual_generation:number}>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;
const signature=(detail:DetailSnapshot)=>JSON.stringify([detail.requirement.status,detail.requirement.document_work_state,detail.current.id,detail.current.content_version]);

/** Owns header intentions for one requirement. Actual full detail replaces
 * facts, not unsent input or an unknown original command. Never touches the
 * document editor, its local ledger, saves, cache, or business cancellation. */
export class RequirementHeaderCommands {
  readonly title:RequirementPropertyEdit;readonly mode:RequirementPropertyEdit;private readonly api:WalleApi;
  private value:HeaderCommandState;private closed=false;private adopting=false;private readonly listeners=new Set<()=>void>();
  private readonly propertyReleases:(()=>void)[];private lifecycleRelease:(()=>void)|undefined;private manualRelease:(()=>void)|undefined;
  private lifecycleSignature='';private manualSignature='';
  constructor(detail:DetailSnapshot,api:WalleApi){
    this.api=api;const actual=capture(detail);this.value=Object.freeze({detail:actual,lifecycle:null,manual:null,revision:0,lifecycle_generation:0,manual_generation:0});
    this.title=new RequirementPropertyEdit('title',actual,api);this.mode=new RequirementPropertyEdit('initialization_mode',actual,api);
    this.propertyReleases=[this.title.subscribe(()=>this.notify()),this.mode.subscribe(()=>this.notify())];this.adopt(actual);
  }
  getSnapshot=():HeaderCommandState=>this.value;
  subscribe=(listener:()=>void):(()=>void)=>{this.listeners.add(listener);return()=>this.listeners.delete(listener);};
  private notify():void{
    if(this.closed||this.adopting)return;this.value=Object.freeze({...this.value,revision:this.value.revision+1});
    for(const listener of this.listeners){try{listener();}catch(error){console.error('WALL-E header observer failed',error);}}
  }
  blockedFor(owner:HeaderOwner):boolean {
    const ownPhase=owner==='TITLE'?this.title.getSnapshot().phase:owner==='MODE'?this.mode.getSnapshot().phase:owner==='LIFECYCLE'?this.value.lifecycle?.getSnapshot().phase:this.value.manual?.getSnapshot().phase;
    // Multiple requests can become unknown through independent activity.
    // Reads/original recovery must not deadlock each other; new writes remain
    // blocked after returning to EDITING/READY.
    if(ownPhase&&['UNKNOWN','OBSERVED','CONFIRMED','STARTED'].includes(ownPhase))return false;
    const property=(flow:RequirementPropertyEdit)=>['SUBMITTING','UNKNOWN','READING','OBSERVED','CONFIRMED'].includes(flow.getSnapshot().phase);
    return (owner!=='TITLE'&&property(this.title))||(owner!=='MODE'&&property(this.mode))||
      (owner!=='LIFECYCLE'&&!!this.value.lifecycle&&['SUBMITTING','READING','UNKNOWN','CONFIRMED'].includes(this.value.lifecycle.getSnapshot().phase))||
      (owner!=='MANUAL'&&!!this.value.manual&&['SUBMITTING','CHECKING','UNKNOWN','STARTED'].includes(this.value.manual.getSnapshot().phase));
  }
  /** Only a complete actual read may be passed here. READY baselines change
   * when source changes; uncertain actions keep their original version/key. */
  adopt(detail:DetailSnapshot):void{
    if(this.closed)return;const old=this.value;
    if(detail.requirement.id!==old.detail.requirement.id||detail.current.document_type!=='CURRENT'||detail.current.requirement_id!==detail.requirement.id)throw TypeError('Owned complete detail required');
    const actual=capture(detail),nextSignature=signature(actual),permissions=detailPermissions(actual,true);
    this.adopting=true;
    try{
      this.title.adoptDetail(actual);this.mode.adoptDetail(actual);
      let lifecycle=old.lifecycle,manual=old.manual;
      const protectedLife=lifecycle&&['SUBMITTING','READING','UNKNOWN'].includes(lifecycle.getSnapshot().phase);
      if(!protectedLife&&(!lifecycle||this.lifecycleSignature!==nextSignature||['ERROR','CONFIRMED'].includes(lifecycle.getSnapshot().phase))){
        this.lifecycleRelease?.();lifecycle?.dispose();const operation:LifecycleOperation|null=permissions.complete_initialization?'INITIALIZATION':permissions.complete_requirement?'COMPLETE':permissions.reactivate?'REACTIVATE':null;
        lifecycle=operation?new RequirementLifecycle(operation,actual,this.api):null;this.lifecycleSignature=nextSignature;
        this.lifecycleRelease=lifecycle?.subscribe(()=>this.notify());
      }
      const protectedStart=manual&&['SUBMITTING','CHECKING','UNKNOWN'].includes(manual.getSnapshot().phase);
      if(!protectedStart&&(!manual||this.manualSignature!==nextSignature||['ERROR','STARTED'].includes(manual.getSnapshot().phase))){
        this.manualRelease?.();manual?.dispose();manual=permissions.manual_start?new ManualDraftStart(actual.requirement,actual.current,this.api):null;
        this.manualSignature=nextSignature;this.manualRelease=manual?.subscribe(()=>this.notify());
      }
      this.value=Object.freeze({detail:actual,lifecycle,manual,revision:old.revision,lifecycle_generation:old.lifecycle_generation+(lifecycle!==old.lifecycle?1:0),manual_generation:old.manual_generation+(manual!==old.manual?1:0)});
    }finally{this.adopting=false;}this.notify();
  }
  dispose():void{if(this.closed)return;this.closed=true;for(const release of this.propertyReleases)release();this.lifecycleRelease?.();this.manualRelease?.();
    this.title.dispose();this.mode.dispose();this.value.lifecycle?.dispose();this.value.manual?.dispose();this.listeners.clear();}
}
