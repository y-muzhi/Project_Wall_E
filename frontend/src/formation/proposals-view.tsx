import { useState, useSyncExternalStore } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationProposal } from '../api/formation-workflow.ts';
import { FormationPage } from './page-view.tsx';
import { FormationPayloadDetails } from './proposal-details.tsx';
import { EditorText } from './editor-fields.tsx';
import { actionReason, availabilityText } from './labels.ts';
import { readSource } from '../requirements/source-reading.ts';
const states = ['PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'] as const;
const labels = {
  PENDING: '待处理',
  DEFERRED: '已暂缓',
  APPLIED: '已采用',
  SUPERSEDED: '已替代',
} as const;
function ProposalRow({
  owner,
  proposal,
}: Readonly<{ owner: FormationWorkspace; proposal: FormationProposal }>) {
  useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  const [deferring, setDeferring] = useState(false),
    [reason, setReason] = useState(''),
    [preview, setPreview] = useState(false);
  const ref = { message_id: proposal.message_id, card_key: proposal.card_key };
  const blocked = (action: string) =>
    actionReason(proposal.availability, action, owner.writeReason);
  const native = async (
    action: 'RESUME_WRITE_PROPOSAL' | 'WITHDRAW_PROPOSAL_ADJUSTMENT' | 'DEFER_WRITE_PROPOSAL',
  ) => {
    await owner.execute({
      type: 'FORMATION',
      action,
      proposal: ref,
      ...(action === 'DEFER_WRITE_PROPOSAL' ? { reason } : {}),
    });
  };
  const adjust = blocked('adjust'),
    defer = blocked('DEFER_WRITE_PROPOSAL'),
    resume = blocked('RESUME_WRITE_PROPOSAL'),
    withdraw = blocked('WITHDRAW_PROPOSAL_ADJUSTMENT');
  return (
    <article className="formation-proposal-row">
      <header>
        <strong>{proposal.purpose === 'STAGED_WRITE' ? '待写入内容' : '路线调整'}</strong>
        <span>{labels[proposal.disposition]}</span>
      </header>
      <p>{String(proposal.payload.change_summary)}</p>
      {proposal.needs_revision && <p>正在调整，原提案暂不可直接采用</p>}
      {proposal.reasons.length > 0 && (
        <p className="field-help">{proposal.reasons.map(availabilityText).join('；')}</p>
      )}
      <div className="formation-toolbar">
        <button
          type="button"
          className="ui-button"
          onClick={() => void owner.openProposal(proposal.source_run_id)}
        >
          查看原提案
        </button>
        <button
          type="button"
          className="ui-button"
          disabled={adjust !== null}
          title={adjust ?? undefined}
          onClick={() => void owner.adjustProposal(proposal)}
        >
          请 AI 继续调整
        </button>
        {proposal.purpose === 'FORMATION_PATH_CHANGE' && (
          <button
            type="button"
            className="ui-button"
            disabled={adjust !== null}
            title={adjust ?? undefined}
            onClick={() => owner.openPathEditor(ref, proposal.payload)}
          >
            手动调整路线
          </button>
        )}
        {proposal.purpose === 'STAGED_WRITE' && proposal.disposition === 'PENDING' && (
          <button
            type="button"
            className="ui-button"
            disabled={defer !== null}
            title={defer ?? undefined}
            onClick={() => setDeferring((value) => !value)}
          >
            暂缓写入
          </button>
        )}
        {proposal.purpose === 'STAGED_WRITE' && proposal.disposition === 'DEFERRED' && (
          <button
            type="button"
            className="ui-button"
            disabled={resume !== null}
            title={resume ?? undefined}
            onClick={() => void native('RESUME_WRITE_PROPOSAL')}
          >
            恢复写入
          </button>
        )}
        {proposal.needs_revision && (
          <button
            type="button"
            className="ui-button"
            disabled={withdraw !== null}
            title={withdraw ?? undefined}
            onClick={() => void native('WITHDRAW_PROPOSAL_ADJUSTMENT')}
          >
            撤回调整
          </button>
        )}
      </div>
      {deferring && (
        <div className="formation-note">
          <EditorText label="暂缓原因" value={reason} onChange={setReason} multiline />
          <button
            type="button"
            className="ui-button"
            disabled={defer !== null || [...reason].length === 0 || [...reason].length > 1000}
            onClick={() => void native('DEFER_WRITE_PROPOSAL')}
          >
            确认暂缓
          </button>
        </div>
      )}
      <details onToggle={(event) => setPreview(event.currentTarget.open)}>
        <summary>查看原文与范围</summary>
        {preview && (
          <FormationPayloadDetails
            purpose={proposal.purpose}
            payload={proposal.payload}
            read={(source, signal) => readSource(owner.requirementId, source, owner.api, signal)}
            render={(markdown) => owner.api.previewMarkdown(markdown)}
          />
        )}
      </details>
    </article>
  );
}
export function FormationProposals({ owner }: Readonly<{ owner: FormationWorkspace }>) {
  const [open, setOpen] = useState(false),
    [state, setState] = useState<(typeof states)[number]>('PENDING');
  const current = useSyncExternalStore(owner.read.subscribe, owner.read.getSnapshot).summary.data;
  const f = current?.formation_version;
  if (current === null || f === null || f === undefined) return null;
  return (
    <details
      className="formation-proposals"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        文档提案 · 待处理 {current.counts.proposals.PENDING} · 已暂缓{' '}
        {current.counts.proposals.DEFERRED}
      </summary>
      {open && (
        <>
          <label>
            提案状态
            <select
              aria-label="提案状态"
              value={state}
              onChange={(event) => setState(event.target.value as (typeof states)[number])}
            >
              {states.map((value) => (
                <option key={value} value={value}>
                  {labels[value]}
                </option>
              ))}
            </select>
          </label>
          <FormationPage<FormationProposal>
            key={[f, state].join(':')}
            scope={[owner.documentId, f, state].join(':')}
            icon="suggestion"
            empty="此状态暂无文档提案"
            load={(cursor, signal) =>
              owner.api.getFormationProposals(
                owner.requirementId,
                owner.documentId,
                {
                  limit: 20,
                  known_f: f,
                  state,
                  ...(cursor === null ? {} : { cursor }),
                },
                signal,
              )
            }
            onPathChanged={() => void owner.refresh()}
            render={(proposal) => <ProposalRow owner={owner} proposal={proposal} />}
          />
        </>
      )}
    </details>
  );
}
