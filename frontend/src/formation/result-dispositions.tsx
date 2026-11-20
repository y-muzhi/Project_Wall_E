import type { FormationStepDetail } from '../api/formation-values.ts';
import type { FormationWorkspace } from './workspace.ts';
import type { ResultChoices } from './result-state.ts';
import { changeResult } from './result-state.ts';
import { FormationEvidencePicker } from './evidence-picker.tsx';
import { FormationPage } from './page-view.tsx';
import { FormationArtifactDetails } from './artifact-view.tsx';

export function FormationResultDispositions({
  owner,
  step,
  values,
  onChange,
}: Readonly<{
  owner: FormationWorkspace;
  step: FormationStepDetail;
  values: ResultChoices;
  onChange: (values: ResultChoices) => void;
}>) {
  const f = owner.read.getSnapshot().summary.data?.formation_version;
  if (f === null || f === undefined) return null;
  return (
    <section aria-label="结束时记录成果">
      <h4>成果完成情况（可选）</h4>
      <p>
        未选择的成果按尚未完成记录，也可以直接结束。已落入文档和已形成分析均由保存时的实际依据核实。
      </p>
      <ul className="formation-records">
        {step.expected_results.map((result) => {
          const selected = values[result.result_ref];
          const update = (changes: Partial<NonNullable<typeof selected>>) => {
            if (selected !== undefined)
              onChange({ ...values, [result.result_ref]: { ...selected, ...changes } });
          };
          return (
            <li key={result.result_ref} className="formation-disposition">
              <strong>{result.description}</strong>
              <label>
                成果记录
                <select
                  aria-label={'成果记录 ' + result.result_ref}
                  value={selected?.status ?? 'OUTSTANDING'}
                  onChange={(event) =>
                    onChange(
                      changeResult(
                        values,
                        result,
                        event.currentTarget.value as 'OUTSTANDING' | 'LANDED' | 'ANALYZED',
                      ),
                    )
                  }
                >
                  <option value="OUTSTANDING">尚未完成</option>
                  {result.kind === 'CONTENT' ? (
                    <option value="LANDED">核实已落入文档</option>
                  ) : (
                    <option value="ANALYZED">核实已形成分析</option>
                  )}
                </select>
              </label>
              {selected?.status === 'LANDED' && (
                <section aria-label={'选择文档关联 ' + result.result_ref}>
                  <h5>选择实际关联 · 已选 {selected.artifact_refs.length}</h5>
                  <p>只能选择仍有效且覆盖本项成果的关联；保存时会再次核实正文。</p>
                  {selected.artifact_refs.length > 0 && (
                    <div className="formation-toolbar">
                      {selected.artifact_refs.map((ref) => (
                        <button
                          type="button"
                          className="ui-button"
                          key={ref}
                          onClick={() =>
                            update({
                              artifact_refs: selected.artifact_refs.filter(
                                (value) => value !== ref,
                              ),
                            })
                          }
                        >
                          移除关联 {ref}
                        </button>
                      ))}
                    </div>
                  )}
                  <FormationPage
                    key={result.result_ref + ':' + f}
                    scope={[owner.documentId, result.result_ref, f, 'completion-artifacts'].join(
                      ':',
                    )}
                    icon="document"
                    empty="此步骤没有当前有效的关联，可保留为尚未完成"
                    onPathChanged={() => void owner.refresh()}
                    load={(cursor, signal) =>
                      owner.api.getFormationArtifacts(
                        owner.requirementId,
                        owner.documentId,
                        {
                          limit: 20,
                          known_f: f,
                          step_ref: step.step_ref,
                          state: 'CURRENT',
                          include_superseded: false,
                          ...(cursor === null ? {} : { cursor }),
                        },
                        signal,
                      )
                    }
                    render={(row) => {
                      const usable =
                        row.is_active &&
                        row.result_refs.includes(result.result_ref) &&
                        row.freshness === 'CURRENT';
                      return (
                        <>
                          <label>
                            <input
                              type="checkbox"
                              aria-label={
                                '选择关联 ' + row.artifact_ref + ' / ' + result.result_ref
                              }
                              checked={selected.artifact_refs.includes(row.artifact_ref)}
                              disabled={!usable}
                              onChange={(event) =>
                                update({
                                  artifact_refs: event.currentTarget.checked
                                    ? [...selected.artifact_refs, row.artifact_ref]
                                    : selected.artifact_refs.filter(
                                        (ref) => ref !== row.artifact_ref,
                                      ),
                                })
                              }
                            />
                            {row.summary}
                          </label>
                          {!usable && <p>此关联未覆盖本项成果，或已失效。</p>}
                          <FormationArtifactDetails owner={owner} artifactRef={row.artifact_ref} />
                        </>
                      );
                    }}
                  />
                </section>
              )}
              {selected !== undefined && (
                <FormationEvidencePicker
                  owner={owner}
                  step={step}
                  values={selected.source_refs}
                  onChange={(sources) => update({ source_refs: sources })}
                />
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
