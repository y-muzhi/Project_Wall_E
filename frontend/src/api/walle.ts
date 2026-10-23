/** Explicit V1.5 API bindings. Each action owns its original body/key and
 * response expectations; retry is a caller decision on the same action.
 */
import type { Ctx } from '@milkdown/kit/ctx';
import type { BlockState } from '../documents/contracts.ts';
import { ApiClient, ApiUnknown, ApiRejected, snapshotObject } from './client.ts';
import type { ApiSuccess, JsonObject } from './client.ts';
import { array, checked, shape, id, require, distinct,choices } from './decoding.ts';
import type { Decoder } from './decoding.ts';
import * as models from './models.ts';
import {modelCalls,modelCallDetail} from './model-calls.ts';
import {suggestionMarkdown} from '../suggestions/preview.ts';

export type ApiAction<T> = Readonly<{ submit: (signal?: AbortSignal) => Promise<ApiSuccess<T>> }>;
const sameJson=(left:unknown,right:unknown)=>JSON.stringify(left,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value)===JSON.stringify(right,(_key,value)=>value&&typeof value==='object'&&!Array.isArray(value)?Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b))):value);
export type RequirementFilters = Readonly<{ keyword?: string; status?: readonly (typeof models.requirementStatuses[number])[];
  requirement_type?: readonly (typeof models.requirementTypes[number])[]; page?: number }>;
export type GuideFilters = Readonly<{ status?: readonly (typeof models.runStatuses[number])[]; action_type?: readonly (typeof models.runActions[number])[]; page?: number }>;
export type CreateRequirement = Readonly<{ title: string; requirement_type: 'NEW' | 'CHANGE'; initial_idea: string }>;
export type DiscussionCommand=Readonly<
 {type:'SET_BINDING';target_document_id:number|null;source_refs:readonly ReturnType<typeof models.sourceRef>[];scope:Readonly<JsonObject>|null}|
 {type:'SET_FOCUS';topic_ref:string}|{type:'CHANGE_PHASE';phase_kind:typeof models.phaseKinds[number];closure_message:string|null;unresolved_refs:readonly string[]}|
 {type:'SET_DISPOSITION';subject_ref:string;decision:'DEFER'|'NOT_APPLICABLE'|'DECLINE_DRAFT';description:string}>;
export type CreateDocument=Readonly<{name:string;document_kind:typeof models.documentKinds[number];template_ref:ReturnType<typeof models.resourceRef>|null}>;
export type DocumentChange=Readonly<{type:'RENAME';name:string}|{type:'ARCHIVE'|'RESTORE'}|{type:'CONFIRM';expected_content_version:number;revision_id:number}>;
export type CreateGuide = Readonly<{expected_discussion_version:number;operation:typeof models.operations[number];instruction:string;
 target:ReturnType<typeof models.targetRef>|null;scope:Readonly<JsonObject>|null;source_refs:readonly ReturnType<typeof models.sourceRef>[];
 proposal_ref:Readonly<{message_id:number;card_key:string}>|null;acknowledge_source_changes:boolean}>;
export type CreateComment = Readonly<{ document_id:number;expected_content_version: number; content: string; anchor_type: 'BLOCK' | 'SELECTION'; block_id: number;
  selection?: Readonly<{ selected_text: string; prefix_text: string; suffix_text: string }> }>;
const root = '/api/v1';
const target = (collection: string, identity: number, suffix = '') => `${root}/${collection}/${id(identity)}${suffix}`;
const owned = <T extends { requirement_id: number }>(decode: Decoder<T>, identity: number) => checked(decode, value => require(value.requirement_id === identity));
const identified = <T extends { id: number }>(decode: Decoder<T>, identity: number) => checked(decode, value => require(value.id === identity));

function bodyFields(value: JsonObject, mandatory: readonly string[], optional: readonly string[] = []): void {
  require(mandatory.every(key => Object.hasOwn(value, key)) && Object.keys(value).every(key => [...mandatory, ...optional].includes(key)));
}
function query(filters: RequirementFilters | GuideFilters): readonly (readonly [string, string])[] {
  const result: [string, string][] = [];
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value)) for (const item of value) result.push([key, item]);
    else if (value !== undefined) result.push([key, String(value)]);
  }
  return result;
}

export class WalleApi {
  private readonly client: ApiClient; private readonly ctx: Ctx;
  constructor(client: ApiClient, ctx: Ctx) { this.client = client; this.ctx = ctx; }
  previewMarkdown(markdown:string,columns?:number):DocumentFragment { return suggestionMarkdown(this.ctx,markdown,columns); }
  private action<T>(method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body: unknown | null,
                    decoder: (original: JsonObject | null) => Decoder<T>, status: 200 | 201 | 202 | readonly (200|201|202)[] = 200, keyed = true): ApiAction<T> {
    const original = body === null ? null : snapshotObject(body);
    const decode = decoder(original), handle = this.client.prepare(method, path, original, { idempotent: keyed, success_status: status });
    return Object.freeze({ submit: async (signal?: AbortSignal) => {
      const response = await this.client.commit(handle, decode, signal);
      if (response.meta.pagination !== undefined) throw new ApiUnknown(true);
      return response;
    } });
  }
  private async single<T>(path: string, decode: Decoder<T>, signal?: AbortSignal,parameters:readonly(readonly[string,string])[]=[]) {
    const response = await this.client.read(path, decode, parameters, signal);
    if (response.meta.pagination !== undefined) throw new ApiUnknown(false);
    return response;
  }
  private async page<T extends { id: number }>(path: string, decode: Decoder<T>, parameters: readonly (readonly [string, string])[], requestedPage: number, signal?: AbortSignal) {
    id(requestedPage); require(requestedPage <= 100000);
    const response = await this.client.read(path, shape({ items: array(decode, 20) }), parameters, signal);
    try {
      const pagination = response.meta.pagination;
      require(pagination !== undefined && 'page' in pagination && pagination.page === requestedPage);
      require(response.data.items.length === Math.min(20, Math.max(0, pagination.total - (requestedPage - 1) * 20)));
      distinct(response.data.items.map(item => item.id));
      return response;
    } catch { throw new ApiUnknown(false); }
  }
  private current = (identity: number) => owned(models.documentDecoder(this.ctx, 'CURRENT'), identity);
  private draft = (identity: number) => owned(models.documentDecoder(this.ctx, 'MANUAL_DRAFT'), identity);

  // I01 / I03 / I08 / I10 / I24 / I25 / I27 / I28 / I16 / I19 / I20 / I35 / I37.
  listRequirements(filters: RequirementFilters = {}, signal?: AbortSignal) {
    return this.page(`${root}/requirements`, models.requirementSummary, query(filters), filters.page ?? 1, signal);
  }
  getRequirementDetail(identity:number,signal?:AbortSignal,expandDiscussion=false){
    const decode=checked(models.requirementDetail,value=>{
      require(value.requirement.id===identity);require(expandDiscussion===(value.discussion!==null));
    });
    return this.single(target('requirements',identity),decode,signal,expandDiscussion?[['expand','discussion']]:[]);
  }
  async getRequirement(identity: number, signal?: AbortSignal) { const response=await this.getRequirementDetail(identity,signal);return {...response,data:response.data.requirement}; }
  getCurrentDocument(identity: number,documentId:number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/current-document'), checked(this.current(identity),document=>require(document.id===documentId)), signal,[['document_id',String(id(documentId))]]); }
  getManualDraft(identity: number,documentId:number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/manual-draft'), checked(this.draft(identity),draft=>require(draft.target_document_id===documentId)), signal,[['document_id',String(id(documentId))]]); }
  listRevisions(identity: number,documentId:number, page = 1, signal?: AbortSignal) { return this.page(target('requirements', identity, '/revisions'), checked(owned(models.revisionSummary, identity),row=>require(row.document_id===documentId)), [['document_id',String(id(documentId))],['page', String(page)]], page, signal); }
  getRevision(identity: number, signal?: AbortSignal) { return this.single(target('revisions', identity), identified(models.revisionDecoder(this.ctx), identity), signal); }
  listComments(identity: number,documentId:number, page = 1, signal?: AbortSignal) { return this.page(target('requirements', identity, '/comments'), checked(owned(models.commentItem, identity),comment=>require(comment.document_id===documentId)), [['document_id',String(id(documentId))],['page', String(page)]], page, signal); }
  getComment(identity: number, signal?: AbortSignal) { return this.single(target('comments', identity), identified(models.comment, identity), signal); }
  getGuideRun(identity: number, signal?: AbortSignal) { return this.single(target('guide-runs', identity), identified(models.guideRun, identity), signal); }
  listModelCalls(identity:number,signal?:AbortSignal){return this.single(target('guide-runs',identity,'/model-calls'),identified(modelCalls,identity),signal);}
  getModelCall(identity:number,signal?:AbortSignal){return this.single(target('model-calls',identity),checked(modelCallDetail,value=>require(value.call.id===identity)),signal);}
  listGuideRuns(identity: number, filters: GuideFilters = {}, signal?: AbortSignal) { return this.page(target('requirements', identity, '/guide-runs'), owned(models.guideSummary, identity), query(filters), filters.page ?? 1, signal); }
  getBatch(identity: number, signal?: AbortSignal) { return this.single(target('suggestion-batches', identity), identified(models.batch, identity), signal); }
  getCommentIndex(identity: number,documentId:number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/comment-index'), checked(owned(models.commentIndex, identity),index=>require(index.document_id===documentId)), signal,[['document_id',String(id(documentId))]]); }
  async listMessages(identity: number, before: number | null = null, signal?: AbortSignal) {
    const parameters: [string, string][] = before === null ? [] : [['before_sequence_no', String(id(before))]];
    const response = await this.client.read(target('requirements', identity, '/messages'), shape({ items: array(owned(models.message, identity), 20) }), parameters, signal);
    try {
      const pagination = response.meta.pagination; require(pagination !== undefined && 'has_more' in pagination);
      const sequences = response.data.items.map(item => item.sequence_no); distinct(sequences); distinct(response.data.items.map(item => item.id));
      require(sequences.every((value, index) => (index === 0 || sequences[index - 1]! < value) && (before === null || value < before)));
      require(!pagination.has_more || (sequences.length > 0 && pagination.next_cursor === sequences[0]));
      return response;
    } catch { throw new ApiUnknown(false); }
  }

  // I02 / I04 / I05 / I06 / I07.
  prepareCreateRequirement(body: CreateRequirement) { return this.action('POST', `${root}/requirements`, body, original => {
    bodyFields(original!, ['title', 'requirement_type', 'initial_idea']);
    return checked(shape({ requirement: models.requirement, initial_message_id: id, documents: array(models.documentDecoder(this.ctx, 'CURRENT'), 0) }), value => {
      require(value.requirement.status === 'PLANNING' && value.requirement.document_work_state === 'IDLE' && value.requirement.initial_message_id === value.initial_message_id);
      for (const field of ['title', 'requirement_type'] as const) require(value.requirement[field] === original![field]);
    });
  }, 201); }
  prepareUpdateRequirement(identity: number, body: Readonly<{ expected_metadata_version: number; changes: Readonly<{ title?: string; status?: models.Requirement['status'] }> }>) {
    return this.action('PATCH', target('requirements', identity), body, original => {
      bodyFields(original!, ['expected_metadata_version', 'changes']); id(original!.expected_metadata_version);
      const changes=snapshotObject(original!.changes);
      require(Object.keys(changes).length>0&&Object.keys(changes).every(key=>key==='title'||key==='status'));
      if(Object.hasOwn(changes,'status'))choices(models.requirementStatuses)(changes.status);
      return checked(identified(models.requirement, identity), value => {
        require(Object.entries(changes).every(([key, submitted]) => value[key as 'title' | 'status'] === submitted));
      });
    });
  }

  // I09 / I11 / I12 / I13 / I26. Draft version never substitutes CURRENT version.
  prepareUpdateDiscussion(identity:number,body:Readonly<{expected_discussion_version:number;discussion_command:DiscussionCommand}>){
    return this.action('PATCH',target('requirements',identity),body,original=>{
      bodyFields(original!,['expected_discussion_version','discussion_command']);const version=id(original!.expected_discussion_version);
      return checked(shape({requirement_id:id,discussion_version:id,discussion:models.discussionState}),value=>{
        require(value.requirement_id===identity&&(value.discussion_version===version||value.discussion_version===version+1));
        const command=original!.discussion_command as JsonObject;
        if(command.type==='SET_FOCUS')require(value.discussion.focus_topic_ref===command.topic_ref);
        if(command.type==='CHANGE_PHASE')require(value.discussion.phase.kind===command.phase_kind);
        if(command.type==='SET_BINDING')require(value.discussion.binding.target_document_id===command.target_document_id&&sameJson(value.discussion.binding.source_refs,command.source_refs)&&sameJson(value.discussion.binding.scope,command.scope));
      });
    });
  }
  prepareStartManualDraft(identity: number, documentId:number,version: number,restoreRevisionId?:number) { return this.action('POST', target('requirements', identity, '/manual-draft'), { document_id:id(documentId),expected_version: id(version),...(restoreRevisionId===undefined?{}:{restore_revision_id:id(restoreRevisionId)}) }, () =>
    checked(shape({ manual_draft: this.draft(identity), requirement: identified(models.requirement, identity) }), value => {
      require(value.manual_draft.content_version === 1 && value.requirement.document_work_state === 'MANUAL_EDITING' && value.requirement.active_operation_id === value.manual_draft.id);
      require(value.manual_draft.target_document_id===documentId&&value.manual_draft.base_content_version===version);
    }), 201); }
  prepareSaveManualDraft(identity: number, body: Readonly<{ document_id:number;draft_id:number;expected_version: number; markdown_content: string; block_state_json: BlockState }>) {
    return this.action('PUT', target('requirements', identity, '/manual-draft'), body, original => {
      bodyFields(original!, ['document_id','draft_id','expected_version', 'markdown_content', 'block_state_json']); id(original!.expected_version);id(original!.document_id);id(original!.draft_id);
      const ids = (original!.block_state_json as JsonObject).blocks;
      require(Array.isArray(ids)); const blockIds = ids.map(item => id((item as JsonObject).block_id));
      return checked(this.draft(identity), value => {
        require(value.content_version === (original!.expected_version as number) + 1 && value.markdown_content === original!.markdown_content);
        require(value.id===original!.draft_id&&value.target_document_id===original!.document_id);
        require(value.block_state_json.next_block_id === (original!.block_state_json as JsonObject).next_block_id);
        require(JSON.stringify(value.block_state_json.blocks.map(item => item.block_id)) === JSON.stringify(blockIds));
      });
    });
  }
  prepareCancelManualDraft(identity: number, documentId:number,draftId:number,version: number) { return this.action('DELETE', target('requirements', identity, '/manual-draft'), {document_id:id(documentId),draft_id:id(draftId),expected_version: id(version) }, () =>
    checked(shape({ requirement_id: id,document_id:id, manual_draft_id: id, cancelled: value => { require(value === true); return true as const; } }), value => require(value.requirement_id === identity&&value.document_id===documentId&&value.manual_draft_id===draftId))); }
  prepareCompleteManualDraft(identity: number, documentId:number,draftId:number,version: number) { return this.action('POST', target('requirements', identity, '/manual-draft/complete'), {document_id:id(documentId),draft_id:id(draftId),expected_version: id(version) }, () =>checked(models.documentEffect,effect=>require(effect.document_id===documentId&&effect.result!=='CREATED'))); }
  prepareCreateRevision(identity: number, body: Readonly<{ document_id:number;expected_version: number; description?: string | null }>) { return this.action('POST', target('requirements', identity, '/revisions'), body, original => {
    bodyFields(original!, ['document_id','expected_version'], ['description']); id(original!.document_id);id(original!.expected_version);
    return models.versionMarker;
  }); }
  prepareCreateDocument(identity:number,body:CreateDocument){return this.action('POST',target('requirements',identity,'/documents'),body,original=>{
    bodyFields(original!,['name','document_kind','template_ref']);
    return checked(shape({document:this.current(identity),revision_id:id}),result=>require(result.document.name===original!.name&&result.document.document_kind===original!.document_kind&&result.document.content_version===1&&result.revision_id===result.document.current_revision_id));
  },201);}
  prepareUpdateDocument(identity:number,body:Readonly<{expected_metadata_version:number;change:DocumentChange}>){return this.action('PATCH',target('documents',identity),body,original=>{
    bodyFields(original!,['expected_metadata_version','change']);id(original!.expected_metadata_version);
    return checked(shape({document:identified(models.documentSummary,identity),event_id:models.nullableId}),result=>{
      const change=original!.change as JsonObject;
      if(change.type==='RENAME')require(result.document.name===change.name);
      if(change.type==='ARCHIVE')require(result.document.archived_at!==null);
      if(change.type==='RESTORE')require(result.document.archived_at===null);
      if(change.type==='CONFIRM')require(result.document.confirmed_revision_id===change.revision_id&&result.document.current_revision_id===change.revision_id&&result.document.content_version===change.expected_content_version);
    });
  });}

  // I14 / I15 / I17 / I18 / I34 / I36.
  prepareCreateGuide(identity:number,body:CreateGuide){return this.action('POST',target('requirements',identity,'/guide-runs'),body,original=>{
    bodyFields(original!,['expected_discussion_version','operation','instruction','target','scope','source_refs','proposal_ref','acknowledge_source_changes']);
    id(original!.expected_discussion_version);if(original!.target!==null)models.targetRef(original!.target);
    if(original!.scope!==null)models.collaborationValue('legacy_scope')(original!.scope);
    return models.runReceipt;
  },202);}
  prepareContinueGuide(identity:number,instruction:string,discussionVersion:number){return this.action('POST',target('guide-runs',identity,'/continue'),
    {instruction,expected_discussion_version:id(discussionVersion)},()=>checked(models.runReceipt,value=>require(value.guide_run_id!==identity)),202);}
  prepareCancelGuide(identity:number){return this.action('POST',target('guide-runs',identity,'/cancel'),null,()=>value=>{
    const row=snapshotObject(value);if(row.status==='COMPLETED')return identified(models.guideRun,identity)(row);
    return checked(identified(models.guideAccepted,identity),actual=>require(actual.status==='CANCELLED'&&actual.current_step==='FINISHED'))(row);
  });}
  prepareRetryGuide(identity:number){return this.action('POST',target('guide-runs',identity,'/retry'),null,()=>checked(models.runReceipt,value=>require(value.guide_run_id!==identity)),202);}
  prepareModifyFromComment(identity:number,version:number,discussionVersion:number){return this.action('POST',target('comments',identity,'/guide-runs'),
    {expected_content_version:id(version),expected_discussion_version:id(discussionVersion)},()=>models.runReceipt,202);}

  prepareCardResponses(identity:number,body:models.Responses,discussionVersion:number){
    const action=this.action('POST',target('conversation-messages',identity,'/responses'),{...body,expected_discussion_version:id(discussionVersion)},original=>{
      const answers=models.responses(Object.fromEntries(Object.entries(original!).filter(([key])=>key!=='expected_discussion_version')));void answers;
      return (value:unknown)=>{const row=snapshotObject(value);return row.processing==='MODEL'?models.runReceipt(row):models.programReceipt(row);};
    },[200,202]);
    return Object.freeze({submit:async(signal?:AbortSignal)=>{const response=await action.submit(signal);
      if(response.status!==(response.data.processing==='MODEL'?202:200)||response.data.user_message_id===identity)throw new ApiUnknown(true);
      return response;
    }});
  }

  // I20 read above; I21 / I22 / I23.
  prepareDecideSuggestion(identity: number, body: Readonly<{ decision: 'ACCEPTED' | 'REJECTED' | 'EDITED'; edited_content?: string | null }>) {
    return this.action('PUT', target('suggestions', identity, '/decision'), body, original => {
      bodyFields(original!, ['decision'], ['edited_content']);
      require(original!.decision==='EDITED'?typeof original!.edited_content==='string':!('edited_content' in original!));
      return checked(shape({ suggestion: identified(models.suggestion, identity), counts: models.counts }), value => {
        require(value.suggestion.status === original!.decision && value.counts[value.suggestion.status.toLowerCase() as 'accepted' | 'rejected' | 'edited'] > 0);
      });
    });
  }
  prepareCompleteBatch(identity: number, version: number) { return this.action('POST', target('suggestion-batches', identity, '/complete'), { expected_content_version: id(version) }, original =>
    checked(shape({ batch: identified(models.batchMetadata, identity), counts: models.counts, current_document: models.documentBodyDecoder(this.ctx, 'CURRENT'),document_effect:models.documentEffect,applied_suggestion_ids:array(id,100) }), value => {
      require(value.batch.status === 'COMPLETED' && value.counts.pending === 0 && value.batch.base_content_version === original!.expected_content_version);
      require(value.current_document.requirement_id === value.batch.requirement_id && value.current_document.content_version === (value.batch.applied_content_version ?? value.batch.base_content_version));
      const effect=value.document_effect;require(value.current_document.id===value.batch.target_document_id&&effect.document_id===value.current_document.id&&effect.before_content_version===value.batch.base_content_version&&effect.after_content_version===value.current_document.content_version&&effect.result===(value.batch.completion_result==='NO_CHANGE'?'NO_CHANGE':'UPDATED'));
      require(new Set(value.applied_suggestion_ids).size===value.applied_suggestion_ids.length&&value.applied_suggestion_ids.length===value.counts.accepted+value.counts.edited);
    })); }
  prepareDiscardBatch(identity: number) { return this.action('POST', target('suggestion-batches', identity, '/discard'), null, () =>
    checked(shape({ batch: identified(models.batchMetadata, identity), counts: models.counts }), value => require(value.batch.status === 'DISCARDED'))); }

  // I29 / I30 / I31 / I32 / I33.
  prepareCreateComment(identity: number, body: CreateComment) { return this.action('POST', target('requirements', identity, '/comments'), body, original => {
    bodyFields(original!, ['document_id','expected_content_version', 'content', 'anchor_type', 'block_id'], ['selection']);
    return checked(owned(models.comment, identity), value => require(value.document_id===original!.document_id&&value.status === 'OPEN' && value.anchor_status === 'ATTACHED' && value.deleted_at === null && value.block_id === original!.block_id && value.anchor_type === original!.anchor_type));
  }, 201); }
  prepareEditComment(identity: number, content: string) { return this.action('PATCH', target('comments', identity), { content }, () => identified(models.comment, identity)); }
  prepareResolveComment(identity: number) { return this.action('POST', target('comments', identity, '/resolve'), null, () =>
    checked(identified(models.comment, identity), value => require(value.status === 'RESOLVED'))); }
  prepareReopenComment(identity: number) { return this.action('POST', target('comments', identity, '/reopen'), null, () =>
    checked(identified(models.comment, identity), value => require(value.status === 'OPEN'))); }
  prepareDeleteComment(identity: number) { return this.action('DELETE', target('comments', identity), null, () =>
    checked(identified(models.comment, identity), value => require(value.deleted_at !== null))); }
}

// Rejected transport errors retain their authoritative identity; success/meta
// projection failures above become ApiUnknown. Export for parent controllers.
export { ApiUnknown, ApiRejected };
