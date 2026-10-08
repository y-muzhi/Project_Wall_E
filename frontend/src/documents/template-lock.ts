import type { Ctx } from '@milkdown/kit/ctx';
import type { Node } from '@milkdown/kit/prose/model';
import type { Requirement } from '../api/models.ts';
import { requirementCatalog } from '../requirements/catalog.ts';
import newRequirement from '../../../backend/resources/v2/templates/new-requirement.v1.md?raw';
import changeRequirement from '../../../backend/resources/v2/templates/change-requirement.v1.md?raw';
import { EditorSource, blockProjection } from './editor-source.ts';

export type InitializationTemplate = Pick<Requirement, 'requirement_type' | 'template_key' | 'template_version'>;
type LockedHeading = Readonly<{ id: number; level: number; text: string }>;
const installedMarkdown: Readonly<Record<string, string>> = Object.freeze({
  'templates/new-requirement.v1.md': newRequirement,
  'templates/change-requirement.v1.md': changeRequirement,
});
export const templateLockMessage = '初始化期间须保留模板标题的文字、级别、相对顺序和身份，请编辑标题下的正文';

/** Use the frozen template's original allocation, never current heading text
 * or TEMPLATE provenance (a template paragraph may become an extra heading).
 * This is an input guard; server relationship validation remains authoritative. */
export class TemplateHeadingLock {
  private readonly headings: readonly LockedHeading[];
  private readonly identities: ReadonlySet<number>;
  constructor(ctx: Ctx, input: InitializationTemplate) {
    const template = requirementCatalog.templates.find(value => value.template_key === input.template_key && value.template_version === input.template_version && value.requirement_types.includes(input.requirement_type));
    const markdown = template && installedMarkdown[template.markdown_path];
    if (!template || markdown === undefined) throw new TypeError('初始化模板资源不可用');
    const headings = new EditorSource(ctx, markdown).blocks.flatMap((block, index) => block.block_type === 'heading'
      ? [{ id: index + 1, level: block.heading_level!, text: block.plain_text }] : []);
    if (headings.length !== template.locked_headings.length || headings.some((heading, index) => heading.level !== template.locked_headings[index]!.level || heading.text !== template.locked_headings[index]!.text)) throw new TypeError('初始化模板与标题契约不一致');
    this.headings = Object.freeze(headings.map(heading => Object.freeze(heading)));
    this.identities = new Set(headings.map(heading => heading.id));
  }
  assertDocument(document: Node): void {
    const actual: LockedHeading[] = [];
    document.forEach(node => {
      const identity: unknown = node.attrs.walle_block_id;
      if (typeof identity !== 'number' || !this.identities.has(identity)) return;
      if (node.type.name !== 'heading') throw new TypeError(templateLockMessage);
      actual.push({ id: identity, level: Number(node.attrs.level), text: blockProjection(node) });
    });
    if (actual.length !== this.headings.length || actual.some((heading, index) => {
      const expected = this.headings[index]!;
      return heading.id !== expected.id || heading.level !== expected.level || heading.text !== expected.text;
    })) throw new TypeError(templateLockMessage);
  }
}
