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
const development = ['--conditions=development', '--test', 'tests/autolinks.test.mjs'];
const developmentResult = spawnSync(process.execPath, development, {cwd: resolve(root, 'frontend'), encoding: 'utf8'});
results.push({args: development, exitCode: developmentResult.status, error: developmentResult.error?.message ?? null,
  stdout: developmentResult.stdout, stderr: developmentResult.stderr});
const recordedAt = new Date().toISOString();
const path = resolve(root, 'docs/verification', `frontend-${recordedAt.replaceAll(':', '-').replaceAll('.', '-')}.json`);
const passed = results.every(result => result.exitCode === 0 && result.error === null);
mkdirSync(dirname(path), { recursive: true });
writeFileSync(path, JSON.stringify({ scope: 'Installed dependencies, TypeScript, projection offsets, identity transactions and actual remark autolinks (default/development conditions); no browser/business acceptance', recordedAt, node: process.version, passed, results }, null, 2) + '\n');
console.log(JSON.stringify({ passed, evidence: path }));
if (!passed) process.exitCode = 1;
