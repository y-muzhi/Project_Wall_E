import { positiveInteger } from '../api/client.ts';
export type ReadingIdentity = Readonly<{
  requirement_id: number;
  document_id: number;
  kind: 'CURRENT' | 'REVISION';
  version: number;
}>;
export function readingKey(identity: ReadingIdentity): string {
  if (identity.kind !== 'CURRENT' && identity.kind !== 'REVISION')
    throw TypeError('Invalid reading kind');
  return [
    positiveInteger(identity.requirement_id),
    positiveInteger(identity.document_id),
    identity.kind,
    positiveInteger(identity.version),
  ].join(':');
}
/** Page-owned scroll positions cannot supply document identity to a write. */
export class ReadingPositions {
  private readonly positions = new Map<string, number>();
  private active: string | null = null;
  private readonly port: Pick<HTMLElement, 'scrollTop'>;
  constructor(port: Pick<HTMLElement, 'scrollTop'>) {
    this.port = port;
  }
  capture(): void {
    if (this.active !== null) this.positions.set(this.active, Math.max(0, this.port.scrollTop));
  }
  select(identity: ReadingIdentity): void {
    const key = readingKey(identity);
    if (key === this.active) return;
    this.active = key;
    this.port.scrollTop = this.positions.get(key) ?? 0;
  }
}
