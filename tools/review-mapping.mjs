import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { inspectSource, coverage } from './spec-audit.mjs';

const root = resolve(import.meta.dirname, '..');
const path = resolve(root, 'docs/需求实现映射.md');
const sources = JSON.parse(readFileSync(resolve(root, 'docs/sources/manifest.json'), 'utf8')).map(inspectSource);
const ledger = JSON.parse(readFileSync(resolve(root, 'docs/sources/reading-ledger.json'), 'utf8'));
for (const source of sources) if (!coverage(source.lineCount, ledger[source.key]).complete) throw new Error('Complete source reading is required');
let mapping = readFileSync(path, 'utf8');
mapping = mapping.replace('这是持续维护台账。自动建立的稳定锚点行只是遗漏检查底稿：标为“待完整正文复核”的行不表示全文已读或行为已梳理。所有业务单元当前未开始；来源读取状态在 reading-ledger.json 单独记录。每次实现前重新阅读对应完整正文、公共规则及失败分支。实现时应将较大来源行继续拆为独立可核验单元。', '两份原文已逐段全文阅读。稳定锚点行用于定位和检查遗漏，行为列是管理摘要，不能代替完整正文；每次实现前重新读取全部条件/失败分支。较大条目继续沿自然边界拆分；公共原语的验证与接口/事务/页面验证分别登记。第8章373项编号场景见 [验收场景映射](验收场景映射.md)，均未执行；无编号的组件和质量要求仍按本表对应条目拆分。');
mapping = mapping.split('\n').map(row => {
  if (!row.startsWith('| frontend ') && !row.startsWith('| backend ')) return row;
  if (!row.includes('待完整正文复核')) return row;
  const cells = row.split('|').slice(1, -1).map(cell => cell.trim());
  const match = cells[0].match(/^(frontend|backend) L(\d+) #([^ ]+)/);
  if (!match) throw new Error(`Unrecognized row ${cells[0]}`);
  const source = sources.find(item => item.key === match[1]);
  const start = Number(match[2]) - 1;
  const lines = source.lines.slice(start, Math.min(source.lines.length, start + 240));
  // Use the source's actual behavior/condition rows for APP entries, not invented semantics.
  const processStart = lines.findIndex(line => line.startsWith('#### 4.3'));
  const processEnd = lines.findIndex((line, index) => index > processStart && line.startsWith('#### 4.4'));
  let behavior;
  if (match[3].startsWith('app-') && processStart >= 0 && processEnd > processStart) {
    behavior = lines.slice(processStart, processEnd).filter(line => /^\|(?:P\d|S\d)/.test(line)).map(line => line.split('|').slice(1, -1).map(cell => cell.trim()).filter((_, index) => index !== 2).join(' → ')).join('；');
  }
  if (!behavior) {
    behavior = lines.slice(1).filter(line => line.trim() && !/^<a |^\|[- ]+\|/.test(line)).slice(0, 8).join('；').replace(/<a[^>]*><\/a>/g, '');
  }
  cells[1] = behavior.replaceAll('|', '／');
  cells[3] = '未执行；第8章对应场景见验收场景映射；完整边界仍以本条原文为准';
  cells[5] = '全文已读；本条尚未实现，具体未决项按决策稿闭合';
  return `| ${cells.join(' | ')} |`;
}).join('\n');
mapping = mapping.replace('CREATE正文及后端创建能力尚未读；Q-01资源待稿', 'CREATE/创建能力已读；Q-01正式资源待稿确认').replace('完整卡片提交能力尚未读；Q-CARD-STATE待稿', '卡片提交能力已读；Q-CARD-STATE待稿确认');
writeFileSync(path, mapping);
console.log('Reviewed source outline updated; existing implementation/evidence rows preserved.');
