import type { Ctx } from '@milkdown/kit/ctx';
import { EditorSource, EditorSourceInvalid } from './editor-source.ts';
import { utf16ToCodepoint } from './selection.ts';

export const BLOCK_TYPES = ['heading', 'paragraph', 'blockquote', 'bullet_list', 'ordered_list', 'task_list',
  'code_block', 'thematic_break', 'table', 'html_block', 'link_definition'] as const;
export type BlockType = typeof BLOCK_TYPES[number];
export type Actor = 'USER' | 'AI' | 'SYSTEM';
export type SourceType = 'TEMPLATE' | 'GUIDE_RUN' | 'SUGGESTION_BATCH' | 'MANUAL_EDIT';

export interface BlockMetadata {
  readonly block_id: number;
  readonly block_type: BlockType;
  readonly section_path: readonly string[];
  readonly created_by_type: Actor;
  readonly created_source_type: SourceType;
  readonly created_source_id: number | null;
  readonly created_at: string;
  readonly last_modified_by_type: Actor;
  readonly last_modified_source_type: SourceType;
  readonly last_modified_source_id: number | null;
  readonly last_modified_at: string;
}

export interface BlockState {
  readonly schema_version: 1;
  readonly next_block_id: number;
  readonly blocks: readonly BlockMetadata[];
}

export interface DocumentReadModel {
  readonly id: number;
  readonly requirement_id: number;
  readonly document_type: 'CURRENT' | 'MANUAL_DRAFT';
  readonly markdown_content: string;
  readonly block_state_json: BlockState;
  readonly content_version: number;
  readonly created_at: string;
  readonly updated_at: string;
}

function invalid(message: string): never { throw new EditorSourceInvalid(message); }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value) as object | null) ||
    Reflect.ownKeys(value).some(key => typeof key !== 'string') ||
    Object.keys(value).sort().join(',') !== [...fields].sort().join(',')) invalid('对象字段缺失、未知或类型错误');
  return value as Record<string, unknown>;
}
function integer(value: unknown): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) invalid('必须为正安全整数');
}
function text(value: unknown): asserts value is string {
  if (typeof value !== 'string') invalid('必须为文本');
  try { utf16ToCodepoint(value, value.length); } catch { invalid('文本包含非法Unicode'); }
}
function time(value: unknown): asserts value is string {
  text(value);
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/.test(value) || value.startsWith('0000-')) invalid('时间必须为UTC毫秒格式');
  const date = new Date(value);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== value) invalid('时间日期不合法');
}
function provenance(actor: unknown, source: unknown, id: unknown): void {
  if (source === 'TEMPLATE') {
    if (actor !== 'SYSTEM' || id !== null) invalid('模板署名或来源ID不合法');
    return;
  }
  integer(id);
  if ((source === 'GUIDE_RUN' && actor === 'AI') ||
    (source === 'SUGGESTION_BATCH' && (actor === 'AI' || actor === 'USER')) ||
    (source === 'MANUAL_EDIT' && actor === 'USER')) return;
  invalid('署名或来源类型组合不合法');
}

const blockFields = ['block_id', 'block_type', 'section_path', 'created_by_type', 'created_source_type',
  'created_source_id', 'created_at', 'last_modified_by_type', 'last_modified_source_type',
  'last_modified_source_id', 'last_modified_at'] as const;

export function validateBlockState(ctx: Ctx, markdown: unknown, value: unknown): Readonly<{source: EditorSource; state: BlockState}> {
  text(markdown);
  const input = object(value, ['schema_version', 'next_block_id', 'blocks']);
  if (input.schema_version !== 1) invalid('BlockState版本不合法');
  integer(input.next_block_id);
  const next = input.next_block_id;
  if (!Array.isArray(input.blocks) || input.blocks.length > 10_000) invalid('区块数组类型或容量不合法');
  const source = new EditorSource(ctx, markdown);
  if (input.blocks.length !== source.blocks.length) invalid('区块数量未对应完整Markdown');
  const identities = new Set<number>();
  const blocks = input.blocks.map((entry: unknown, index: number) => {
    const metadata = object(entry, blockFields);
    integer(metadata.block_id);
    if (metadata.block_id >= next || identities.has(metadata.block_id)) invalid('区块ID重复或超过高水位');
    identities.add(metadata.block_id);
    const parsed = source.blocks[index]!;
    if (!BLOCK_TYPES.includes(metadata.block_type as BlockType) || metadata.block_type !== parsed.block_type) invalid('区块类型未对应Markdown');
    if (!Array.isArray(metadata.section_path)) invalid('章节路径必须为数组');
    metadata.section_path.forEach(text);
    if (JSON.stringify(metadata.section_path) !== JSON.stringify(parsed.section_path)) invalid('章节路径未对应Markdown');
    provenance(metadata.created_by_type, metadata.created_source_type, metadata.created_source_id);
    provenance(metadata.last_modified_by_type, metadata.last_modified_source_type, metadata.last_modified_source_id);
    time(metadata.created_at);
    time(metadata.last_modified_at);
    if (metadata.created_at > metadata.last_modified_at) invalid('区块时间倒退');
    return Object.freeze({...metadata, section_path: Object.freeze([...metadata.section_path])}) as unknown as BlockMetadata;
  });
  const state = Object.freeze({schema_version: 1 as const, next_block_id: next,
    blocks: Object.freeze(blocks)}) as BlockState;
  if (new TextEncoder().encode(JSON.stringify(state)).length > 4 * 1024 * 1024) invalid('BlockState超过容量');
  return Object.freeze({source, state});
}

// This checks shape and the Markdown/metadata pair. Actual source object
// relationships, permissions and persistent versions belong to backend/parent.
export function validateDocumentReadModel(ctx: Ctx, value: unknown): Readonly<{document: DocumentReadModel; source: EditorSource}> {
  const input = object(value, ['id', 'requirement_id', 'document_type', 'markdown_content', 'block_state_json',
    'content_version', 'created_at', 'updated_at']);
  integer(input.id);
  integer(input.requirement_id);
  integer(input.content_version);
  if (input.document_type !== 'CURRENT' && input.document_type !== 'MANUAL_DRAFT') invalid('文档类型不合法');
  time(input.created_at);
  time(input.updated_at);
  if (input.created_at > input.updated_at) invalid('文档时间倒退');
  const validated = validateBlockState(ctx, input.markdown_content, input.block_state_json);
  const document = Object.freeze({...input, markdown_content: validated.source.markdown,
    block_state_json: validated.state}) as unknown as DocumentReadModel;
  return Object.freeze({document, source: validated.source});
}
