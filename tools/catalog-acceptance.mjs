import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { coverage, inspectSource } from './spec-audit.mjs';

const root = resolve(import.meta.dirname, '..');
const manifest = JSON.parse(readFileSync(resolve(root, 'docs/sources/manifest.json'), 'utf8'));
const ledger = JSON.parse(readFileSync(resolve(root, 'docs/sources/reading-ledger.json'), 'utf8'));
const path = resolve(root, 'docs/验收场景映射.md');
const prior = new Map();
try {
  for (const row of readFileSync(path, 'utf8').split('\n').filter(line => line.startsWith('| frontend ') || line.startsWith('| backend '))) {
    const cells = row.split('|').slice(1, -1).map(cell => cell.trim());
    prior.set(cells[0], cells);
  }
} catch (error) { if (error.code !== 'ENOENT') throw error; }
const output = ['# 验收场景映射', '', '来源第8章的编号场景逐项登记；完整前置、故障注入及过程仍须读取原文。登记不代表已实现或已运行。既有状态/证据保留；禁止通过重新生成清除失败记录。无编号场景在需求映射中的组件/质量/技术保证单元另行拆分。', '', '| 设计来源与条目 | 需要实现的行为及边界（原文预期） | 实现位置 | 验证依据与证据 | 状态 | 阻塞或差异 |', '| --- | --- | --- | --- | --- | --- |'];
const cell = text => text.replaceAll('|', '／').replaceAll('\n', ' ');
const seen = new Set();
const counts = {};
for (const metadata of manifest) {
  const source = inspectSource(metadata);
  if (!coverage(source.lineCount, ledger[source.key]).complete) throw new Error('Full reading must be complete before cataloging acceptance');
  counts[source.key] = 0;
  source.lines.forEach((line, index) => {
    if (!line.startsWith('|')) return;
    const cells = line.split('|').slice(1, -1).map(value => value.replace(/<a[^>]*><\/a>/g, '').trim());
    const id = cells[0]?.match(/^(TC-[^\s]+)/)?.[1];
    if (!id) return;
    const key = `${source.key} L${index + 1} ${id}`;
    if (seen.has(key)) throw new Error(`Duplicate acceptance row: ${key}`);
    seen.add(key);
    // Six-column scene tables use column 5 for expected result; shorter FE tables
    // keep the complete non-identity cells to avoid guessing a column meaning.
    const behavior = cells.length === 6 ? cells[4] : cells.slice(1).join('；');
    const existing = prior.get(key);
    output.push(`| ${key} | ${cell(behavior)} | ${existing?.[2] ?? '—'} | ${existing?.[3] ?? '未执行；前置/过程/验证方式见该来源行'} | ${existing?.[4] ?? '未开始'} | ${existing?.[5] ?? '资源/算法及环境就绪后按原文执行，不降为不适用'} |`);
    counts[source.key]++;
  });
}
for (const key of prior.keys()) if (!seen.has(key)) throw new Error(`Existing evidence no longer has a matching source: ${key}`);
writeFileSync(path, output.join('\n') + '\n');
console.log(JSON.stringify({ counts, total: seen.size, path }));
