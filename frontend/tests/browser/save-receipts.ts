import type { Crepe } from '@milkdown/crepe';
import { editorViewCtx } from '@milkdown/kit/core';
import { splitBlock } from '@milkdown/kit/prose/commands';
import { closeHistory, undo, redo } from '@milkdown/kit/prose/history';
import { TextSelection } from '@milkdown/kit/prose/state';
import type { Ctx } from '@milkdown/kit/ctx';
import type { DocumentReadModel } from '../../src/documents/contracts.ts';
import { EditedSnapshotLedger, type ManualDraftSubmission, type EditedSnapshot } from '../../src/documents/edited-snapshot.ts';
import { identityState, topBlockIds } from '../../src/documents/identity.ts';
import { EditorSource } from '../../src/documents/editor-source.ts';

function equal(actual: unknown, expected: unknown, label: string) {
  const ordered = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(ordered);
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, entry]) => [key, ordered(entry)]));
    return value;
  };
  if (JSON.stringify(ordered(actual)) !== JSON.stringify(ordered(expected))) throw new Error(label);
}

export function receiptScenario(load: (document: DocumentReadModel) => Promise<void>, get: () => Crepe) {
  let ledger: EditedSnapshotLedger, ticket: ManualDraftSubmission;
  let clock = Date.now(), local: EditedSnapshot;
  const checks: string[] = [], outputs: EditedSnapshot[] = [];
  const action = <T>(callback: (ctx: Ctx) => T) => get().editor.action(callback);
  const capture = () => action(ctx => {
    local = ledger.capture(ctx.get(editorViewCtx).state, new Date(clock = Math.max(clock+1, Date.now())).toISOString());
    outputs.push(local);
    return local;
  });
  const history = (command: typeof undo) => action(ctx => {
    const view = ctx.get(editorViewCtx);
    if (!command(view.state, view.dispatch.bind(view))) throw new Error('实际历史命令未执行');
  });
  const split = () => action(ctx => {
    const view = ctx.get(editorViewCtx);
    view.dispatch(closeHistory(view.state.tr.setSelection(TextSelection.create(view.state.doc, 2))));
    if (!splitBlock(view.state, view.dispatch.bind(view))) throw new Error('实际拆分未执行');
  });
  const removeSecond = (insert = false) => action(ctx => {
    const view = ctx.get(editorViewCtx), start = view.state.doc.child(0).nodeSize;
    let tr = closeHistory(view.state.tr).delete(start, start+view.state.doc.child(1).nodeSize);
    if (insert) tr = tr.insertText('新', 1);
    view.dispatch(tr);
  });
  function accepted(document: DocumentReadModel) {
    const state = action(ctx => ctx.get(editorViewCtx).state);
    const body = local.markdown_content, high = local.block_state_json.next_block_id;
    const acknowledged = ledger.acknowledgeSave(ticket, document);
    equal(acknowledged.markdown_content, body, '迟到回执覆盖新正文');
    equal(acknowledged.block_state_json.next_block_id, high, '回执回退高水位');
    if (action(ctx => ctx.get(editorViewCtx).state) !== state) throw new Error('回执改动真实状态/选区/历史');
    clock = Math.max(clock, Date.parse(document.updated_at)+1);
    local = acknowledged;
    outputs.push(acknowledged);
    const old = ticket;
    let rejected = false;
    try { ledger.acknowledgeSave(old, document); } catch { rejected = true; }
    if (!rejected) throw new Error('重复回执被接受');
  }
  return {
    async start(document: DocumentReadModel) {
      await load(document);
      clock = Math.max(Date.now(), Date.parse(document.updated_at)+1);
      ledger = action(ctx => new EditedSnapshotLedger(ctx, document, ctx.get(editorViewCtx).state));
      split(); capture(); ticket = ledger.beginSave();
      const sent = ticket;
      removeSecond(true); capture();
      split(); capture();
      equal(local.block_state_json.blocks.map(block => block.block_id), [1,4,2], '等待期间真实新分配');
      return {request: sent, local};
    },
    first(document: DocumentReadModel) {
      for (const [name, mutate] of [
        ['foreign-draft', (value: DocumentReadModel) => ({...value, id: value.id+1})],
        ['foreign-requirement', (value: DocumentReadModel) => ({...value, requirement_id: 102})],
        ['wrong-version', (value: DocumentReadModel) => ({...value, content_version: value.content_version+1})],
        ['changed-source', (value: DocumentReadModel) => ({...value, markdown_content: value.markdown_content+'\nextra'})],
        ['forged-new-birth', (value: DocumentReadModel) => ({...value, block_state_json: {...value.block_state_json, blocks: value.block_state_json.blocks.map(block => block.block_id === 3 ? {...block, created_at: value.created_at} : block)}})],
      ] as const) {
        let rejected = false;
        try { ledger.acknowledgeSave(ticket, mutate(document)); } catch { rejected = true; }
        if (!rejected) throw new Error('错误回执被接受: '+name);
        checks.push(name);
      }
      let forged = false;
      try { ledger.acknowledgeSave({...ticket}, document); } catch { forged = true; }
      if (!forged) throw new Error('相似提交对象代替实际发送证明');
      checks.push('forged-ticket');
      accepted(document); checks.push('late-ack-keeps-local-state');
      history(undo); capture();
      history(undo); capture();
      equal(local.block_state_json.blocks.find(block => block.block_id === 3)?.created_at, document.updated_at, '删除块历史出生未接续');
      checks.push('deleted-submitted-block-undo-birth');
      history(redo); capture(); history(redo); capture();
      equal(local.block_state_json.blocks.map(block => block.block_id), [1,4,2], '真实重做恢复后续分配');
      ticket = ledger.beginSave();
      const request = ticket;
      removeSecond(); capture();
      return {request, checks};
    },
    second(document: DocumentReadModel) {
      accepted(document);
      history(undo); capture();
      equal(local.block_state_json.blocks.find(block => block.block_id === 4)?.created_at, document.updated_at, '再次保存删除后恢复出生');
      checks.push('second-receipt-updates-deleted-birth');
      action(ctx => {
        const view = ctx.get(editorViewCtx), position = view.state.doc.content.size;
        view.dispatch(closeHistory(view.state.tr).insert(position, view.state.schema.nodes.paragraph!.create(null, view.state.schema.text('未曾保存可见'))));
      });
      // No ledger capture while the new identity is visible.
      action(ctx => {
        const view = ctx.get(editorViewCtx), last = view.state.doc.lastChild!;
        view.dispatch(closeHistory(view.state.tr).delete(view.state.doc.content.size-last.nodeSize, view.state.doc.content.size));
      });
      capture();
      equal(local.block_state_json.next_block_id, 6, '未可见分配高水位');
      ticket = ledger.beginSave();
      return {request: ticket, checks};
    },
    third(document: DocumentReadModel) {
      accepted(document);
      history(undo); capture();
      equal(local.block_state_json.blocks.find(block => block.block_id === 5)?.created_at, document.updated_at, '只提交高水位的出生恢复');
      checks.push('invisible-allocation-undo-receipt-time');
      ticket = ledger.beginSave();
      return {request: ticket, checks};
    },
    fourth(document: DocumentReadModel) {
      accepted(document);
      const current = capture();
      equal(current.block_state_json, document.block_state_json, '全量实际保存确认未接续');
      const ids = action(ctx => topBlockIds(ctx.get(editorViewCtx).state.doc));
      const next = action(ctx => identityState(ctx.get(editorViewCtx).state).next_block_id);
      ticket = ledger.beginSave();
      ledger.dispose();
      let rejected = false;
      try { ledger.acknowledgeSave(ticket, document); } catch { rejected = true; }
      if (!rejected) throw new Error('已结束生命周期仍接受回执');
      checks.push('disposed-lifecycle-rejects');
      return {checks, outputs: action(ctx => outputs.map(pair => ({pair, projection: new EditorSource(ctx, pair.markdown_content).blocks.map(block => ({block_type: block.block_type, plain_text: block.plain_text, section_path: block.section_path}))}))), ids, next};
    },
  };
}
