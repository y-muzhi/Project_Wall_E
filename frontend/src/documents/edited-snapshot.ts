import type { Ctx } from '@milkdown/kit/ctx';
import { serializerCtx } from '@milkdown/kit/core';
import { Fragment, type Node } from '@milkdown/kit/prose/model';
import type { EditorState } from '@milkdown/kit/prose/state';
import { validateBlockState, validateDocumentReadModel, type BlockMetadata, type BlockState } from './contracts.ts';
import { EditorSource, EditorSourceInvalid } from './editor-source.ts';
import { bindIdentityDocument, hasRawSource, identityState, IdentityInvalid, rebindSourceContext, replaceParsedSourceDocument, sourceRevision, topBlockIds } from './identity.ts';
import { normalizationProof, normalizeRawSourceBlock, type RawSourceNormalization } from './source-normalization.ts';

export interface EditedSnapshot {
  readonly markdown_content: string;
  readonly block_state_json: BlockState;
}
interface Unit { id: number; node: Node; raw: string; gap: string; actualGap: string; verbatim: boolean; }
interface Version { node: Node; raw: string; revision: number; }
interface Layout { document: Node; markdown: string; units: readonly Unit[]; trailer: string; }
export interface PreparedEditorSnapshot { readonly state: EditorState; readonly pair: EditedSnapshot; }
const preparations = new WeakMap<PreparedEditorSnapshot, {owner: EditedSnapshotLedger; generation: number; staged: EditedSnapshotLedger}>();

function fail(message: string): never { throw new EditorSourceInvalid(message); }
function timestamp(value: string): void {
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/.test(value) || value.startsWith('0000-') ||
      !Number.isFinite(new Date(value).getTime()) || new Date(value).toISOString() !== value) fail('编辑时间必须为真实UTC毫秒');
}

// Compare the user's complete node/mark structure, excluding private identity
// and the code tail derived from source line endings. A serializer may choose
// another Markdown spelling, but it must not lose text, marks or node content.
function intent(node: Node): unknown {
  const attrs = {...node.attrs};
  delete attrs.walle_block_id;
  delete attrs.walle_code_tail;
  if (node.type.name === 'heading') delete attrs.id;
  const children: unknown[] = [];
  node.forEach(child => children.push(intent(child)));
  return {type: node.type.name, attrs, text: node.text ?? null,
    marks: node.marks.map(mark => mark.toJSON()), content: children};
}

// An editor-local source ledger. It emits a local pair, never a saved version
// or authorization decision. The backend must bind MANUAL_EDIT to its real
// persistent session and derive/check the metadata in the save transaction.
export class EditedSnapshotLedger {
  private readonly ctx: Ctx;
  private readonly sessionId: number;
  private readonly initialNext: number;
  private readonly versions = new Map<number, Version[]>();
  private readonly births = new Map<number, BlockMetadata>();
  private readonly layouts: Layout[];
  private units: Unit[];
  private trailer: string;
  private pair: EditedSnapshot;
  private lastTime: string;
  private generation = 0;

  constructor(ctx: Ctx, input: unknown, state: EditorState) {
    const {document, source} = validateDocumentReadModel(ctx, input);
    if (document.document_type !== 'MANUAL_DRAFT') fail('只有真实人工草稿可输出编辑快照');
    const ids = document.block_state_json.blocks.map(block => block.block_id);
    const identity = identityState(state);
    if (identity.next_block_id !== document.block_state_json.next_block_id ||
        !state.doc.eq(bindIdentityDocument(source.document, ids, identity.next_block_id))) fail('载入快照与编辑器状态不一致');
    this.ctx = ctx;
    this.sessionId = document.id;
    this.initialNext = identity.next_block_id;
    this.units = source.blocks.map((block, index) => ({id: ids[index]!, node: state.doc.child(index),
      raw: block.markdown, gap: source.parts[index * 2]!, actualGap: source.parts[index * 2]!, verbatim: true}));
    this.trailer = source.parts.at(-1)!;
    this.pair = Object.freeze({markdown_content: document.markdown_content, block_state_json: document.block_state_json});
    this.lastTime = document.updated_at;
    this.layouts = [{document: state.doc, markdown: document.markdown_content,
      units: this.units.map(unit => ({...unit})), trailer: this.trailer}];
    this.units.forEach((unit, index) => {
      this.versions.set(unit.id, [{node: unit.node, raw: unit.raw, revision: sourceRevision(state.doc)}]);
      this.births.set(unit.id, document.block_state_json.blocks[index]!);
    });
  }

  normalizeRawBlock(state: EditorState, index: number): RawSourceNormalization {
    const id = topBlockIds(state.doc)[index];
    const unit = this.units.find(unit => unit.id === id);
    const sourceIndex = this.pair.block_state_json.blocks.findIndex(block => block.block_id === id);
    if (!unit || sourceIndex < 0) fail('原始节点没有当前账本身份/源码');
    const source = new EditorSource(this.ctx, this.pair.markdown_content);
    const markdown = source.rewriteRawBlock(sourceIndex, unit.node, state.doc.child(index));
    return normalizeRawSourceBlock(this.ctx, state, index, markdown);
  }

  // A raw-source edit may legitimately swallow a later block, or split into
  // several blocks. Reparse the complete authored source and map intersecting
  // old source spans in document order. First split/merge ownership follows
  // the approved rule; later pieces allocate new IDs above the live high water.
  prepareRawDocument(state: EditorState, index: number, at: string): PreparedEditorSnapshot {
    timestamp(at);
    if (at < this.lastTime) fail('编辑时间不能倒退');
    const identity = identityState(state), stateIds = topBlockIds(state.doc);
    const initial = new EditorSource(this.ctx, this.pair.markdown_content);
    let logical = 0, selected = -1;
    state.doc.forEach((node, _position, childIndex) => {
      if (node.type.name === 'paragraph' && !node.content.size) return;
      const unit = this.units[logical];
      if (!unit || unit.id !== stateIds[childIndex] || (childIndex !== index && !unit.node.eq(node))) fail('完整原始源编辑没有同次节点身份映射');
      if (childIndex === index) selected = logical;
      logical++;
    });
    if (logical !== this.units.length || selected < 0 || identity.next_block_id < this.pair.block_state_json.next_block_id) fail('完整原始源编辑缺少当前账本基线');
    if (!hasRawSource(state.doc.child(index))) fail('完整原始源编辑需要实际原始节点');
    const original = initial.blocks[selected]!;
    const raw = initial.rewriteRawBlock(selected, this.units[selected]!.node, state.doc.child(index));
    if (raw === original.markdown) return this.prepare(state, at);
    const markdown = this.pair.markdown_content.slice(0, original.start_utf16) + raw + this.pair.markdown_content.slice(original.end_utf16);
    const source = new EditorSource(this.ctx, markdown), delta = raw.length - original.markdown.length;
    const owners = initial.blocks.map((block, blockIndex) => ({id: this.units[blockIndex]!.id,
      start: block.start_utf16 + (blockIndex > selected ? delta : 0),
      end: blockIndex === selected ? block.start_utf16 + raw.length : block.end_utf16 + (blockIndex > selected ? delta : 0)}));
    let ownerIndex = 0, next = identity.next_block_id;
    const used = new Set<number>();
    const ids = source.blocks.map(block => {
      while (ownerIndex < owners.length && owners[ownerIndex]!.end <= block.start_utf16) ownerIndex++;
      const owner = owners[ownerIndex];
      let id = owner && owner.start < block.end_utf16 ? owner.id : undefined;
      if (id === undefined || used.has(id)) {
        if (next >= Number.MAX_SAFE_INTEGER) throw new IdentityInvalid('区块ID容量耗尽', true);
        id = next++;
      }
      used.add(id);
      return id;
    });
    const prior = new Map(this.pair.block_state_json.blocks.map(block => [block.block_id, block]));
    const oldRaw = new Map(this.units.map(unit => [unit.id, unit.raw]));
    const origin = {last_modified_by_type: 'USER' as const, last_modified_source_type: 'MANUAL_EDIT' as const,
      last_modified_source_id: this.sessionId, last_modified_at: at};
    const blocks = source.blocks.map((block, blockIndex) => {
      const id = ids[blockIndex]!, old = prior.get(id);
      const changed = !old || oldRaw.get(id) !== block.markdown || JSON.stringify(old.section_path) !== JSON.stringify(block.section_path);
      return {block_id: id, ...(old ?? {created_by_type: 'USER' as const, created_source_type: 'MANUAL_EDIT' as const,
        created_source_id: this.sessionId, created_at: at}), ...(changed ? origin : {}),
        block_type: block.block_type, section_path: block.section_path};
    });
    const validated = validateBlockState(this.ctx, markdown, {schema_version: 1, next_block_id: next, blocks});
    const rebound = replaceParsedSourceDocument(state, source.document, ids, next);
    const staged = this.fork();
    staged.units = source.blocks.map((block, blockIndex) => ({id: ids[blockIndex]!, node: rebound.doc.child(blockIndex), raw: block.markdown,
      gap: source.parts[blockIndex * 2]!, actualGap: source.parts[blockIndex * 2]!, verbatim: true}));
    staged.trailer = source.parts.at(-1)!;
    staged.pair = Object.freeze({markdown_content: markdown, block_state_json: validated.state});
    staged.lastTime = at;
    staged.generation++;
    staged.units.forEach((unit, blockIndex) => { if (!staged.births.has(unit.id)) staged.births.set(unit.id, validated.state.blocks[blockIndex]!); });
    return this.preparation(staged, rebound, staged.pair);
  }

  private fork(): EditedSnapshotLedger {
    const staged = Object.create(EditedSnapshotLedger.prototype) as EditedSnapshotLedger;
    Object.assign(staged, this, {
      versions: new Map([...this.versions].map(([id, versions]) => [id, [...versions]])),
      births: new Map(this.births), units: this.units.map(unit => ({...unit})), layouts: [...this.layouts],
    });
    return staged;
  }

  // Stage the source ledger and the actual parsed editor state together. No
  // cache, birth fact or timestamp is published until the caller accepts the
  // exact displayed state. This also rebinds references in unedited blocks.
  prepare(state: EditorState, at: string, normalization?: RawSourceNormalization): PreparedEditorSnapshot {
    const staged = this.fork();
    const pair = staged.capture(state, at, normalization);
    const source = new EditorSource(this.ctx, pair.markdown_content);
    const parsed = bindIdentityDocument(source.document, pair.block_state_json.blocks.map(block => block.block_id), pair.block_state_json.next_block_id);
    let index = 0;
    const children: Node[] = [];
    state.doc.forEach(node => children.push(node.type.name === 'paragraph' && !node.content.size ? node : parsed.child(index++)));
    if (index !== source.blocks.length) fail('完整源码重绑定没有逐块映射');
    const rebound = rebindSourceContext(state, state.doc.copy(Fragment.fromArray(children)));
    return this.preparation(staged, rebound, pair);
  }

  private preparation(staged: EditedSnapshotLedger, rebound: EditorState, pair: EditedSnapshot): PreparedEditorSnapshot {
    const actual = new Map<number, Node>();
    rebound.doc.forEach(node => { const id = Number(node.attrs.walle_block_id); if (id > 0) actual.set(id, node); });
    staged.units = staged.units.map(unit => ({...unit, node: actual.get(unit.id)!}));
    staged.units.forEach(unit => {
      const versions = staged.versions.get(unit.id) ?? [];
      if (!versions.some(version => version.node.eq(unit.node) && version.raw === unit.raw)) {
        versions.push({node: unit.node, raw: unit.raw, revision: sourceRevision(rebound.doc)});
      }
      staged.versions.set(unit.id, versions);
    });
    if (!staged.layouts.some(layout => layout.document.eq(rebound.doc) && layout.markdown === pair.markdown_content)) {
      staged.layouts.push({document: rebound.doc, markdown: pair.markdown_content,
        units: staged.units.map(unit => ({...unit})), trailer: staged.trailer});
    }
    const preparation = Object.freeze({state: rebound, pair});
    preparations.set(preparation, {owner: this, generation: this.generation, staged});
    return preparation;
  }

  accept(preparation: PreparedEditorSnapshot, displayed: EditorState): EditedSnapshot {
    const proof = preparations.get(preparation);
    if (!proof || proof.owner !== this || proof.generation !== this.generation || preparation.state !== displayed) {
      fail('编辑输出没有同次未过期视图/账本证明');
    }
    Object.assign(this, proof.staged);
    preparations.delete(preparation);
    return preparation.pair;
  }

  capture(state: EditorState, at: string, normalization?: RawSourceNormalization): EditedSnapshot {
    timestamp(at);
    if (at < this.lastTime) fail('编辑时间不能倒退');
    const identity = identityState(state);
    if (identity.next_block_id < this.pair.block_state_json.next_block_id) fail('编辑高水位不能倒退');
    const ids = topBlockIds(state.doc);
    const revision = sourceRevision(state.doc);
    const normalized = normalization ? normalizationProof(normalization, state) : undefined;
    const sourceOverrides = new Map<number, {raw: string; gap: string; index: number}>();
    if (normalized) {
      const beforeNext = identityState(normalized.before).next_block_id;
      const sourceIds = normalized.source.blocks.map((_block, index) => ids[normalized.index + index]!);
      if (sourceIds.some((id, index) => id === null || !identity.known_ids.has(id) ||
          (index === 0 ? id !== normalized.original_id : id !== beforeNext + index - 1))) fail('重新分块没有实际身份映射');
      const expected = bindIdentityDocument(normalized.source.document, sourceIds, identity.next_block_id);
      normalized.source.blocks.forEach((block, index) => {
        if (!expected.child(index).eq(state.doc.child(normalized.index + index))) fail('重新分块改变实际解析内容');
        sourceOverrides.set(sourceIds[index]!, {raw: block.markdown, gap: normalized.source.parts[index * 2]!, index});
      });
    }
    const targets: Unit[] = [];
    const used = new Set<number>();
    state.doc.forEach((node, _pos, index) => {
      // Empty paragraphs are caret/gap positions, not Markdown blocks.
      if (node.type.name === 'paragraph' && node.content.size === 0) return;
      const id = ids[index];
      if (id == null || id >= identity.next_block_id || !identity.known_ids.has(id) ||
          (!this.births.has(id) && id < this.initialNext) || used.has(id)) fail('区块没有同会话身份证明');
      used.add(id);
      const override = sourceOverrides.get(id);
      const previous = this.versions.get(id)?.findLast(version => version.revision <= revision && version.node.eq(node));
      const raw = override?.raw ?? previous?.raw ?? (node.type.name === 'walle_raw_source' ? node.textContent :
        this.ctx.get(serializerCtx)(state.doc.copy(Fragment.from(node))));
      targets.push({id, node, raw, gap: '', actualGap: '', verbatim: override !== undefined || previous !== undefined});
    });

    // Preserve authored gaps. A removed block transfers its gap to the next
    // survivor (or trailer); moves carry their own gap. New blocks before a
    // survivor receive its gap. No raw bytes of surviving blocks are trimmed.
    const surviving = new Set(targets.map(unit => unit.id));
    const emptySuccessors = new Map<number, number>();
    let successor: number | undefined;
    for (let index = ids.length - 1; index >= 0; index--) {
      const id = ids[index];
      if (id == null) continue;
      if (surviving.has(id)) successor = id;
      else if (successor !== undefined) emptySuccessors.set(id, successor);
    }
    const gaps = new Map<number, string>();
    let pending = '';
    for (const old of this.units) {
      pending += old.gap;
      if (normalized?.source.blocks.length === 0 && old.id === normalized.original_id) pending += normalized.source.markdown;
      const recipient = surviving.has(old.id) ? old.id : emptySuccessors.get(old.id);
      if (recipient !== undefined && !gaps.has(recipient)) { gaps.set(recipient, pending); pending = ''; }
    }
    let trailer = pending + this.trailer;
    let runStart = 0;
    targets.forEach((unit, index) => {
      if (!gaps.has(unit.id)) return;
      let recipient = runStart;
      while (recipient < index && (sourceOverrides.get(targets[recipient]!.id)?.index ?? 0) > 0) recipient++;
      targets[recipient]!.gap = gaps.get(unit.id)!;
      runStart = index + 1;
    });
    if (normalized) {
      targets.forEach(unit => { unit.gap += sourceOverrides.get(unit.id)?.gap ?? ''; });
      const trailing = normalized.source.blocks.length ? normalized.source.parts.at(-1)! :
        this.units.some(unit => unit.id === normalized.original_id) ? '' : normalized.source.markdown;
      if (trailing) {
        const followingIds = new Set(ids.slice(normalized.index + normalized.source.blocks.length).filter(id => id !== null));
        const following = targets.find(unit => followingIds.has(unit.id));
        if (following) following.gap = trailing + following.gap;
        else trailer = trailing + trailer;
      }
    }
    // Same-session history can restore a complete prior node layout, including
    // its authored gaps. This does not assign identities: the identity plugin
    // has already proved every ID above. Content alone never selects an ID.
    const restoredLayout = normalized ? undefined : this.layouts.findLast(layout => layout.document.eq(state.doc));
    if (restoredLayout) {
      const restored = new Map(restoredLayout.units.map(unit => [unit.id, unit]));
      for (const unit of targets) {
        const original = restored.get(unit.id);
        if (!original || !original.node.eq(unit.node)) fail('恢复源码没有完整同会话布局');
        unit.raw = original.raw;
        unit.gap = original.gap;
        unit.verbatim = true;
      }
      trailer = restoredLayout.trailer;
    }
    const adjacent = new Set(this.units.slice(1).map((unit, index) => `${this.units[index]!.id}:${unit.id}`));
    const oldRaw = new Map(this.units.map(unit => [unit.id, unit.raw]));
    const oldActualGaps = new Map(this.units.map(unit => [unit.id, unit.actualGap]));
    let markdown = '';
    const starts: number[] = [];
    for (const [index, unit] of targets.entries()) {
      let gap = unit.gap;
      const previous = targets[index - 1];
      const unchangedBoundary = previous && adjacent.has(`${previous.id}:${unit.id}`) &&
        previous.raw === oldRaw.get(previous.id) && unit.raw === oldRaw.get(unit.id);
      const normalizedBoundary = previous && sourceOverrides.has(previous.id) && sourceOverrides.has(unit.id) &&
        sourceOverrides.get(previous.id)!.index + 1 === sourceOverrides.get(unit.id)!.index;
      if (unchangedBoundary) gap = oldActualGaps.get(unit.id)!;
      if (previous && !unchangedBoundary && !normalizedBoundary) {
        const boundary = (/[ \t\r\n]*$/.exec(markdown)?.[0] ?? '') + unit.gap + (/^[ \t\r\n]*/.exec(unit.raw)?.[0] ?? '');
        const endings = boundary.match(/\r\n|\r|\n/g)?.length ?? 0;
        const ending = markdown.endsWith('\r\n') ? '\r\n' : markdown.endsWith('\r') ? '\r' : '\n';
        gap = ending.repeat(Math.max(0, 2 - endings)) + gap;
      }
      markdown += gap;
      starts.push(markdown.length);
      markdown += unit.raw;
    }
    markdown += trailer;
    if (restoredLayout) markdown = restoredLayout.markdown;
    const source = new EditorSource(this.ctx, markdown);
    if (source.blocks.length !== targets.length) fail('重组源码吞掉、合并或新增区块');
    source.blocks.forEach((block, index) => {
      const unit = targets[index]!;
      const suffix = block.markdown.startsWith(unit.raw) ? block.markdown.slice(unit.raw.length) : null;
      const appendedEnding = !/[\r\n]$/.test(unit.raw) && ['\r\n', '\r', '\n'].includes(suffix ?? '');
      if ((!restoredLayout && block.start_utf16 !== starts[index]) || !(suffix === '' || appendedEnding)) fail('重组源码改变区块边界');
      const literal = unit.node.type.name === 'walle_raw_source';
      if (literal ? block.block_type !== unit.node.attrs.kind ||
          !(block.plain_text === unit.node.textContent || appendedEnding && block.plain_text === unit.node.textContent + suffix) :
          !unit.verbatim && JSON.stringify(intent(block.node)) !== JSON.stringify(intent(unit.node))) fail('序列化改变区块解释或丢失编辑内容');
    });
    const prior = new Map(this.pair.block_state_json.blocks.map(block => [block.block_id, block]));
    const priorRaw = new Map(this.units.map(unit => [unit.id, unit.raw]));
    const blocks = targets.map((unit, index) => {
      const parsed = source.blocks[index]!;
      const old = prior.get(unit.id);
      const birth = this.births.get(unit.id);
      const changed = !old || priorRaw.get(unit.id) !== parsed.markdown ||
        JSON.stringify(old.section_path) !== JSON.stringify(parsed.section_path);
      const origin = {last_modified_by_type: 'USER' as const, last_modified_source_type: 'MANUAL_EDIT' as const,
        last_modified_source_id: this.sessionId, last_modified_at: at};
      return {block_id: unit.id, ...(old ?? birth ?? {created_by_type: 'USER' as const, created_source_type: 'MANUAL_EDIT' as const,
        created_source_id: this.sessionId, created_at: at}), ...(changed ? origin : {}),
        block_type: parsed.block_type, section_path: parsed.section_path};
    });
    const validated = validateBlockState(this.ctx, markdown, {schema_version: 1, next_block_id: identity.next_block_id, blocks});
    const nextPair = Object.freeze({markdown_content: markdown, block_state_json: validated.state});
    // Publish ledger updates only after the complete pair has passed. Failed
    // composition cannot poison later retries or manufacture creation facts.
    targets.forEach((unit, index) => {
      if (!this.births.has(unit.id)) this.births.set(unit.id, validated.state.blocks[index]!);
      const history = this.versions.get(unit.id) ?? [];
      const raw = source.blocks[index]!.markdown;
      if (!history.some(version => version.node.eq(unit.node) && version.raw === raw && version.revision <= revision)) history.push({node: unit.node, raw, revision});
      this.versions.set(unit.id, history);
    });
    // Only authored gaps transfer on a later edit. Syntax separators added by
    // composition are recomputed, so split/join/undo cannot accumulate them.
    this.units = targets.map((unit, index) => ({...unit, raw: source.blocks[index]!.markdown, actualGap: source.parts[index * 2]!}));
    this.trailer = trailer;
    if (!restoredLayout) this.layouts.push({document: state.doc, markdown,
      units: this.units.map(unit => ({...unit})), trailer});
    this.pair = nextPair;
    this.lastTime = at;
    this.generation++;
    return nextPair;
  }
}
