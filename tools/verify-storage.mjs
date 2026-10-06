import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const python = resolve(root, '.venv/Scripts/python.exe');
function inputHashes() {
  const files = readdirSync(resolve(root, 'backend'), { recursive: true, withFileTypes: true })
    .filter(entry => entry.isFile() && /\.(py|sql|json|md|lock)$/.test(entry.name))
    .map(entry => resolve(entry.parentPath, entry.name));
  files.push(resolve(root, 'tools/verify-storage.mjs'));
  return Object.fromEntries(files.sort().map(path => [path.slice(root.length + 1).replaceAll('\\', '/'),
    createHash('sha256').update(readFileSync(path)).digest('hex')]));
}
const runtimeCheck = process.argv.includes('--guide-runtime');
if (process.argv.slice(2).some(value => value !== '--guide-runtime')) throw new Error('Unknown verification option');
const before = inputHashes();
const commands = [
  ['node', ['tools/spec-audit.mjs', 'check']],
  [python, ['-m', 'pip', 'check']],
  [python, runtimeCheck ? ['-m', 'unittest', 'backend.tests.guide.test_orchestrator', 'backend.tests.guide.test_trusted_output', 'backend.tests.guide.test_result_persistence', 'backend.tests.infrastructure.test_audit_repository', 'backend.tests.infrastructure.test_model_gateway', '-v'] : ['-m', 'unittest', 'discover', '-s', 'backend/tests', '-t', '.', '-v']],
];
const results = commands.map(([command, args]) => {
  const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  return { command, args, exitCode: result.status, error: result.error?.message ?? null, stdout: result.stdout, stderr: result.stderr };
});
const after = inputHashes();
const changedInputs = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(path => before[path] !== after[path]);
const diagnosticErrors = results.filter(result => (result.stderr ?? '').includes('Traceback (most recent call last):')).map(result => result.command);
const passed = changedInputs.length === 0 && diagnosticErrors.length === 0 && results.every(result => result.exitCode === 0 && result.error === null);
const record = { batch: runtimeCheck ? 'Actual private ORCH S01-S06 plus native audit/proof/C07 and loopback gateway regression; only named modules, offline expanded-budget compatibility fixtures, no production tokenizer/Provider/effects, worker/service/pages or whole acceptance' : 'P1/P2 foundations, implemented P3 document units and P4 queries/lifecycle/baseline/revisions/draft start-save-complete-cancel, D-009 identity proofs, all-comment C06, durable initial-run acceptance, OS-lock-bound C09 recovery, Guide status/history/create/continue/retry/comment acceptance, logical cancellation and failure bookkeeping, P5 comments and suggestion batch complete reads/decision/application/discard, message cursor reads, derived card state and whole-card submission acceptance, C03 model-context snapshot reads and exact frozen input assembly/conservative budget rejection (expanded-budget compiler fixtures are diagnostic only, not production compatibility), D-007 frozen model profile, private audit sanitization and actual SQLite request preparation/transport/parse/failure/retention stages, actual loopback HTTP gateway single-attempt/error/usage/cancellation tests plus real prepared-audit integration; approved D-010 immutable dual resource versions, exact user/formal fact and card proof gates, sealed actual audit validation receipts and C07 atomic business submission including a controlled real TCP-to-C07 roundtrip (expanded budgets and response fixtures are explicit diagnostics, no Volcengine/paid request or tokenizer/effect proof), private actual ORCH bounded logical attempts, per-task native SQL retirement fences, OS-lock-bound worker startup and prior-claim recovery, deduplicated dispatch before HTTP projection, serial30s no-progress monitoring/30-day audit retention and actual10s shutdown drain/late-C07 fence recovery, thirty-seven actual HTTP adapters, and production API main/lifespan admission with native HTTP SQL retirement, actual subprocess/TCP initialization/lock refusal/graceful restart and controlled forced process death recovery; D-011 standalone reachable-schema/text-count adapters and frozen exact-count compiler candidate with fixed budgets/whole-item trimming (no production enablement), scope is the actual test names, not real Provider effects, product pages or whole business acceptance', recordedAt: new Date().toISOString(), node: process.version, cwd: root, inputs: { before, after, changedInputs }, results };
record.diagnosticErrors = diagnosticErrors;
record.passed = passed;
record.countedRuntimeScope = 'D-011 private actual counted ORCH/worker, native prepared/outcome file audit and 30-day raw retention, same exact texts into local Chat TCP and full signed output validation/C07; explicit offline compatibility injections only, production default stays closed pending real framing proof.';
mkdirSync(resolve(root, 'docs/verification'), { recursive: true });
const stamp = record.recordedAt.replaceAll(':', '-').replaceAll('.', '-');
const path = resolve(root, `docs/verification/P2-${stamp}.json`);
writeFileSync(path, JSON.stringify(record, null, 2) + '\n');
console.log(JSON.stringify({ passed, evidence: path, scope: record.batch }));
if (!passed) process.exitCode = 1;
