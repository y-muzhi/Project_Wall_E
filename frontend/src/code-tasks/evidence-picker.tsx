import { useState } from 'react';
import { evidenceKinds } from '../api/code-task-question-response.ts';
import type { QuestionEvidenceRef } from '../api/code-task-question-response.ts';

const evidenceNames = {
  VERIFICATION_ITEM: '检查项',
  QUESTION: '原生问题',
  OPERATION: '原操作',
  COMMAND: '命令',
  LLM_USE: '模型调用',
};

export function evidenceLabel(item: QuestionEvidenceRef) {
  return evidenceNames[item.kind] + ' #' + item.id;
}

export function EvidencePicker({
  value,
  changed,
}: Readonly<{
  value: readonly QuestionEvidenceRef[];
  changed(value: QuestionEvidenceRef[]): void;
}>) {
  const [kind, setKind] = useState<QuestionEvidenceRef['kind']>('OPERATION');
  const [rawId, setRawId] = useState('');
  const id = Number(rawId);
  const eligible =
    /^[1-9][0-9]*$/.test(rawId) &&
    Number.isSafeInteger(id) &&
    !value.some((item) => item.kind === kind && item.id === id);
  return (
    <div>
      <div className="code-task-toolbar">
        <label>
          证据类型{' '}
          <select
            value={kind}
            onChange={(event) => {
              const next = evidenceKinds.find((item) => item === event.target.value);
              if (next) setKind(next);
            }}
          >
            {evidenceKinds.map((item) => (
              <option key={item} value={item}>
                {evidenceNames[item]}
              </option>
            ))}
          </select>
        </label>
        <label>
          已保存证据编号{' '}
          <input
            inputMode="numeric"
            value={rawId}
            onChange={(event) => setRawId(event.target.value)}
          />
        </label>
        <button
          type="button"
          className="ui-button"
          disabled={!eligible}
          onClick={() => {
            changed([...value, { kind, id }]);
            setRawId('');
          }}
        >
          添加同任务证据
        </button>
      </div>
      {value.length > 0 && (
        <ul>
          {value.map((item, index) => (
            <li key={item.kind + ':' + item.id}>
              {evidenceNames[item.kind]} #{item.id}{' '}
              <button
                type="button"
                className="ui-button"
                onClick={() => changed(value.filter((_, i) => i !== index))}
              >
                移除证据
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
