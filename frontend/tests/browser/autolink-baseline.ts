import type { Crepe } from '@milkdown/crepe';
import fixtures from '../../../shared/fixtures/autolink-v1.json';
import { EditorSource } from '../../src/documents/editor-source.ts';

// Observation only: never turns an implementation's differences into goldens.
export async function autolinkBaseline(load: (markdown: string) => Promise<unknown>, get: () => Crepe) {
  const records = [];
  for (const entry of fixtures.cases) {
    await load(entry.markdown);
    const actual = get().editor.action(ctx => {
      const parsed = new EditorSource(ctx, entry.markdown);
      if (parsed.blocks.length !== 1) throw new Error(`边界样例没有完整一个区块: ${entry.name}`);
      const links: {text: string; href: string}[] = [];
      parsed.document.descendants(node => {
        const link = node.marks.find(mark => mark.type.name === 'link');
        if (link && node.isText) links.push({text: node.text!, href: String(link.attrs.href)});
      });
      return {plain_text: parsed.blocks[0]!.plain_text, links};
    });
    const expected = {plain_text: entry.plain_text, links: entry.links};
    records.push({name: entry.name, markdown: entry.markdown, expected, actual,
      conforms: JSON.stringify(actual) === JSON.stringify(expected)});
  }
  return {scope: 'Observed installed Crepe baseline, not a conformance pass', records,
    mismatches: records.filter(record => !record.conforms).map(record => record.name)};
}
