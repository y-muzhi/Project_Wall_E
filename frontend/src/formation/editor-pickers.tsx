import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { FormationWorkspace } from './workspace.ts';
import type { FormationPathEditor } from './path-editor.ts';
import type { FormationCursorPagination } from '../api/client.ts';
import { ApiRejected, snapshotObject } from '../api/client.ts';
import { EmptyState } from '../shared/empty-state.tsx';
import { SourceReference } from '../requirements/source-reference.tsx';
import { readSource } from '../requirements/source-reading.ts';
type Kind = 'STEP' | 'RESULT' | 'ISSUE' | 'BRANCH';
export type EditorChoice = Readonly<{ value: string; label: string; parent?: string }>;
type ChoicePage = Readonly<{
  items: readonly EditorChoice[];
  total: number;
  pagination: FormationCursorPagination;
}>;
const noPage: ChoicePage = {
  items: [],
  total: 0,
  pagination: { page_size: 20, next_cursor: null, has_more: false },
};
export function temporaryChoices(
  editor: FormationPathEditor,
  kind: 'STEP' | 'RESULT',
): EditorChoice[] {
  return editor.getSnapshot().changes.flatMap(({ value }) => {
    if (kind === 'STEP')
      return value.type === 'ADD_STEP'
        ? [
            {
              value: String(value.temp_step_ref),
              label: '新步骤：' + String(value.title || '未命名'),
            },
          ]
        : [];
    if (value.type === 'ADD_STEP' && Array.isArray(value.expected_results))
      return value.expected_results.map((item) => {
        const result = snapshotObject(item);
        return {
          value: String(result.temp_result_ref),
          label: '新成果：' + String(result.description || '待填写'),
          parent: String(value.temp_step_ref),
        };
      });
    if (value.type === 'ADD_RESULT')
      return [
        {
          value: String(value.temp_result_ref),
          label: '新成果：' + String(value.description || '待填写'),
          parent: String(value.step_ref),
        },
      ];
    return [];
  });
}
export function FormationPicker({
  owner,
  editor,
  kind,
  label,
  values,
  onChange,
  multiple = false,
  nullable = false,
  temporary = false,
}: Readonly<{
  owner: FormationWorkspace;
  editor: FormationPathEditor;
  kind: Kind;
  label: string;
  values: readonly string[];
  onChange: (values: string[]) => void;
  multiple?: boolean;
  nullable?: boolean;
  temporary?: boolean;
}>) {
  const draft = useSyncExternalStore(editor.subscribe, editor.getSnapshot);
  const [cursor, setCursor] = useState<string | null>(null),
    [history, setHistory] = useState<(string | null)[]>([]);
  const [parent, setParent] = useState<string>(''),
    [reload, setReload] = useState(0);
  const [page, setPage] = useState<ChoicePage | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState<string | null>(null);
  const names = useRef(new Map<string, string>());
  const locals =
    temporary && (kind === 'STEP' || kind === 'RESULT') ? temporaryChoices(editor, kind) : [];
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const load = async (): Promise<ChoicePage> => {
      const query = { limit: 20, known_f: draft.base_F, ...(cursor === null ? {} : { cursor }) },
        req = owner.requirementId,
        doc = owner.documentId;
      if (kind === 'STEP') {
        const result = await owner.api.getFormationSteps(
          req,
          doc,
          { ...query, include_cancelled: true },
          controller.signal,
        );
        return {
          items: result.data.items.map((row) => ({ value: row.step_ref, label: row.title })),
          total: result.data.total,
          pagination: result.meta.pagination,
        };
      }
      if (kind === 'ISSUE') {
        const result = await owner.api.getFormationIssues(req, doc, query, controller.signal);
        return {
          items: result.data.items.map((row) => ({ value: row.issue_ref, label: row.description })),
          total: result.data.total,
          pagination: result.meta.pagination,
        };
      }
      if (kind === 'BRANCH') {
        const result = await owner.api.getFormationBranches(req, doc, query, controller.signal);
        return {
          items: result.data.items.map((row) => ({ value: row.branch_ref, label: row.question })),
          total: result.data.total,
          pagination: result.meta.pagination,
        };
      }
      if (parent === '' || parent.startsWith('new_')) return noPage;
      const result = await owner.api.getFormationStep(
        req,
        doc,
        parent,
        draft.base_F,
        controller.signal,
      );
      return {
        items: result.data.expected_results.map((row) => ({
          value: row.result_ref,
          label: row.description,
        })),
        total: result.data.expected_results.length,
        pagination: noPage.pagination,
      };
    };
    void load().then(
      (result) => {
        if (controller.signal.aborted) return;
        for (const option of result.items) names.current.set(option.value, option.label);
        setPage(result);
        setLoading(false);
      },
      (reason) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setError(reason instanceof ApiRejected ? reason.message : '选项暂时无法读取');
      },
    );
    return () => controller.abort();
  }, [owner, kind, draft.base_F, cursor, parent, reload]);
  const options = [
    ...locals.filter((row) => kind !== 'RESULT' || parent === '' || row.parent === parent),
    ...(page?.items ?? []),
  ];
  for (const option of locals) names.current.set(option.value, option.label);
  const selected = multiple ? '' : (values[0] ?? '');
  const absent = selected !== '' && !options.some((row) => row.value === selected);
  return (
    <fieldset className="formation-picker">
      <legend>
        {label}
        {nullable ? '（可不选）' : ' *'}
      </legend>
      {kind === 'RESULT' && (
        <FormationPicker
          owner={owner}
          editor={editor}
          kind="STEP"
          label="成果所属步骤"
          values={parent === '' ? [] : [parent]}
          onChange={(value) => {
            setParent(value[0] ?? '');
            setCursor(null);
            setHistory([]);
          }}
          temporary={temporary}
          nullable
        />
      )}
      <select
        aria-label={label}
        value={selected}
        disabled={loading}
        onChange={(event) => {
          const value = event.target.value;
          if (multiple) {
            if (value !== '' && !values.includes(value)) onChange([...values, value]);
          } else onChange(value === '' ? [] : [value]);
        }}
      >
        <option value="">{loading ? '正在读取…' : nullable ? '不指定' : '请选择'}</option>
        {absent && (
          <option value={selected}>已选：{names.current.get(selected) ?? selected}</option>
        )}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {multiple && values.length > 0 && (
        <ul className="formation-selected-options">
          {values.map((value) => (
            <li key={value}>
              <span>{names.current.get(value) ?? value}</span>
              <button
                type="button"
                className="ui-button"
                aria-label={'移除 ' + (names.current.get(value) ?? value)}
                onClick={() => onChange(values.filter((item) => item !== value))}
              >
                移除
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert">
          {error}
          <button
            className="ui-button"
            type="button"
            onClick={() => setReload((value) => value + 1)}
          >
            重试
          </button>
        </p>
      )}
      {!loading && error === null && options.length === 0 && (
        <EmptyState
          icon={kind === 'ISSUE' ? 'comment' : 'outline'}
          message={
            kind === 'RESULT' && parent === '' ? '选择步骤后读取其预期成果' : '此页暂无可选记录'
          }
          compact
        />
      )}
      {kind !== 'RESULT' && (
        <div className="formation-picker-pages">
          <span>共 {page?.total ?? '—'} 项</span>
          <button
            type="button"
            className="ui-button"
            disabled={loading || history.length === 0}
            onClick={() => {
              setCursor(history.at(-1) ?? null);
              setHistory((rows) => rows.slice(0, -1));
            }}
          >
            上一页
          </button>
          <button
            type="button"
            className="ui-button"
            disabled={loading || page?.pagination.has_more !== true}
            onClick={() => {
              setHistory((rows) => [...rows, cursor]);
              setCursor(page?.pagination.next_cursor ?? null);
            }}
          >
            下一页
          </button>
        </div>
      )}
    </fieldset>
  );
}
type Revision = Awaited<ReturnType<FormationWorkspace['api']['getRevision']>>['data'];
export function ContentBlockPicker({
  owner,
  revisionId,
  blockIds,
  onRevision,
  onBlocks,
}: Readonly<{
  owner: FormationWorkspace;
  revisionId: number;
  blockIds: readonly number[];
  onRevision: (value: number) => void;
  onBlocks: (values: number[]) => void;
}>) {
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState<Revision | null>(null),
    [error, setError] = useState<string | null>(null),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setPage(0);
    setError(null);
    void owner.api.getRevision(revisionId, controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return;
        if (result.data.document_id !== owner.documentId) {
          setError('版本不属于当前文档');
          setLoading(false);
          return;
        }
        setRevision(result.data);
        setLoading(false);
      },
      () => {
        if (!controller.signal.aborted) {
          setError('文档快照暂时无法读取');
          setLoading(false);
        }
      },
    );
    return () => controller.abort();
  }, [owner, revisionId]);
  return (
    <fieldset className="formation-picker">
      <legend>选择已有正文内容 *</legend>
      <p>关联当前文档的正式内容，正文版本 V{owner.contentVersion}</p>
      {revisionId !== owner.revisionId && (
        <div>
          <p role="alert">所选来源版本已变化，请明确改用当前正式版本后重新选择区块。</p>
          <button
            type="button"
            className="ui-button"
            onClick={() => {
              onRevision(owner.revisionId);
              onBlocks([]);
            }}
          >
            使用当前正式版本
          </button>
        </div>
      )}
      <SourceReference
        label="查看所选版本原文"
        read={(signal) =>
          readSource(
            owner.requirementId,
            {
              kind: 'REVISION',
              document_id: owner.documentId,
              revision_id: revisionId,
              block_ids: null,
            },
            owner.api,
            signal,
          )
        }
      />
      {loading && <p role="status">正在读取区块…</p>}
      {error && <p role="alert">{error}</p>}
      {revision !== null && revision.id === revisionId && (
        <div className="formation-block-choices">
          {revision.block_state_json.blocks.slice(page * 20, (page + 1) * 20).map((block) => (
            <label key={block.block_id}>
              <input
                type="checkbox"
                checked={blockIds.includes(block.block_id)}
                disabled={
                  loading ||
                  revisionId !== owner.revisionId ||
                  (!blockIds.includes(block.block_id) && blockIds.length >= 100)
                }
                onChange={(event) =>
                  onBlocks(
                    event.target.checked
                      ? [...blockIds, block.block_id]
                      : blockIds.filter((value) => value !== block.block_id),
                  )
                }
              />
              区块 {block.block_id} · {block.section_path.join(' / ') || '正文'}
            </label>
          ))}
          <div className="formation-picker-pages">
            <span>
              共 {revision.block_state_json.blocks.length} 个区块 · 已选 {blockIds.length} 个
            </span>
            <button
              type="button"
              className="ui-button"
              disabled={loading || page === 0}
              onClick={() => setPage((value) => value - 1)}
            >
              上一页区块
            </button>
            <button
              type="button"
              className="ui-button"
              disabled={loading || (page + 1) * 20 >= revision.block_state_json.blocks.length}
              onClick={() => setPage((value) => value + 1)}
            >
              下一页区块
            </button>
          </div>
          {revision.block_state_json.blocks.length === 0 && (
            <EmptyState icon="document" message="所选版本没有可关联内容" compact />
          )}
        </div>
      )}
    </fieldset>
  );
}
