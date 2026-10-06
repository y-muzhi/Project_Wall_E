"""TC-E2E-05 four independent dual-status scenarios, native HTTP and SQLite.

Original-identity restoration is an explicitly installed historical snapshot
fixture. It verifies C06 reattachment, not a new cross-session undo mechanism.
"""
from copy import deepcopy
from contextlib import closing
import json
import sqlite3
from uuid import uuid4


def facts(database):
    with closing(sqlite3.connect(database.path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: [dict(row) for row in connection.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid')]
                for name in names}


async def read_pair(checker, client, req):
    return (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']


async def delete_original_block(checker, client, req, current):
    draft = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft', status=201,
                                  body={'expected_version': current['content_version']}, key=str(uuid4())))['data']['manual_draft']
    state = deepcopy(draft['block_state_json'])
    state['blocks'] = [b for b in state['blocks'] if b['block_id'] != 3]
    body = {'expected_version': 1, 'markdown_content': draft['markdown_content'].replace('审批人为部门经理。\n', '', 1),
            'block_state_json': state}
    saved = (await checker.request(client, 'PUT', f'/requirements/{req}/manual-draft', body=body))['data']
    checker.check('Deletion save changes draft only', await read_pair(checker, client, req) == current)
    result = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                   body={'expected_version': 2}, key=str(uuid4())))['data']
    checker.check('Public deletion writes exact draft pair with original CURRENT identity/version+1',
                  result['id'] == current['id'] and result['content_version'] == current['content_version'] + 1
                  and result['markdown_content'] == saved['markdown_content'] and result['block_state_json'] == saved['block_state_json'])
    return result


async def read_only(checker, client, database, req, expected, chat, counter, location):
    before = checker.database_facts(database)
    network = (len(chat.receipts), len(counter.server.receipts))
    for _ in range(2):
        listed = (await checker.request(client, 'GET', f'/requirements/{req}/comments'))['data']['items']
        index = (await checker.request(client, 'GET', f'/requirements/{req}/comment-index'))['data']
        checker.check('Both status comments listed at actual location with persistent anchor kept',
                      len(listed) == 2 and all(c['location']['status'] == location for c in listed)
                      and {c['id']: {k: v for k, v in c.items() if k != 'location'} for c in listed} == expected)
        checker.check('Complete index reflects both persistent statuses and read-only locations',
                      index['total_count'] == 2 and index['open_count'] == sum(c['status'] == 'OPEN' for c in expected.values())
                      and all(c['location']['status'] == location for c in index['comments']))
        for identity, comment in expected.items():
            actual = (await checker.request(client, 'GET', f'/comments/{identity}'))['data']
            checker.check('Comment detail preserves all original fields', actual == comment)
    checker.check('Repeated comment reads change no actual database fact or network request',
                  before == checker.database_facts(database) and network == (len(chat.receipts), len(counter.server.receipts)))


async def run(checker, client, database, req, current, chat, counter, branch):
    initial_status, initial_anchor = branch.split('-')
    await checker.edit_and_save(client, req, current, '审批人为部门经理。')
    original = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                      body={'expected_version': 2}, key=str(uuid4())))['data']
    checker.check('F-A original current version 3 through actual public edit', original['content_version'] == 3)
    expected = {}
    for kind in ('BLOCK', 'SELECTION'):
        body = {'expected_content_version': 3, 'content': '请说明审批人', 'anchor_type': kind, 'block_id': 3}
        if kind == 'SELECTION':
            body['selection'] = {'selected_text': '部门经理', 'prefix_text': '审批人为', 'suffix_text': '。'}
        comment = (await checker.request(client, 'POST', f'/requirements/{req}/comments', status=201,
                                         body=body, key=str(uuid4())))['data']
        if initial_status == 'RESOLVED':
            comment = (await checker.request(client, 'POST', f'/comments/{comment["id"]}/resolve', key=str(uuid4())))['data']
        expected[comment['id']] = comment
    active = original
    if initial_anchor == 'ORPHANED':
        active = await delete_original_block(checker, client, req, active)
        expected = {i: {**c, 'anchor_status': 'ORPHANED'} for i, c in expected.items()}
    checker.check('Independent original dual-status precondition',
                  all(c['status'] == initial_status and c['anchor_status'] == initial_anchor for c in expected.values()))
    await read_only(checker, client, database, req, expected, chat, counter, initial_anchor)
    # Resolve/reopen independently of anchor; only these explicit commands change
    # the comment business state/time. Reanchor itself must preserve both.
    for identity, old in list(expected.items()):
        resolved = (await checker.request(client, 'POST', f'/comments/{identity}/resolve', key=str(uuid4())))['data']
        checker.check('Resolve preserves original anchor fields', resolved['status'] == 'RESOLVED'
                      and all(resolved[k] == old[k] for k in ('anchor_status', 'anchor_ref', 'block_id', 'content', 'created_at')))
        reopened = (await checker.request(client, 'POST', f'/comments/{identity}/reopen', key=str(uuid4())))['data']
        checker.check('Reopen preserves original anchor and clears resolved time', reopened['status'] == 'OPEN'
                      and reopened['resolved_at'] is None and reopened['anchor_ref'] == old['anchor_ref']
                      and reopened['anchor_status'] == initial_anchor)
        expected[identity] = reopened
    block = next(c for c in expected.values() if c['anchor_type'] == 'BLOCK')
    expected[block['id']] = (await checker.request(client, 'POST', f'/comments/{block['id']}/resolve', key=str(uuid4())))['data']
    checker.check('C06 deletion/restoration later includes both OPEN and RESOLVED business states',
                  {c['status'] for c in expected.values()} == {'OPEN', 'RESOLVED'})
    source = next(c for c in expected.values() if c['anchor_type'] == 'SELECTION')
    if initial_anchor == 'ORPHANED':
        before = checker.database_facts(database)
        failed = await checker.request(client, 'POST', f'/comments/{source["id"]}/guide-runs', status=409,
                                       body={'expected_content_version': active['content_version']}, key=str(uuid4()))
        checker.check('Persisted orphan cannot create any message/run/claim', failed['error']['code'] == 'COMMENT_ORPHANED'
                      and before == checker.database_facts(database))
    else:
        checker.queue_output(chat, {'schema_version': 1, 'response_type': 'NO_CHANGE', 'message': '本次无需修改正文'})
        accepted = (await checker.request(client, 'POST', f'/comments/{source["id"]}/guide-runs', status=202,
                                          body={'expected_content_version': 3}, key=str(uuid4())))['data']
        checker.check('Public comment source binds actual original selection authority',
                      accepted['source_type'] == 'COMMENT' and accepted['source_id'] == source['id']
                      and accepted['function_type'] == 'MODIFY_FROM_COMMENT'
                      and accepted['scope'] == {'scope_type': 'SELECTION', 'scope_ref': {'block_id': 3, **source['anchor_ref']}})
        await checker.wait_run(client, accepted['id'], 'COMPLETED')
        checker.check('Completed comment MODIFY does not auto-resolve comment or change CURRENT',
                      (await checker.request(client, 'GET', f'/comments/{source["id"]}'))['data'] == source
                      and await read_pair(checker, client, req) == active)
        active = await delete_original_block(checker, client, req, active)
        expected = {i: {**c, 'anchor_status': 'ORPHANED'} for i, c in expected.items()}
    await read_only(checker, client, database, req, expected, chat, counter, 'ORPHANED')
    # Exact old-ID historical snapshot is explicitly supplied as a native fixture.
    # Reads must compute ATTACHED without writing persistent ORPHANED. A later
    # actual public completion calls C06 and alone persists reattachment.
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE requirement_id=? AND document_type='CURRENT'",
                           (original['markdown_content'], json.dumps(original['block_state_json'], ensure_ascii=False), req))
    checker.record['historical_identity_fixture'] = 'Original valid pair/identity restored explicitly in isolated native SQLite before public completion; not public cross-session undo'
    await read_only(checker, client, database, req, expected, chat, counter, 'ATTACHED')
    draft = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft', status=201,
                                  body={'expected_version': active['content_version']}, key=str(uuid4())))['data']['manual_draft']
    recovered = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                      body={'expected_version': 1}, key=str(uuid4())))['data']
    checker.check('Public completion preserves historical original body/IDs and increments once',
                  recovered['markdown_content'] == original['markdown_content']
                  and recovered['block_state_json'] == original['block_state_json']
                  and recovered['content_version'] == active['content_version'] + 1)
    expected = {i: {**c, 'anchor_status': 'ATTACHED'} for i, c in expected.items()}
    await read_only(checker, client, database, req, expected, chat, counter, 'ATTACHED')
    # A separately explicit legacy drift leaves the stored anchor ATTACHED but
    # removes its unique selection. C05 must commit only ORPHANED on refusal.
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE requirement_documents SET markdown_content=? WHERE requirement_id=? AND document_type='CURRENT'",
                           (recovered['markdown_content'].replace('审批人为部门经理。\n', '审批人为财务负责人。\n', 1), req))
    before_reads = facts(database)
    listing = (await checker.request(client, 'GET', f'/requirements/{req}/comments'))['data']['items']
    target = next(c for c in listing if c['id'] == source['id'])
    checker.check('Stale location is read-only and does not correct persistent anchor',
                  target['anchor_status'] == 'ATTACHED' and target['location']['status'] == 'ORPHANED'
                  and before_reads == facts(database))
    expected_facts = deepcopy(before_reads)
    next(c for c in expected_facts['comments'] if c['id'] == source['id'])['anchor_status'] = 'ORPHANED'
    network = (len(chat.receipts), len(counter.server.receipts))
    failed = await checker.request(client, 'POST', f'/comments/{source["id"]}/guide-runs', status=409,
                                   body={'expected_content_version': recovered['content_version']}, key=str(uuid4()))
    checker.check('Stale source refusal commits only anchor_status with no timestamp/message/run/claim/network effect',
                  failed['error']['code'] == 'COMMENT_ORPHANED' and expected_facts == facts(database)
                  and network == (len(chat.receipts), len(counter.server.receipts)))
    before_retry = checker.database_facts(database)
    failed_again = await checker.request(client, 'POST', f'/comments/{source["id"]}/guide-runs', status=409,
                                         body={'expected_content_version': recovered['content_version']}, key=str(uuid4()))
    checker.check('Second orphan refusal has no additional stored or network effect',
                  failed_again['error']['code'] == 'COMMENT_ORPHANED' and before_retry == checker.database_facts(database))
    checker.record['comment_initial_combination'] = branch
    checker.record['actual_local_count_requests'] = len(counter.server.receipts)
    checker.record['actual_local_chat_requests'] = len(chat.receipts)
