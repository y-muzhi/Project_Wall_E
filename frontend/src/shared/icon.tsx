import type {ReactNode} from 'react';

const shapes = {
  robot: <><circle cx="8" cy="8" r="6.25"/>{[5.75,10.25].map(cx=><ellipse key={cx} cx={cx} cy="8" rx=".8" ry="1.15" fill="currentColor" stroke="none"/>)}</>,
  menu: <path d="M3 4h10M3 8h10M3 12h10"/>,
  workbench: <><rect x="2.5" y="2.5" width="11" height="11" rx="1.5"/><path d="M2.5 6h11M6 6v7.5"/></>,
  outline: <><path d="M6 4h7M6 8h7M6 12h7"/>{[4,8,12].map(cy=><circle key={cy} cx="3" cy={cy} r=".7" fill="currentColor" stroke="none"/>)}</>,
  panel: <><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M10 2.5v11"/></>,
  close: <path d="m4 4 8 8M12 4l-8 8"/>,
  search: <><circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3"/></>,
  up: <path d="m4 10 4-4 4 4"/>,
  send: <path d="M8 13V3m-4 4 4-4 4 4"/>,
  down: <path d="m4 6 4 4 4-4"/>,
  left: <path d="m10 4-4 4 4 4"/>,
  collapseLeft: <path d="m8 4-4 4 4 4m5-8-4 4 4 4"/>,
  right: <path d="m6 4 4 4-4 4"/>,
  success: <><circle cx="8" cy="8" r="6"/><path d="m5 8 2 2 4-4"/></>,
  error: <><circle cx="8" cy="8" r="6"/><path d="m6 6 4 4m0-4-4 4"/></>,
  info: <><circle cx="8" cy="8" r="6"/><path d="M8 7v4m0-7v.5"/></>,
  warning: <><path d="m8 2 6.5 12h-13L8 2Z"/><path d="M8 6v3m0 2v.5"/></>,
  more: <>{[3, 8, 13].map(cx=><circle key={cx} cx={cx} cy="8" r="1" fill="currentColor" stroke="none"/>)}</>,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof shapes;
/** Decorative only: the owning control/message supplies its accessible name. */
export function Icon({name}: Readonly<{name: IconName}>) {
  return <svg className="ui-icon" width="16" height="16" viewBox="0 0 16 16" fill="none"
    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{shapes[name]}</svg>;
}
export function BusyIndicator({busy}: Readonly<{busy: boolean}>) {
  return <span className="busy-slot" aria-hidden="true">{busy&&<Icon name="more"/>}</span>;
}
