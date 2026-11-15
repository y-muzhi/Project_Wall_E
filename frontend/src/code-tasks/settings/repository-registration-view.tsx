import { useSyncExternalStore } from 'react';
import type { FormEvent } from 'react';
import { ERROR_MESSAGES } from '../../api/code-errors.ts';
import type { CodeErrorCode } from '../../api/code-errors.ts';
import { localTime } from '../../shared/time.ts';
import type { PendingSummary } from '../command-recovery-model.ts';
import type { RepositoryRegistrationOwner } from './repository-registration-owner.ts';

const statuses = {
  PENDING: '等待执行',
  RUNNING: '正在核对仓库',
  SUCCEEDED: '仓库已保存',
  FAILED: '登记失败',
  UNKNOWN: '登记结果待核对',
  CANCELLED: '登记已取消',
};
const inputs = [
  { field: 'name', label: '仓库名称' },
  { field: 'root_path', label: '本机仓库目录' },
] as const;

export function RepositoryRegistration({
  owner,
  pending,
  recoveryKnown,
  changed,
  openRepository,
}: Readonly<{
  owner: RepositoryRegistrationOwner;
  pending: PendingSummary | null;
  recoveryKnown: boolean;
  changed(): void;
  openRepository(id: number): void;
}>) {
  const state = useSyncExternalStore(owner.subscribe, owner.getSnapshot);
  const held = pending !== null || state.commandKey !== null;
  const disabledReason = state.busy
    ? '正在提交登记请求'
    : pending !== null
      ? '已有登记请求待核对'
      : state.commandKey !== null
        ? '请先核对当前草稿关联的原请求'
        : !recoveryKnown
          ? '请先核对待核对操作'
          : !state.fields.name || !state.fields.root_path
            ? '填写名称和目录后可登记'
            : null;
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabledReason !== null) return;
    await owner.submit();
    changed();
  }
  async function readOperation() {
    await owner.read(pending);
    if (pending !== null && owner.getSnapshot().commandKey === null) changed();
  }
  const original = state.original;
  const operation = state.operation;
  return (
    <>
      <form
        className="code-settings-create"
        aria-label="登记仓库"
        aria-busy={state.busy}
        noValidate
        onSubmit={(event) => void submit(event)}
      >
        {inputs.map(({ field, label }) => {
          const id = 'repository-registration-' + field;
          const fieldError = state.fieldErrors[field];
          return (
            <div className="code-settings-registration-field" key={field}>
              <label htmlFor={id}>{label}</label>
              <input
                id={id}
                name={field}
                className="ui-input"
                value={state.fields[field]}
                autoComplete="off"
                disabled={state.busy || held}
                aria-invalid={fieldError !== undefined}
                aria-describedby={
                  fieldError === undefined ? 'repository-registration-status' : id + '-error'
                }
                onChange={(event) => owner.edit(field, event.target.value)}
              />
              {fieldError && (
                <p className="inline-error" id={id + '-error'} role="alert">
                  {fieldError}
                </p>
              )}
            </div>
          );
        })}
        <div className="code-settings-form-actions">
          <button type="submit" className="ui-button" disabled={disabledReason !== null}>
            {state.busy ? '正在提交…' : '登记仓库'}
          </button>
          <p id="repository-registration-status" className="read-status" role="status">
            {disabledReason ?? ''}
          </p>
        </div>
        {state.draftWarning && (
          <p className="read-status" role="status">
            {state.draftWarning}
          </p>
        )}
        {state.submitError && (
          <p className="inline-error" role="alert">
            {state.submitError}
          </p>
        )}
        {original === null && state.operationError && (
          <p className="inline-error" role="alert">
            {state.operationError}
          </p>
        )}
      </form>
      {original !== null && (
        <section
          className="code-settings-resource-detail"
          aria-label="登记原操作"
          aria-busy={state.operationLoading}
        >
          <h3>登记原操作 #{original.operationId}</h3>
          {operation === null ? (
            !state.operationError && <p role="status">登记请求已接收，等待核对原操作。</p>
          ) : (
            <dl className="code-settings-resource-facts">
              <dt>登记状态</dt>
              <dd>{statuses[operation.status]}</dd>
              {operation.failure_code !== null && (
                <>
                  <dt>登记结果</dt>
                  <dd>{ERROR_MESSAGES[operation.failure_code as CodeErrorCode]}</dd>
                </>
              )}
              {operation.ended_at !== null && (
                <>
                  <dt>完成时间</dt>
                  <dd>
                    <time dateTime={operation.ended_at}>{localTime(operation.ended_at)}</time>
                  </dd>
                </>
              )}
            </dl>
          )}
          {state.operationError && (
            <p className="inline-error" role="alert">
              {state.operationError}
            </p>
          )}
          <div className="code-settings-form-actions">
            <button
              type="button"
              className="ui-button"
              disabled={state.operationLoading}
              onClick={() => void readOperation()}
            >
              {state.operationLoading ? '正在读取…' : '读取原登记操作'}
            </button>
            {operation?.status === 'SUCCEEDED' && (
              <button
                type="button"
                className="ui-button"
                onClick={() => openRepository(operation.resource_id)}
              >
                查看已保存仓库 #{operation.resource_id}
              </button>
            )}
          </div>
        </section>
      )}
    </>
  );
}
