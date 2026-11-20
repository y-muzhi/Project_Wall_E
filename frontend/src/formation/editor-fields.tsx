import { useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';
import { snapshotObject } from '../api/client.ts';
import type { JsonObject, Json } from '../api/client.ts';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationPathEditor, EditorChange } from './path-editor.ts';
import { ContentBlockPicker, FormationPicker } from './editor-pickers.tsx';
import { FormationPage } from './page-view.tsx';
import type { RelationKind } from '../api/formation-reads.ts';
export const stringValue = (value: Json | undefined) => (typeof value === 'string' ? value : '');
export const stringValues = (value: Json | undefined): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
const numberValues = (value: Json | undefined): number[] =>
  Array.isArray(value) ? value.filter((item): item is number => typeof item === 'number') : [];
export function EditorText({
  label,
  value,
  onChange,
  maximum = 1000,
  multiline = false,
}: Readonly<{
  label: string;
  value: string;
  onChange: (text: string) => void;
  maximum?: number;
  multiline?: boolean;
}>) {
  const length = [...value].length;
  return (
    <label className="formation-editor-field">
      {label} *
      {multiline ? (
        <textarea
          value={value}
          maxLength={maximum * 2}
          rows={3}
          aria-invalid={length > maximum}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          value={value}
          maxLength={maximum * 2}
          aria-invalid={length > maximum}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <small>
        {length} / {maximum} 字符
      </small>
    </label>
  );
}
export function RelatedCancellation({
  owner,
  stepRef,
  baseF,
}: Readonly<{ owner: FormationWorkspace; stepRef: string; baseF: number }>) {
  const [opened, setOpened] = useState(false),
    [kind, setKind] = useState<RelationKind>('ISSUE');
  return (
    <details onToggle={(event) => setOpened(event.currentTarget.open)}>
      <summary>查看取消影响的完整关系</summary>
      {opened && (
        <>
          <label>
            关系类型
            <select
              aria-label="关系类型"
              value={kind}
              onChange={(event) => setKind(event.target.value as RelationKind)}
            >
              <option value="ISSUE">待处理问题</option>
              <option value="BRANCH">返回此步的支线</option>
              <option value="DEPENDENCY">前置依赖</option>
              <option value="REPLACES">替代来源</option>
              <option value="ARTIFACT">已有成果</option>
            </select>
          </label>
          <FormationPage
            key={[stepRef, kind, baseF].join(':')}
            scope={[stepRef, kind, baseF].join(':')}
            icon="outline"
            empty="此类关系暂无记录"
            load={(cursor, signal) =>
              owner.api.getFormationRelations(
                owner.requirementId,
                owner.documentId,
                stepRef,
                {
                  relation_kind: kind,
                  limit: 20,
                  known_f: baseF,
                  ...(cursor === null ? {} : { cursor }),
                },
                signal,
              )
            }
            render={(row) => (
              <p>
                {'issue' in row
                  ? row.issue.description
                  : 'branch' in row
                    ? row.branch.question
                    : 'artifact' in row
                      ? row.artifact.summary
                      : 'to_step_ref' in row
                        ? '关联步骤 ' + row.to_step_ref
                        : '相关主题'}
              </p>
            )}
          />
          <p className="field-help">
            开放问题应明确转交或处置；开放支线应调整返回步骤或明确处置。未加载的关系仍由程序完整核对。
          </p>
        </>
      )}
    </details>
  );
}
export function PathChangeFields({
  owner,
  editor,
  change,
}: Readonly<{ owner: FormationWorkspace; editor: FormationPathEditor; change: EditorChange }>) {
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot),
    value = change.value;
  const update = (patch: JsonObject) => editor.update(change.local_key, patch);
  const text = (field: string, label: string, max = 1000, multiline = false) => (
    <EditorText
      label={label}
      value={stringValue(value[field])}
      onChange={(text) => update({ [field]: text })}
      maximum={max}
      multiline={multiline}
    />
  );
  const pick = (
    field: string,
    label: string,
    kind: 'STEP' | 'RESULT' | 'ISSUE' | 'BRANCH' = 'STEP',
    multi = false,
    temporary = false,
    nullable = false,
  ) => (
    <FormationPicker
      owner={owner}
      editor={editor}
      kind={kind}
      label={label}
      values={
        multi
          ? stringValues(value[field])
          : typeof value[field] === 'string' && value[field] !== ''
            ? [value[field]]
            : []
      }
      onChange={(rows) => update({ [field]: multi ? rows : (rows[0] ?? (nullable ? null : '')) })}
      multiple={multi}
      temporary={temporary}
      nullable={nullable}
    />
  );
  const kind = (
    <label className="formation-editor-field">
      成果类型
      <select
        aria-label="成果类型"
        value={stringValue(value.kind) || 'CONTENT'}
        onChange={(event) => update({ kind: event.target.value })}
      >
        <option value="CONTENT">文档内容</option>
        <option value="ANALYSIS">分析结论</option>
      </select>
    </label>
  );
  let content: ReactNode;
  switch (value.type) {
    case 'SET_GOAL':
      content = text('text', '文档目标', 1000, true);
      break;
    case 'ADD_STEP': {
      const expected = Array.isArray(value.expected_results)
        ? value.expected_results.map(snapshotObject)
        : [];
      content = (
        <>
          {text('title', '新步骤名称', 120)}
          <fieldset>
            <legend>预期成果（1—20项） *</legend>
            {expected.map((result, index) => (
              <div className="formation-expected-form" key={String(result.temp_result_ref)}>
                <EditorText
                  label={'成果 ' + (index + 1) + ' 说明'}
                  value={stringValue(result.description)}
                  multiline
                  onChange={(description) =>
                    update({
                      expected_results: expected.map((row, n) =>
                        n === index ? { ...row, description } : row,
                      ),
                    })
                  }
                />
                <label>
                  成果类型
                  <select
                    aria-label="成果类型"
                    value={stringValue(result.kind)}
                    onChange={(event) =>
                      update({
                        expected_results: expected.map((row, n) =>
                          n === index ? { ...row, kind: event.target.value } : row,
                        ),
                      })
                    }
                  >
                    <option value="CONTENT">文档内容</option>
                    <option value="ANALYSIS">分析结论</option>
                  </select>
                </label>
                <button
                  className="ui-button"
                  type="button"
                  disabled={expected.length <= 1}
                  onClick={() =>
                    update({ expected_results: expected.filter((_row, n) => n !== index) })
                  }
                >
                  删除此成果
                </button>
              </div>
            ))}
            <button
              className="ui-button"
              type="button"
              disabled={expected.length >= 20}
              onClick={() => editor.addExpected(change.local_key)}
            >
              添加预期成果
            </button>
          </fieldset>
          {pick('dependencies', '前置步骤', 'STEP', true, true, true)}
          {pick('replaces_step_refs', '替代哪些原步骤', 'STEP', true, false, true)}
          {pick('before_step_ref', '放在此步骤之前', 'STEP', false, true, true)}
        </>
      );
      break;
    }
    case 'RENAME_STEP':
      content = (
        <>
          {pick('step_ref', '步骤')}
          {text('title', '新名称', 120)}
        </>
      );
      break;
    case 'MOVE_STEP':
      content = (
        <>
          {pick('step_ref', '移动步骤')}
          {pick('before_step_ref', '移到此步骤之前', 'STEP', false, true, true)}
        </>
      );
      break;
    case 'SET_DEPENDENCIES':
      content = (
        <>
          {pick('step_ref', '步骤')}
          {pick('dependencies', '前置步骤', 'STEP', true, true, true)}
        </>
      );
      break;
    case 'UPDATE_RESULT':
      content = (
        <>
          {pick('result_ref', '原成果', 'RESULT')}
          {text('description', '新成果说明', 1000, true)}
        </>
      );
      break;
    case 'ADD_RESULT':
      content = (
        <>
          {pick('step_ref', '所属步骤', 'STEP', false, true)}
          {text('description', '成果说明', 1000, true)}
          {kind}
        </>
      );
      break;
    case 'CANCEL_STEP': {
      const facts = state.cancellations[change.local_key];
      content = (
        <>
          {pick('step_ref', '要取消的步骤')}
          {pick('replacement_step_refs', '承接步骤', 'STEP', true, true, true)}
          {facts?.loading && <p role="status">正在读取原步骤的完整成果…</p>}
          {facts?.error && <p role="alert">{facts.error}</p>}
          {facts?.step && (
            <section className="formation-note">
              <h4>原步骤成果</h4>
              <ul>
                {facts.step.expected_results.map((result) => (
                  <li key={result.result_ref}>{result.description}</li>
                ))}
              </ul>
              <p>下方逐项设置成果去向；取消不会删除原始成果、正文或来源记录。</p>
              <RelatedCancellation
                owner={owner}
                stepRef={facts.step.step_ref}
                baseF={state.base_F}
              />
            </section>
          )}
        </>
      );
      break;
    }
    case 'LINK_CONTENT':
      content = (
        <>
          {pick('step_ref', '关联到步骤', 'STEP', false, true)}
          {pick('result_refs', '覆盖预期成果', 'RESULT', true, true)}
          <ContentBlockPicker
            owner={owner}
            revisionId={
              typeof value.revision_id === 'number' ? value.revision_id : owner.revisionId
            }
            blockIds={numberValues(value.block_ids)}
            onRevision={(revision_id) => update({ revision_id })}
            onBlocks={(block_ids) => update({ block_ids })}
          />
        </>
      );
      break;
    case 'MOVE_ISSUE':
      content = (
        <>
          {pick('issue_ref', '问题', 'ISSUE')}
          {pick('to_step_ref', '转交到步骤', 'STEP', false, true)}
        </>
      );
      break;
    case 'SET_BRANCH_RETURN':
      content = (
        <>
          {pick('branch_ref', '支线', 'BRANCH')}
          {pick('return_step_ref', '返回到步骤', 'STEP', false, true)}
        </>
      );
      break;
    case 'DISPOSE_ISSUE':
    case 'DISPOSE_BRANCH': {
      const issue = value.type === 'DISPOSE_ISSUE';
      content = (
        <>
          {pick(
            issue ? 'issue_ref' : 'branch_ref',
            issue ? '问题' : '支线',
            issue ? 'ISSUE' : 'BRANCH',
          )}
          <label className="formation-editor-field">
            处置方式
            <select
              aria-label="处置方式"
              value={stringValue(value.disposition)}
              onChange={(event) => update({ disposition: event.target.value })}
            >
              <option value="DEFERRED">暂缓</option>
              <option value="DROPPED">放弃</option>
            </select>
          </label>
          {text('reason', '处置原因', 1000, true)}
        </>
      );
      break;
    }
    case 'RESUME_ISSUE':
      content = pick('issue_ref', '需要恢复的问题', 'ISSUE');
      break;
    default:
      content = <p role="alert">此操作草稿无法识别，请核对后删除该项。</p>;
  }
  return <div className="formation-change-fields">{content}</div>;
}
export function ResultRouteFields({
  owner,
  editor,
}: Readonly<{ owner: FormationWorkspace; editor: FormationPathEditor }>) {
  const state = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  if (state.result_routes.length === 0) return null;
  return (
    <section className="formation-result-routes">
      <h3>原成果的去向</h3>
      {state.result_routes.map((route) => {
        const ref = stringValue(route.from_result_ref);
        const label =
          Object.values(state.cancellations)
            .flatMap((value) => value.step?.expected_results ?? [])
            .find((value) => value.result_ref === ref)?.description ?? ref;
        return (
          <fieldset key={ref}>
            <legend>{label}</legend>
            <label>
              去向
              <select
                aria-label="去向"
                value={stringValue(route.disposition)}
                onChange={(event) =>
                  editor.updateRoute(ref, {
                    disposition: event.target.value,
                    ...(event.target.value === 'NOT_REQUIRED' ? { target_result_refs: [] } : {}),
                  })
                }
              >
                <option value="REPLACED">由其他成果承接</option>
                <option value="NOT_REQUIRED">不再需要</option>
              </select>
            </label>
            {route.disposition === 'REPLACED' && (
              <FormationPicker
                owner={owner}
                editor={editor}
                kind="RESULT"
                label="由哪些成果承接"
                multiple
                temporary
                values={stringValues(route.target_result_refs)}
                onChange={(target_result_refs) => editor.updateRoute(ref, { target_result_refs })}
              />
            )}
            <EditorText
              label="成果去向说明"
              value={stringValue(route.reason)}
              multiline
              onChange={(reason) => editor.updateRoute(ref, { reason })}
            />
          </fieldset>
        );
      })}
    </section>
  );
}
