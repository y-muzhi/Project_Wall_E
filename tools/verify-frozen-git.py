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
for path in ('backend/resources/v1/manifest.json', 'backend/app/infrastructure/migrations/002_idempotency_guards.sql', 'docs/resource-adoption-v1.json', 'docs/verification/proposals-v1.json'):
    expected[path] = digest((ROOT / path).read_bytes())
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
