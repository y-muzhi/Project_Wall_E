import { useState } from 'react';
import type { JsonObject } from '../api/client.ts';
import { stableJson } from '../api/client.ts';
import type { FormationWorkspace } from './workspace.ts';
import { sourceLabel } from './evidence-picker.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import { EmptyState } from '../shared/empty-state.tsx';

export function FormationReadSources({
  owner,
  sources,
  label,
}: Readonly<{
  owner: FormationWorkspace;
  sources: readonly JsonObject[];
  label: string;
}>) {
  const [open, setOpen] = useState(false),
    [page, setPage] = useState(0);
  const rows = [...new Map(sources.map((source) => [stableJson(source), source])).values()];
  const current = Math.min(page, Math.max(0, Math.ceil(rows.length / 20) - 1));
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        {label}（{rows.length}）
      </summary>
      {open &&
        (rows.length === 0 ? (
          <EmptyState icon="document" message="暂无已记录的依据来源" compact />
        ) : (
          <>
            <ul className="formation-records">
              {rows.slice(current * 20, (current + 1) * 20).map((source) => (
                <li key={stableJson(source)!}>
                  <SourceReference
                    label={sourceLabel(source)}
                    read={(signal) => readSource(owner.requirementId, source, owner.api, signal)}
                  />
                </li>
              ))}
            </ul>
            <nav className="formation-pagination" aria-label={label + '分页'}>
              <button
                type="button"
                className="ui-button"
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
              >
                上一页依据
              </button>
              <button
                type="button"
                className="ui-button"
                disabled={(current + 1) * 20 >= rows.length}
                onClick={() => setPage(current + 1)}
              >
                下一页依据
              </button>
            </nav>
          </>
        ))}
    </details>
  );
}
