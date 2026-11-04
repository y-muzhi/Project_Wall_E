import { useId, useLayoutEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { Icon } from '../shared/icon.tsx';

/** A fixed icon rail shares its header geometry with every application page. */
export function ApplicationNavigation({
  current,
  navigate,
  headerHost,
  headerHeight,
}: Readonly<{
  current: 'page' | 'location' | undefined;
  navigate(): void;
  headerHost?(element: HTMLDivElement | null): void;
  headerHeight?(height: number): void;
}>) {
  const header = useRef<HTMLDivElement>(null);
  const hintId = useId();
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
  const showHint = () => setHintDismissed(false);
  const dismissHint = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape') setHintDismissed(true);
  };
  const visit = () => {
    setHintDismissed(true);
    navigate();
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
      </nav>
    </>
  );
}
