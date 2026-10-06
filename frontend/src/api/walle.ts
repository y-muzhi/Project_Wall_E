/** The 37 explicit API bindings. Each action owns its original body/key and
 * response expectations; retry is a caller decision on the same action.
 */
import type { Ctx } from '@milkdown/kit/ctx';
import type { BlockState } from '../documents/contracts.ts';
import { ApiClient, ApiUnknown, ApiRejected, snapshotObject } from './client.ts';
import type { ApiSuccess, JsonObject } from './client.ts';
import { array, checked, shape, id, require, distinct } from './decoding.ts';
import type { Decoder } from './decoding.ts';
import * as models from './models.ts';

export type ApiAction<T> = Readonly<{ submit: (signal?: AbortSignal) => Promise<ApiSuccess<T>> }>;
export type RequirementFilters = Readonly<{ keyword?: string; status?: readonly (typeof models.requirementStatuses[number])[];
  requirement_type?: readonly (typeof models.requirementTypes[number])[]; page?: number }>;
export type GuideFilters = Readonly<{ status?: readonly (typeof models.runStatuses[number])[]; action_type?: readonly (typeof models.runActions[number])[]; page?: number }>;
export type CreateRequirement = Readonly<{ title: string; requirement_type: 'NEW' | 'CHANGE'; template_key: string; template_version: string;
  initial_idea: string; initialization_mode: 'IDEATION' | 'DESIGN' }>;
export type CreateGuide = Readonly<{ expected_version: number; action_type: 'INITIALIZE' | 'ASK' | 'REVIEW' | 'MODIFY'; instruction: string;
  scope_type: 'DOCUMENT' | 'SECTION' | 'BLOCK' | 'SELECTION'; scope_ref?: ReturnType<typeof models.scope>['scope_ref'];
  source_type: 'USER_INSTRUCTION' | 'REVIEW_RESULT'; source_id?: number | null }>;
export type CreateComment = Readonly<{ expected_content_version: number; content: string; anchor_type: 'BLOCK' | 'SELECTION'; block_id: number;
  selection?: Readonly<{ selected_text: string; prefix_text: string; suffix_text: string }> | null }>;
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
  private action<T>(method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', path: string, body: unknown | null,
                    decoder: (original: JsonObject | null) => Decoder<T>, status: 200 | 201 | 202 = 200, keyed = true): ApiAction<T> {
    const original = body === null ? null : snapshotObject(body);
    const decode = decoder(original), handle = this.client.prepare(method, path, original, { idempotent: keyed, success_status: status });
    return Object.freeze({ submit: async (signal?: AbortSignal) => {
      const response = await this.client.commit(handle, decode, signal);
      if (response.meta.pagination !== undefined) throw new ApiUnknown(true);
      return response;
    } });
  }
  private async single<T>(path: string, decode: Decoder<T>, signal?: AbortSignal) {
    const response = await this.client.read(path, decode, [], signal);
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
  getRequirement(identity: number, signal?: AbortSignal) { return this.single(target('requirements', identity), identified(models.requirement, identity), signal); }
  getCurrentDocument(identity: number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/current-document'), this.current(identity), signal); }
  getManualDraft(identity: number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/manual-draft'), this.draft(identity), signal); }
  listRevisions(identity: number, page = 1, signal?: AbortSignal) { return this.page(target('requirements', identity, '/revisions'), owned(models.revisionSummary, identity), [['page', String(page)]], page, signal); }
  getRevision(identity: number, signal?: AbortSignal) { return this.single(target('revisions', identity), identified(models.revisionDecoder(this.ctx), identity), signal); }
  listComments(identity: number, page = 1, signal?: AbortSignal) { return this.page(target('requirements', identity, '/comments'), owned(models.commentItem, identity), [['page', String(page)]], page, signal); }
  getComment(identity: number, signal?: AbortSignal) { return this.single(target('comments', identity), identified(models.comment, identity), signal); }
  getGuideRun(identity: number, signal?: AbortSignal) { return this.single(target('guide-runs', identity), identified(models.guideRun, identity), signal); }
  listGuideRuns(identity: number, filters: GuideFilters = {}, signal?: AbortSignal) { return this.page(target('requirements', identity, '/guide-runs'), owned(models.guideSummary, identity), query(filters), filters.page ?? 1, signal); }
  getBatch(identity: number, signal?: AbortSignal) { return this.single(target('suggestion-batches', identity), identified(models.batch, identity), signal); }
  getCommentIndex(identity: number, signal?: AbortSignal) { return this.single(target('requirements', identity, '/comment-index'), owned(models.commentIndex, identity), signal); }
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
    bodyFields(original!, ['title', 'requirement_type', 'template_key', 'template_version', 'initial_idea', 'initialization_mode']);
    return checked(shape({ requirement: models.requirement, current_document_id: id, guide_run_id: id }), value => {
      require(value.requirement.status === 'INITIALIZING' && value.requirement.document_work_state === 'GUIDE_ACTIVE' && value.requirement.active_operation_id === value.guide_run_id);
      for (const field of ['requirement_type', 'template_key', 'template_version', 'initialization_mode'] as const) require(value.requirement[field] === original![field]);
    });
  }, 201); }
  prepareUpdateRequirement(identity: number, body: Readonly<{ title?: string; initialization_mode?: 'IDEATION' | 'DESIGN' }>) {
    return this.action('PATCH', target('requirements', identity), body, original => {
      bodyFields(original!, [], ['title', 'initialization_mode']); require(Object.keys(original!).length > 0); return identified(models.requirement, identity);
    }, 200, false);
  }
  prepareCompleteInitialization(identity: number, version: number) { return this.action('POST', target('requirements', identity, '/complete-initialization'), { expected_content_version: id(version) }, original =>
    checked(shape({ requirement: identified(models.requirement, identity), baseline_revision: owned(models.revisionSummary, identity), current_document: shape({ id, content_version: id }) }), value => {
      require(value.requirement.status === 'ACTIVE' && value.requirement.document_work_state === 'IDLE' && value.baseline_revision.revision_type === 'BASELINE');
      require(value.baseline_revision.source_content_version === original!.expected_content_version && value.current_document.content_version === original!.expected_content_version);
    })); }
  prepareCompleteRequirement(identity: number, version: number) { return this.action('POST', target('requirements', identity, '/complete'), { expected_version: id(version) }, () =>
    checked(identified(models.requirement, identity), value => require(value.status === 'COMPLETED' && value.document_work_state === 'IDLE'))); }
  prepareReactivateRequirement(identity: number) { return this.action('POST', target('requirements', identity, '/reactivate'), null, () =>
    checked(identified(models.requirement, identity), value => require(value.status === 'ACTIVE' && value.document_work_state === 'IDLE'))); }

  // I09 / I11 / I12 / I13 / I26. Draft version never substitutes CURRENT version.
  prepareStartManualDraft(identity: number, version: number) { return this.action('POST', target('requirements', identity, '/manual-draft'), { expected_version: id(version) }, () =>
    checked(shape({ manual_draft: this.draft(identity), requirement: identified(models.requirement, identity) }), value => {
      require(value.manual_draft.content_version === 1 && value.requirement.document_work_state === 'MANUAL_EDITING' && value.requirement.active_operation_id === value.manual_draft.id);
    }), 201); }
  prepareSaveManualDraft(identity: number, body: Readonly<{ expected_version: number; markdown_content: string; block_state_json: BlockState }>) {
    return this.action('PUT', target('requirements', identity, '/manual-draft'), body, original => {
      bodyFields(original!, ['expected_version', 'markdown_content', 'block_state_json']); id(original!.expected_version);
      const ids = (original!.block_state_json as JsonObject).blocks;
      require(Array.isArray(ids)); const blockIds = ids.map(item => id((item as JsonObject).block_id));
      return checked(this.draft(identity), value => {
        require(value.content_version === (original!.expected_version as number) + 1 && value.markdown_content === original!.markdown_content);
        require(value.block_state_json.next_block_id === (original!.block_state_json as JsonObject).next_block_id);
        require(JSON.stringify(value.block_state_json.blocks.map(item => item.block_id)) === JSON.stringify(blockIds));
      });
    }, 200, false);
  }
  prepareCancelManualDraft(identity: number, version: number) { return this.action('DELETE', target('requirements', identity, '/manual-draft'), { expected_version: id(version) }, () =>
    checked(shape({ requirement_id: id, manual_draft_id: id, cancelled: value => { require(value === true); return true as const; } }), value => require(value.requirement_id === identity))); }
  prepareCompleteManualDraft(identity: number, version: number) { return this.action('POST', target('requirements', identity, '/manual-draft/complete'), { expected_version: id(version) }, () => this.current(identity)); }
  prepareCreateRevision(identity: number, body: Readonly<{ expected_version: number; description?: string | null }>) { return this.action('POST', target('requirements', identity, '/revisions'), body, original => {
    bodyFields(original!, ['expected_version'], ['description']); id(original!.expected_version);
    return checked(owned(models.revisionSummary, identity), value => require(value.revision_type === 'MANUAL' && value.source_content_version === original!.expected_version));
  }, 201); }

  // I14 / I15 / I17 / I18 / I34 / I36.
  prepareCreateGuide(identity: number, body: CreateGuide) { return this.action('POST', target('requirements', identity, '/guide-runs'), body, original => {
    bodyFields(original!, ['expected_version', 'action_type', 'instruction', 'scope_type', 'source_type'], ['scope_ref', 'source_id']);
    return checked(shape({ guide_run: owned(models.guideAccepted, identity), user_message: owned(models.message, identity) }), value => {
      require(value.guide_run.status === 'RUNNING' && value.guide_run.current_step === 'PREPARING' && value.user_message.role === 'USER' && value.user_message.message_type === 'TEXT' && value.user_message.guide_run_id === value.guide_run.id);
    });
  }, 202); }
  prepareContinueGuide(identity: number, instruction: string) { return this.action('POST', target('guide-runs', identity, '/continue'), { instruction }, () =>
    checked(identified(models.guideAccepted, identity), value => require(value.status === 'RUNNING' && value.current_step === 'PREPARING')), 202); }
  prepareCancelGuide(identity: number) { return this.action('POST', target('guide-runs', identity, '/cancel'), null, () =>
    checked(identified(models.guideAccepted, identity), value => require(value.status === 'CANCELLED' && value.current_step === 'FINISHED'))); }
  prepareRetryGuide(identity: number) { return this.action('POST', target('guide-runs', identity, '/retry'), null, () =>
    checked(models.guideRun, value => require(value.id !== identity && value.retry_of_guide_run_id === identity && value.status === 'RUNNING' && value.current_step === 'PREPARING')), 202); }
  prepareModifyFromComment(identity: number, version: number) { return this.action('POST', target('comments', identity, '/guide-runs'), { expected_content_version: id(version) }, () =>
    checked(models.guideRun, value => require(value.action_type === 'MODIFY' && value.function_type === 'MODIFY_FROM_COMMENT' && value.source_type === 'COMMENT' && value.source_id === identity && value.status === 'RUNNING' && value.current_step === 'PREPARING' && ['BLOCK', 'SELECTION'].includes(value.scope.scope_type))), 202); }
  prepareCardResponses(identity: number, body: models.Responses) { return this.action('POST', target('conversation-messages', identity, '/responses'), body, original => {
    const answers = models.responses(original);
    return checked(shape({ response_message: models.message, guide_run: models.guideAccepted,
      card_state: value => { require(value === 'ANSWERED'); return 'ANSWERED' as const; } }), value => {
      require(value.guide_run.status === 'RUNNING' && value.guide_run.current_step === 'PREPARING' && value.response_message.message_type === 'CARD_RESPONSE' && value.response_message.reply_to_message_id === identity);
      require(value.response_message.guide_run_id === value.guide_run.id && value.response_message.requirement_id === value.guide_run.requirement_id);
      const formal = models.responses(value.response_message.structured_content);
      require(JSON.stringify(formal.responses.map(item => [item.card_key, item.selected_option_keys, item.skipped])) === JSON.stringify(answers.responses.map(item => [item.card_key, item.selected_option_keys, item.skipped])));
    });
  }, 202); }

  // I20 read above; I21 / I22 / I23.
  prepareDecideSuggestion(identity: number, body: Readonly<{ decision: 'ACCEPTED' | 'REJECTED' | 'EDITED'; edited_content?: string | null }>) {
    return this.action('PUT', target('suggestions', identity, '/decision'), body, original => {
      bodyFields(original!, ['decision'], ['edited_content']);
      return checked(shape({ suggestion: identified(models.suggestion, identity), counts: models.counts }), value => {
        require(value.suggestion.status === original!.decision && value.counts[value.suggestion.status.toLowerCase() as 'accepted' | 'rejected' | 'edited'] > 0);
      });
    });
  }
  prepareCompleteBatch(identity: number, version: number) { return this.action('POST', target('suggestion-batches', identity, '/complete'), { expected_content_version: id(version) }, original =>
    checked(shape({ batch: identified(models.batchMetadata, identity), counts: models.counts, current_document: models.documentDecoder(this.ctx, 'CURRENT') }), value => {
      require(value.batch.status === 'COMPLETED' && value.counts.pending === 0 && value.batch.base_content_version === original!.expected_content_version);
      require(value.current_document.requirement_id === value.batch.requirement_id && value.current_document.content_version === (value.batch.applied_content_version ?? value.batch.base_content_version));
    })); }
  prepareDiscardBatch(identity: number) { return this.action('POST', target('suggestion-batches', identity, '/discard'), null, () =>
    checked(shape({ batch: identified(models.batchMetadata, identity), counts: models.counts }), value => require(value.batch.status === 'DISCARDED'))); }

  // I29 / I30 / I31 / I32 / I33.
  prepareCreateComment(identity: number, body: CreateComment) { return this.action('POST', target('requirements', identity, '/comments'), body, original => {
    bodyFields(original!, ['expected_content_version', 'content', 'anchor_type', 'block_id'], ['selection']);
    return checked(owned(models.comment, identity), value => require(value.status === 'OPEN' && value.anchor_status === 'ATTACHED' && value.deleted_at === null && value.block_id === original!.block_id && value.anchor_type === original!.anchor_type));
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
