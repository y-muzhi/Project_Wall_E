import { useRef, useState, useSyncExternalStore } from 'react';
import type { DetailSnapshot } from './detail-read.ts';
import type { RequirementPropertyEdit } from './property-edit.ts';
import { NameEditor } from '../shared/name-editor.tsx';

/** Full reads belong to the page owner. Never reconstruct an activity/draft
 * from PATCH or replace the editor merely because a title changed. */
export function RequirementPropertyControl(
  props: Readonly<{
    flow: RequirementPropertyEdit;
    blocked: boolean;
    writeReady?: boolean;
    refresh(): Promise<DetailSnapshot>;
  }>,
) {
  const state = useSyncExternalStore(props.flow.subscribe, props.flow.getSnapshot),
    [busy, setBusy] = useState(false),
    [readError, setReadError] = useState<string | null>(null),
    pending = useRef(false);
  const locked = props.blocked || busy || state.phase === 'SUBMITTING' || state.phase === 'READING';
  const read = async () => {
    const detail = await props.refresh();
    props.flow.adoptDetail(detail);
    if (props.flow.getSnapshot().phase === 'CONFIRMED') props.flow.finishConfirmed();
  };
  const execute = async (kind: 'SAVE' | 'INSPECT' | 'REFRESH') => {
    if (pending.current || props.blocked || (kind === 'SAVE' && props.writeReady === false)) return;
    pending.current = true;
    setBusy(true);
    setReadError(null);
    try {
      if (kind === 'REFRESH') await read();
      else {
        const completed =
          kind === 'SAVE' ? await props.flow.save() : await props.flow.inspectUnknown();
        const code = props.flow.getSnapshot().error_code;
        if (completed || code === 'STATE_CONFLICT' || code === 'WORK_STATE_CONFLICT') await read();
      }
    } catch {
      setReadError(
        props.flow.getSnapshot().phase === 'CONFIRMED'
          ? '属性保存已确认，实际详情暂时无法读取，请重试读取'
          : '实际详情暂时无法读取，本次输入已保留，请重试读取',
      );
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const unresolved = ['UNKNOWN', 'READING', 'OBSERVED', 'CONFIRMED'].includes(state.phase);
  return (
    <NameEditor
      label="需求名称"
      heading="h1"
      value={state.actual.title}
      draft={state.draft}
      editing={state.phase !== 'VIEW'}
      disabled={locked || !props.flow.allowed || props.writeReady === false}
      inputDisabled={locked || !props.flow.allowed || props.writeReady === false}
      readOnly={unresolved}
      saveDisabled={
        state.phase !== 'EDITING' ||
        locked ||
        !props.flow.allowed ||
        !!readError ||
        props.writeReady === false
      }
      cancelDisabled={
        locked ||
        !['EDITING', 'OBSERVED'].includes(state.phase) ||
        (state.phase === 'OBSERVED' && !!readError)
      }
      begin={() => props.flow.begin()}
      change={(value) => props.flow.change(value)}
      save={() => void execute('SAVE')}
      cancel={() => {
        if (props.flow.cancel()) setReadError(null);
      }}
      feedback={
        <>
          {state.phase === 'SUBMITTING' && <p role="status">保存中…</p>}
          {state.phase === 'READING' && <p role="status">正在核实原请求…</p>}
          {state.phase === 'UNKNOWN' && (
            <button
              className="ui-button"
              type="button"
              disabled={locked}
              onClick={() => void execute('INSPECT')}
            >
              核实保存结果
            </button>
          )}
          {state.phase === 'OBSERVED' && (
            <>
              <p role="status">
                已读取当前实际属性，本次保存结果仍未确认。可继续编辑后显式保存，或取消本次输入。
              </p>
              <button
                className="ui-button"
                type="button"
                disabled={
                  locked || !!readError || !props.flow.allowed || props.writeReady === false
                }
                onClick={() => props.flow.continueEditing()}
              >
                继续编辑
              </button>
            </>
          )}
          {state.phase === 'CONFIRMED' && (
            <p role="status">
              属性保存已确认，{readError ? '详情尚未重新读取。' : '正在读取实际详情。'}
            </p>
          )}
          {state.error && (
            <p role="alert" className="inline-error">
              {state.error}
            </p>
          )}
          {readError && (
            <p role="alert" className="inline-error">
              {readError}
            </p>
          )}
          {(readError ||
            state.error_code === 'STATE_CONFLICT' ||
            state.error_code === 'WORK_STATE_CONFLICT') && (
            <button
              className="ui-button"
              type="button"
              disabled={locked}
              onClick={() => void execute('REFRESH')}
            >
              重新读取属性
            </button>
          )}
        </>
      }
    />
  );
}
