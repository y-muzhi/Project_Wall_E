import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiRejected, ApiUnknown, snapshotObject } from '../../api/client.ts';
import { normalizedName } from '../../api/code-configuration-identities.ts';
import { testingModelBinding, testingProfilePath } from '../../api/testing-policy.ts';
import { array, distinct, nonempty, nullable, require, shape, text } from '../../api/decoding.ts';
import type {
  TestingLimits,
  TestingProfile,
  TestingProfileContent,
} from '../../api/testing-policy.ts';
import type { TestingProfileChoices } from '../../api/testing-profile-options.ts';
import type { WalleApi } from '../../api/walle.ts';
import { environmentBrowserStorage } from '../../api/environment-storage.ts';
import { CommandStorageError } from '../../code-tasks/command-recovery-store.ts';
import type { CommandRecovery } from '../../code-tasks/command-recovery.ts';
import { Confirmation } from '../../shared/confirmation.tsx';
import { EmptyState } from '../../shared/empty-state.tsx';

const fields = {
  max_model_requests: '计划模型请求上限',
  max_active_seconds: '活动时长上限（秒）',
  max_check_output_bytes: '检查输出上限（字节）',
  max_check_cases: '检查用例上限',
  max_case_steps: '每用例步骤上限',
  max_case_payload_bytes: '用例载荷上限（字节）',
  max_input_bytes: '输入上限（字节）',
  query_timeout_seconds: '查询超时（秒）',
  send_timeout_seconds: '发送超时（秒）',
  graceful_stop_seconds: '正常停止等待（秒）',
  force_stop_wait_seconds: '强制停止等待（秒）',
} satisfies Record<keyof TestingLimits, string>;
const limitNames = Object.keys(fields) as (keyof TestingLimits)[];
type Option = { id: string; label: string; ready: boolean };
type Draft = {
  name: string;
  runner: string[];
  environment: string[];
  commands: string[];
  admission: string[];
  limits: Partial<Record<keyof TestingLimits, string>>;
  model: TestingProfileContent['model_binding'];
};
const empty = (): Draft => ({
  name: '',
  runner: [],
  environment: [],
  commands: [],
  admission: [],
  limits: {},
  model: null,
});

const draftKey = 'walle:v20:testing-profile-draft';
const draftIds = (value: unknown): string[] => {
  const ids = array(nonempty, 256)(value);
  distinct(ids);
  return [...ids];
};
const decodeDraft = shape({
  name: text,
  runner: draftIds,
  environment: draftIds,
  commands: draftIds,
  admission: draftIds,
  model: nullable(testingModelBinding),
  limits(value: unknown) {
    require(typeof value === 'object' && value !== null && !Array.isArray(value));
    const result: Draft['limits'] = {};
    for (const [key, amount] of Object.entries(value)) {
      const field = key as keyof TestingLimits;
      require(limitNames.includes(field));
      result[field] = text(amount);
    }
    return result;
  },
});
function loadDraft(api: WalleApi): Draft {
  try {
    const stored = environmentBrowserStorage('sessionStorage', api.environmentScope).getItem(
      draftKey,
    );
    return stored === null ? empty() : decodeDraft(JSON.parse(stored));
  } catch {
    return empty();
  }
}

function copyOf(profile: TestingProfile): Draft {
  const limits = Object.fromEntries(limitNames.map((key) => [key, String(profile.limits[key])]));
  return {
    name: profile.name,
    runner: [...profile.runner_refs],
    environment: [...profile.environment_refs],
    commands: profile.commands.map((command) => command.command_id),
    admission: [...profile.admission_refs],
    limits,
    model: profile.model_binding,
  };
}

function OptionList({
  label,
  options,
  selected,
  change,
}: Readonly<{
  label: string;
  options: readonly Option[];
  selected: readonly string[];
  change(value: string[]): void;
}>) {
  return (
    <fieldset className="code-settings-versions">
      <legend>{label}</legend>
      {options.length === 0 && (
        <EmptyState icon="outline" message={'当前没有已登记的' + label} compact />
      )}
      {options.map((option) => (
        <div key={option.id}>
          <label>
            <input
              type="checkbox"
              checked={selected.includes(option.id)}
              onChange={(event) => {
                if (event.currentTarget.checked) change([...selected, option.id]);
                else change(selected.filter((id) => id !== option.id));
              }}
            />{' '}
            {option.label}
            {option.ready ? '' : '（尚未就绪）'}
          </label>
        </div>
      ))}
      {selected.some((id) => !options.some((option) => option.id === id)) && (
        <p className="inline-error">
          旧选择中存在当前未登记的资源。
          <button
            type="button"
            className="ui-button"
            onClick={() =>
              change(selected.filter((id) => options.some((option) => option.id === id)))
            }
          >
            移除失效选择
          </button>
        </p>
      )}
    </fieldset>
  );
}

function inputFor(
  draft: Draft,
  options: TestingProfileChoices | null,
): TestingProfileContent | null {
  if (
    options === null ||
    !draft.runner.length ||
    !draft.environment.length ||
    !draft.admission.length
  )
    return null;
  if (
    !draft.runner.every((id) => options.RUNNER.some((option) => option.value.runner_ref === id)) ||
    !draft.environment.every((id) =>
      options.RUNTIME.some((option) => option.value.runtime_ref === id),
    ) ||
    !draft.admission.every((id) =>
      options.CAPABILITY.some((option) => option.value.evidence_ref === id),
    )
  )
    return null;
  const commands = options.COMMAND.filter((option) =>
    draft.commands.includes(option.value.command_id),
  ).map((option) => option.value);
  if (commands.length !== draft.commands.length) return null;
  let name: string;
  try {
    name = normalizedName(draft.name);
  } catch {
    return null;
  }
  if ([...name].length > 200) return null;
  const values: Partial<Record<keyof TestingLimits, number>> = {};
  for (const key of limitNames) {
    const source = draft.limits[key] ?? '';
    const limit = Number(source);
    if (
      !/^[1-9][0-9]*$/.test(source) ||
      !Number.isSafeInteger(limit) ||
      (key === 'max_input_bytes' && limit > 8 * 1024 * 1024)
    )
      return null;
    values[key] = limit;
  }
  return {
    name,
    runner_refs: draft.runner,
    environment_refs: draft.environment,
    commands,
    model_binding: draft.model,
    admission_refs: draft.admission,
    limits: values as TestingLimits,
  };
}

export function TestingProfileForm({
  api,
  recovery,
  selected,
  unavailable,
  published,
  settled,
}: Readonly<{
  api: WalleApi;
  recovery: CommandRecovery;
  selected: TestingProfile | null;
  unavailable: string | null;
  published(id: number): void;
  settled(): void;
}>) {
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [draft, setDraft] = useState<Draft>(() => loadDraft(api));
  const [draftUnavailable, setDraftUnavailable] = useState(false);
  const [options, setOptions] = useState<TestingProfileChoices | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [fixed, setFixed] = useState<TestingProfileContent | null>(null);
  const [saving, setSaving] = useState(false);
  const active = useRef(true);
  const running = useRef(false);

  useEffect(() => {
    try {
      environmentBrowserStorage('sessionStorage', api.environmentScope).setItem(
        draftKey,
        JSON.stringify(draft),
      );
    } catch {
      setDraftUnavailable(true);
    }
  }, [api, draft]);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    if (!open) return;
    const request = new AbortController();
    setLoading(true);
    setError(null);
    void api
      .testingProfileChoices(request.signal)
      .then(
        (result) => {
          if (!request.signal.aborted) setOptions(result);
        },
        (failure: unknown) => {
          if (!request.signal.aborted)
            setError(
              failure instanceof ApiRejected ? failure.message : '暂时无法核实已登记的测试资源',
            );
        },
      )
      .finally(() => {
        if (!request.signal.aborted) setLoading(false);
      });
    return () => request.abort();
  }, [api, attempt, open]);

  const body = inputFor(draft, options);
  const reason = saving
    ? '正在保存配置版本'
    : (unavailable ??
      (loading
        ? '正在读取可选资源'
        : error !== null
          ? '请先核实可选资源'
          : options !== null &&
              (!options.RUNNER.length || !options.RUNTIME.length || !options.CAPABILITY.length)
            ? '需要已登记的运行器、环境和准入依据'
            : body === null
              ? '请填写名称、必选资源及全部正整数限制'
              : null));

  function requestPublish(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason === null && body !== null) {
      setWriteError(null);
      setFixed(body);
    }
  }

  async function publish() {
    if (fixed === null || reason !== null || running.current) return;
    const exact = fixed;
    running.current = true;
    setSaving(true);
    setWriteError(null);
    try {
      const staged = await recovery.stageIntent(
        testingProfilePath,
        snapshotObject({ profile_content: exact }),
      );
      if (staged.kind !== 'PREPARED') {
        setWriteError('已有原配置请求，请先核对');
        return;
      }
      const result = await recovery.send(staged.record.key, staged.record.record_revision);
      if (active.current) {
        setDraft(empty());
        published((result.response.data as TestingProfile).id);
      }
    } catch (failure) {
      if (active.current)
        setWriteError(
          failure instanceof ApiRejected ||
            failure instanceof ApiUnknown ||
            failure instanceof CommandStorageError
            ? failure.message
            : '暂时无法核实配置结果，请检查原请求',
        );
    } finally {
      running.current = false;
      if (active.current) {
        setSaving(false);
        setFixed(null);
        settled();
      }
    }
  }

  return (
    <details
      className="code-settings-versions testing-profile-form"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>新建测试配置版本</summary>
      {open && (
        <form className="code-settings-create" onSubmit={requestPublish}>
          {draftUnavailable && (
            <p className="read-status">草稿暂存不可用，离开页面前请保存所需输入。</p>
          )}
          {selected && (
            <div className="code-settings-form-actions">
              <button
                className="ui-button"
                type="button"
                disabled={saving}
                title={saving ? '正在保存配置版本' : undefined}
                onClick={() => setDraft(copyOf(selected))}
              >
                复制所选版本
              </button>
            </div>
          )}
          <label>
            新配置名称{' '}
            <input
              className="ui-input"
              value={draft.name}
              onChange={(event) => {
                const name = event.currentTarget.value;
                setDraft((current) => ({ ...current, name }));
              }}
            />
          </label>
          {loading && <p role="status">正在读取已登记的测试资源…</p>}
          {error && (
            <div className="code-settings-form-actions">
              <p className="inline-error" role="alert">
                {error}
              </p>
              <button
                className="ui-button"
                type="button"
                onClick={() => setAttempt((current) => current + 1)}
              >
                重试读取资源
              </button>
            </div>
          )}
          {options && (
            <>
              <OptionList
                label="运行器"
                options={options.RUNNER.map((entry) => ({ ...entry, id: entry.value.runner_ref }))}
                selected={draft.runner}
                change={(runner) => setDraft((current) => ({ ...current, runner }))}
              />
              <OptionList
                label="运行环境"
                options={options.RUNTIME.map((entry) => ({
                  ...entry,
                  id: entry.value.runtime_ref,
                }))}
                selected={draft.environment}
                change={(environment) => setDraft((current) => ({ ...current, environment }))}
              />
              <OptionList
                label="检查或服务命令"
                options={options.COMMAND.map((entry) => ({ ...entry, id: entry.value.command_id }))}
                selected={draft.commands}
                change={(commands) => setDraft((current) => ({ ...current, commands }))}
              />
              <OptionList
                label="准入依据"
                options={options.CAPABILITY.map((entry) => ({
                  ...entry,
                  id: entry.value.evidence_ref,
                }))}
                selected={draft.admission}
                change={(admission) => setDraft((current) => ({ ...current, admission }))}
              />
            </>
          )}
          <div className="code-settings-form-actions">
            <p>计划模型 {draft.model?.model_profile_ref ?? '未配置'}</p>
            {draft.model && (
              <button
                className="ui-button"
                type="button"
                onClick={() => setDraft((current) => ({ ...current, model: null }))}
              >
                移除计划模型
              </button>
            )}
          </div>
          <fieldset className="code-settings-versions">
            <legend>执行限制</legend>
            <div className="testing-profile-limits">
              {limitNames.map((key) => (
                <label key={key}>
                  {fields[key]}
                  <input
                    className="ui-input"
                    inputMode="numeric"
                    value={draft.limits[key] ?? ''}
                    onChange={(event) => {
                      const value = event.currentTarget.value;
                      setDraft((current) => ({
                        ...current,
                        limits: { ...current.limits, [key]: value },
                      }));
                    }}
                  />
                </label>
              ))}
            </div>
          </fieldset>
          <div className="code-settings-form-actions">
            <button
              className="ui-button"
              type="submit"
              disabled={reason !== null}
              title={reason ?? undefined}
            >
              发布测试配置
            </button>
            {reason && <p className="read-status">{reason}</p>}
          </div>
          {writeError && (
            <p className="inline-error" role="alert">
              {writeError}
            </p>
          )}
        </form>
      )}
      <Confirmation
        open={fixed !== null}
        title="发布测试配置版本"
        description={
          fixed === null ? '' : '确认发布固定配置“' + fixed.name + '”。发布后可用于单独批准授权。'
        }
        busy={saving}
        confirmLabel="确认发布"
        confirm={() => void publish()}
        cancel={() => setFixed(null)}
      />
    </details>
  );
}
