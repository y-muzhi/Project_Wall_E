import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Icon } from '../shared/icon.tsx';
import type { IconName } from '../shared/icon.tsx';

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
}: Readonly<{
  current: 'page' | 'location' | undefined;
  navigate(): void;
  coding(): void;
  codingCurrent: 'page' | 'location' | undefined;
  settings(): void;
  settingsCurrent: 'page' | undefined;
  testing(): void;
  testingCurrent: 'page' | undefined;
  headerHost?(element: HTMLDivElement | null): void;
  headerHeight?(height: number): void;
}>) {
  const header = useRef<HTMLDivElement>(null);
  const [hintDismissed, setHintDismissed] = useState(false);
  useLayoutEffect(() => {
    const element = header.current;
    if (!element || !headerHeight) return;
    const measure = () => headerHeight(Math.ceil(element.getBoundingClientRect().height));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [headerHeight]);
  useEffect(() => {
    const dismissHint = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setHintDismissed(true);
    };
    document.addEventListener('keydown', dismissHint, true);
    return () => document.removeEventListener('keydown', dismissHint, true);
  }, []);
  const showHint = () => setHintDismissed(false);
  const destinations: readonly {
    label: string;
    icon: IconName;
    active: 'page' | 'location' | undefined;
    visit(): void;
  }[] = [
    { label: '需求工作台', icon: 'workbench', active: current, visit: navigate },
    { label: '代码开发', icon: 'code', active: codingCurrent, visit: coding },
    { label: '测试验收', icon: 'outline', active: testingCurrent, visit: testing },
    { label: '设置', icon: 'settings', active: settingsCurrent, visit: settings },
  ];
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
        {destinations.map(({ label, icon, active, visit }) => (
          <div className="application-navigation-entry" key={label} onMouseEnter={showHint}>
            <button
              type="button"
              className="ui-button application-navigation-item"
              aria-label={label}
              aria-current={active}
              onFocus={showHint}
              onClick={() => {
                setHintDismissed(true);
                visit();
              }}
            >
              <Icon name={icon} />
            </button>
            <span
              className="application-navigation-tooltip"
              hidden={hintDismissed}
              aria-hidden="true"
            >
              {label}
            </span>
          </div>
        ))}
      </nav>
    </>
  );
}
