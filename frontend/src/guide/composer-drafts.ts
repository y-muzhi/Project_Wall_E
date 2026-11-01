import { exact, positiveInteger } from '../api/client.ts';
type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
/** Only unsubmitted text. No operation, scope, API key or command receipt is restored. */
export class ComposerDrafts {
  private readonly storage: () => StoragePort;
  private readonly documentId: number | null;
  constructor(storage: () => StoragePort = () => sessionStorage, documentId: number | null = null) {
    this.documentId = documentId;
    this.storage = storage;
  }
  private key(requirement: number): string {
    return `walle:v1.5:document-composer:${positiveInteger(requirement)}:${positiveInteger(this.documentId)}`;
  }
  load(requirement: number): Readonly<{ instruction: string; warning: string | null }> {
    if (this.documentId === null) return { instruction: '', warning: null };
    try {
      const raw = this.storage().getItem(this.key(requirement));
      if (raw === null) return { instruction: '', warning: null };
      const row = exact(JSON.parse(raw), [
        'schema_version',
        'requirement_id',
        'document_id',
        'instruction',
      ]);
      if (
        row.schema_version !== 1 ||
        row.requirement_id !== requirement ||
        row.document_id !== this.documentId ||
        typeof row.instruction !== 'string' ||
        [...row.instruction].length > 10000
      )
        throw TypeError('Invalid composer draft');
      return { instruction: row.instruction, warning: null };
    } catch {
      return { instruction: '', warning: '本地消息草稿无法读取，请保持页面并保留需要的文字。' };
    }
  }
  save(requirement: number, instruction: string): string | null {
    try {
      if ([...instruction].length > 10000) throw TypeError('Oversized draft');
      this.storage().setItem(
        this.key(requirement),
        JSON.stringify({
          schema_version: 1,
          requirement_id: requirement,
          document_id: this.documentId,
          instruction,
        }),
      );
      return null;
    } catch {
      return '消息暂存失败，输入仍保留在当前页面。';
    }
  }
  clear(requirement: number): string | null {
    try {
      this.storage().removeItem(this.key(requirement));
      return null;
    } catch {
      return '消息已接受，本地草稿清理失败。';
    }
  }
}
