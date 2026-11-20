import type { FormationWorkspace } from './workspace.ts';
import { FormationPage } from './page-view.tsx';
import { branchLabels } from './labels.ts';
export function FormationInlineBranches({
  owner,
  stepRef,
  formationVersion,
  discuss,
}: Readonly<{
  owner: FormationWorkspace;
  stepRef: string;
  formationVersion: number;
  discuss: () => void;
}>) {
  const scope = [owner.documentId, stepRef, formationVersion, 'inline-branches'].join(':');
  return (
    <section className="formation-inline-branches" aria-label={'步骤' + stepRef + '的支线'}>
      <FormationPage
        scope={scope}
        icon="outline"
        empty="此步骤暂无支线"
        onPathChanged={() => void owner.refresh()}
        load={(cursor, signal) =>
          owner.api.getFormationBranches(
            owner.requirementId,
            owner.documentId,
            {
              limit: 20,
              known_f: formationVersion,
              step_ref: stepRef,
              ...(cursor === null ? {} : { cursor }),
            },
            signal,
          )
        }
        render={(row) => (
          <>
            <strong>{row.question}</strong>
            <p>{branchLabels[row.status]}</p>
            <p>来自：{row.origin_step_ref}</p>
            <p>返回：{row.return_step_ref}</p>
            {row.result_summary && <p>已有结论：{row.result_summary}</p>}
            <button
              type="button"
              className="ui-button"
              disabled={row.status === 'DROPPED' || owner.targetReason !== null}
              title={
                row.status === 'DROPPED' ? '已放弃支线不能继续' : (owner.targetReason ?? undefined)
              }
              onClick={() =>
                void owner.chooseBranch(row).then((ok) => {
                  if (ok) discuss();
                })
              }
            >
              {owner.busy ? '下一轮讨论支线' : row.status === 'OPEN' ? '讨论支线' : '继续讨论支线'}
            </button>
          </>
        )}
      />
    </section>
  );
}
