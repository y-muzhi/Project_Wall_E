"""Independently audit closed native databases for the comment batch application matrix."""
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
            assert current == final['current'] and current['content_version'] == 4, name + ' full applied CURRENT'
            assert current['id'] == initial['current']['id']
            original = result['before_batch']['suggestions'][0]
            assert current['markdown_content'] == initial['current']['markdown_content'].replace(original['original_content'], result['effective_proposal'])
            old_state, new_state = initial['current']['block_state_json'], current['block_state_json']
            assert old_state['next_block_id'] == new_state['next_block_id'] and len(old_state['blocks']) == len(new_state['blocks'])
            for old in old_state['blocks']:
                new = next(block for block in new_state['blocks'] if block['block_id'] == old['block_id'])
                if old['block_id'] != original['target_ref']['block_id']:
                    assert new == old, name + ' unchanged other block'
                else:
                    for key in old:
                        if key.startswith('created_') or key in ('block_id','block_type','section_path'):
                            assert new[key] == old[key], name + ' original block identity/birth'
                    assert new['last_modified_by_type'] == ('USER' if result['user_edited'] else 'AI')
                    assert new['last_modified_source_type'] == 'SUGGESTION_BATCH' and new['last_modified_source_id'] == result['final_batch']['id']
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
                assert revisions == initial['revision_details'], name + ' immutable Baseline/no automatic Revision'
            drafts = connection.execute("SELECT count(*) FROM requirement_documents WHERE requirement_id=? AND document_type='MANUAL_DRAFT'", (identity,)).fetchone()[0]
            assert drafts == int(result.get('external_busy', False)), name + ' explicit external occupancy'
            assert requirement['document_work_state'] == ('MANUAL_EDITING' if drafts else 'IDLE'), name + ' work state'
            runs = connection.execute('SELECT * FROM guide_runs WHERE requirement_id=? ORDER BY id', (identity,)).fetchall()
            assert len(runs) == (2 if result.get('accepted_run') else 1), name + ' unique native runs'
            assert (runs[0]['mode_snapshot'], runs[0]['function_type'], runs[0]['status']) == ('DESIGN', 'INITIALIZE_REQUIREMENT', 'FAILED'), name + ' original run'
            assert connection.execute('SELECT count(*) FROM suggestion_batches WHERE requirement_id=?', (identity,)).fetchone()[0] == 1, name + ' unique explicit generation fixture batch'
            if result.get('accepted_run'):
                run = runs[1]
                assert (run['id'], run['source_id']) == (result['accepted_run']['id'], case['comment']['id'])
                assert (run['mode_snapshot'], run['function_type'], run['action_type'], run['source_type'], run['status'], run['error_code']) == (None, 'MODIFY_FROM_COMMENT', 'MODIFY', 'COMMENT', 'COMPLETED', None), name + ' named generation fixture'
                assert json.loads(run['scope_ref_json']) == result['original_scope'], name + ' frozen backend scope'
                assert run['scope_type'] == case['comment']['anchor_type']
                message = dict(connection.execute('SELECT * FROM conversation_messages WHERE id=?', (run['trigger_message_id'],)).fetchone())
                assert (message['requirement_id'], message['guide_run_id'], message['role'], message['message_type'], message['sequence_no']) == (identity, run['id'], 'USER', 'TEXT', 2), name + ' unique user message'
                assert message['content'] == case['comment']['content'], name + ' backend copied actual source'
                writes = [r for r in result['wire']['requests'] if r['method'] != 'GET']
                assert message['idempotency_key'] == writes[0]['key'], name + ' original accepted key'
                decisions = [request for request in writes if request['path'].endswith('/decision')]
                completes = [request for request in writes if request['path'].endswith('/complete')]
                assert len(decisions) == (2 if result.get('known_edit_rejected') else 1)
                assert [request['status'] for request in decisions] == ([422,200] if result.get('known_edit_rejected') else [200])
                assert len(completes) == (2 if result.get('completion_original_replay') else 1)
                for request in completes:
                    assert request['status'] == 200 and json.loads(request['body']) == {'expected_content_version':3}
                    persisted = connection.execute('SELECT * FROM idempotency_records WHERE capability_id=? AND target_identity=? AND idempotency_key=?', ('APP-BATCH-CMD-C02','SuggestionBatch:'+str(result['final_batch']['id']),request['key'])).fetchone()
                    assert persisted is not None and persisted['status'] == 'SUCCEEDED' and persisted['http_status'] == 200
                    assert json.loads(persisted['success_result_json'])['data'] == request['response']['data'], name + ' exact durable completion receipt'
                if result.get('completion_original_replay'):
                    assert completes[0]['key'] == completes[1]['key'] and completes[0]['body'] == completes[1]['body']
                    assert not completes[0]['delivered'] and completes[1]['delivered']
                    assert completes[0]['response']['data'] == completes[1]['response']['data']
                assert result.get('actual_document_displayed'), name + ' root document display/target verified'

                assert connection.execute('SELECT count(*) FROM conversation_messages WHERE guide_run_id=?', (run['id'],)).fetchone()[0] == 1, name + ' no duplicate trigger/fake assistant'
                assert result['fixture_generation'] is True and result['current_before_apply'] == initial['current'], name + ' generation preserved full CURRENT'
                assert '--seed-comment-suggestion-fixture' in report['native']['args'], name + ' explicit diagnostic factory'
                stored = dict(connection.execute('SELECT * FROM suggestion_batches WHERE guide_run_id=?', (run['id'],)).fetchone())
                final_batch = result['final_batch']
                assert stored == {key:value for key,value in final_batch.items() if key not in ('suggestions','counts')}, name + ' complete batch metadata'
                assert (stored['source_type'],stored['source_id'],stored['status'],stored['completion_result'],stored['applied_content_version']) == ('COMMENT',case['comment']['id'],'COMPLETED','CHANGES_APPLIED',4)
                assert json.loads(run['final_result_json'])['suggestion_batch_id'] == stored['id'], name + ' run result links unique batch'
                suggestions = []
                for item in connection.execute('SELECT * FROM suggestions WHERE batch_id=? ORDER BY order_no', (stored['id'],)):
                    item = dict(item)
                    for public,private in (('target_ref','target_ref_json'),('selector','selector_json'),('proposed_data','proposed_data_json')):
                        value = item.pop(private);item[public] = json.loads(value) if value is not None else None
                    suggestions.append(item)
                assert suggestions == final_batch['suggestions'], name + ' complete stored decided suggestion'
                for key,value in result['before_batch']['suggestions'][0].items():
                    if key not in ('status','user_edited_content','decided_at','updated_at'):
                        assert suggestions[0][key] == value, name + ' immutable target/proposal'
                assert suggestions[0]['user_edited_content'] == (result['effective_proposal'] if result['user_edited'] else None)
                assert len(suggestions) == 1 and suggestions[0]['target_ref'] == {'block_id':case['comment']['block_id']} and suggestions[0]['status'] == ('EDITED' if result['user_edited'] else 'ACCEPTED')

            comments = [dict(row) for row in connection.execute('SELECT * FROM comments WHERE requirement_id=?', (identity,))]
            expected = result.get('finalComment') or case['comment']
            assert len(comments) == int(expected is not None), name + ' comment count'
            if comments:
                comments[0]['anchor_ref'] = json.loads(comments[0].pop('anchor_ref_json'))
                assert comments[0] == {key: value for key, value in expected.items() if key != 'location'}, name + ' actual preserved comment/anchor'
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
              'scope': 'Closed SQLite comment batch application audit: named generation fixture only; actual I34/I21/I22; complete CURRENT v4, immutable Baseline/no automatic Revision, original block identities, decision attribution, source links and OPEN/orphaned comments; no C07/Provider/effect proof'}
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
    target = ROOT / 'docs/verification' / ('comment-apply-post-audit-' + now.replace(':', '-') + '.json')
    with target.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print(json.dumps({'passed': result['passed'], 'evidence': str(target), 'error': result.get('error')}))
    raise SystemExit(0 if result['passed'] else 1)
