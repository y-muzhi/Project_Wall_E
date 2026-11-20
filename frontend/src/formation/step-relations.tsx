import { useState } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationStepDetail } from '../api/formation-values.ts';
import { FormationPage } from './page-view.tsx';
const kinds = { DEPENDENCY: '前置步骤', REPLACES: '替代来源步骤', TOPIC: '相关主题' } as const;
export function FormationStepRelations({
  owner,
  step,
}: Readonly<{ owner: FormationWorkspace; step: FormationStepDetail }>) {
  const [opened, setOpened] = useState<ReadonlySet<keyof typeof kinds>>(new Set());
  const f = owner.read.getSnapshot().summary.data?.formation_version;
  if (f === null || f === undefined) return null;
  const count = {
    DEPENDENCY: step.relation_counts.dependencies,
    REPLACES: step.relation_counts.replaces,
    TOPIC: step.relation_counts.topics,
  };
  return (
    <section aria-label="步骤关系">
      {(Object.keys(kinds) as (keyof typeof kinds)[]).map((kind) => {
        const scope = [owner.documentId, step.step_ref, f, kind].join(':');
        return (
          <details
            key={kind}
            onToggle={(event) => {
              const open = event.currentTarget.open;
              setOpened((previous) => {
                const next = new Set(previous);
                if (open) next.add(kind);
                else next.delete(kind);
                return next;
              });
            }}
          >
            <summary>
              {kinds[kind]}（{count[kind]}）
            </summary>
            {opened.has(kind) && (
              <FormationPage
                scope={scope}
                key={scope}
                icon="outline"
                empty={'没有' + kinds[kind]}
                onPathChanged={() => void owner.refresh()}
                load={(cursor, signal) =>
                  owner.api.getFormationRelations(
                    owner.requirementId,
                    owner.documentId,
                    step.step_ref,
                    {
                      relation_kind: kind,
                      limit: 20,
                      known_f: f,
                      ...(cursor === null ? {} : { cursor }),
                    },
                    signal,
                  )
                }
                render={(row) =>
                  'to_step_ref' in row ? (
                    <button
                      type="button"
                      className="ui-button"
                      onClick={() => void owner.selectView(row.to_step_ref)}
                    >
                      查看步骤 {row.to_step_ref}
                    </button>
                  ) : 'topic_ref' in row ? (
                    <span>{row.topic_ref}</span>
                  ) : null
                }
              />
            )}
          </details>
        );
      })}
    </section>
  );
}
