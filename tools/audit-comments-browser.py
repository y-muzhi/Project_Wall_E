"""Read-only postcondition audit after the owned comment service has closed."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(evidence):
    report = json.loads(evidence.read_text(encoding='utf-8'))
    assert report['passed'] and len(report['cases']) == len(report['selected_cases'])
    assert report['native']['code'] == 0 and not report['changed_inputs']
    assert report['inputs_before'] == report['inputs_after']
    for path, expected in report['inputs_after'].items():
        assert sha(Path(path)) == expected, path
    arguments = report['native']['args']
    database = Path(arguments[arguments.index('--database') + 1]).resolve()
    assert database.is_relative_to((ROOT / 'output/playwright').resolve())
    before = sha(database)
    assert before == report['database_sha256']
    receipt = [json.loads(line) for line in report['native']['stdout'].splitlines()
               if line.startswith('{')][-1]
    assert receipt['closed'] and receipt['facts']['llm_uses'] == 0
    cases = []
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        counts = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in report['native_facts']}
        assert counts == report['native_facts'] and counts['llm_uses'] == 0
        for case in report['cases']:
            initial, final = case['before'], case['after']
            identity = initial['requirement']['id']
            requirement = dict(connection.execute('SELECT * FROM requirements WHERE id=?', (identity,)).fetchone())
            assert all(requirement[key] == value for key, value in final['requirement'].items())
            assert initial['current'] == final['current'] and initial['revisions'] == final['revisions']
            assert requirement['status'] == initial['requirement']['status'] == 'ACTIVE'
            current = dict(connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (identity,)).fetchone())
            current['block_state_json'] = json.loads(current['block_state_json'])
            assert current == final['current']
            revisions = [dict(row) for row in connection.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no', (identity,))]
            assert len(revisions) == len(final['revisions']['items']) == 1
            for row, expected in zip(revisions, sorted(final['revisions']['items'], key=lambda item: item['version_no'])):
                row['block_state_snapshot_json'] = json.loads(row['block_state_snapshot_json'])
                assert all(row[key] == value for key, value in expected.items())
                assert row['revision_type'] == 'BASELINE' and row['source_content_version'] == 3
                assert '部门经理负责核验。本轮正式基线😀' in row['markdown_snapshot']
                assert any(block['block_id'] == 26 for block in row['block_state_snapshot_json']['blocks'])
            expected = {comment['id']: comment for comment in case['comments']}
            # Last confirmed public response per ID; explicit latest observations
            # below supersede held/stale receipts or externally changed comments.
            for request in case['result']['wire']['requests']:
                if request['method'] != 'GET' and request.get('status') in (200, 201):
                    data = request.get('response', {}).get('data', {})
                    if 'anchor_ref' in data and 'deleted_at' in data:
                        expected[data['id']] = data
            result = case['result']
            for comment in result.get('list', []):
                expected[comment['id']] = comment
            for key in ('reopened', 'actual'):
                if key in result:
                    expected[result[key]['id']] = result[key]
            comments = [dict(row) for row in connection.execute('SELECT * FROM comments WHERE requirement_id=? ORDER BY id', (identity,))]
            assert len(comments) == len(expected)
            for comment in comments:
                comment['anchor_ref'] = json.loads(comment.pop('anchor_ref_json'))
                assert comment == {key: value for key, value in expected[comment['id']].items() if key != 'location'}
            drafts = connection.execute("SELECT count(*) FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'", (identity,)).fetchone()[0]
            assert drafts == int(result.get('external_busy', False))
            assert requirement['document_work_state'] == ('MANUAL_EDITING' if drafts else 'IDLE')
            cases.append({'name': case['name'], 'requirement_id': identity,
                          'current_version': current['content_version'], 'revision_count': len(revisions),
                          'comments': len(comments), 'soft_deleted': sum(row['deleted_at'] is not None for row in comments),
                          'external_manual_drafts': drafts, 'passed': True})
    assert sha(database) == before
    return {'scope': 'Independent read-only closed SQLite audit; actual CURRENT, revisions, lifecycle, final comments, explicit external drafts and byte identity; no new model calls',
            'source_evidence': evidence.name, 'passed': True, 'source_inputs_unchanged': len(report['inputs_after']),
            'native_counts': counts, 'database_sha256': before, 'database_bytes_unchanged': True, 'cases': cases}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat()
    result = {'recorded_at': now, 'audit_source_sha256': sha(Path(__file__))}
    try:
        result.update(audit(args.evidence))
    except Exception as error:
        result.update(passed=False, error=f'{type(error).__name__}: {error}', source_evidence=args.evidence.name)
    target = ROOT / 'docs/verification' / ('comments-post-audit-' + now.replace(':', '-') + '.json')
    with target.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'passed': result['passed'], 'evidence': str(target), 'error': result.get('error')}))
    raise SystemExit(0 if result['passed'] else 1)
