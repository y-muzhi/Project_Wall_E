import { useCallback, useState } from 'react';
import type { WalleApi } from '../../api/walle.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { ReadState, useTestingRead } from '../plans/read.tsx';
import { draftSources, QuotePicker } from './basis.tsx';
import {
  driverLabels,
  importanceLabels,
  linkCases,
  modeLabels,
  newBehavior,
  newCase,
  remove,
  replace,
  stageLabels,
} from './draft.ts';
import type { Behavior, Case, Draft, Driver, Importance, Mode, Stage } from './draft.ts';
import { CaseOperations } from './operations.tsx';

type CoverageProps = Readonly<{
  api: WalleApi;
  draft: Draft;
  disabled: boolean;
  change(value: Draft): void;
}>;

function BehaviorEditor({
  api,
  draft,
  item,
  index,
  disabled,
  change,
}: CoverageProps &
  Readonly<{
    item: Behavior;
    index: number;
  }>) {
  const [expanded, setExpanded] = useState(false);
  const sources = draftSources(draft);
  function update(fields: Partial<Behavior>) {
    const behaviors = replace(draft.behaviors, index, { ...item, ...fields });
    if (fields.mode === undefined) {
      change({ ...draft, behaviors });
      return;
    }
    const cases =
      fields.mode === 'AUTO'
        ? draft.cases
        : draft.cases.map((test) => ({
            ...test,
            behavior_ids: test.behavior_ids.filter((key) => key !== item.behavior_id),
          }));
    change(linkCases({ ...draft, behaviors }, cases));
  }
  function deleteBehavior() {
    const cases = draft.cases.map((test) => ({
      ...test,
      behavior_ids: test.behavior_ids.filter((key) => key !== item.behavior_id),
    }));
    change(linkCases({ ...draft, behaviors: remove(draft.behaviors, index) }, cases));
  }
  return (
    <details
      className="testing-editor-panel"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        行为 {index + 1} · {item.name || '待填写'} · {modeLabels[item.mode]}
      </summary>
      {expanded && (
        <fieldset disabled={disabled} className="testing-editor-panel">
          <legend>行为 {index + 1}</legend>
          <label>
            行为名称{' '}
            <input
              value={item.name}
              onChange={(event) => update({ name: event.currentTarget.value })}
            />
          </label>
          <fieldset>
            <legend>适用阶段</legend>
            <div className="code-settings-form-actions">
              {(Object.keys(stageLabels) as Stage[]).map((stage) => (
                <label key={stage}>
                  <input
                    type="checkbox"
                    checked={item.stages.includes(stage)}
                    onChange={(event) =>
                      update({
                        stages: event.currentTarget.checked
                          ? [...item.stages, stage]
                          : item.stages.filter((value) => value !== stage),
                      })
                    }
                  />{' '}
                  {stageLabels[stage]}
                </label>
              ))}
            </div>
          </fieldset>
          <label>
            重要性{' '}
            <select
              value={item.importance}
              onChange={(event) => update({ importance: event.currentTarget.value as Importance })}
            >
              {Object.entries(importanceLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            覆盖方式{' '}
            <select
              value={item.mode}
              onChange={(event) => update({ mode: event.currentTarget.value as Mode })}
            >
              {Object.entries(modeLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            覆盖说明{' '}
            <textarea
              rows={3}
              value={item.explanation}
              onChange={(event) => update({ explanation: event.currentTarget.value })}
            />
          </label>
          {item.mode === 'AUTO' && (
            <p>
              关联用例{' '}
              {draft.cases
                .filter((test) => item.case_ids.includes(test.case_id))
                .map((test) => test.name || test.case_id)
                .join('、') || '请在用例中选择此行为'}
            </p>
          )}
          {item.basis_refs.length === 0 ? (
            <EmptyState icon="outline" message="此行为尚无原文引用" compact />
          ) : (
            <ol>
              {item.basis_refs.map((ref, position) => (
                <li key={JSON.stringify(ref)}>
                  <p>
                    文档 #{ref.document_id} · 版本 #{ref.revision_id}
                  </p>
                  <blockquote>{ref.quote}</blockquote>
                  <button
                    type="button"
                    className="ui-button"
                    onClick={() => update({ basis_refs: remove(item.basis_refs, position) })}
                  >
                    移除此引用
                  </button>
                </li>
              ))}
            </ol>
          )}
          {draft.requirement_id !== null && sources.length > 0 && (
            <QuotePicker
              api={api}
              requirement={draft.requirement_id}
              sources={sources}
              refs={item.basis_refs}
              disabled={disabled}
              added={(ref) => update({ basis_refs: [...item.basis_refs, ref] })}
            />
          )}
          {sources.length === 0 && <p>选定固定依据后可引用原文。</p>}
          <div className="code-settings-form-actions">
            <button className="ui-button" type="button" onClick={deleteBehavior}>
              移除此行为
            </button>
          </div>
        </fieldset>
      )}
    </details>
  );
}

function CaseEditor({
  item,
  behaviors,
  index,
  disabled,
  commands,
  change,
  deleted,
}: Readonly<{
  item: Case;
  behaviors: Draft['behaviors'];
  index: number;
  disabled: boolean;
  commands: readonly { id: string; label: string }[];
  change(value: Case): void;
  deleted(): void;
}>) {
  const [expanded, setExpanded] = useState(false);
  const choices = behaviors.filter(
    (row) => row.mode === 'AUTO' || item.behavior_ids.includes(row.behavior_id),
  );
  const locked = item.steps.length > 0 || item.assertions.length > 0;
  return (
    <details
      className="testing-editor-panel"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        用例 {index + 1} · {item.name || '待填写'} · {driverLabels[item.driver_kind]}
      </summary>
      {expanded && (
        <fieldset disabled={disabled} className="testing-editor-panel">
          <legend>用例 {index + 1}</legend>
          <label>
            用例名称{' '}
            <input
              value={item.name}
              onChange={(event) => change({ ...item, name: event.currentTarget.value })}
            />
          </label>
          <label>
            公开范围{' '}
            <select
              value={item.visibility}
              onChange={(event) =>
                change({
                  ...item,
                  visibility: event.currentTarget.value === 'HELD_OUT' ? 'HELD_OUT' : 'PUBLIC',
                })
              }
            >
              <option value="PUBLIC">公开</option>
              <option value="HELD_OUT">保留</option>
            </select>
          </label>
          <label>
            固定 Driver{' '}
            <select
              value={item.driver_kind}
              disabled={locked}
              title={locked ? '先移除现有步骤和断言' : undefined}
              onChange={(event) =>
                change({ ...item, driver_kind: event.currentTarget.value as Driver })
              }
            >
              {Object.entries(driverLabels).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {locked && <p>保留现有步骤和断言时，Driver 固定。</p>}
          <label>
            用例超时（秒）{' '}
            <input
              inputMode="numeric"
              value={item.timeout_seconds}
              onChange={(event) => change({ ...item, timeout_seconds: event.currentTarget.value })}
            />
          </label>
          <fieldset>
            <legend>关联自动行为</legend>
            {choices.length === 0 && (
              <EmptyState icon="outline" message="当前没有可关联的自动行为" compact />
            )}
            {choices.map((row) => (
              <label key={row.behavior_id}>
                <input
                  type="checkbox"
                  checked={item.behavior_ids.includes(row.behavior_id)}
                  onChange={(event) =>
                    change({
                      ...item,
                      behavior_ids: event.currentTarget.checked
                        ? [...item.behavior_ids, row.behavior_id]
                        : item.behavior_ids.filter((key) => key !== row.behavior_id),
                    })
                  }
                />{' '}
                {row.name || row.behavior_id}
              </label>
            ))}
          </fieldset>
          <CaseOperations
            key={item.driver_kind + ':steps'}
            item={item}
            kind="step"
            commands={commands}
            disabled={disabled}
            change={change}
          />
          <CaseOperations
            key={item.driver_kind + ':assertions'}
            item={item}
            kind="assertion"
            commands={commands}
            disabled={disabled}
            change={change}
          />
          <div className="code-settings-form-actions">
            <button className="ui-button" type="button" onClick={deleted}>
              移除此用例
            </button>
          </div>
        </fieldset>
      )}
    </details>
  );
}

export function CoverageEditor({ api, draft, disabled, change }: CoverageProps) {
  const readOptions = useCallback(
    (signal: AbortSignal) => api.testingProfileChoices(signal),
    [api],
  );
  const resources = useTestingRead(
    'draft-resource-options',
    draft.cases.length ? readOptions : null,
  );
  const commands =
    resources.data?.COMMAND.filter((item) => item.value.purpose === 'CHECK').map((item) => ({
      id: item.value.command_id,
      label: item.label,
    })) ?? [];
  return (
    <>
      <section className="testing-editor-panel" aria-label="编辑行为与覆盖">
        <header className="code-settings-section-heading">
          <h4>行为与覆盖</h4>
          <button
            type="button"
            className="ui-button"
            disabled={disabled || draft.behaviors.length >= 4096}
            title={draft.behaviors.length >= 4096 ? '已达行为数量上限' : undefined}
            onClick={() => change({ ...draft, behaviors: [...draft.behaviors, newBehavior()] })}
          >
            添加行为
          </button>
        </header>
        {draft.behaviors.length === 0 && (
          <EmptyState icon="outline" message="此草稿尚无测试行为" compact />
        )}
        {draft.behaviors.map((item, index) => (
          <BehaviorEditor
            key={item.behavior_id}
            api={api}
            item={item}
            index={index}
            draft={draft}
            disabled={disabled}
            change={change}
          />
        ))}
      </section>
      <section className="testing-editor-panel" aria-label="编辑测试用例">
        <header className="code-settings-section-heading">
          <h4>测试用例</h4>
          <button
            type="button"
            className="ui-button"
            disabled={disabled || draft.cases.length >= 4096}
            title={draft.cases.length >= 4096 ? '已达用例数量上限' : undefined}
            onClick={() => change({ ...draft, cases: [...draft.cases, newCase()] })}
          >
            添加用例
          </button>
        </header>
        <ReadState
          loading={resources.loading}
          error={resources.error}
          stale={resources.data !== null}
          retry={resources.reload}
        />
        {resources.data && !resources.data.RUNNER.some((item) => item.ready) && (
          <p>独立 Runner 尚未准入。可保存结构化草稿，执行资格由服务端确认。</p>
        )}
        {draft.cases.length === 0 && (
          <EmptyState icon="outline" message="此草稿尚无结构化用例" compact />
        )}
        {draft.cases.map((item, index) => (
          <CaseEditor
            key={item.case_id}
            item={item}
            index={index}
            behaviors={draft.behaviors}
            disabled={disabled}
            commands={commands}
            change={(value) => change(linkCases(draft, replace(draft.cases, index, value)))}
            deleted={() => change(linkCases(draft, remove(draft.cases, index)))}
          />
        ))}
      </section>
      <section className="testing-editor-panel" aria-label="编辑待解决问题">
        <header className="code-settings-section-heading">
          <h4>待解决问题</h4>
          <button
            type="button"
            className="ui-button"
            disabled={disabled || draft.unresolved_questions.length >= 256}
            title={draft.unresolved_questions.length >= 256 ? '已达问题数量上限' : undefined}
            onClick={() =>
              change({ ...draft, unresolved_questions: [...draft.unresolved_questions, ''] })
            }
          >
            添加待解决问题
          </button>
        </header>
        {draft.unresolved_questions.length === 0 && (
          <EmptyState icon="outline" message="此草稿没有待解决问题" compact />
        )}
        {draft.unresolved_questions.map((item, index) => (
          <div key={index} className="testing-editor-panel">
            <label>
              待解决问题 {index + 1}{' '}
              <textarea
                rows={2}
                value={item}
                disabled={disabled}
                onChange={(event) =>
                  change({
                    ...draft,
                    unresolved_questions: replace(
                      draft.unresolved_questions,
                      index,
                      event.currentTarget.value,
                    ),
                  })
                }
              />
            </label>
            <div className="code-settings-form-actions">
              <button
                className="ui-button"
                type="button"
                disabled={disabled}
                onClick={() =>
                  change({
                    ...draft,
                    unresolved_questions: remove(draft.unresolved_questions, index),
                  })
                }
              >
                移除此问题
              </button>
            </div>
          </div>
        ))}
      </section>
    </>
  );
}
