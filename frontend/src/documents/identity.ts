import type { Crepe } from '@milkdown/crepe';
import { createTimer, type MilkdownPlugin } from '@milkdown/kit/ctx';
import { InitReady, nodesCtx, schemaTimerCtx, editorStateOptionsCtx } from '@milkdown/kit/core';
import { Fragment, type Node } from '@milkdown/kit/prose/model';
import { Plugin, PluginKey, TextSelection, type Command, type EditorState, type Transaction } from '@milkdown/kit/prose/state';
import { Mapping, canJoin } from '@milkdown/kit/prose/transform';
import { keymap } from '@milkdown/kit/prose/keymap';
import { isHistoryTransaction } from '@milkdown/kit/prose/history';
import { Decoration, DecorationSet } from '@milkdown/kit/prose/view';

const MAX_SAFE = 9_007_199_254_740_991;
const ATTRIBUTE = 'walle_block_id';
const SOURCE_REVISION = 'walle_source_revision';
const sourceCounters = new WeakMap<EditorState['schema'], number>();
const key = new PluginKey<IdentityState>('WALLE_BLOCK_IDENTITY');
const moveKey = new PluginKey('WALLE_EXPLICIT_MOVE');

export class IdentityInvalid extends Error {
  readonly code: 'DOCUMENT_INVALID' | 'CAPACITY_EXCEEDED';
  constructor(message: string, capacity = false) {
    super(message);
    this.code = capacity ? 'CAPACITY_EXCEEDED' : 'DOCUMENT_INVALID';
  }
}

export interface IdentityState {
  readonly next_block_id: number;
  readonly known_ids: ReadonlySet<number>;
}

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 && value <= MAX_SAFE;
}

function validateInitial(ids: readonly number[], next: number): void {
  if (ids.length > 10_000 || !integer(next) || ids.some(id => !integer(id) || id >= next) || new Set(ids).size !== ids.length) {
    throw new IdentityInvalid('初始区块身份或高水位不合法');
  }
}

function emptyCaret(doc: Node): boolean {
  return doc.childCount === 1 && doc.firstChild?.type.name === 'paragraph' && doc.firstChild.content.size === 0;
}

function emptyParagraph(node: Node): boolean {
  return node.type.name === 'paragraph' && node.content.size === 0;
}

function rewrite(node: Node, id: number | null): Node {
  if (node.isText) return node;
  const children: Node[] = [];
  node.forEach(child => children.push(rewrite(child, null)));
  const attrs = ATTRIBUTE in node.attrs && node.attrs[ATTRIBUTE] !== id ? {...node.attrs, [ATTRIBUTE]: id} : node.attrs;
  if (id !== null && !(ATTRIBUTE in node.attrs)) throw new IdentityInvalid('编辑器未安装身份属性');
  const content = Fragment.fromArray(children);
  return attrs === node.attrs && content.eq(node.content) ? node : node.type.create(attrs, content, node.marks);
}

export function bindIdentityDocument(doc: Node, ids: readonly number[], next: number): Node {
  validateInitial(ids, next);
  const logicalCount = emptyCaret(doc) && ids.length === 0 ? 0 : doc.childCount;
  if (ids.length !== logicalCount) throw new IdentityInvalid('身份未对应初始区块');
  const children: Node[] = [];
  doc.forEach((node, _pos, index) => children.push(rewrite(node, ids[index] ?? null)));
  return doc.copy(Fragment.fromArray(children));
}

export function identityState(state: EditorState): IdentityState {
  const identity = key.getState(state);
  if (!identity) throw new IdentityInvalid('编辑器身份状态未安装');
  // Do not expose the live mutable Set to callers.
  return Object.freeze({next_block_id: identity.next_block_id, known_ids: new Set(identity.known_ids)});
}

export function topBlockIds(doc: Node): readonly (number | null)[] {
  const result: (number | null)[] = [];
  doc.forEach(node => result.push(integer(node.attrs[ATTRIBUTE]) ? node.attrs[ATTRIBUTE] as number : null));
  return Object.freeze(result);
}

export function sourceRevision(doc: Node): number {
  const revision: unknown = doc.attrs[SOURCE_REVISION] ?? 0;
  if (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 0) throw new IdentityInvalid('源码历史修订不合法');
  return revision;
}

export function createIdentityPlugin(ids: readonly number[], next: number): Plugin<IdentityState> {
  validateInitial(ids, next);
  const initial = Object.freeze([...ids]);
  return new Plugin<IdentityState>({
    key,
    state: {
      init: (_config, state) => {
        const actual = emptyCaret(state.doc) && initial.length === 0 ? [] : topBlockIds(state.doc);
        if (JSON.stringify(actual) !== JSON.stringify(initial)) throw new IdentityInvalid('初始节点身份未绑定');
        return Object.freeze({next_block_id: next, known_ids: new Set(initial)});
      },
      apply: (tr, prior) => tr.getMeta(key) as IdentityState | undefined ?? prior,
    },
    props: {
      decorations: state => {
        const decorations: Decoration[] = [];
        state.doc.forEach((node, pos) => {
          const id = node.attrs[ATTRIBUTE];
          if (integer(id)) decorations.push(Decoration.node(pos, pos + node.nodeSize, {'data-block-id': String(id)}));
        });
        return DecorationSet.create(state.doc, decorations);
      },
    },
    appendTransaction: (transactions, oldState, newState) => {
      if (!transactions.some(tr => tr.docChanged && !tr.getMeta(key))) return;
      const current = identityState(newState);
      const mapping = new Mapping();
      transactions.forEach(tr => mapping.appendMapping(tr.mapping));
      const targets: {node: Node; pos: number}[] = [];
      newState.doc.forEach((node, pos) => targets.push({node, pos}));
      if (targets.filter(target => !emptyParagraph(target.node)).length > 10_000) throw new IdentityInvalid('顶层区块超过容量');
      const assigned = new Map<number, number>();
      const used = new Set<number>();
      const moves = transactions.flatMap(tr => (tr.getMeta(moveKey) ?? []) as {old_index: number; new_index: number}[]);
      for (const move of moves) {
        const old = oldState.doc.maybeChild(move.old_index);
        const target = targets[move.new_index];
        if (!old || !target || !old.eq(target.node) || !integer(old.attrs[ATTRIBUTE]) || used.has(old.attrs[ATTRIBUTE]) || assigned.has(move.new_index)) {
          throw new IdentityInvalid('移动没有明确原节点映射');
        }
        assigned.set(move.new_index, old.attrs[ATTRIBUTE] as number);
        used.add(old.attrs[ATTRIBUTE] as number);
      }
      // Map an actual old node position through the transaction's StepMaps.
      // This is provenance, not a search for equal or similar text. Iterating
      // old document order makes joins keep the first original identity.
      oldState.doc.forEach((node, pos) => {
        const id = node.attrs[ATTRIBUTE];
        if (!integer(id) || used.has(id)) return;
        const anchors = node.nodeSize === 1 ? [pos] : [pos, pos + 1];
        for (const anchor of anchors) {
          const mapped = mapping.mapResult(anchor, 1);
          if (mapped.deleted) continue;
          let low = 0, high = targets.length;
          while (low < high) {
            const middle = Math.floor((low + high) / 2);
            if (targets[middle]!.pos <= mapped.pos) low = middle + 1;
            else high = middle;
          }
          const index = low - 1;
          if (index < 0 || mapped.pos > targets[index]!.pos + targets[index]!.node.nodeSize - 1) continue;
          if (!assigned.has(index)) {
            assigned.set(index, id);
            used.add(id);
          }
          return;
        }
      });
      // Only the same editor's actual history transactions may restore a
      // removed allocated identity. Pasted attributes never grant ownership.
      if (transactions.some(isHistoryTransaction)) targets.forEach(({node}, index) => {
        const id = node.attrs[ATTRIBUTE];
        if (!assigned.has(index) && integer(id) && current.known_ids.has(id) && !used.has(id)) {
          assigned.set(index, id);
          used.add(id);
        }
      });
      const known = new Set(current.known_ids);
      let highWater = current.next_block_id;
      const children = targets.map(({node}, index) => {
        let id = assigned.get(index);
        if (emptyCaret(newState.doc) || (id === undefined && emptyParagraph(node))) return rewrite(node, null);
        if (id === undefined) {
          if (highWater >= MAX_SAFE) throw new IdentityInvalid('区块ID容量耗尽', true);
          id = highWater++;
          known.add(id);
        }
        return rewrite(node, id);
      });
      const doc = newState.doc.copy(Fragment.fromArray(children));
      if (doc.eq(newState.doc) && highWater === current.next_block_id) return;
      const normalized = newState.tr;
      const topPositions = new Map(targets.map((target, index) => [target.pos, children[index]!.attrs[ATTRIBUTE] as number | null]));
      newState.doc.descendants((node, pos) => {
        if (!(ATTRIBUTE in node.attrs)) return;
        const id = topPositions.get(pos) ?? null;
        if (node.attrs[ATTRIBUTE] !== id) normalized.setNodeMarkup(pos, undefined, {...node.attrs, [ATTRIBUTE]: id});
      });
      return normalized.setMeta(key, Object.freeze({next_block_id: highWater, known_ids: known}));
    },
  });
}

export function moveTopBlock(state: EditorState, from: number, to: number): Transaction {
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= state.doc.childCount || to >= state.doc.childCount) {
    throw new IdentityInvalid('移动区块位置不合法');
  }
  if (from === to) return state.tr;
  const order = Array.from({length: state.doc.childCount}, (_, index) => index);
  const [oldIndex] = order.splice(from, 1);
  order.splice(to, 0, oldIndex!);
  const nodes = order.map(index => state.doc.child(index));
  return state.tr.replaceWith(0, state.doc.content.size, Fragment.fromArray(nodes)).setMeta(moveKey,
    order.map((index, newIndex) => ({old_index: index, new_index: newIndex}))
      .filter(move => integer(state.doc.child(move.old_index).attrs[ATTRIBUTE])));
}

// An explicit source-editor operation, not an inference from pasted attrs or
// equal text. A reparsed raw block keeps its first identity; later parsed
// blocks are new. All validation/allocation completes before returning a tr.
export function replaceParsedRawBlock(state: EditorState, index: number, nodes: readonly Node[]): Transaction {
  if (!Number.isSafeInteger(index) || index < 0 || index >= state.doc.childCount) throw new IdentityInvalid('原始节点位置不合法');
  const original = state.doc.child(index), current = identityState(state);
  const id: unknown = original.attrs[ATTRIBUTE];
  if (original.type.name !== 'walle_raw_source' || !integer(id) || !current.known_ids.has(id) ||
      nodes.some(node => node.type.schema !== state.schema || emptyParagraph(node))) throw new IdentityInvalid('重新解析没有实际原始节点/同schema区块证明');
  let logicalCount = nodes.length;
  state.doc.forEach((node, _pos, childIndex) => { if (childIndex !== index && !emptyParagraph(node)) logicalCount++; });
  if (logicalCount > 10_000) throw new IdentityInvalid('顶层区块超过容量');
  let next = current.next_block_id;
  const known = new Set(current.known_ids);
  const replacements = nodes.map((node, childIndex) => {
    let assigned = id;
    if (childIndex) {
      if (next >= MAX_SAFE) throw new IdentityInvalid('区块ID容量耗尽', true);
      assigned = next++;
      known.add(assigned);
    }
    return rewrite(node, assigned);
  });
  if (!replacements.length && state.doc.childCount === 1) {
    const caret = state.schema.nodes.paragraph!.createAndFill();
    if (!caret) throw new IdentityInvalid('空文档缺少实际caret节点');
    replacements.push(rewrite(caret, null));
  }
  let position = 0;
  for (let childIndex = 0; childIndex < index; childIndex++) position += state.doc.child(childIndex).nodeSize;
  if (!(SOURCE_REVISION in state.doc.attrs)) throw new IdentityInvalid('源码历史属性未安装');
  const revision = Math.max(sourceCounters.get(state.schema) ?? 1, sourceRevision(state.doc) + 1);
  if (revision > MAX_SAFE) throw new IdentityInvalid('源码历史容量耗尽', true);
  const transaction = state.tr.replaceWith(position, position + original.nodeSize, Fragment.fromArray(replacements))
    .setDocAttribute(SOURCE_REVISION, revision)
    .setMeta(key, Object.freeze({next_block_id: next, known_ids: known}));
  sourceCounters.set(state.schema, revision + 1);
  return transaction;
}

// ProseMirror's generic backward/forward deletion sometimes removes an empty
// paragraph instead of joining. For an actual top-level paragraph join, the
// approved rule keeps the first identity even when that first part is empty.
function joinEmptyParagraph(direction: -1 | 1): Command {
  return (state, dispatch) => {
    const selection = state.selection;
    if (!(selection instanceof TextSelection) || !selection.empty || selection.$from.depth !== 1) return false;
    const current = selection.$from.parent;
    const offset = selection.$from.parentOffset;
    if (current.type.name !== 'paragraph' || (direction < 0 ? offset !== 0 : offset !== current.content.size)) return false;
    const boundary = direction < 0 ? selection.$from.before(1) : selection.$from.after(1);
    const resolved = state.doc.resolve(boundary);
    const neighbor = direction < 0 ? resolved.nodeBefore : resolved.nodeAfter;
    if (!neighbor || neighbor.type.name !== 'paragraph' || (neighbor.content.size && current.content.size) || !canJoin(state.doc, boundary)) return false;
    dispatch?.(state.tr.join(boundary).scrollIntoView());
    return true;
  };
}

export const joinEmptyParagraphBackward = joinEmptyParagraph(-1);
export const joinEmptyParagraphForward = joinEmptyParagraph(1);

export function installIdentityAttributes(crepe: Crepe): void {
  const ready = createTimer('WalleIdentityAttributes');
  const plugin: MilkdownPlugin = ctx => {
    ctx.record(ready).update(schemaTimerCtx, timers => [...timers, ready]);
    return async () => {
      await ctx.wait(InitReady);
      ctx.update(nodesCtx, nodes => nodes.map(([name, schema]) => [name, name === 'doc'
        ? {...schema, attrs: {...schema.attrs, [SOURCE_REVISION]: {default: 0, validate: (value: unknown) => {
          if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new IdentityInvalid('源码历史属性不合法');
        }}}} : schema.group?.split(' ').includes('block')
        ? {...schema, attrs: {...schema.attrs, [ATTRIBUTE]: {default: null, validate: (value: unknown) => {
          if (value !== null && !integer(value)) throw new IdentityInvalid('节点身份属性不合法');
        }}}} : schema]));
      ctx.done(ready);
      return () => { ctx.clearTimer(ready); };
    };
  };
  crepe.editor.use(plugin);
}

export function installIdentityState(crepe: Crepe, ids: readonly number[], next: number): void {
  const initial = Object.freeze([...ids]);
  validateInitial(initial, next);
  crepe.editor.config(ctx => ctx.update(editorStateOptionsCtx, previous => options => {
    const configured = previous(options);
    if (!configured.doc) throw new IdentityInvalid('初始文档缺失');
    return {...configured, doc: bindIdentityDocument(configured.doc, initial, next),
      plugins: [keymap({Backspace: joinEmptyParagraphBackward, Delete: joinEmptyParagraphForward}),
        ...configured.plugins ?? [], createIdentityPlugin(initial, next)]};
  }));
}
