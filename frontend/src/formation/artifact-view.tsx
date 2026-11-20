import { useState } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import { FormationPage } from './page-view.tsx';
import { FormationEventChanges } from './history-view.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
const tabs = { ORIGIN: '原始关联范围', CURRENT: '当前核实范围', LINEAGE: '替代历史' } as const;
type Tab = keyof typeof tabs;
export function FormationArtifactDetails({
  owner,
  artifactRef,
}: Readonly<{ owner: FormationWorkspace; artifactRef: string }>) {
  const [open, setOpen] = useState(false),
    [tab, setTab] = useState<Tab>('ORIGIN'),
    [selected, setSelected] = useState(artifactRef);
  const f = owner.read.getSnapshot().summary.data?.formation_version;
  if (f === null || f === undefined) return null;
  const scope = [owner.documentId, selected, f, tab].join(':');
  const query = (cursor: string | null) => ({
    limit: 20,
    known_f: f,
    ...(cursor === null ? {} : { cursor }),
  });
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>查看关联范围与替代历史</summary>
      {open && (
        <>
          <div role="tablist" aria-label="正文关联详情" className="formation-tabs">
            {(Object.keys(tabs) as Tab[]).map((value) => (
              <button
                type="button"
                key={value}
                role="tab"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
              >
                {tabs[value]}
              </button>
            ))}
          </div>
          <p>当前查看关联：{selected}</p>
          {tab === 'LINEAGE' ? (
            <FormationPage
              key={scope}
              scope={scope}
              icon="history"
              empty="暂无替代记录"
              onPathChanged={() => void owner.refresh()}
              load={(cursor, signal) =>
                owner.api.getFormationLineage(
                  owner.requirementId,
                  owner.documentId,
                  selected,
                  query(cursor),
                  signal,
                )
              }
              render={(row) => (
                <>
                  <strong>
                    {row.artifact_ref} · {row.is_active ? '当前关联' : '已被替代'}
                  </strong>
                  <p>
                    前一关联：{row.predecessor_ref ?? '无'} · 后一关联：{row.successor_ref ?? '无'}
                  </p>
                  <button
                    type="button"
                    className="ui-button"
                    onClick={() => {
                      setSelected(row.artifact_ref);
                      setTab('ORIGIN');
                    }}
                  >
                    查看此关联范围
                  </button>
                  {row.predecessor_review_event_id !== null && (
                    <FormationEventChanges
                      owner={owner}
                      eventId={row.predecessor_review_event_id}
                      label="查看形成此关联时的复核记录"
                    />
                  )}
                  {row.successor_review_event_id !== null && (
                    <FormationEventChanges
                      owner={owner}
                      eventId={row.successor_review_event_id}
                      label="查看此关联被替代时的复核记录"
                    />
                  )}
                </>
              )}
            />
          ) : (
            <FormationPage
              key={scope}
              scope={scope}
              icon="document"
              empty={tab === 'ORIGIN' ? '没有原始关联范围' : '暂无当前核实范围'}
              onPathChanged={() => void owner.refresh()}
              load={(cursor, signal) =>
                owner.api.getFormationRanges(
                  owner.requirementId,
                  owner.documentId,
                  selected,
                  tab,
                  query(cursor),
                  signal,
                )
              }
              render={(row) => (
                <SourceReference
                  label={'版本#' + row.revision_id + ' · 区块' + row.block_id}
                  read={(signal) =>
                    readSource(
                      owner.requirementId,
                      {
                        kind: 'REVISION',
                        document_id: owner.documentId,
                        revision_id: row.revision_id,
                        block_ids: [row.block_id],
                      },
                      owner.api,
                      signal,
                    )
                  }
                />
              )}
            />
          )}
        </>
      )}
    </details>
  );
}
