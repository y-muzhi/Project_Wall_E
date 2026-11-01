import type { ReactNode } from 'react';

const shapes = {
  robot: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      {[5.75, 10.25].map((cx) => (
        <ellipse key={cx} cx={cx} cy="8" rx=".8" ry="1.15" fill="currentColor" stroke="none" />
      ))}
    </>
  ),
  menu: <path d="M3 4h10M3 8h10M3 12h10" />,
  workbench: (
    <>
      <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" />
      <path d="M2.5 6h11M6 6v7.5" />
    </>
  ),
  outline: (
    <>
      <path d="M6 4h7M6 8h7M6 12h7" />
      {[4, 8, 12].map((cy) => (
        <circle key={cy} cx="3" cy={cy} r=".7" fill="currentColor" stroke="none" />
      ))}
    </>
  ),
  panel: (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
      <path d="M10 2.5v11" />
    </>
  ),
  sidebar: (
    <>
      <rect x="2.5" y="2.5" width="11" height="11" rx="2.5" />
      <path d="M6 5v6" />
    </>
  ),
  close: <path d="m4 4 8 8M12 4l-8 8" />,
  plus: <path d="M8 3v10M3 8h10" />,
  edit: (
    <>
      <path d="m10.5 2.5 3 3-7.75 7.75-3.75.75.75-3.75Z" />
      <path d="m9 4 3 3" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="m10.5 10.5 3 3" />
    </>
  ),
  up: <path d="m4 10 4-4 4 4" />,
  send: <path d="M8 13V3m-4 4 4-4 4 4" />,
  down: <path d="m4 6 4 4 4-4" />,
  left: <path d="m10 4-4 4 4 4" />,
  collapseLeft: <path d="m8 4-4 4 4 4m5-8-4 4 4 4" />,
  right: <path d="m6 4 4 4-4 4" />,
  success: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="m5 8 2 2 4-4" />
    </>
  ),
  error: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="m6 6 4 4m0-4-4 4" />
    </>
  ),
  info: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 7v4m0-7v.5" />
    </>
  ),
  comment: <path d="M3 2.5h10v8H7l-4 3v-11Z" />,
  document: (
    <>
      <path d="M9 1.5H3.5v13h9V5L9 1.5Z" />
      <path d="M9 1.5V5h3.5M5.5 8h5M5.5 10.5H9" />
    </>
  ),
  suggestion: (
    <>
      <path d="M6 12H3.5v-10h9V7M5.5 5h5M5.5 7.5H8" />
      <path d="m8 12 4.5-4.5 2 2L10 14H8v-2Z" />
    </>
  ),
  history: (
    <>
      <path d="M2 6a6 6 0 1 1 .5 5M2 2v4h4" />
      <path d="M8 4.5V8l2.5 1.5" />
    </>
  ),
  versions: (
    <>
      <rect x="5" y="2" width="8.5" height="10.5" rx="1" />
      <path d="M10.5 14.5h-8V4M7.5 5h3.5M7.5 7.5h3.5" />
    </>
  ),
  progress: (
    <>
      <path d="M2.5 2v11.5H14M5 10l3-4 3 2 3-5" />
      <path d="M11 3h3v3" />
    </>
  ),
  warning: (
    <>
      <path d="m8 2 6.5 12h-13L8 2Z" />
      <path d="M8 6v3m0 2v.5" />
    </>
  ),
  locate: (
    <>
      <circle cx="8" cy="8" r="4" />
      <path d="M8 1v3m0 8v3M1 8h3m8 0h3" />
    </>
  ),
  check: <path d="m3.5 8 3 3 6-6" />,
  reopen: (
    <>
      <path d="M3 6.5a5 5 0 1 1 .5 5.5M3 2.5v4h4" />
    </>
  ),
  trash: (
    <>
      <path d="M3 4.5h10M6 2h4m-6 2.5.7 9h6.6l.7-9M6.5 7v4m3-4v4" />
    </>
  ),
  more: (
    <>
      {[3, 8, 13].map((cx) => (
        <circle key={cx} cx={cx} cy="8" r="1" fill="currentColor" stroke="none" />
      ))}
    </>
  ),
  blockActions: (
    <>
      {[3, 8, 13].flatMap((cy) =>
        [5, 11].map((cx) => (
          <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="1" fill="currentColor" stroke="none" />
        )),
      )}
    </>
  ),
  settings: (
    <>
      <path d="M2 4h3m4 0h5M2 8h7m4 0h1M2 12h1m4 0h7" />
      <circle cx="7" cy="4" r="2" />
      <circle cx="11" cy="8" r="2" />
      <circle cx="5" cy="12" r="2" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof shapes;
/** Decorative only: the owning control/message supplies its accessible name. */
export function Icon({ name }: Readonly<{ name: IconName }>) {
  return (
    <svg
      className="ui-icon"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {shapes[name]}
    </svg>
  );
}
export function BusyIndicator({ busy }: Readonly<{ busy: boolean }>) {
  return (
    <span className="busy-slot" aria-hidden="true">
      {busy && <Icon name="more" />}
    </span>
  );
}
