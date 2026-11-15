import { useState } from 'react';

export function CopyButton({ content }: Readonly<{ content: string }>) {
  const [result, setResult] = useState('');
  return (
    <span className="model-copy">
      <button
        className="ui-button"
        type="button"
        onClick={() => {
          void Promise.resolve()
            .then(() => navigator.clipboard.writeText(content))
            .then(
              () => setResult('已复制'),
              () => setResult('复制失败，请选中文字复制'),
            );
        }}
      >
        复制
      </button>
      <span role="status">{result}</span>
    </span>
  );
}
