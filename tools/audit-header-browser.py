"""Independently audit closed native databases for the header browser matrix."""
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


def audit(path):
    report = json.loads(path.read_text(encoding='utf-8'))
    assert report['passed'] and report['native']['code'] == 0 and not report['changed_inputs']
    assert report['inputs_before'] == report['inputs_after']
    assert len(report['cases']) == len(report['selected_cases'])
    for name, expected in report['inputs_after'].items():
        assert sha(ROOT / name) == expected, name
    args = report['native']['args']
    database = Path(args[args.index('--database') + 1]).resolve()
    assert database.is_relative_to((ROOT / 'output/playwright').resolve())
    before = sha(database)
    assert before == report['database_sha256']
    receipt = [json.loads(line) for line in report['native']['stdout'].splitlines() if line.startswith('{')][-1]
    assert receipt['closed'] and receipt['facts']['llm_uses'] == 0
    rows = []
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        counts = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in report['native_facts']}
        assert counts == report['native_facts'] and counts['llm_uses'] == 0
        for case in report['cases']:
            initial, final, result = case['before'], case['after'], case['result']
            identity, name = initial['requirement']['id'], case['name']
            requirement = dict(connection.execute('SELECT * FROM requirements WHERE id=?', (identity,)).fetchone())
            assert requirement == final['requirement'], name + ' requirement'
            for field in ('id', 'requirement_no', 'requirement_type', 'template_key', 'template_version', 'created_at'):
                assert requirement[field] == initial['requirement'][field], name + ' original identity/template'
            if not name.startswith('HEADER-title-'):
                assert requirement['title'] == initial['requirement']['title'], name + ' untouched title'
            if not name.startswith('HEADER-initialization_mode-'):
                assert requirement['initialization_mode'] == initial['requirement']['initialization_mode'], name + ' untouched mode'
            current = dict(connection.execute("SELECT * FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (identity,)).fetchone())
            current['block_state_json'] = json.loads(current['block_state_json'])
            assert current == initial['current'] == final['current'], name + ' full CURRENT'
            revisions = []
            for row in connection.execute('SELECT * FROM revisions WHERE requirement_id=? ORDER BY version_no', (identity,)):
                revision = dict(row)
                revision['markdown_content'] = revision.pop('markdown_snapshot')
                revision['block_state_json'] = json.loads(revision.pop('block_state_snapshot_json'))
                revisions.append(revision)
            assert revisions == sorted(final['revision_details'], key=lambda row: row['version_no']), name + ' full snapshots'
            if result.get('completed_initialization'):
                assert initial['revision_details'] == [] and len(revisions) == 1, name + ' unique baseline'
                assert revisions[0]['revision_type'] == 'BASELINE' and revisions[0]['source_content_version'] == 3
                assert revisions[0]['markdown_content'] == current['markdown_content']
                assert revisions[0]['block_state_json'] == current['block_state_json']
            else:
                assert initial['revision_details'] == final['revision_details'], name + ' immutable versions'
            drafts = connection.execute("SELECT count(*) FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'", (identity,)).fetchone()[0]
            assert drafts == int(result.get('external_busy', False)), name + ' explicit external occupancy'
            assert requirement['document_work_state'] == ('MANUAL_EDITING' if drafts else 'IDLE'), name + ' work state'
            runs = connection.execute('SELECT id,mode_snapshot,function_type,status FROM guide_runs WHERE requirement_id=? ORDER BY id', (identity,)).fetchall()
            assert len(runs) == (2 if result.get('subsequent_run') else 1), name + ' exact runs'
            assert tuple(runs[0])[1:] == ('DESIGN', 'INITIALIZE_REQUIREMENT', 'FAILED'), name + ' original run'
            if result.get('subsequent_run'):
                assert name == 'HEADER-initialization_mode-success'
                assert tuple(runs[1]) == (result['subsequent_run']['id'], 'IDEATION', 'INITIALIZE_REQUIREMENT', 'FAILED'), name + ' next mode'
                assert requirement['initialization_mode'] == 'IDEATION'
            comments = [dict(row) for row in connection.execute('SELECT * FROM comments WHERE requirement_id=?', (identity,))]
            expected = result.get('finalComment') or case['comment']
            assert len(comments) == int(expected is not None), name + ' comment count'
            if comments:
                comments[0]['anchor_ref'] = json.loads(comments[0].pop('anchor_ref_json'))
                assert comments[0] == {key: value for key, value in expected.items() if key != 'location'}, name + ' actual tombstone/original'
            rows.append({'name': name, 'requirement_id': identity, 'status': requirement['status'],
                         'current_version': current['content_version'], 'revisions': len(revisions),
                         'external_manual_drafts': drafts, 'comments': len(comments), 'passed': True})
    assert sha(database) == before
    return {'source_evidence': path.name, 'passed': True, 'source_inputs': len(report['inputs_after']),
            'native_counts': counts, 'database_sha256': before, 'database_bytes_unchanged': True, 'cases': rows}, report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path, nargs='+')
    args = parser.parse_args()
    now = datetime.now(timezone.utc).isoformat()
    result = {'recorded_at': now, 'audit_source_sha256': sha(Path(__file__)),
              'scope': 'Independent read-only closed SQLite audit of unchanged full CURRENT/snapshots, lifecycle/attributes, original run/template and explicit external occupancy; no new model requests'}
    try:
        audits, sources = [], []
        for evidence in args.evidence:
            checked, source = audit(evidence)
            audits.append(checked)
            sources.append(source)
        assert all(source['inputs_after'] == sources[0]['inputs_after'] for source in sources)
        names = [case['name'] for checked in audits for case in checked['cases']]
        assert len(names) == len(set(names)), 'Each branch must have an independent accepted record'
        result.update(passed=True, distinct_cases=len(names), audits=audits)
    except Exception as error:
        result.update(passed=False, error=f'{type(error).__name__}: {error}')
    target = ROOT / 'docs/verification' / ('header-post-audit-' + now.replace(':', '-') + '.json')
    with target.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'passed': result['passed'], 'evidence': str(target), 'error': result.get('error')}))
    raise SystemExit(0 if result['passed'] else 1)
