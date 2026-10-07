"""Verify committed blobs retain the exact approved/adopted byte identities."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def blob(path):
    return subprocess.run(['git', 'show', 'HEAD:' + path], cwd=ROOT, check=True, capture_output=True).stdout


def digest(content):
    return hashlib.sha256(content).hexdigest()


adoption = json.loads((ROOT / 'docs/resource-adoption-v1.json').read_text(encoding='utf-8'))
approval = json.loads((ROOT / 'docs/verification/proposals-v1.json').read_text(encoding='utf-8'))
expected = {'backend/resources/v1/' + entry['path']: entry['sha256'] for entry in adoption['files']}
expected[adoption['migration']['path']] = adoption['migration']['sha256']
expected.update({'docs/proposals/' + path: sha for path, sha in approval['content_hashes'].items()})
manual = json.loads((ROOT / 'docs/manual-edit-source-adoption-v1.json').read_text(encoding='utf-8'))
expected.update({entry['path']: entry['sha256'] for entry in manual['approved']})
expected[manual['migration']['path']] = manual['migration']['sha256']
expected['docs/manual-edit-source-adoption-v1.json'] = digest((ROOT / 'docs/manual-edit-source-adoption-v1.json').read_bytes())
identity = json.loads((ROOT / 'docs/manual-identity-adoption-v1.json').read_text(encoding='utf-8'))
expected.update({entry['path']: entry['sha256'] for entry in identity['approved']})
expected[identity['migration']['path']] = identity['migration']['sha256']
expected['docs/manual-identity-adoption-v1.json'] = digest((ROOT / 'docs/manual-identity-adoption-v1.json').read_bytes())
output_path = ROOT / 'docs/output-evidence-adoption-v2.json'
if output_path.exists():
    output = json.loads(output_path.read_text(encoding='utf-8'))
    expected.update({entry['path']: entry['sha256'] for entry in output['approved']})
    expected.update({'backend/resources/v2/' + entry['path']: entry['sha256'] for entry in output['files']})
    expected['backend/resources/v2/manifest.json'] = output['manifest_sha256']
    expected['docs/output-evidence-adoption-v2.json'] = digest(output_path.read_bytes())
counting_path = ROOT / 'docs/context-counting-adoption-v1.json'
if counting_path.exists():
    counting = json.loads(counting_path.read_text(encoding='utf-8'))
    expected.update({entry['path']: entry['sha256'] for entry in counting['approved']})
    expected.update({entry['path']: entry['sha256'] for entry in counting['files']})
    expected['docs/context-counting-adoption-v1.json'] = digest(counting_path.read_bytes())
framing_path = ROOT / 'docs/proposals/framing-observation-approval-v1.json'
if framing_path.exists():
    framing = json.loads(framing_path.read_text(encoding='utf-8'))
    expected[framing['proposal_path']] = framing['proposal_sha256']
    expected[framing['plan_path']] = framing['plan_file_sha256']
    expected['docs/proposals/framing-observation-approval-v1.json'] = digest(framing_path.read_bytes())
for path in ('backend/resources/v1/manifest.json', 'backend/app/infrastructure/migrations/002_idempotency_guards.sql', 'docs/resource-adoption-v1.json', 'docs/verification/proposals-v1.json'):
    expected[path] = digest((ROOT / path).read_bytes())
deepseek_path = ROOT / 'docs/deepseek-production-adoption-v1.json'
if deepseek_path.exists():
    deepseek = json.loads(deepseek_path.read_text(encoding='utf-8'))
    expected.update({entry['path']: entry['sha256'] for entry in deepseek['approved']})
    expected.update({entry['path']: entry['sha256'] for entry in deepseek.get('files', [])})
    expected['docs/deepseek-production-adoption-v1.json'] = digest(deepseek_path.read_bytes())
actual = []
for path, sha in expected.items():
    committed = digest(blob(path))
    working = digest((ROOT / path).read_bytes())
    actual.append({'path': path, 'expected': sha, 'committed': committed, 'working': working, 'passed': sha == committed == working})
passed = all(entry['passed'] for entry in actual)
now = datetime.now(timezone.utc).isoformat()
record = {'scope': 'Git byte preservation only, not business acceptance', 'recorded_at': now, 'commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(), 'passed': passed, 'files': actual}
path = ROOT / 'docs/verification' / ('frozen-git-' + now.replace(':', '-').replace('.', '-') + '.json')
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'passed': passed, 'files_checked': len(actual), 'evidence': str(path)}, ensure_ascii=False))
if not passed:
    raise SystemExit(1)
