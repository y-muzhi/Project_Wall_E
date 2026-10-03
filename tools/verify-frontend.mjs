import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const npmCli = resolve(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
const commands = [['ls', '--depth=0'], ['run', 'typecheck'], ['test']];
const results = commands.map(args => {
  const result = spawnSync(process.execPath, [npmCli, ...args], { cwd: resolve(root, 'frontend'), encoding: 'utf8' });
  return { args, exitCode: result.status, error: result.error?.message ?? null, stdout: result.stdout, stderr: result.stderr };
});
const recordedAt = new Date().toISOString();
const path = resolve(root, 'docs/verification', `frontend-${recordedAt.replaceAll(':', '-').replaceAll('.', '-')}.json`);
const passed = results.every(result => result.exitCode === 0 && result.error === null);
mkdirSync(dirname(path), { recursive: true });
writeFileSync(path, JSON.stringify({ scope: 'Installed dependency versions, TypeScript and projected-text offset helpers only; no editor/browser/business acceptance', recordedAt, node: process.version, passed, results }, null, 2) + '\n');
console.log(JSON.stringify({ passed, evidence: path }));
if (!passed) process.exitCode = 1;
