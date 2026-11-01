import type { ReactNode } from 'react';
import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import type { RequirementHeaderCommands } from './header-commands.ts';
import type { LifecycleOutcome } from './lifecycle.ts';
import type { DetailSnapshot } from './detail-read.ts';
import { RequirementLifecycleControl } from './lifecycle-control.tsx';
import { ManualStartControl } from '../documents/manual-controls.tsx';
import { Icon } from '../shared/icon.tsx';
import { activeModal } from '../shared/modal.ts';
import type { ConfirmedNotice } from '../shared/toast-store.ts';

/** Real header fields and available command owners. Other business regions
 * remain the detail parent's responsibility; no fake action handlers. */
export function RequirementHeader(
  props: Readonly<{
    tools?: ReactNode;
    documentActions?: ReactNode;
    commands: RequirementHeaderCommands;
    ready: boolean;
    blocked: boolean;
    history: boolean;
    refresh(): Promise<DetailSnapshot>;
    refreshRevisions(): Promise<void>;
    notifyConfirmed?: ConfirmedNotice;
  }>,
) {
  const state = useSyncExternalStore(props.commands.subscribe, props.commands.getSnapshot),
    [reading, setReading] = useState(false),
    [readError, setReadError] = useState<string | null>(null),
    pending = useRef<Promise<DetailSnapshot> | null>(null);
  const external = props.blocked || props.history;
  const refresh = (): Promise<DetailSnapshot> => {
    if (pending.current) return pending.current;
    setReading(true);
    setReadError(null);
    const promise = Promise.resolve()
      .then(() => props.refresh())
      .then((actual) => {
        props.commands.adopt(actual);
        return actual;
      })
      .catch((error) => {
        setReadError('实际详情读取失败，现有内容和输入已保留');
        throw error;
      })
      .finally(() => {
        if (pending.current === promise) pending.current = null;
        setReading(false);
      });
    pending.current = promise;
    return promise;
  };
  const life = state.lifecycle,
    manual = state.manual;
  const ready = props.ready && !reading;
  const [toolsOpen, setToolsOpen] = useState(false),
    toolsId = useId(),
    toolsHost = useRef<HTMLDivElement>(null),
    toolsToggle = useRef<HTMLButtonElement>(null);
  const expanded = toolsOpen;
  useEffect(() => {
    if (!toolsOpen) return;
    const outside = (event: Event) => {
      if (
        !activeModal() &&
        event.target instanceof Node &&
        !toolsHost.current?.contains(event.target)
      )
        setToolsOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', outside);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', outside);
    };
  }, [toolsOpen]);
  const closeTools = () => {
    setToolsOpen(false);
    toolsToggle.current?.focus({ preventScroll: true });
  };
  const requirementStatusChanged = async (outcome: LifecycleOutcome) => {
    props.notifyConfirmed?.(outcome, '需求状态已保存');
    await refresh();
    closeTools();
  };
  const manualEditingStarted = async () => {
    await refresh();
    closeTools();
  };
  return (
    <section className="requirement-header" aria-label="需求属性和操作">
      <div className="requirement-operations">
        {props.documentActions}
        <div
          className="requirement-tools"
          ref={toolsHost}
          onKeyDown={(event) => {
            if (event.key === 'Escape' && !event.defaultPrevented && !activeModal() && expanded) {
              event.preventDefault();
              event.stopPropagation();
              closeTools();
            }
          }}
        >
          <button
            ref={toolsToggle}
            className="ui-button icon-button"
            type="button"
            aria-label="更多操作"
            title="更多操作"
            aria-expanded={expanded}
            aria-controls={toolsId}
            onClick={() => setToolsOpen((value) => !value)}
          >
            <Icon name="more" />
          </button>
          <div
            id={toolsId}
            className="requirement-tools-popover"
            role="region"
            aria-label="详情工具"
            hidden={!expanded}
            inert={!expanded}
            aria-hidden={!expanded}
          >
            <p className="requirement-tools-caption">详情工具</p>
            <div className="requirement-menu-actions" role="group" aria-label="需求操作">
              {life && (
                <RequirementLifecycleControl
                  key={'lifecycle-' + state.lifecycle_generation}
                  caption="修改需求状态"
                  flow={life}
                  blocked={props.blocked || props.commands.blockedFor('LIFECYCLE')}
                  writeReady={ready}
                  changed={requirementStatusChanged}
                />
              )}
              {manual && (!props.history || manual.getSnapshot().phase !== 'READY') && (
                <ManualStartControl
                  key={'manual-' + state.manual_generation}
                  flow={manual}
                  disabled={external || props.commands.blockedFor('MANUAL')}
                  writeReady={ready}
                  started={manualEditingStarted}
                />
              )}
            </div>
            {props.tools && (
              <div
                className="requirement-tool-actions"
                onClick={(event) => {
                  if (event.target instanceof Element && event.target.closest('button'))
                    closeTools();
                }}
              >
                {props.tools}
              </div>
            )}
          </div>
        </div>
      </div>
      {(life?.getSnapshot().phase === 'ERROR' ||
        manual?.getSnapshot().phase === 'ERROR' ||
        readError) && (
        <button
          className="ui-button"
          type="button"
          disabled={external || reading}
          onClick={() => void refresh().catch(() => undefined)}
        >
          重新读取操作状态
        </button>
      )}
      {reading && <p role="status">正在读取实际详情…</p>}
      {readError && (
        <p role="alert" className="inline-error">
          {readError}
        </p>
      )}
    </section>
  );
}
