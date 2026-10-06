import {ApiRejected,positiveInteger,snapshotObject} from '../api/client.ts';
import type {ApiAction,WalleApi} from '../api/walle.ts';
import type {Comment,CommentItem,GuideRun} from '../api/models.ts';
import type {DetailSnapshot} from '../requirements/detail-read.ts';
import {detailPermissions} from '../requirements/permissions.ts';
import {ordinaryInput} from '../shared/text.ts';
import type {SelectionEvent} from '../documents/selection.ts';
export type CommentTarget=Readonly<{document_id:number;content_version:number;block_id:number;anchor_type:'BLOCK'|'SELECTION';selection:SelectionEvent|null;quote:string}>;
export type CommentIntent=Readonly<{kind:'CREATE';target:CommentTarget}|{kind:'EDIT'|'RESOLVE'|'REOPEN'|'DELETE'|'MODIFY';comment:CommentItem}>;
export type CommentOutcome=Readonly<{kind:'COMMENT';comment:Comment}|{kind:'GUIDE';run:GuideRun}>;
export type CommentCommandState=Readonly<{phase:'READY'|'SUBMITTING'|'READING'|'UNKNOWN'|'ERROR'|'CONFIRMED';content:string;error:string|null;error_code:string|null;outcome:CommentOutcome|null;observed:Readonly<{detail:DetailSnapshot;comment:Comment|null}>|null}>;
type Api=Pick<WalleApi,'prepareCreateComment'|'prepareEditComment'|'prepareResolveComment'|'prepareReopenComment'|'prepareDeleteComment'|'prepareModifyFromComment'|'getComment'>;
const capture=<T>(value:T):T=>snapshotObject(value) as unknown as T;

/** One intention per comment owner. Recovery must first read real facts, then
 * replay the same opaque action. Matching text/status/deleted_at from a GET
 * never identifies this request. Parent retains this owner across refreshes. */
export class CommentCommand{
  readonly intent:CommentIntent;private detail:DetailSnapshot;private readonly api:Api;private action:ApiAction<Comment>|ApiAction<GuideRun>|undefined;
  private actualComment:CommentItem|null;
  private normalized:string|null=null;private readonly listeners=new Set<()=>void>();private pending:Promise<boolean>|undefined;private work:'SEND'|'READ'|undefined;private controller:AbortController|undefined;private closed=false;
  private value:CommentCommandState;
  constructor(detail:DetailSnapshot,intent:CommentIntent,api:Api){
    this.assertDetail(detail);this.detail=capture(detail);this.intent=capture(intent);this.api=api;this.actualComment=intent.kind==='CREATE'?null:capture(intent.comment);
    if(intent.kind==='CREATE')this.assertTarget(intent.target,detail);
    else if(intent.comment.requirement_id!==detail.requirement.id)throw TypeError('Owned comment required');
    this.value=Object.freeze({phase:'READY',content:intent.kind==='EDIT'?intent.comment.content:'',error:null,error_code:null,outcome:null,observed:null});
    if(!this.allowed)throw TypeError('Actual comment operation permissions required');
  }
  private assertDetail(detail:DetailSnapshot):void{positiveInteger(detail.requirement.id);if(detail.current.requirement_id!==detail.requirement.id||detail.current.document_type!=='CURRENT')throw TypeError('Actual owned CURRENT required');}
  private assertTarget(target:CommentTarget,detail:DetailSnapshot):void{
    positiveInteger(target.block_id);if(target.document_id!==detail.current.id||target.content_version!==detail.current.content_version||!detail.current.block_state_json.blocks.some(block=>block.block_id===target.block_id))throw TypeError('Current comment target required');
    if(target.anchor_type==='BLOCK'){if(target.selection!==null)throw TypeError('Block target has no selection');}
    else{const selection=target.selection;if(!selection||selection.document_id!==target.document_id||selection.content_version!==target.content_version||selection.block_id!==target.block_id||!Number.isSafeInteger(selection.start_offset)||selection.start_offset<0||selection.end_offset-selection.start_offset!==[...selection.selected_text].length||[...selection.selected_text].length<1||[...selection.selected_text].length>2000||[...selection.prefix_text].length>100||[...selection.suffix_text].length>100)throw TypeError('Original current selection required');}
  }
  getSnapshot=():CommentCommandState=>this.value;
  subscribe=(callback:()=>void):(()=>void)=>{this.listeners.add(callback);return()=>this.listeners.delete(callback);};
  get allowed():boolean{
    if(this.closed||!detailPermissions(this.detail,true).comment_write)return false;
    const intent=this.intent;if(intent.kind==='CREATE')return intent.target.document_id===this.detail.current.id&&intent.target.content_version===this.detail.current.content_version;
    const comment=this.actualComment!;if(comment.deleted_at!==null)return false;
    return intent.kind==='DELETE'||intent.kind==='REOPEN'&&comment.status==='RESOLVED'||['EDIT','RESOLVE'].includes(intent.kind)&&comment.status==='OPEN'||intent.kind==='MODIFY'&&comment.status==='OPEN'&&comment.anchor_status==='ATTACHED'&&comment.location.status==='ATTACHED';
  }
  private publish(changes:Partial<CommentCommandState>):void{if(this.closed)return;this.value=Object.freeze({...this.value,...changes});for(const callback of this.listeners)try{callback();}catch(error){console.error('WALL-E comment command observer failed',error);}}
  change(content:string):void{if(!this.closed&&!this.pending&&['CREATE','EDIT'].includes(this.intent.kind)&&['READY','ERROR'].includes(this.value.phase))this.publish({content,error:null,error_code:null});}
  rebase(actual:DetailSnapshot,comment?:CommentItem):boolean{
    if(this.closed||this.pending||!['READY','ERROR'].includes(this.value.phase))return false;this.assertDetail(actual);if(actual.requirement.id!==this.detail.requirement.id)throw TypeError('Owned actual detail required');
    if(this.intent.kind!=='CREATE'){const original=this.intent.comment;if(!comment)return false;if(comment.id!==original.id||comment.requirement_id!==original.requirement_id||comment.block_id!==original.block_id||comment.anchor_type!==original.anchor_type||comment.created_at!==original.created_at||JSON.stringify(comment.anchor_ref)!==JSON.stringify(original.anchor_ref))throw TypeError('Actual same comment origin required');this.actualComment=capture(comment);}
    this.detail=capture(actual);this.action=undefined;return true;
  }
  private run(kind:'SEND'|'READ',work:()=>Promise<boolean>):Promise<boolean>{if(this.closed)return Promise.resolve(false);if(this.pending)return this.work===kind?this.pending:Promise.resolve(false);const pending=Promise.resolve().then(()=>this.closed?false:work()).finally(()=>{if(this.pending===pending)this.pending=undefined;});this.pending=pending;this.work=kind;return pending;}
  submit():Promise<boolean>{
    if(!['READY','ERROR'].includes(this.value.phase)&&!(this.pending&&this.work==='SEND'))return Promise.resolve(false);
    return this.run('SEND',async()=>{
      if(!this.allowed){this.publish({phase:'ERROR',error:'当前状态或正文范围已变化，请重新读取并确认操作',error_code:'STATE_CONFLICT'});return false;}
      try{
        const intent=this.intent,identity=intent.kind==='CREATE'?this.detail.requirement.id:intent.comment.id;
        this.normalized=['CREATE','EDIT'].includes(intent.kind)?ordinaryInput(this.value.content,'评论正文',1,2000):null;
        switch(intent.kind){
          case 'CREATE':{const target=intent.target;this.assertTarget(target,this.detail);this.action=this.api.prepareCreateComment(identity,{expected_content_version:target.content_version,content:this.normalized!,anchor_type:target.anchor_type,block_id:target.block_id,...(target.selection?{selection:{selected_text:target.selection.selected_text,prefix_text:target.selection.prefix_text,suffix_text:target.selection.suffix_text}}:{})});break;}
          case 'EDIT':this.action=this.api.prepareEditComment(identity,this.normalized!);break;
          case 'RESOLVE':this.action=this.api.prepareResolveComment(identity);break;
          case 'REOPEN':this.action=this.api.prepareReopenComment(identity);break;
          case 'DELETE':this.action=this.api.prepareDeleteComment(identity);break;
          case 'MODIFY':this.action=this.api.prepareModifyFromComment(identity,this.detail.current.content_version);break;
        }
      }catch(error){this.publish({phase:'ERROR',error:error instanceof Error?error.message:'无法准备评论操作',error_code:'INVALID_INPUT'});return false;}
      return this.send();
    });
  }
  retryUnknown(readActual:()=>Promise<DetailSnapshot>):Promise<boolean>{
    if(this.value.phase!=='UNKNOWN'||!this.action)return Promise.resolve(false);
    return this.run('READ',async()=>{this.publish({phase:'READING',error:null});const controller=new AbortController();this.controller=controller;
      try{const detail=await readActual();if(this.closed)return false;this.assertDetail(detail);if(detail.requirement.id!==this.detail.requirement.id)throw Error('Ownership');
        const comment=this.intent.kind==='CREATE'?null:(await this.api.getComment(this.intent.comment.id,controller.signal)).data;if(this.closed)return false;
        if(comment&&(comment.id!==(this.intent as Exclude<CommentIntent,{kind:'CREATE'}>).comment.id||comment.requirement_id!==detail.requirement.id))throw Error('Ownership');
        this.publish({observed:capture({detail,comment})});
      }catch{this.publish({phase:'UNKNOWN',error:'结果仍待核实，暂时无法读取实际状态；原请求与输入已保留'});return false;}
      finally{if(this.controller===controller)this.controller=undefined;}return this.send();
    });
  }
  private async send():Promise<boolean>{
    this.publish({phase:'SUBMITTING',error:null,error_code:null});
    try{const receipt=(await this.action!.submit()).data;if(this.closed)return false;let outcome:CommentOutcome;
      if(this.intent.kind==='MODIFY'){
        const run=receipt as GuideRun,scope=run.scope;if(run.requirement_id!==this.detail.requirement.id||run.source_type!=='COMMENT'||run.source_id!==this.intent.comment.id||run.function_type!=='MODIFY_FROM_COMMENT'||run.action_type!=='MODIFY'||run.status!=='RUNNING'||run.current_step!=='PREPARING'||scope.scope_type!==this.intent.comment.anchor_type||!scope.scope_ref||!('block_id' in scope.scope_ref)||scope.scope_ref.block_id!==this.intent.comment.block_id)throw Error('Unconfirmed comment Run');outcome={kind:'GUIDE',run};
      }else{
        const comment=receipt as Comment,intent=this.intent;if(comment.requirement_id!==this.detail.requirement.id||intent.kind!=='CREATE'&&comment.id!==intent.comment.id)throw Error('Unconfirmed comment ownership');
        if(['CREATE','EDIT'].includes(intent.kind)&&comment.content!==this.normalized)throw Error('Unconfirmed content');
        if(intent.kind==='CREATE'){
          if(comment.status!=='OPEN'||comment.anchor_status!=='ATTACHED'||comment.deleted_at!==null||comment.block_id!==intent.target.block_id||comment.anchor_type!==intent.target.anchor_type)throw Error('Unconfirmed anchor');
          if(intent.target.selection){const expected=intent.target.selection;if(!('selected_text' in comment.anchor_ref)||comment.anchor_ref.selected_text!==expected.selected_text||comment.anchor_ref.prefix_text!==expected.prefix_text||comment.anchor_ref.suffix_text!==expected.suffix_text)throw Error('Unconfirmed original selection');}
          else if(!('block_markdown_snapshot' in comment.anchor_ref)||comment.anchor_ref.block_markdown_snapshot!==intent.target.quote)throw Error('Unconfirmed original block quote');
        }
        if(intent.kind!=='CREATE'&&(comment.block_id!==intent.comment.block_id||comment.anchor_type!==intent.comment.anchor_type||JSON.stringify(comment.anchor_ref)!==JSON.stringify(intent.comment.anchor_ref)||comment.created_at!==intent.comment.created_at))throw Error('Comment origin changed');
        if(intent.kind==='RESOLVE'&&(comment.status!=='RESOLVED'||comment.resolved_at===null)||intent.kind==='REOPEN'&&(comment.status!=='OPEN'||comment.resolved_at!==null)||intent.kind==='DELETE'&&comment.deleted_at===null)throw Error('Unconfirmed status');
        if(['EDIT','RESOLVE','REOPEN'].includes(intent.kind)&&comment.deleted_at!==null||intent.kind==='EDIT'&&comment.status!=='OPEN')throw Error('Unconfirmed live comment');
        outcome={kind:'COMMENT',comment};
      }
      this.publish({phase:'CONFIRMED',outcome:capture(outcome),...(['CREATE','EDIT'].includes(this.intent.kind)&&outcome.kind==='COMMENT'?{content:outcome.comment.content}:{}),error:null,error_code:null});this.action=undefined;return true;
    }catch(error){if(this.closed)return false;if(error instanceof ApiRejected&&error.code!=='REQUEST_IN_PROGRESS'){this.action=undefined;this.publish({phase:'ERROR',error:error.message,error_code:error.code});}else this.publish({phase:'UNKNOWN',error:'评论操作结果待核实，请保留原请求并重新确认'});return false;}
  }
  dispose():void{this.closed=true;this.controller?.abort();this.listeners.clear();}
}
