import { Crepe } from '@milkdown/crepe';
import { ApiClient, ApiRejected } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { require } from '../../src/api/decoding.ts';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import type { DocumentReadModel } from '../../src/documents/contracts.ts';
import { recoveryProbe } from './recovery-probe.ts';
import { autosaveProbe } from './autosave-probe.ts';
import { editorHostProbe } from './editor-host-probe.ts';
import { readLimitsProbe } from './read-limits-probe.ts';
import { mountCreateProbe } from './create-probe.tsx';
import { mountWorkbenchProbe } from './workbench-probe.tsx';
import { mountDetailFrameProbe } from './detail-frame-probe.tsx';
import { detailReadProbe } from './detail-read-probe.ts';
import { manualEndProbe } from './manual-end-probe.ts';
import { manualStartProbe } from './manual-start-probe.ts';
import {prepareRecoveryAdoption,resumeRecoveryAdoption} from './recovery-adoption-probe.ts';

const editor = new Crepe({ root: document.querySelector<HTMLElement>('#editor')!, defaultValue: '', features: {
  [Crepe.Feature.CodeMirror]: false, [Crepe.Feature.ListItem]: false, [Crepe.Feature.LinkTooltip]: false, [Crepe.Feature.Cursor]: false,
  [Crepe.Feature.ImageBlock]: false, [Crepe.Feature.BlockEdit]: false, [Crepe.Feature.Toolbar]: false, [Crepe.Feature.Placeholder]: false,
  [Crepe.Feature.Table]: false, [Crepe.Feature.Latex]: false, [Crepe.Feature.TopBar]: false, [Crepe.Feature.AI]: false,
} });
await installSourceNodes(editor); await editor.create(); editor.setReadonly(true);
const wires: { path: string; method: string; status: number; body?: string; key?: string; error_response?: string }[] = [];
const responses: { path: string; status: number; response: string }[] = [];
const transport: typeof fetch = async (input, options) => {
  let response: Response;
  try { response = await fetch(input, options); } catch (error) { wires.push({path:String(input),method:options?.method ?? 'GET',status:0,error_response:String(error)}); throw error; }
  const received = await response.clone().text(); responses.push({path:String(input),status:response.status,response:received}); if (responses.length > 5) responses.shift();
  wires.push({ path: String(input), method: options?.method ?? 'GET', status: response.status,
    ...((options?.method === 'POST' && String(input) === '/api/v1/requirements') ||
      (String(input).startsWith('/api/v1/requirements/') &&
        ((options?.method === 'POST' && (String(input).endsWith('/manual-draft/complete') || String(input).endsWith('/manual-draft'))) ||
          (options?.method === 'DELETE' && String(input).endsWith('/manual-draft'))))
      ? { body: String(options?.body), key: new Headers(options?.headers).get('Idempotency-Key')! } : {}),
    ...(response.status >= 400 ? { error_response: received } : {}) }); return response;
};
const api = editor.editor.action(ctx => new WalleApi(new ApiClient(transport), ctx));
const status = document.querySelector<HTMLElement>('#status')!;
let lastRequirement = 0;
const hostProbe = editorHostProbe(api, () => lastRequirement);

async function run() {
  const records: { name: string; status: 'SUCCESS' | 'REJECTED'; error?: string }[] = [];
  const pairs: DocumentReadModel[] = [];
  async function accept<T>(name: string, operation: Promise<T>): Promise<T> { const value = await operation; records.push({ name, status: 'SUCCESS' }); return value; }
  async function reject(name: string, operation: Promise<unknown>, code: string) {
    try { await operation; throw new Error(name + ' must refuse'); }
    catch (error) { require(error instanceof ApiRejected && error.code === code); records.push({ name, status: 'REJECTED', error: code }); }
  }
  async function failed(identity: number) {
    const due = Date.now() + 10000;
    while (Date.now() < due) {
      const result = await api.getGuideRun(identity);
      if (result.data.status === 'FAILED') { require(result.data.error_code === 'CONFIG_INVALID'); return result.data; }
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    throw new Error('Real missing-config run did not finish');
  }
  const created = await accept('I02', api.prepareCreateRequirement({ title: 'API联调😀', requirement_type: 'NEW', template_key: 'new-requirement',
    template_version: 'v1', initial_idea: '明确的隔离测试输入', initialization_mode: 'DESIGN' }).submit());
  const identity = created.data.requirement.id;
  lastRequirement = identity;
  await failed(created.data.guide_run_id);
  await accept('I16', api.getGuideRun(created.data.guide_run_id));
  await accept('I01', api.listRequirements({ keyword: '联调😀', status: ['INITIALIZING'], requirement_type: ['NEW'] }));
  await accept('I03', api.getRequirement(identity));
  await accept('I04', api.prepareUpdateRequirement(identity, { title: '更新联调😀' }).submit());
  let current = (await accept('I08', api.getCurrentDocument(identity))).data; pairs.push(current);
  let draft = (await accept('I09', api.prepareStartManualDraft(identity, current.content_version).submit())).data.manual_draft; pairs.push(draft);
  draft = (await accept('I10', api.getManualDraft(identity))).data; pairs.push(draft);
  await accept('I13', api.prepareCancelManualDraft(identity, draft.content_version).submit());
  draft = (await api.prepareStartManualDraft(identity, current.content_version).submit()).data.manual_draft;
  for (let index = 0; index < 3; index++) {
    draft = (await accept('I11', api.prepareSaveManualDraft(identity, { expected_version: draft.content_version,
      markdown_content: draft.markdown_content, block_state_json: draft.block_state_json }).submit())).data; pairs.push(draft);
  }
  const draftVersion = draft.content_version;
  current = (await accept('I12', api.prepareCompleteManualDraft(identity, draftVersion).submit())).data; pairs.push(current);
  require(current.document_type === 'CURRENT' && current.content_version !== draftVersion);
  const baseline = await accept('I05', api.prepareCompleteInitialization(identity, current.content_version).submit());
  require(baseline.data.baseline_revision.source_content_version === current.content_version);
  const revision = await accept('I26', api.prepareCreateRevision(identity, { expected_version: current.content_version, description: '隔离诊断快照' }).submit());
  await accept('I24', api.listRevisions(identity));
  const history = (await accept('I25', api.getRevision(revision.data.id))).data;
  require(history.markdown_content === current.markdown_content && history.source_content_version === current.content_version);
  const block = current.block_state_json.blocks.find(value => value.block_type === 'paragraph')!; require(block !== undefined);
  const comment = await accept('I29', api.prepareCreateComment(identity, { expected_content_version: current.content_version,
    content: '实际评论😀', anchor_type: 'BLOCK', block_id: block.block_id }).submit());
  const commentId = comment.data.id;
  await accept('I28', api.getComment(commentId)); await accept('I27', api.listComments(identity));
  const index = await accept('I37', api.getCommentIndex(identity)); require(index.data.total_count === 1 && index.data.open_count === 1);
  await accept('I30', api.prepareEditComment(commentId, '实际编辑后的评论').submit());
  await accept('I31', api.prepareResolveComment(commentId).submit()); await accept('I32', api.prepareReopenComment(commentId).submit());
  const fromComment = await accept('I34', api.prepareModifyFromComment(commentId, current.content_version).submit()); await failed(fromComment.data.id);
  const ask = await accept('I14', api.prepareCreateGuide(identity, { expected_version: current.content_version, action_type: 'ASK', instruction: '实际普通提问',
    scope_type: 'DOCUMENT', source_type: 'USER_INSTRUCTION' }).submit()); await failed(ask.data.guide_run.id);
  await reject('I15', api.prepareContinueGuide(ask.data.guide_run.id, '失败运行不能继续').submit(), 'STATE_CONFLICT');
  await reject('I17', api.prepareCancelGuide(ask.data.guide_run.id).submit(), 'STATE_CONFLICT');
  const retried = await accept('I18', api.prepareRetryGuide(ask.data.guide_run.id).submit()); await failed(retried.data.id);
  await accept('I19', api.listGuideRuns(identity, { status: ['FAILED'] })); await accept('I35', api.listMessages(identity));
  await reject('I20', api.getBatch(999), 'NOT_FOUND');
  await reject('I21', api.prepareDecideSuggestion(999, { decision: 'ACCEPTED' }).submit(), 'NOT_FOUND');
  await reject('I22', api.prepareCompleteBatch(999, current.content_version).submit(), 'NOT_FOUND');
  await reject('I23', api.prepareDiscardBatch(999).submit(), 'NOT_FOUND');
  await reject('I36', api.prepareCardResponses(999, { schema_version: 1, responses: [{ card_key: 'missing', selected_option_keys: [], custom_answer: null, skipped: true }] }).submit(), 'NOT_FOUND');
  await accept('I33', api.prepareDeleteComment(commentId).submit());
  await accept('I06', api.prepareCompleteRequirement(identity, current.content_version).submit());
  await accept('I07', api.prepareReactivateRequirement(identity).submit());
  const final = await api.getRequirement(identity); require(final.data.status === 'ACTIVE' && final.data.document_work_state === 'IDLE');
  const expected = Array.from({ length: 37 }, (_, index) => 'I' + String(index + 1).padStart(2, '0'));
  require(expected.every(name => records.some(record => record.name === name)));
  const recovery = await editor.editor.action(ctx => recoveryProbe(ctx, api, identity, retried.data.id));
  const autosave = await autosaveProbe(api, identity);
  const result = { passed: true, records, wires, pairs, history, recovery, autosave, current_version: current.content_version, draft_version: draftVersion,
    scope: 'Actual same-origin Vite proxy / production API / isolated SQLite / real Crepe paired documents; failure/config cases explicit, no paid Provider, product page or whole acceptance' };
  status.textContent = JSON.stringify({ ...result, pairs: pairs.length }, null, 2); return result;
}
Object.assign(window, { apiProbe: { run, hostProbe, readLimits: () => readLimitsProbe(api), mountCreate: () => {
  const probe = mountCreateProbe(api); Object.assign(window,{createProbe:probe});
}, mountWorkbench:async(seed:boolean)=>{Object.assign(window,{workbenchProbe:await mountWorkbenchProbe(api,seed)});},
 mountDetailFrame:async()=>{Object.assign(window,{detailFrameProbe:await mountDetailFrameProbe(api,2)});},
 detailRead:()=>detailReadProbe(api,2),
 manualEnd:()=>manualEndProbe(api,2),
 manualStart:()=>manualStartProbe(api,2),
 recoveryAdoptionPrepare:()=>prepareRecoveryAdoption(api,2),recoveryAdoptionResume:()=>resumeRecoveryAdoption(api),
 wireFacts: () => wires, transportFacts: () => responses, creationWires: () => wires.filter(wire => wire.body?.includes('真实抽屉😀')), destroy: () => editor.destroy() } }); status.textContent = 'READY';
