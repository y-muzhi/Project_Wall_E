import { useEffect, useRef, useState } from 'react';
import { ApiRejected, ApiUnknown } from '../../api/client.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { CommandStorageError } from '../command-recovery-store.ts';
import type {
  CommandRecovery,
  OriginalRecoveryOptions,
  RecoveryLookup,
} from '../command-recovery.ts';
import type { PendingSummary } from '../command-recovery-model.ts';

type Choice = Readonly<{ action: 'REPLAY' | 'CLOSE'; original: PendingSummary }>;
type Options = Readonly<{ revision: number; value: OriginalRecoveryOptions | null }>;
const closeScope = '关闭只能阻止尚未接收的原请求。已接收的操作仍须核对或终止。';

function resultMessage(choice: Choice, result: RecoveryLookup): string {
  const local = result.local;
  if (local !== null && 'final_state' in local) {
    if (local.final_state === 'CLOSED_UNEXECUTED') return '原请求已关闭';
    if (local.final_state === 'REJECTED') return '已核实原请求被拒绝';
    if (local.final_state === 'CONFIRMED') return '已核实原请求结果';
  }
  if (
    local !== null &&
    !('final_state' in local) &&
    (local.close_state === 'ALREADY_RECEIVED' || local.status === 'ACCEPTED')
  )
    return choice.action === 'CLOSE'
      ? '原请求已接收，不能用关闭取消'
      : '原请求已接收，请核对原操作';
  return '原请求结果仍待核对';
}

export function RecoveryActions({
  record,
  recovery,
  replayEnabled,
  settled,
}: Readonly<{
  record: PendingSummary;
  recovery: CommandRecovery;
  replayEnabled: boolean;
  settled(record: PendingSummary, result: RecoveryLookup | null, message: string): void;
}>) {
  const [expanded, setExpanded] = useState(false);
  const [options, setOptions] = useState<Options | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const key = record.key;
  const revision = record.record_revision;
  useEffect(() => {
    if (!expanded) return;
    let retired = false;
    void recovery.inspectOriginal(key, revision, replayEnabled).then(
      (value) => {
        if (!retired) setOptions({ revision, value });
      },
      () => {
        if (!retired) setOptions({ revision, value: null });
      },
    );
    return () => {
      retired = true;
    };
  }, [expanded, recovery, key, revision, replayEnabled]);

  const currentOptions = options?.revision === revision ? options : null;
  const choiceCurrent = choice?.original.record_revision === revision;
  async function confirm() {
    if (choice === null || !choiceCurrent || running.current) return;
    running.current = true;
    setBusy(true);
    const original = choice.original;
    try {
      const result =
        choice.action === 'REPLAY'
          ? await recovery.replayOriginal(original.key, original.record_revision)
          : await recovery.closeOriginal(original.key, original.record_revision);
      settled(original, result, resultMessage(choice, result));
    } catch (error) {
      const message =
        error instanceof ApiRejected ||
        error instanceof ApiUnknown ||
        error instanceof CommandStorageError
          ? error.message
          : '无法确认操作结果，请重新核对原请求';
      settled(original, null, message);
    } finally {
      running.current = false;
      setBusy(false);
      setChoice(null);
    }
  }
  return (
    <>
      <details
        className="code-settings-recovery-actions"
        onToggle={(event) => {
          const open = event.currentTarget.open;
          setExpanded(open);
          if (!open) setOptions(null);
        }}
      >
        <summary>恢复选项</summary>
        {expanded && currentOptions === null && <p role="status">正在核对可用操作…</p>}
        {expanded && currentOptions?.value === null && (
          <p className="inline-error" role="alert">
            无法验证原请求，请重新核对
          </p>
        )}
        {expanded && currentOptions?.value && (
          <>
            <div className="code-settings-form-actions">
              {currentOptions.value.replay && (
                <button
                  type="button"
                  className="ui-button"
                  onClick={() => setChoice({ action: 'REPLAY', original: record })}
                >
                  按原请求恢复
                </button>
              )}
              {currentOptions.value.close && (
                <button
                  type="button"
                  className="ui-button"
                  onClick={() => setChoice({ action: 'CLOSE', original: record })}
                >
                  {record.close_state === 'REQUESTED' ? '继续核对关闭' : '关闭原请求'}
                </button>
              )}
            </div>
            {currentOptions.value.replayReason && <p>{currentOptions.value.replayReason}</p>}
            {currentOptions.value.close ? (
              <p>{closeScope}</p>
            ) : (
              (record.status === 'ACCEPTED' ||
                record.close_state === 'ALREADY_RECEIVED' ||
                record.lookup_status === 'IN_PROGRESS') && <p>原请求已接收，不能用关闭取消。</p>
            )}
          </>
        )}
      </details>
      <Confirmation
        open={choice !== null}
        title={choice?.action === 'REPLAY' ? '按原请求恢复' : '关闭原请求'}
        description={
          choice?.action === 'REPLAY' ? '将按原请求保存的输入和请求标识提交。' : closeScope
        }
        error={
          choice !== null && !choiceCurrent && !busy
            ? '原请求状态已更新，请重新打开恢复选项。'
            : null
        }
        confirmLabel={choice?.action === 'REPLAY' ? '确认恢复' : '确认关闭'}
        busy={busy}
        dangerous={choice?.action === 'CLOSE'}
        confirmDisabled={!choiceCurrent}
        confirm={() => void confirm()}
        cancel={() => {
          if (!running.current) setChoice(null);
        }}
      />
    </>
  );
}
