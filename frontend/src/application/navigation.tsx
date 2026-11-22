import { useId, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Icon } from '../shared/icon.tsx';

/** A fixed icon rail shares its header geometry with every application page. */
export function ApplicationNavigation({
  current,
  navigate,
  headerHost,
  headerHeight,
  coding,
  codingCurrent,
  settings,
  settingsCurrent,
  testing,
  testingCurrent,
  codingReason,
  testingReason,
  settingsReason,
}: Readonly<{
  current: 'page' | 'location' | undefined;
  navigate(): void;
  coding(): void;
  codingCurrent: 'page' | 'location' | undefined;
  settings(): void;
  settingsCurrent: 'page' | undefined;
  testing(): void;
  testingCurrent: 'page' | undefined;
  codingReason?: string;
  testingReason?: string;
  settingsReason?: string;
  headerHost?(element: HTMLDivElement | null): void;
  headerHeight?(height: number): void;
}>) {
  const header = useRef<HTMLDivElement>(null);
  const hintId = useId();
  const codingHintId = useId();
  const settingsHintId = useId();
  const testingHintId = useId();
  const [hintDismissed, setHintDismissed] = useState(false);
  const [settingsHintDismissed, setSettingsHintDismissed] = useState(false);
  useLayoutEffect(() => {
    const element = header.current;
    if (!element || !headerHeight) return;
    const measure = () => headerHeight(Math.ceil(element.getBoundingClientRect().height));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [headerHeight]);
  const showHint = () => setHintDismissed(false);
  const dismissHint = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') {
      setHintDismissed(true);
      setSettingsHintDismissed(true);
    }
  };
  const visit = () => {
    setHintDismissed(true);
    navigate();
  };
  const showSettingsHint = () => setSettingsHintDismissed(false);
  const visitSettings = () => {
    setSettingsHintDismissed(true);
    settings();
  };
  return (
    <>
      <div className="application-header" role="banner" ref={header}>
        <div className="application-brand-zone">
          <span className="application-brand-mark" role="img" aria-label="WALL-E">
            W
          </span>
        </div>
        <div className="application-page-header" ref={headerHost} />
      </div>
      <nav className="application-navigation" aria-label="主导航">
        <div
          className="application-navigation-entry"
          onMouseEnter={showHint}
          onMouseLeave={showHint}
        >
          <button
            type="button"
            className="ui-button application-navigation-item"
            aria-label="需求工作台"
            aria-describedby={hintId}
            aria-current={current}
            onClick={visit}
            onFocus={showHint}
            onKeyDown={dismissHint}
          >
            <Icon name="workbench" />
          </button>
          <span
            id={hintId}
            role="tooltip"
            className="application-navigation-tooltip"
            hidden={hintDismissed}
          >
            需求工作台
          </span>
        </div>
        <div className="application-navigation-entry">
          <button
            type="button"
            className="ui-button application-navigation-item"
            aria-label="代码开发"
            aria-describedby={codingHintId}
            aria-current={codingCurrent}
            disabled={!!codingReason}
            title={codingReason}
            onClick={coding}
          >
            <Icon name="code" />
          </button>
          <span id={codingHintId} role="tooltip" className="application-navigation-tooltip">
            {codingReason ?? '代码开发'}
          </span>
        </div>
        <div className="application-navigation-entry">
          <button
            type="button"
            className="ui-button application-navigation-item"
            aria-label="测试验收"
            aria-describedby={testingHintId}
            aria-current={testingCurrent}
            disabled={!!testingReason}
            title={testingReason}
            onClick={testing}
          >
            <Icon name="outline" />
          </button>
          <span id={testingHintId} role="tooltip" className="application-navigation-tooltip">
            {testingReason ?? '测试验收'}
          </span>
        </div>
        <div
          className="application-navigation-entry"
          onMouseEnter={showSettingsHint}
          onMouseLeave={showSettingsHint}
        >
          <button
            type="button"
            className="ui-button application-navigation-item"
            aria-label="设置"
            aria-describedby={settingsHintId}
            onFocus={showSettingsHint}
            onKeyDown={dismissHint}
            aria-current={settingsCurrent}
            disabled={!!settingsReason}
            title={settingsReason}
            onClick={visitSettings}
          >
            <Icon name="settings" />
          </button>
          <span
            className="application-navigation-tooltip"
            role="tooltip"
            id={settingsHintId}
            hidden={settingsHintDismissed}
          >
            {settingsReason ?? '设置'}
          </span>
        </div>
      </nav>
    </>
  );
}
