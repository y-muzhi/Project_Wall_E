import { useId, useState } from 'react';
import { snapshotObject } from '../../api/client.ts';
import { testPlanAssertion, testPlanStep } from '../../api/testing-plans.ts';
import type { TestPlanAssertion, TestPlanStep } from '../../api/testing-plans.ts';
import { EmptyState } from '../../shared/empty-state.tsx';
import { remove, replace } from './draft.ts';
import type { Case, Driver } from './draft.ts';

type Kind = 'step' | 'assertion';
type Value = TestPlanStep | TestPlanAssertion;
const stepOps = {
  CLI: ['RUN'],
  HTTP: ['REQUEST'],
  BROWSER: ['NAVIGATE', 'CLICK', 'FILL', 'SELECT', 'PRESS'],
} as const;
const assertionOps = {
  CLI: ['EXIT_CODE', 'STDOUT_BYTES'],
  HTTP: ['STATUS', 'HEADER', 'JSON_POINTER', 'BODY_BYTES'],
  BROWSER: ['VISIBLE', 'TEXT', 'COUNT'],
} as const;
const labels: Readonly<Record<string, string>> = {
  RUN: '运行登记命令',
  REQUEST: '发送 HTTP 请求',
  NAVIGATE: '打开受管路径',
  CLICK: '点击',
  FILL: '填入文本',
  SELECT: '选择值',
  PRESS: '按键',
  EXIT_CODE: '退出码',
  STDOUT_BYTES: '标准输出字节',
  STATUS: 'HTTP 状态',
  HEADER: '响应头',
  JSON_POINTER: 'JSON 字段',
  BODY_BYTES: '响应体字节',
  VISIBLE: '可见性',
  TEXT: '界面文本',
  COUNT: '匹配数量',
};
const requestHeaders = [
  'accept',
  'content-type',
  'content-language',
  'if-match',
  'if-none-match',
] as const;
const responseHeaders = [...requestHeaders, 'cache-control', 'etag', 'vary', 'content-encoding'];
const httpMethods = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'] as const;
const browserKeys = [
  'Enter',
  'Escape',
  'Tab',
  'Space',
  'ArrowUp',
  'ArrowDown',
  'ArrowLeft',
  'ArrowRight',
] as const;
const browserRoles = [
  'alert',
  'button',
  'cell',
  'checkbox',
  'combobox',
  'dialog',
  'form',
  'heading',
  'img',
  'link',
  'list',
  'listbox',
  'listitem',
  'main',
  'menu',
  'menuitem',
  'navigation',
  'option',
  'progressbar',
  'radio',
  'region',
  'row',
  'searchbox',
  'slider',
  'spinbutton',
  'status',
  'switch',
  'tab',
  'table',
  'tabpanel',
  'textbox',
  'tree',
  'treeitem',
] as const;

function identity(item: Value) {
  return 'assertion_id' in item ? item.assertion_id : item.step_id;
}
function fail(message: string): never {
  throw new TypeError(message);
}
function reference(value: string, field: string) {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$/.test(value)) fail(field + '须为有效的登记标识');
  return value;
}
function literal(value: string, field: string, maximum = 4096, allowEmpty = true) {
  if (
    [...value].length > maximum ||
    (!allowEmpty && !value.trim()) ||
    /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value)
  )
    fail(field + '的长度或字符不符合用例协议');
  return value;
}
function bytes(value: string, field: string) {
  if (
    value.length > 1398104 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)
  )
    fail(field + '须为标准 Base64 字节');
  const decoded = atob(value);
  if (decoded.length > 1024 * 1024 || btoa(decoded) !== value)
    fail(field + '须为规范且有界的 Base64 字节');
  return value;
}
function path(value: string) {
  if (
    !/^\/(?!\/)[/A-Za-z0-9._~!$&()*+,;=:@?%\-]*$/.test(value) ||
    value.length > 2048 ||
    /%(?![A-Fa-f0-9]{2})/.test(value)
  )
    fail('请输入原受管端点内的相对路径');
  if (/%(?:0[0-9a-f]|1[0-9a-f]|7f)/i.test(value)) fail('路径不能包含编码控制字符');
  for (const part of value.split('?')[0]!.split('/')) {
    const decoded = part.replace(/%([a-fA-F0-9]{2})/g, (_match, code: string) =>
      String.fromCharCode(Number.parseInt(code, 16)),
    );
    if (decoded === '.' || decoded === '..' || /[/\\%?#]/.test(decoded))
      fail('路径不能越过所选端点');
  }
  return value;
}
function integer(value: string, minimum: number, maximum: number) {
  const parsed = Number(value);
  if (
    !/^(0|[1-9][0-9]*)$/.test(value) ||
    !Number.isSafeInteger(parsed) ||
    parsed < minimum ||
    parsed > maximum
  )
    fail('预期整数范围为 ' + minimum + ' 到 ' + maximum);
  return parsed;
}
function headerValue(value: string) {
  if (value.length > 1024 || /[^ -~]/.test(value)) fail('HTTP 头值须为 1024 字符内可见 ASCII');
  return value;
}

function initial(prior: Value | null, driver: Driver, kind: Kind) {
  const values: Record<string, string> = {
    method: 'GET',
    header: 'content-type',
    locator_kind: 'TEST_ID',
    role: 'button',
    key: 'Enter',
    visible: 'true',
  };
  if (prior === null) return values;
  for (const [field, value] of Object.entries(prior)) {
    if (typeof value === 'string') values[field] = value;
  }
  if ('locator' in prior) {
    values.locator_kind = prior.locator.kind;
    values.target = prior.locator.value;
    if ('name' in prior.locator) {
      values.role = prior.locator.value;
      values.role_name = prior.locator.name ?? '';
    }
  }
  if (prior.op === 'PRESS') values.key = prior.value;
  if (prior.op === 'REQUEST') {
    for (const [header, value] of Object.entries(prior.headers)) {
      if (typeof value === 'string') values['header:' + header] = value;
    }
  }
  if ('expected' in prior && kind === 'assertion') {
    if (prior.op === 'JSON_POINTER') values.expected = JSON.stringify(prior.expected);
    else if (prior.op === 'VISIBLE') values.visible = prior.expected === true ? 'true' : 'false';
    else values.expected = String(prior.expected);
  }
  if (driver === 'HTTP' && 'step_id' in prior) values.step_id = prior.step_id;
  return values;
}

type OperationProps = Readonly<{
  driver: Driver;
  kind: Kind;
  prior: Value | null;
  steps: readonly TestPlanStep[];
  commands: readonly { id: string; label: string }[];
  disabled: boolean;
  save(value: Value): void;
  cancel(): void;
}>;
function OperationEditor({
  driver,
  kind,
  prior,
  steps,
  commands,
  disabled,
  save,
  cancel,
}: OperationProps) {
  const options = kind === 'step' ? stepOps[driver] : assertionOps[driver];
  const [op, setOp] = useState<string>(prior?.op ?? options[0]!);
  const [fields, setFields] = useState(() => initial(prior, driver, kind));
  const [error, setError] = useState<string | null>(null);
  const commandList = useId();
  const field = (name: string) => fields[name] ?? '';
  function update(name: string, value: string) {
    setFields((current) => ({ ...current, [name]: value }));
    setError(null);
  }
  const locatorOp = driver === 'BROWSER' && op !== 'NAVIGATE';
  const endpointOp = op === 'NAVIGATE' || op === 'REQUEST';
  const needsExpected = kind === 'assertion' && op !== 'VISIBLE';
  const httpAssertion = kind === 'assertion' && driver === 'HTTP';

  function locator() {
    return field('locator_kind') === 'ROLE'
      ? {
          kind: 'ROLE',
          value: field('role'),
          name:
            field('role_name') === ''
              ? null
              : literal(field('role_name'), '可访问名称', 256, false),
        }
      : { kind: 'TEST_ID', value: reference(field('target'), '测试标识') };
  }
  function expected() {
    const value = field('expected');
    switch (op) {
      case 'VISIBLE':
        return field('visible') === 'true';
      case 'EXIT_CODE':
        return integer(value, 0, 4294967295);
      case 'STATUS':
        return integer(value, 100, 599);
      case 'COUNT':
        return integer(value, 0, 100000);
      case 'STDOUT_BYTES':
      case 'BODY_BYTES':
        return bytes(value, '预期字节');
      case 'JSON_POINTER': {
        let parsed: unknown;
        try {
          parsed = JSON.parse(value);
        } catch {
          return fail('请输入一个有效的 JSON 字面值');
        }
        return snapshotObject({ value: parsed }).value;
      }
      case 'HEADER':
        return headerValue(value);
      default:
        return literal(value, '预期文本');
    }
  }
  function commit() {
    if (disabled) return;
    try {
      const operation: Record<string, unknown> = { op };
      operation[kind === 'step' ? 'step_id' : 'assertion_id'] =
        prior === null ? kind + '-' + crypto.randomUUID() : identity(prior);
      if (locatorOp) operation.locator = locator();
      if (endpointOp) {
        operation.endpoint_ref = reference(field('endpoint_ref'), '受管端点');
        operation.path = path(field('path'));
      }
      if (op === 'RUN') {
        operation.command_id = reference(field('command_id'), '命令');
        operation.stdin = bytes(field('stdin'), '标准输入');
      }
      if (op === 'REQUEST') {
        operation.method = field('method');
        operation.body = bytes(field('body'), '请求体');
        operation.headers = Object.fromEntries(
          requestHeaders
            .filter((header) => Object.hasOwn(fields, 'header:' + header))
            .map((header) => [header, headerValue(field('header:' + header))]),
        );
      }
      if (op === 'FILL' || op === 'SELECT')
        operation.value = literal(field('value'), '输入值', 4096, op === 'FILL');
      if (op === 'PRESS') operation.value = field('key');
      if (kind === 'assertion') operation.expected = expected();
      if (httpAssertion) {
        if (!steps.some((step) => step.step_id === field('step_id')))
          fail('请选择本用例的 HTTP 请求步骤');
        operation.step_id = field('step_id');
      }
      if (op === 'HEADER') operation.header = field('header');
      if (op === 'JSON_POINTER') {
        const pointer = literal(field('pointer'), 'JSON Pointer', 1024);
        if (
          pointer &&
          (!pointer.startsWith('/') || /~(?![01])/.test(pointer) || pointer.split('/').length > 33)
        )
          fail('请输入受支持的 JSON Pointer');
        operation.pointer = pointer;
      }
      save(kind === 'step' ? testPlanStep(operation) : testPlanAssertion(operation));
    } catch (problem) {
      setError(
        problem instanceof Error && problem.message !== 'API projection is inconsistent'
          ? problem.message
          : '请核对用例操作字段',
      );
    }
  }
  const textInput = (name: string, label: string, multiline = false) => (
    <label>
      {label}
      {multiline ? (
        <textarea
          value={field(name)}
          rows={3}
          onChange={(event) => update(name, event.currentTarget.value)}
        />
      ) : (
        <input
          type="text"
          value={field(name)}
          onChange={(event) => update(name, event.currentTarget.value)}
        />
      )}
    </label>
  );
  const select = (name: string, label: string, values: readonly string[]) => (
    <label>
      {label}
      <select value={field(name)} onChange={(event) => update(name, event.currentTarget.value)}>
        {values.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <fieldset className="testing-editor-panel" disabled={disabled}>
      <legend>
        {prior === null ? '新增' : '编辑'}
        {kind === 'step' ? '步骤' : '断言'}
      </legend>
      <label>
        操作类型{' '}
        <select
          value={op}
          onChange={(event) => {
            setOp(event.currentTarget.value);
            setError(null);
          }}
        >
          {options.map((value) => (
            <option key={value} value={value}>
              {labels[value]}
            </option>
          ))}
        </select>
      </label>
      {op === 'RUN' && (
        <>
          <label>
            登记命令标识{' '}
            <input
              type="text"
              list={commandList}
              value={field('command_id')}
              onChange={(event) => update('command_id', event.currentTarget.value)}
            />
          </label>
          <datalist id={commandList}>
            {commands.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </datalist>
          {textInput('stdin', '标准输入（Base64，留空为空字节）', true)}
        </>
      )}
      {endpointOp && (
        <>
          {textInput('endpoint_ref', '受管端点标识')}
          {textInput('path', '受管相对路径')}
        </>
      )}
      {op === 'REQUEST' && (
        <>
          {select('method', '请求方法', httpMethods)}
          {textInput('body', '请求体（Base64，留空为空字节）', true)}
          <fieldset>
            <legend>请求头</legend>
            {requestHeaders.map((header) => {
              const name = 'header:' + header;
              return (
                <div key={header}>
                  <label>
                    <input
                      type="checkbox"
                      checked={Object.hasOwn(fields, name)}
                      onChange={(event) => {
                        const enabled = event.currentTarget.checked;
                        setFields((current) => {
                          const next = { ...current };
                          if (enabled) next[name] = '';
                          else delete next[name];
                          return next;
                        });
                      }}
                    />{' '}
                    {header}
                  </label>
                  {Object.hasOwn(fields, name) && textInput(name, header + ' 值')}
                </div>
              );
            })}
          </fieldset>
        </>
      )}
      {locatorOp && (
        <>
          {select('locator_kind', '定位方式', ['TEST_ID', 'ROLE'])}
          {field('locator_kind') === 'ROLE' ? (
            <>
              {select('role', '可访问角色', browserRoles)}
              {textInput('role_name', '可访问名称（可空）')}
            </>
          ) : (
            textInput('target', '测试标识')
          )}
        </>
      )}
      {(op === 'FILL' || op === 'SELECT') && textInput('value', '输入值', true)}
      {op === 'PRESS' && select('key', '键', browserKeys)}
      {httpAssertion && (
        <label>
          对应请求步骤{' '}
          <select
            value={field('step_id')}
            onChange={(event) => update('step_id', event.currentTarget.value)}
          >
            <option value="">请选择请求步骤</option>
            {steps.map((step, index) => (
              <option key={step.step_id} value={step.step_id}>
                步骤 {index + 1}
              </option>
            ))}
          </select>
        </label>
      )}
      {op === 'HEADER' && select('header', '响应头', responseHeaders)}
      {op === 'JSON_POINTER' && textInput('pointer', 'JSON Pointer（留空表示根）')}
      {op === 'VISIBLE' && select('visible', '预期可见性', ['true', 'false'])}
      {needsExpected &&
        textInput(
          'expected',
          op === 'JSON_POINTER'
            ? '预期 JSON 字面值'
            : op === 'STDOUT_BYTES' || op === 'BODY_BYTES'
              ? '预期字节（Base64）'
              : '预期值',
          op !== 'STATUS' && op !== 'EXIT_CODE' && op !== 'COUNT' && op !== 'HEADER',
        )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <div className="code-settings-form-actions">
        <button className="ui-button" type="button" onClick={commit}>
          确认{kind === 'step' ? '步骤' : '断言'}
        </button>
        <button className="ui-button" type="button" onClick={cancel}>
          取消编辑
        </button>
      </div>
    </fieldset>
  );
}

export function CaseOperations({
  item,
  kind,
  commands,
  disabled,
  change,
}: Readonly<{
  item: Case;
  kind: Kind;
  commands: OperationProps['commands'];
  disabled: boolean;
  change(value: Case): void;
}>) {
  const [editing, setEditing] = useState<number | 'new' | null>(null);
  const values: readonly Value[] = kind === 'step' ? item.steps : item.assertions;
  const label = kind === 'step' ? '步骤' : '断言';
  function save(value: Value) {
    const index = editing;
    if (index === null) return;
    if (!('assertion_id' in value) && kind === 'step') {
      const steps = index === 'new' ? [...item.steps, value] : replace(item.steps, index, value);
      change({ ...item, steps });
    }
    if ('assertion_id' in value && kind === 'assertion') {
      const assertions =
        index === 'new' ? [...item.assertions, value] : replace(item.assertions, index, value);
      change({ ...item, assertions });
    }
    setEditing(null);
  }
  function removeOperation(index: number) {
    if (kind === 'step') {
      const step = item.steps[index];
      if (!step) return;
      change({
        ...item,
        steps: remove(item.steps, index),
        assertions: item.assertions.filter(
          (assertion) => !('step_id' in assertion) || assertion.step_id !== step.step_id,
        ),
      });
    } else change({ ...item, assertions: remove(item.assertions, index) });
    setEditing(null);
  }

  return (
    <section className="testing-editor-panel" aria-label={'用例' + label}>
      <h5>{label}</h5>
      {values.length === 0 && <EmptyState icon="outline" message={'此用例尚无' + label} compact />}
      <ol className="code-settings-version-items">
        {values.map((value, index) => (
          <li key={identity(value)}>
            <div className="code-settings-form-actions">
              <span>{labels[value.op]}</span>
              <button
                type="button"
                className="ui-button"
                disabled={disabled || editing !== null}
                onClick={() => setEditing(index)}
              >
                编辑{label} {index + 1}
              </button>
              <button
                type="button"
                className="ui-button"
                disabled={disabled || editing !== null}
                onClick={() => removeOperation(index)}
              >
                移除{label} {index + 1}
              </button>
            </div>
          </li>
        ))}
      </ol>
      {editing === null ? (
        <button
          type="button"
          className="ui-button"
          disabled={disabled || values.length >= 256}
          title={values.length >= 256 ? '已达操作数量上限' : undefined}
          onClick={() => setEditing('new')}
        >
          添加{label}
        </button>
      ) : (
        <OperationEditor
          key={editing}
          driver={item.driver_kind}
          kind={kind}
          prior={editing === 'new' ? null : (values[editing] ?? null)}
          steps={item.steps}
          commands={commands}
          disabled={disabled}
          save={save}
          cancel={() => setEditing(null)}
        />
      )}
    </section>
  );
}
