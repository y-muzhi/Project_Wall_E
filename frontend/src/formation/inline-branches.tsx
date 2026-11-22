import type { branchView } from '../api/formation-values.ts';
import type { FormationWorkspace } from './workspace.ts';
import { FormationPage } from './page-view.tsx';
import { FormationEventChanges } from './history-view.tsx';
import { branchLabels } from './labels.ts';
export function FormationInlineBranches({
  owner,
  stepRef,
  stepTitle,
  stepTitles,
  formationVersion,
  locating,
  locate,
  discuss,
}: Readonly<{
  owner: FormationWorkspace;
  stepRef: string;
  stepTitle: string;
  stepTitles: ReadonlyMap<string, string>;
  formationVersion: number;
  locating: boolean;
  locate: (ref: string) => void;
  discuss: () => void;
}>) {
  const scope = [owner.documentId, stepRef, formationVersion, 'inline-branches'].join(':');
  return (
    <section className="formation-inline-branches" aria-label={stepTitle + '的支线'}>
      <FormationPage<ReturnType<typeof branchView>>
        key={scope}
        scope={scope}
        icon="outline"
        empty="此步骤暂无支线"
        showTotal={false}
        compactControls
        identity={(row) => row.branch_ref}
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
          <details className="formation-branch">
            <summary>
              <strong>{row.question}</strong>
              <span className="formation-node-status">{branchLabels[row.status]}</span>
              <span className="formation-branch-summary-source">来自 {stepTitle}</span>
            </summary>
            <div className="formation-branch-body">
              <p>{row.relevance}</p>
              {row.result_summary && <p>{row.result_summary}</p>}
              <FormationEventChanges
                owner={owner}
                eventId={row.origin_event_ref}
                label="查看支线来源"
              />
              <div className="formation-toolbar">
                <button
                  type="button"
                  className="ui-button"
                  disabled={locating}
                  onClick={() => locate(row.return_step_ref)}
                >
                  {stepTitles.has(row.return_step_ref)
                    ? '返回位置 · ' + stepTitles.get(row.return_step_ref)
                    : '查看返回位置'}
                </button>
                {row.status !== 'DROPPED' && (
                  <button
                    type="button"
                    className="ui-button"
                    disabled={owner.targetReason !== null}
                    title={owner.targetReason ?? undefined}
                    onClick={() =>
                      void owner.chooseBranch(row).then((ok) => {
                        if (ok) discuss();
                      })
                    }
                  >
                    {owner.busy
                      ? '下一轮讨论支线'
                      : row.status === 'OPEN'
                        ? '讨论支线'
                        : '继续讨论支线'}
                  </button>
                )}
              </div>
            </div>
          </details>
        )}
      />
    </section>
  );
}
