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
