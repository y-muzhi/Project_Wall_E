import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const python = resolve(root, '.venv/Scripts/python.exe');
const commands = [
  ['node', ['tools/spec-audit.mjs', 'check']],
  [python, ['-m', 'pip', 'check']],
  [python, ['-m', 'unittest', 'discover', '-s', 'backend/tests', '-t', '.', '-v']],
];
const results = commands.map(([command, args]) => {
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  return { command, args, exitCode: result.status, error: result.error?.message ?? null, stdout: result.stdout, stderr: result.stderr };
});
const record = { batch: 'P1/P2 foundations, implemented P3 document units and P4 requirement/document/revision queries and requirement attribute command; scope is the actual test names, not whole business acceptance', recordedAt: new Date().toISOString(), node: process.version, cwd: root, results };
mkdirSync(resolve(root, 'docs/verification'), { recursive: true });
const stamp = record.recordedAt.replaceAll(':', '-').replaceAll('.', '-');
const path = resolve(root, `docs/verification/P2-${stamp}.json`);
writeFileSync(path, JSON.stringify(record, null, 2) + '\n');
const passed = results.every(result => result.exitCode === 0 && result.error === null);
console.log(JSON.stringify({ passed, evidence: path, scope: record.batch }));
if (!passed) process.exitCode = 1;
