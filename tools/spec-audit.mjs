import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const manifestPath = resolve(root, 'docs/sources/manifest.json');
const ledgerPath = resolve(root, 'docs/sources/reading-ledger.json');
const definitions = [
  { key: 'frontend', path: 'C:/Users/羊牧之/Desktop/WALL-E.V1_0.6.前端设计文档.md', expectedVersion: '1.1-draft', expectedHash: '91ECFFF98EDB1ABBDF6D5076B810F72EDE2AB7A8B8FDBA066884117AE4BD37CA' },
  { key: 'backend', path: 'C:/Users/羊牧之/Desktop/WALL-E.V1_0.6.后端设计文档.md', expectedVersion: '1.0-draft', expectedHash: 'EB9D40453576587AED754A53E939842233E48C64FAC14A4D64F56E908F186D9F' },
];

export function inspectSource(definition) {
  const bytes = readFileSync(definition.path);
  const hash = createHash('sha256').update(bytes).digest('hex').toUpperCase();
  if (hash !== definition.expectedHash) throw new Error(`${definition.key}: source hash changed; review the change before updating the manifest`);
  const text = bytes.toString('utf8');
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  if (lines.at(-1) === '') lines.pop();
  const version = text.match(/\|规格版本\|([^|]+)\|/)?.[1];
  if (version !== definition.expectedVersion) throw new Error(`${definition.key}: unexpected specification version ${version}`);
  if (definition.key === 'frontend') {
    for (const name of ['FE-UI-PRINCIPLES', 'FE-UI-COLOR', 'FE-UI-TYPOGRAPHY', 'FE-UI-LAYOUT']) {
      if (!text.includes(`**${name} `)) throw new Error(`missing visual principle: ${name}`);
    }
  }
  const headings = [];
  const anchors = [];
  lines.forEach((line, index) => {
    if (/^#{1,4} /.test(line)) headings.push({ line: index + 1, title: line });
    for (const match of line.matchAll(/<a id="([^"]+)"><\/a>/g)) {
      anchors.push({ id: match[1], line: index + 1, text: line.replace(/<a[^>]*><\/a>/g, '').trim() || lines[index + 1]?.trim() || lines[index + 2]?.trim() || '' });
    }
  });
  const ids = anchors.map(item => item.id);
  if (new Set(ids).size !== ids.length) throw new Error(`${definition.key}: duplicate stable anchors`);
  return { ...definition, hash, version, bytes: bytes.length, lineCount: lines.length, headings, anchors, lines };
}

export function coverage(lineCount, ranges) {
  const seen = new Set();
  for (const { start, end } of ranges) {
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start || end > lineCount) throw new Error('invalid reading range');
    for (let line = start; line <= end; line++) seen.add(line);
  }
  const missing = [];
  for (let line = 1; line <= lineCount; line++) {
    if (!seen.has(line)) {
      const start = line;
      while (line < lineCount && !seen.has(line + 1)) line++;
      missing.push({ start, end: line });
    }
  }
  return { readLines: seen.size, totalLines: lineCount, complete: seen.size === lineCount, missing };
}

function main() {
  const [command = 'check', sourceKey, startArg, endArg] = process.argv.slice(2);
  const sources = definitions.map(inspectSource);
  const ledger = existsSync(ledgerPath) ? JSON.parse(readFileSync(ledgerPath, 'utf8')) : { frontend: [], backend: [] };
  if (command === 'index') {
    mkdirSync(resolve(root, 'docs/sources'), { recursive: true });
    writeFileSync(manifestPath, JSON.stringify(sources.map(({ lines, ...metadata }) => metadata), null, 2) + '\n');
    const out = ['# 设计来源索引', '', '自动定位索引，不代替正文，不表示已经阅读或实现。输入 SHA-256 见 manifest.json。', ''];
    for (const source of sources) {
      out.push(`## ${source.key} (${source.version})`, '', `来源：${source.path}`, '', '| 行 | 标题 |', '| --- | --- |');
      source.headings.forEach(h => out.push(`| ${h.line} | ${h.title.replace(/\|/g, '／')} |`));
      out.push('', '| 行 | 稳定锚点 |', '| --- | --- |');
      source.anchors.forEach(a => out.push(`| ${a.line} | ${a.id} |`));
      out.push('');
    }
    writeFileSync(resolve(root, 'docs/设计来源索引.md'), out.join('\n') + '\n');
    console.log(JSON.stringify(sources.map(({ key, version, lineCount, hash, headings, anchors }) => ({ key, version, lineCount, hash, headings: headings.length, anchors: anchors.length })), null, 2));
    return;
  }
  if (command === 'read' || command === 'confirm-read') {
    const source = sources.find(s => s.key === sourceKey);
    if (!source) throw new Error('source must be frontend or backend');
    const start = Number(startArg), end = Number(endArg);
    coverage(source.lineCount, [{ start, end }]);
    const excerpt = source.lines.slice(start - 1, end).join('\n');
    // Bound output conservatively. Confirm only in a later invocation after checking tool output.
    if (excerpt.length > 18000) throw new Error('range exceeds 18000 characters; split it to prevent tool truncation');
    if (command === 'read') {
      console.log(`SOURCE ${sourceKey} ${source.version} SHA256=${source.hash} LINES=${start}-${end}\n${excerpt}\nEND ${sourceKey} ${start}-${end}`);
    } else {
      if (!existsSync(manifestPath)) throw new Error('create index before recording reading');
      ledger[sourceKey].push({ start, end, sha256: source.hash, confirmedAt: new Date().toISOString(), evidence: 'Complete range displayed and inspected; no truncation warning; explicit later confirmation' });
      writeFileSync(ledgerPath, JSON.stringify(ledger, null, 2) + '\n');
      console.log(JSON.stringify({ source: sourceKey, ...coverage(source.lineCount, ledger[sourceKey]) }));
    }
    return;
  }
  if (command !== 'check') throw new Error(`unknown command ${command}`);
  for (const source of sources) {
    for (const range of ledger[source.key]) if (range.sha256 !== source.hash) throw new Error(`${source.key}: reading evidence belongs to different input`);
    console.log(JSON.stringify({ source: source.key, version: source.version, hash: source.hash, ...coverage(source.lineCount, ledger[source.key]) }));
  }
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(import.meta.filename)) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
