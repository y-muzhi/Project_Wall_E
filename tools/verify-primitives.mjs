import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const commands = [
  ['node', ['tools/spec-audit.mjs', 'check']],
  ['python', ['-c', 'import sys, sqlite3; print(sys.version); print("SQLite", sqlite3.sqlite_version)']],
  ['python', ['-m', 'unittest', 'backend.tests.shared.test_validation', 'backend.tests.shared.test_http_errors', '-v']],
];
const results = commands.map(([command, args]) => {
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  return { command, args, exitCode: result.status, error: result.error?.message ?? null, stdout: result.stdout, stderr: result.stderr };
});
const record = { batch: 'P1 shared primitives only', recordedAt: new Date().toISOString(), node: process.version, cwd: root, results };
mkdirSync(resolve(root, 'docs/verification'), { recursive: true });
const stamp = record.recordedAt.replaceAll(':', '-').replaceAll('.', '-');
const path = resolve(root, `docs/verification/P1-${stamp}.json`);
writeFileSync(path, JSON.stringify(record, null, 2) + '\n');
const passed = results.every(result => result.exitCode === 0 && result.error === null);
console.log(JSON.stringify({ passed, evidence: path, scope: record.batch }));
if (!passed) process.exitCode = 1;
