import { Icon } from './icon.tsx';
import type { IconName } from './icon.tsx';

export type EmptyStateContent = Readonly<{ icon: IconName; message: string }>;

/** A content placeholder. Loading, errors and actions belong to the caller. */
export function EmptyState({
  icon,
  message,
  compact = false,
  fill = false,
}: EmptyStateContent & Readonly<{ compact?: boolean; fill?: boolean }>) {
  return (
    <div className={`empty-state${compact ? ' is-compact' : ''}${fill ? ' fills-region' : ''}`}>
      <Icon name={icon} />
      <p>{message}</p>
    </div>
  );
}
