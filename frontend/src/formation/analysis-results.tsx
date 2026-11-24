import { assessmentStaleLabels } from './labels.ts';
import { useState } from 'react';
import type { FormationStepDetail } from '../api/formation-values.ts';
import type { FormationWorkspace } from './workspace.ts';
import { stableJson } from '../api/client.ts';
import { stepEvidence, sourceLabel } from './source-list.tsx';
import { FormationClosureResults } from './closure-view.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
import { EmptyState } from '../shared/empty-state.tsx';

export function FormationAnalysisResults({
  owner,
  step,
}: Readonly<{ owner: FormationWorkspace; step: FormationStepDetail }>) {
  const [open, setOpen] = useState(false),
    [page, setPage] = useState(0);
  const results = step.expected_results.filter((item) => item.kind === 'ANALYSIS');
  const sources = stepEvidence(step);
  const unavailable = step.sources.filter((item) => item.availability !== 'AVAILABLE');
  return (
    <section aria-label="分析成果依据" className="formation-analysis-results">
      <h4>分析成果与依据</h4>
      {results.length === 0 ? (
        <EmptyState icon="document" message="本步骤未设置分析类成果" compact />
      ) : (
        <>
          <ul className="formation-records">
            {results.map((result) => (
              <li key={result.result_ref}>
                <strong>{result.description}</strong>
                <p>分析要求；完成情况以结束时的记录为准。</p>
              </li>
            ))}
          </ul>
          <section aria-label="步骤分析依据">
            <h5>步骤分析依据</h5>
            {step.assessment === null ? (
              <p>尚无步骤评估；已有步骤来源可作为讨论参考。</p>
            ) : (
              <>
                <p>
                  {step.assessment.validity === 'STALE'
                    ? '最近评估依据已变化'
                    : '最近评估依据仍适用于当前版本'}
                </p>
                <p>{step.assessment.reason}</p>
                {step.assessment.stale_reason !== null && (
                  <p>{assessmentStaleLabels[step.assessment.stale_reason]}</p>
                )}
              </>
            )}
            <p>以下是步骤来源及最近评估依据，不代表每项分析成果已完成。</p>
            {unavailable.length > 0 && (
              <div role="status">
                <p>有 {unavailable.length} 条步骤来源暂不可读取：</p>
                <ul>
                  {unavailable.map((item) => (
                    <li key={stableJson(item.source_ref)!}>
                      {sourceLabel(item.source_ref)} ·{' '}
                      {item.availability === 'MISSING' ? '来源已缺失' : '来源资源暂不支持'}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <details onToggle={(event) => setOpen(event.currentTarget.open)}>
              <summary>查看步骤依据（{sources.length}）</summary>
              {open &&
                (sources.length === 0 ? (
                  <EmptyState icon="document" message="暂无步骤分析依据" compact />
                ) : (
                  <>
                    <ul className="formation-records">
                      {sources.slice(page * 20, (page + 1) * 20).map((source) => (
                        <li key={stableJson(source)!}>
                          <SourceReference
                            label={sourceLabel(source)}
                            read={(signal) =>
                              readSource(owner.requirementId, source, owner.api, signal)
                            }
                          />
                        </li>
                      ))}
                    </ul>
                    <nav className="formation-pagination" aria-label="分析依据分页">
                      <button
                        type="button"
                        className="ui-button"
                        disabled={page === 0}
                        onClick={() => setPage((n) => n - 1)}
                      >
                        上一页依据
                      </button>
                      <button
                        type="button"
                        className="ui-button"
                        disabled={(page + 1) * 20 >= sources.length}
                        onClick={() => setPage((n) => n + 1)}
                      >
                        下一页依据
                      </button>
                    </nav>
                  </>
                ))}
            </details>
          </section>
          {step.closure !== null && (
            <section aria-label="结束时的分析成果">
              <h5>最近结束时的分析成果</h5>
              <p>以下记录固定在本次结束时，后续讨论或正文修改不会改写。</p>
              <FormationClosureResults
                owner={owner}
                eventId={step.closure.event_id}
                resultKind="ANALYSIS"
              />
            </section>
          )}
        </>
      )}
    </section>
  );
}
