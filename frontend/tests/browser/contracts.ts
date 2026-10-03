import type { Ctx } from '@milkdown/kit/ctx';
import { validateBlockState, validateDocumentReadModel } from '../../src/documents/contracts.ts';
import fixtures from '../../../shared/fixtures/markdown-v1.json';
import editorFixtures from '../../../shared/fixtures/markdown-editor-v1.json';

type RecordValue = Record<string, unknown>;
const timestamp = '2026-10-03T00:00:00.000Z';
function metadata(block: {type: string; section_path: readonly string[]}, index: number) {
  return {block_id: index + 1, block_type: block.type, section_path: [...block.section_path],
    created_by_type: 'SYSTEM', created_source_type: 'TEMPLATE', created_source_id: null, created_at: timestamp,
    last_modified_by_type: 'SYSTEM', last_modified_source_type: 'TEMPLATE', last_modified_source_id: null, last_modified_at: timestamp};
}
function document(entry: typeof fixtures.cases[number]): RecordValue {
  return {id: 1, requirement_id: 7, document_type: 'CURRENT', markdown_content: entry.markdown,
    block_state_json: {schema_version: 1, next_block_id: entry.blocks.length + 1, blocks: entry.blocks.map(metadata)},
    content_version: 3, created_at: timestamp, updated_at: timestamp};
}
function state(doc: RecordValue): RecordValue { return doc.block_state_json as RecordValue; }
function blocks(doc: RecordValue): RecordValue[] { return state(doc).blocks as RecordValue[]; }
function reject(ctx: Ctx, doc: RecordValue, name: string, message?: string): void {
  try { validateDocumentReadModel(ctx, doc); }
  catch (error) {
    if ((error as {code?: string}).code !== 'DOCUMENT_INVALID') throw error;
    if (message && !(error instanceof Error && error.message.includes(message))) throw error;
    return;
  }
  throw new Error(`无效完整快照被接受: ${name}`);
}

// Structural contract tests. These fixture origins are not real repository
// objects, so these tests make no source-relationship or authorization claim.
export function verifyContracts(ctx: Ctx) {
  const positives = [];
  for (const entry of [...fixtures.cases, ...editorFixtures.cases]) {
    const input = document(entry);
    const result = validateDocumentReadModel(ctx, input);
    if (result.document.markdown_content !== entry.markdown ||
        JSON.stringify(result.document.block_state_json) !== JSON.stringify(input.block_state_json) ||
        !Object.isFrozen(result.document) || !Object.isFrozen(result.document.block_state_json.blocks)) throw new Error('完整快照验证改变原值或没有冻结');
    positives.push(entry.name);
  }
  const mutations: [string, (doc: RecordValue) => void][] = [
    ['document-unknown', doc => { doc.extra = true; }],
    ['document-missing', doc => { delete doc.id; }],
    ['boolean-id', doc => { doc.requirement_id = true; }],
    ['unsafe-id', doc => { doc.id = Number.MAX_SAFE_INTEGER + 1; }],
    ['string-version', doc => { doc.content_version = '3'; }],
    ['unknown-document-type', doc => { doc.document_type = 'REVISION'; }],
    ['markdown-object', doc => { doc.markdown_content = {}; }],
    ['invalid-unicode', doc => { doc.markdown_content = '\ud800'; }],
    ['serialized-state', doc => { doc.block_state_json = JSON.stringify(doc.block_state_json); }],
    ['state-unknown', doc => { state(doc).extra = null; }],
    ['boolean-schema-version', doc => { state(doc).schema_version = true; }],
    ['invalid-next', doc => { state(doc).next_block_id = 0; }],
    ['blocks-object', doc => { state(doc).blocks = {}; }],
    ['block-count', doc => { blocks(doc).pop(); }],
    ['block-unknown', doc => { blocks(doc)[0]!.extra = true; }],
    ['block-missing', doc => { delete blocks(doc)[0]!.created_source_id; }],
    ['duplicate-id', doc => { blocks(doc)[1]!.block_id = 1; }],
    ['over-water-id', doc => { blocks(doc)[1]!.block_id = 3; }],
    ['wrong-type', doc => { blocks(doc)[0]!.block_type = 'paragraph'; }],
    ['wrong-path', doc => { blocks(doc)[0]!.section_path = ['错误']; }],
    ['serialized-path', doc => { blocks(doc)[0]!.section_path = '["标题😀"]'; }],
    ['template-actor', doc => { blocks(doc)[0]!.created_by_type = 'USER'; }],
    ['template-id', doc => { blocks(doc)[0]!.created_source_id = 1; }],
    ['manual-actor', doc => { blocks(doc)[0]!.last_modified_source_type = 'MANUAL_EDIT'; blocks(doc)[0]!.last_modified_source_id = 99; }],
    ['run-boolean-id', doc => { blocks(doc)[0]!.created_by_type = 'AI'; blocks(doc)[0]!.created_source_type = 'GUIDE_RUN'; blocks(doc)[0]!.created_source_id = true; }],
    ['unknown-source', doc => { blocks(doc)[0]!.last_modified_source_type = 'UNKNOWN'; }],
    ['invalid-calendar', doc => { blocks(doc)[0]!.created_at = '2026-02-30T00:00:00.000Z'; }],
    ['zero-year', doc => { blocks(doc)[0]!.created_at = '0000-01-01T00:00:00.000Z'; }],
    ['non-utc', doc => { blocks(doc)[0]!.created_at = '2026-10-03T08:00:00.000+08:00'; }],
    ['block-time-backward', doc => { blocks(doc)[0]!.last_modified_at = '2026-10-02T00:00:00.000Z'; }],
    ['document-time-backward', doc => { doc.updated_at = '2026-10-02T00:00:00.000Z'; }],
  ];
  const negatives = [];
  for (const [name, mutate] of mutations) {
    const input = document(fixtures.cases[1]!);
    mutate(input);
    reject(ctx, input, name);
    negatives.push(name);
  }
  const input = document(fixtures.cases[1]!);
  const frozen = validateDocumentReadModel(ctx, input);
  (blocks(input)[0]!.section_path as string[])[0] = '外部变化';
  blocks(input)[0]!.block_id = 99;
  if (frozen.document.block_state_json.blocks[0]!.section_path[0] !== '标题😀' || frozen.document.block_state_json.blocks[0]!.block_id !== 1) throw new Error('输入变更污染已验证快照');
  for (const [actor, source] of [['AI', 'GUIDE_RUN'], ['AI', 'SUGGESTION_BATCH'], ['USER', 'SUGGESTION_BATCH'], ['USER', 'MANUAL_EDIT']]) {
    const valid = document(fixtures.cases[1]!);
    for (const block of blocks(valid)) for (const prefix of ['created', 'last_modified']) {
      block[`${prefix}_by_type`] = actor;
      block[`${prefix}_source_type`] = source;
      block[`${prefix}_source_id`] = 99;
    }
    validateDocumentReadModel(ctx, valid);
  }
  const largeMarkdown = '# ' + '长'.repeat(6000) + '\n\n' + 'p\n\n'.repeat(1000);
  const largeBlocks = Array.from({length:1001}, (_, index) => metadata({type: index ? 'paragraph' : 'heading', section_path:['长'.repeat(6000)]}, index));
  try { validateBlockState(ctx, largeMarkdown, {schema_version:1, next_block_id:1002, blocks:largeBlocks}); throw new Error('超容量元数据被接受'); }
  catch (error) { if (!(error instanceof Error && error.message.includes('BlockState超过容量'))) throw error; }
  return {scope: 'Structure and same-source snapshot only; repository relationships and authorization excluded',
    positive_fixtures: positives, rejected_variants: negatives, independent_copy: true, valid_origin_combinations: 4, metadata_capacity_rejected: true};
}
