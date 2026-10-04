import type { Ctx } from '@milkdown/kit/ctx';
import { serializerCtx } from '@milkdown/kit/core';
import { Fragment } from '@milkdown/kit/prose/model';
import type { EditorState } from '@milkdown/kit/prose/state';
import { EditorSource, EditorSourceInvalid } from './editor-source.ts';
import { hasRawSource, identityState, replaceParsedRawBlock } from './identity.ts';

export interface RawSourceNormalization { readonly state: EditorState; }
interface Proof {
  readonly before: EditorState;
  readonly index: number;
  readonly original_id: number;
  readonly source: EditorSource;
}
const proofs = new WeakMap<RawSourceNormalization, Proof>();

// Apply the real transaction/plugin/history pipeline to a staged immutable
// state. The caller can validate/capture before displaying this actual state.
export function normalizeRawSourceBlock(ctx: Ctx, state: EditorState, index: number, preservedMarkdown?: string): RawSourceNormalization {
  if (!Number.isSafeInteger(index) || index < 0 || index >= state.doc.childCount) throw new EditorSourceInvalid('原始节点位置不合法');
  const original = state.doc.maybeChild(index);
  if (!original || !hasRawSource(original)) throw new EditorSourceInvalid('重新解析需要实际原始节点');
  const nested = original.type.name !== 'walle_raw_source';
  // Serialize the enclosing real block so quote/list indentation and sibling
  // definitions participate in parsing. Parsing only a child's text would
  // incorrectly lose its container and reference context.
  const markdown = preservedMarkdown ?? (nested ? ctx.get(serializerCtx)(state.doc.copy(Fragment.from(original))) : original.textContent);
  const source = Object.freeze(new EditorSource(ctx, markdown));
  if (nested && (source.blocks.length !== 1 || source.blocks[0]!.node.type !== original.type)) {
    throw new EditorSourceInvalid('容器重新解释改变了顶层区块边界');
  }
  const nodes = source.blocks.map(block => block.node);
  const transaction = replaceParsedRawBlock(state, index, nodes);
  const after = state.applyTransaction(transaction).state;
  const expected = state.doc.childCount - 1 + nodes.length;
  if (after.doc.childCount !== Math.max(1, expected) || identityState(after).next_block_id < identityState(state).next_block_id) {
    throw new EditorSourceInvalid('实际重新解析事务改变了区块边界或高水位');
  }
  const result = Object.freeze({state: after});
  proofs.set(result, Object.freeze({before: state, index, original_id: Number(original.attrs.walle_block_id), source}));
  return result;
}

export function normalizationProof(result: RawSourceNormalization, state: EditorState): Proof {
  const proof = proofs.get(result);
  if (!proof || result.state !== state) throw new EditorSourceInvalid('重新解析没有同次实际状态证明');
  return proof;
}
