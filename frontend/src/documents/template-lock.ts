import type { Ctx } from '@milkdown/kit/ctx';
import type { Node } from '@milkdown/kit/prose/model';
import type { DocumentView } from '../api/models.ts';
import { documentStructureRefs } from '../requirements/catalog.ts';
import specificationTemplate from '../../../backend/resources/v7/templates/new-requirement.v4.md?raw';
import { EditorSource, blockProjection } from './editor-source.ts';

export type DocumentStructureBinding = Pick<
  DocumentView,
  'document_kind' | 'template_ref' | 'markdown_content' | 'block_state_json'
>;
type LockedHeading = Readonly<{ id: number; level: number; text: string }>;
export const templateLockMessage =
  '须保留规格文档固定标题的文字、级别、顺序和身份，请编辑标题下的正文';

/** Frozen rules belong to this actual document. Only existing fixed headings
 * are locked, so omitted conditional sections are never manufactured. */
export class TemplateHeadingLock {
  private readonly headings: readonly LockedHeading[];
  private readonly identities: ReadonlySet<number>;
  constructor(ctx: Ctx, input: DocumentStructureBinding) {
    const reference = documentStructureRefs.SPECIFICATION;
    if (
      input.document_kind !== 'SPECIFICATION' ||
      input.template_ref === null ||
      !reference ||
      input.template_ref.key !== reference.key ||
      input.template_ref.version !== reference.version ||
      input.template_ref.digest !== reference.digest
    )
      throw TypeError('真实规格文档结构资源不可用');
    const approved = new Set(
      new EditorSource(ctx, specificationTemplate).blocks
        .filter((block) => block.block_type === 'heading')
        .map((block) => JSON.stringify([block.heading_level, block.plain_text])),
    );
    const source = new EditorSource(ctx, input.markdown_content);
    this.headings = Object.freeze(
      source.blocks.flatMap((block, index) =>
        block.block_type === 'heading' &&
        approved.has(JSON.stringify([block.heading_level, block.plain_text]))
          ? [
              Object.freeze({
                id: input.block_state_json.blocks[index]!.block_id,
                level: block.heading_level!,
                text: block.plain_text,
              }),
            ]
          : [],
      ),
    );
    this.identities = new Set(this.headings.map((heading) => heading.id));
  }
  assertDocument(document: Node): void {
    const actual: LockedHeading[] = [];
    document.forEach((node) => {
      const identity: unknown = node.attrs.walle_block_id;
      if (typeof identity !== 'number' || !this.identities.has(identity)) return;
      if (node.type.name !== 'heading') throw TypeError(templateLockMessage);
      actual.push({ id: identity, level: Number(node.attrs.level), text: blockProjection(node) });
    });
    if (
      actual.length !== this.headings.length ||
      actual.some((heading, index) => {
        const expected = this.headings[index]!;
        return (
          heading.id !== expected.id ||
          heading.level !== expected.level ||
          heading.text !== expected.text
        );
      })
    )
      throw TypeError(templateLockMessage);
  }
}
