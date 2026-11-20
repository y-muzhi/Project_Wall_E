import { RequirementDocumentOwner } from '../../src/requirements/document-owner.ts';
import { createRoot } from 'react-dom/client';
import { Crepe } from '@milkdown/crepe';
import { ApiClient } from '../../src/api/client.ts';
import { WalleApi } from '../../src/api/walle.ts';
import { cards, message, guideRun, requirementDetail } from '../../src/api/models.ts';
import { InteractionCards } from '../../src/guide/cards.ts';
import { InteractionCardsView } from '../../src/guide/cards-view.tsx';
import { CardDrafts } from '../../src/guide/card-drafts.ts';
import { installSourceNodes } from '../../src/documents/source-nodes.ts';
import '../../src/shared/styles.css';
const at = '2026-11-16T09:00:00.000Z',
  long = '本次改动保留完整来源与范围，用户确认后精确保存。'.repeat(10);
const parser = new Crepe({
  root: document.querySelector<HTMLElement>('#parser')!,
  defaultValue: '',
});
await installSourceNodes(parser);
await parser.create();
parser.setReadonly(true);
const detail = {
  ...requirementDetail({
    requirement: {
      id: 1,
      requirement_no: 'REQ000001',
      title: '提案审阅',
      requirement_type: 'NEW',
      metadata_version: 1,
      initial_message_id: 1,
      discussion_version: 7,
      status: 'PLANNING',
      document_work_state: 'IDLE',
      active_operation_type: null,
      active_operation_id: null,
      created_at: at,
      updated_at: at,
      completed_at: null,
      closed_at: null,
      state_started_at: null,
    },
    documents: [],
    discussion_summary: {
      discussion_version: 7,
      focus_topic_ref: null,
      focus_title: null,
      next_step: null,
      pending_count: 0,
    },
    discussion: null,
    active_operation: null,
  }),
  current: null,
  selected_document_id: 1,
  activity: { kind: 'IDLE' as const },
  comment_index: null,
};
const source = guideRun({
  id: 10,
  requirement_id: 1,
  document_id: 1,
  action_type: 'ASK',
  function_type: 'collaboration_v1',
  source_type: 'USER_INSTRUCTION',
  source_id: null,
  scope: null,
  status: 'COMPLETED',
  current_step: 'FINISHED',
  suggestion_batch_id: null,
  latest_assistant_message_id: 20,
  error_code: null,
  error_message: null,
  cancel_reason: null,
  retry_of_guide_run_id: null,
  created_at: at,
  started_at: at,
  waiting_user_at: null,
  ended_at: at,
  updated_at: at,
  operation: 'DISCUSS',
  parent_guide_run_id: null,
  target: { kind: 'EXISTING', document_id: 1, expected_content_version: 1 },
  discussion_version_snapshot: 2,
  material_summary: null,
  application_result: 'NOT_REQUESTED',
  progress_result: 'NOT_APPLICABLE',
  progress_error: null,
  document_effect: null,
  accepted_target: {
    discussion_step_ref: null,
    discussion_branch_ref: null,
    branch_intent: null,
    branch_resume_basis: null,
  },
  effect_state: 'APPLIED',
  formation_result: 'NO_CHANGE',
  proposal_result: 'APPLIED',
  component_errors: [],
  final_result: {
    summary: '精确提案已形成。',
    assistant_message_id: 20,
    current_document_version: null,
    suggestion_batch_id: null,
    analysis: null,
  },
  returned_responses: [],
});
const selected = new URLSearchParams(location.search).get('purpose') ?? 'write';
const group = cards({
  schema_version: 1,
  intro: '请核对以下提案。',
  purpose: selected === 'path' ? 'FORMATION_PATH_CHANGE' : 'STAGED_WRITE',
  cards: [
    {
      card_key: 'c1',
      card_type: 'SINGLE_SELECT',
      question: selected === 'path' ? '是否采用以下路线调整？' : '是否按以下原文写入文档？',
      context: '',
      required: true,
      options: [
        { option_key: 'apply', label: '采用以上内容', description: '', impact: '', risks: '' },
      ],
      selection_rule: { min: 1, max: 1 },
      custom_answer: { enabled: false, max_length: 0 },
      recommendation: null,
      related_spec_context: [],
    },
  ],
  program_binding: { discussion_version: 3, target_content_version: 1, source_heads: [] },
  action_payload:
    selected === 'path'
      ? {
          basis: {
            formation_version: 1,
            goal_version: 1,
            document_revision_id: 1,
            content_version: 1,
          },
          changes: [
            {
              type: 'ADD_STEP',
              temp_step_ref: 'new_step_1',
              title: '补充异常流程与恢复设计',
              expected_results: [
                { temp_result_ref: 'new_result_1', description: long, kind: 'CONTENT' },
              ],
              dependencies: [],
              replaces_step_refs: ['s1'],
              before_step_ref: null,
            },
            { type: 'CANCEL_STEP', step_ref: 's1', replacement_step_refs: ['new_step_1'] },
          ],
          result_routes: [
            {
              from_result_ref: 's1.o1',
              disposition: 'REPLACED',
              target_result_refs: ['new_result_1'],
              reason: '由新步骤承接原有设计成果',
            },
          ],
          change_summary: '补充设计路线与成果要求',
          source_refs: [],
        }
      : {
          step_ref: 's1',
          result_refs: ['s1.o1'],
          write_mode: selected === 'patch' ? 'PATCH_EXISTING' : 'FILL_EMPTY',
          document_revision_id: 1,
          content_version: 1,
          goal_version: 1,
          definition_version: 1,
          scope: { scope_type: 'DOCUMENT', scope_ref: null },
          markdown_content:
            selected === 'patch'
              ? null
              : '# 待写入的设计\n\n' +
                long +
                '\n\n- 保留用户输入\n- 明确失败恢复\n\n```text\n' +
                'long_value_'.repeat(20) +
                '\n```\n',
          patches:
            selected === 'patch'
              ? [
                  {
                    title: '精确替换',
                    explanation: '保持其他段落与来源',
                    impact: null,
                    target_ref: { block_id: 1 },
                    original_content: long,
                    patch_operation: 'REPLACE_BLOCK',
                    selector_json: null,
                    proposed_markdown: '更新后的正文。\n',
                    proposed_data_json: null,
                  },
                  {
                    title: '删除旧段落',
                    explanation: '已被新设计替代',
                    impact: null,
                    target_ref: { block_id: 2 },
                    original_content: '过时的设计说明。\n',
                    patch_operation: 'DELETE_BLOCK',
                    selector_json: null,
                    proposed_markdown: null,
                    proposed_data_json: null,
                  },
                  {
                    title: '更新表格行',
                    explanation: '明确新的约束',
                    impact: null,
                    target_ref: { block_id: 3 },
                    original_content: '| A | 原值 |',
                    patch_operation: 'REPLACE_TABLE_ROW',
                    selector_json: { key_column_index: 0, key_value: 'A' },
                    proposed_markdown: null,
                    proposed_data_json: { cells: ['A', long] },
                  },
                ]
              : [],
          change_summary: '保存本阶段已形成的设计内容',
          source_refs: [],
        },
});
const owners: InteractionCards[] = [];
const documentOwners: RequirementDocumentOwner[] = [];
for (const [index, mode] of (['NORMAL', 'DISABLED', 'PROCESSING', 'HISTORY'] as const).entries()) {
  const mid = 20 + index;
  const api = parser.editor
    .action(
      (ctx) =>
        new WalleApi(
          new ApiClient(async (_url, options) => {
            if (mode === 'PROCESSING')
              return await new Promise<Response>((_resolve, reject) =>
                options?.signal?.addEventListener(
                  'abort',
                  () => reject(new Error('fixture stopped')),
                  { once: true },
                ),
              );
            throw new Error('Isolated UI transport failure');
          }),
          ctx,
        ),
    )
    .forDocumentAssistant(1);
  const original = message({
    id: mid,
    requirement_id: 1,
    document_id: 1,
    guide_run_id: 10,
    sequence_no: mid,
    role: 'ASSISTANT',
    content: '提案说明',
    message_type: 'INTERACTION_CARDS',
    structured_content: group,
    reply_to_message_id: null,
    created_at: at,
    card_state: mode === 'HISTORY' ? 'EXPIRED' : 'AVAILABLE',
    phase_ref: null,
    topic_refs: [],
    document_ids: [1],
    program_receipt: null,
  });
  const memory = new Map<string, string>();
  const storage = {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      memory.set(key, value);
    },
    removeItem: (key: string) => {
      memory.delete(key);
    },
  };
  const owner = new InteractionCards(
    original,
    source,
    detail,
    api,
    new CardDrafts(
      () => storage,
      () => at,
      1,
    ),
    async () => detail,
    async () => {},
    async () => {},
    async () => {},
  );
  owner.setAvailable(mode !== 'DISABLED');
  owners.push(owner);
  const section = document.createElement('section');
  section.dataset.mode = mode;
  section.className = 'conversation-discussion';
  section.style.cssText =
    'min-width:0;padding:20px;border:1px solid #dedede;border-radius:10px;margin-block:16px';
  const title = document.createElement('h2');
  title.textContent = {
    NORMAL: '待确认提案',
    DISABLED: '人工编辑期间，操作不可用',
    PROCESSING: '正在处理采用请求',
    HISTORY: '历史提案，只读',
  }[mode];
  section.append(title);
  const host = document.createElement('div');
  section.append(host);
  document.querySelector('#product')!.append(section);
  const documents = new RequirementDocumentOwner(
    document.createElement('div'),
    1,
    api,
    async () => detail,
  );
  documentOwners.push(documents);
  createRoot(host).render(
    <InteractionCardsView owner={owner} busy={mode === 'DISABLED'} documents={documents} />,
  );
  if (mode === 'PROCESSING') {
    owner.toggle('c1', 'apply', true);
    void owner.submit();
  }
}
Object.assign(window, {
  formationUi: {
    ready: true,
    states: () => owners.map((owner) => owner.getSnapshot().phase),
    dispose: async () => {
      owners.forEach((owner) => owner.dispose());
      await Promise.all(documentOwners.map((owner) => owner.retire()));
      await parser.destroy();
    },
  },
});
