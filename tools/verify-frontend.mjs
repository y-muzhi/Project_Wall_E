import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readdirSync, readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const npmCli = resolve(dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
function inputHashes() {
  const files = [];
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (['node_modules', 'dist', '__pycache__'].includes(entry.name)) continue;
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (/\.(ts|tsx|mjs|json|css|html)$/.test(entry.name)) files.push(path);
    }
  }
  for (const directory of ['frontend', 'shared']) walk(resolve(root, directory));
  for (const module of ['requirements', 'documents', 'revisions', 'comments', 'suggestions', 'guide', 'messages']) files.push(resolve(root, `backend/app/${module}/api.py`));
  files.push(resolve(root, 'backend/resources/v2/schemas/ASK_OUTPUT.v1.json'), resolve(root, 'backend/resources/v2/templates/catalog.v1.json'),
    resolve(root, 'backend/app/shared/validation.py'), resolve(root, 'tools/verify-frontend.mjs'));
  return Object.fromEntries(files.sort().map(path => [path.slice(root.length + 1).replaceAll('\\', '/'), createHash('sha256').update(readFileSync(path)).digest('hex')]));
}
const before = inputHashes();
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
const after = inputHashes();
const changedInputs = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(path => before[path] !== after[path]);
const passed = changedInputs.length === 0 && results.every(result => result.exitCode === 0 && result.error === null);
mkdirSync(dirname(path), { recursive: true });
writeFileSync(path, JSON.stringify({ scope: 'Installed dependencies, TypeScript, projection offsets, identity transactions, actual remark autolinks (default/development), immutable API actions and 37 explicit bindings/complete public read-model/frozen schema/response ownership/pagination/error-detail diagnostics; Node response fixtures, no browser/business/Provider or whole acceptance', recordedAt, node: process.version, passed, inputs: { before, after, changedInputs }, results }, null, 2) + '\n');
console.log(JSON.stringify({ passed, evidence: path }));
if (!passed) process.exitCode = 1;
