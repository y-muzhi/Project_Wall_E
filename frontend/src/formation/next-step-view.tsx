import { useState } from 'react';
import { FormationPage } from './page-view.tsx';
import type { FormationWorkspace } from './workspace.ts';
export function FormationNextStep({
  owner,
  current,
  value,
  onChange,
  label = '结束后的讨论目标',
  allowKeep = true,
}: Readonly<{
  owner: FormationWorkspace;
  current: string;
  value: string | null;
  onChange: (ref: string | null) => void;
  label?: string;
  allowKeep?: boolean;
}>) {
  const f = owner.read.getSnapshot().summary.data?.formation_version;
  const [name, setName] = useState<string | null>(null);
  if (f === null || f === undefined) return null;
  const scope = [owner.documentId, current, f, 'completion-next'].join(':');
  return (
    <fieldset className="formation-next-choice">
      <legend>{label}</legend>
      <p>已选：{value === null ? (allowKeep ? '保持原讨论目标' : '尚未选择') : (name ?? value)}</p>
      {allowKeep && (
        <button
          type="button"
          className="ui-button"
          aria-pressed={value === null}
          onClick={() => {
            setName(null);
            onChange(null);
          }}
        >
          保持原讨论目标
        </button>
      )}
      <FormationPage
        key={scope}
        scope={scope}
        icon="outline"
        empty="暂无其他步骤可选"
        onPathChanged={() => void owner.refresh()}
        load={(cursor, signal) =>
          owner.api.getFormationSteps(
            owner.requirementId,
            owner.documentId,
            {
              limit: 20,
              known_f: f,
              include_cancelled: false,
              ...(cursor === null ? {} : { cursor }),
            },
            signal,
          )
        }
        render={(row) => (
          <button
            type="button"
            className="ui-button"
            disabled={row.step_ref === current}
            aria-pressed={value === row.step_ref}
            onClick={() => {
              setName(row.title);
              onChange(row.step_ref);
            }}
          >
            {row.title}
            {row.step_ref === current ? '（当前步骤）' : ''}
          </button>
        )}
      />
    </fieldset>
  );
}
