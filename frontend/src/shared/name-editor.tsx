import { useId, useLayoutEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Icon } from './icon.tsx';

/** Presentation only. The command owner retains drafts, permissions and recovery. */
export function NameEditor({
  label,
  value,
  draft,
  editing,
  heading: Heading = 'strong',
  canRename = true,
  disabled = false,
  inputDisabled = disabled,
  readOnly = false,
  saveDisabled = inputDisabled || readOnly,
  cancelDisabled = false,
  feedback,
  begin,
  change,
  save,
  cancel,
}: Readonly<{
  label: string;
  value: string;
  draft: string;
  editing: boolean;
  heading?: 'h1' | 'strong';
  canRename?: boolean;
  disabled?: boolean;
  inputDisabled?: boolean;
  readOnly?: boolean;
  saveDisabled?: boolean;
  cancelDisabled?: boolean;
  feedback?: ReactNode;
  begin(): void;
  change(value: string): void;
  save(): void;
  cancel(): void;
}>) {
  const inputId = useId(),
    input = useRef<HTMLInputElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    heading = useRef<HTMLHeadingElement>(null),
    composing = useRef(false),
    previousEditing = useRef(false),
    restoreFocus = useRef(false);

  useLayoutEffect(() => {
    if (editing && !previousEditing.current) {
      composing.current = false;
      input.current?.focus({ preventScroll: true });
      input.current?.select();
    }
    if (!editing && previousEditing.current) restoreFocus.current = true;
    previousEditing.current = editing;
    if (!editing && restoreFocus.current && !disabled) {
      restoreFocus.current = false;
      (canRename ? trigger.current : heading.current)?.focus({ preventScroll: true });
    }
  }, [editing, disabled, canRename]);

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!composing.current && !saveDisabled) save();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLFormElement>) {
    if (event.nativeEvent.isComposing || composing.current || event.keyCode === 229) {
      if (event.key === 'Enter') event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && !cancelDisabled) {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
  }

  return (
    <div className="name-editor" role="group" aria-label={label} data-editing={editing}>
      <div className="name-editor-display" aria-hidden={editing} inert={editing}>
        <Heading ref={heading} className="name-editor-value" tabIndex={-1} title={value}>
          {value}
        </Heading>
        {canRename && (
          <button
            ref={trigger}
            className="ui-button icon-button name-editor-trigger"
            type="button"
            aria-label={`修改${label}`}
            title={`修改${label}`}
            disabled={disabled}
            onClick={begin}
          >
            <Icon name="edit" />
          </button>
        )}
      </div>
      {(editing || feedback) && (
        <div className="name-editor-layer">
          {editing && (
            <form
              className="name-editor-form"
              aria-label={`修改${label}`}
              onSubmit={submit}
              onKeyDown={handleKeyDown}
              onCompositionStart={() => {
                composing.current = true;
              }}
              onCompositionEnd={() => {
                composing.current = false;
              }}
            >
              <label className="sr-only" htmlFor={inputId}>
                {label}
              </label>
              <input
                ref={input}
                id={inputId}
                className="ui-input"
                value={draft}
                autoComplete="off"
                disabled={inputDisabled}
                readOnly={readOnly}
                onChange={(event) => change(event.currentTarget.value)}
              />
              <div className="name-editor-actions">
                <button className="ui-button primary" type="submit" disabled={saveDisabled}>
                  保存
                </button>
                <button
                  className="ui-button"
                  type="button"
                  disabled={cancelDisabled}
                  onClick={cancel}
                >
                  取消
                </button>
              </div>
            </form>
          )}
          {feedback && <div className="name-editor-feedback">{feedback}</div>}
        </div>
      )}
    </div>
  );
}
