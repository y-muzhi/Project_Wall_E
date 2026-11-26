import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MessageContent } from '../messages/content.tsx';
import type { MessageMarkdownRenderer } from '../messages/content.tsx';
import { EmptyState } from '../shared/empty-state.tsx';
import { registerModal, trapModalTab } from '../shared/modal.ts';
import type { OperationDetail } from './saved-operation.ts';

export function OperationDetailDialog({
  title,
  read,
  close,
  renderMarkdown,
}: Readonly<{
  title: string;
  read: (signal: AbortSignal) => Promise<OperationDetail>;
  close: () => void;
  renderMarkdown?: MessageMarkdownRenderer;
}>) {
  const [result, setResult] = useState<OperationDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, retry] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const heading = useId();
  useLayoutEffect(() => {
    const element = dialog.current!;
    const opener = document.activeElement;
    element.showModal();
    const release = registerModal(element);
    return () => {
      element.close();
      release();
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void read(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setResult(value);
      },
      () => {
        if (!controller.signal.aborted) setFailed(true);
      },
    );
    return () => controller.abort();
  }, [attempt, read]);
  const render = renderMarkdown ? { render: renderMarkdown } : {};
  return createPortal(
    <dialog
      ref={dialog}
      aria-labelledby={heading}
      className="guide-operation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
      onKeyDown={trapModalTab}
    >
      <header>
        <h2 id={heading}>{title}</h2>
        <button className="ui-button" type="button" onClick={close}>
          关闭
        </button>
      </header>
      <div className="guide-operation-dialog-body" tabIndex={0} role="region" aria-label={title}>
        {!result && !failed && <p role="status">正在读取…</p>}
        {failed && (
          <p role="alert" className="inline-error">
            暂时无法读取本次记录。
            <button
              className="ui-button"
              type="button"
              onClick={() => {
                setFailed(false);
                retry((n) => n + 1);
              }}
            >
              重试
            </button>
          </p>
        )}
        {result?.kind === 'VERSION' &&
          (result.saved.markdown_content.trim() ? (
            <MessageContent content={result.saved.markdown_content} {...render} />
          ) : (
            <EmptyState icon="document" message="此版本暂无内容" />
          ))}
        {result?.kind === 'COMPARE' &&
          (result.changes.length === 0 ? (
            <EmptyState icon="document" message="这两个版本的正文区块内容相同" />
          ) : (
            <div className="guide-saved-changes">
              {result.changes.map((change, index) => (
                <section key={index} aria-label={change.section.join(' / ') || '正文变更'}>
                  {change.section.length > 0 && <h3>{change.section.join(' / ')}</h3>}
                  {change.removed && (
                    <div className="document-revision-deleted-block">
                      <span className="guide-saved-change-label">
                        V{result.base.source_content_version} · 删除
                      </span>
                      <MessageContent content={change.removed} {...render} />
                    </div>
                  )}
                  {change.added && (
                    <div className="document-revision-added-block">
                      <span className="guide-saved-change-label">
                        V{result.saved.source_content_version} · 新增
                      </span>
                      <MessageContent content={change.added} {...render} />
                    </div>
                  )}
                </section>
              ))}
            </div>
          ))}
      </div>
    </dialog>,
    document.body,
  );
}
