"""Independent TC-E2E-10 list and all-query runs, no paid calls.

F-L is prepared through actual public creation/lifecycle/occupancy commands.
F-M and legacy corruption are explicit native historical fixtures, not legal
model outputs. Expected ordering/filtering/windows are literal Python references.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from urllib.parse import urlencode
from uuid import uuid4
from backend.app.infrastructure.identifiers import EntityKind, entity_id, requirement_number
from backend.app.infrastructure.resources import ResourceCatalog
from backend.app.documents.snapshot import create_snapshot, Provenance
from backend.app.documents.sources import DocumentSources
from backend.tests.messages.test_queries import cards_fixture


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


async def create(checker, client, chat, *, title, kind='NEW', status='ACTIVE'):
    checker.queue_output(chat, {'schema_version': 1, 'response_type': 'INITIALIZE_TEXT',
                               'message': '请提供更多背景信息。', 'confirmed_fact_patches': []})
    data = (await checker.request(client, 'POST', '/requirements', status=201, key=str(uuid4()),
                    body={'title': title, 'requirement_type': kind,
                          'template_key': 'new-requirement' if kind == 'NEW' else 'change-requirement',
                          'template_version': 'v1', 'initialization_mode': 'IDEATION',
                          'initial_idea': '此隔离查询场景只需保留完整模板。'}))['data']
    req, run = data['requirement']['id'], data['guide_run_id']
    await checker.wait_run(client, run, 'COMPLETED')
    if status != 'INITIALIZING':
        await checker.request(client, 'POST', f'/requirements/{req}/complete-initialization',
                              body={'expected_content_version': 1}, key=str(uuid4()))
        if status == 'COMPLETED':
            await checker.request(client, 'POST', f'/requirements/{req}/complete',
                                  body={'expected_version': 1}, key=str(uuid4()))
    return req


async def guide(checker, client, chat, req, version, action, output):
    checker.queue_output(chat, output)
    data = (await checker.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
                    body={'expected_version': version, 'action_type': action,
                          'instruction': '此隔离查询场景建立合法终态或等待记录。',
                          'scope_type': 'DOCUMENT', 'source_type': 'USER_INSTRUCTION'}, key=str(uuid4())))['data']
    expected = 'WAITING_USER' if output['response_type'].startswith('CLARIFY') else 'COMPLETED'
    return await checker.wait_run(client, data['guide_run']['id'], expected)


def patches(first_original='待确认。\n'):
    return [{'title': '待决定查询建议', 'explanation': '保留建议审阅占用', 'impact': None,
             'target_ref': {'block_id': identity}, 'original_content': first_original if identity == 3 else '待确认。\n',
             'patch_operation': 'REPLACE_BLOCK', 'selector_json': None,
             'proposed_markdown': text + '\n', 'proposed_data_json': None}
            for identity, text in ((3, '查询建议一'), (5, '查询建议二'))]


async def list_flow(checker, client, database, req, current, chat, counter):
    await checker.request(client, 'PATCH', f'/requirements/{req}', body={'title': 'A%_甲'})
    identities = [req]
    for index in range(2, 42):
        identities.append(await create(checker, client, chat,
                title='a甲' if index == 2 else '列表需求' + str(index),
                kind='CHANGE' if index % 2 == 0 else 'NEW',
                status=('INITIALIZING', 'ACTIVE', 'COMPLETED')[index % 3]))
    # All four occupied/idle combinations use real child objects and native
    # public commands. Completed ASK waiting is legal and must remain untouched.
    active = [identity for identity in identities if identity != req and identity % 3 == 1]
    await checker.request(client, 'POST', f'/requirements/{active[0]}/manual-draft', status=201,
                          body={'expected_version': 1}, key=str(uuid4()))
    await guide(checker, client, chat, active[1], 1, 'ASK',
                {'schema_version': 1, 'response_type': 'CLARIFY_TEXT', 'message': '需要用户补充说明。'})
    batch = await guide(checker, client, chat, active[2], 1, 'MODIFY',
                {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '请处理建议。',
                 'title': '待决定', 'summary': '两条查询夹具建议', 'suggestions': patches()})
    completed_req = next(identity for identity in identities if identity % 3 == 2 and identity != 2)
    await guide(checker, client, chat, completed_req, 1, 'ASK',
                {'schema_version': 1, 'response_type': 'CLARIFY_TEXT', 'message': '已完成需求仍可询问。'})
    with database.transaction(write=True) as connection:
        tied = timestamp()
        connection.execute('UPDATE requirements SET updated_at=? WHERE id IN (?,?)', (tied, req, identities[1]))
    with database.transaction() as connection:
        roots = [dict(r) for r in connection.execute('SELECT * FROM requirements')]
    checker.check('Actual F-L has 41 legal roots, both types, three statuses and four work states',
                  len(roots) == 41 and {r['requirement_type'] for r in roots} == {'NEW', 'CHANGE'}
                  and {r['status'] for r in roots} == {'INITIALIZING', 'ACTIVE', 'COMPLETED'}
                  and {r['document_work_state'] for r in roots} == {'IDLE', 'MANUAL_EDITING', 'GUIDE_ACTIVE', 'SUGGESTION_REVIEWING'})
    ordered = sorted(roots, key=lambda r: (r['updated_at'], r['id']), reverse=True)
    checker.check('Tie fixture is literal first two requirement numbers and case-sensitive titles',
                  roots[0]['requirement_no'] == 'REQ000001' and roots[1]['requirement_no'] == 'REQ000002'
                  and roots[0]['title'] == 'A%_甲' and roots[1]['title'] == 'a甲'
                  and ordered[:2] == [roots[1], roots[0]])
    before = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
    cases = [({}, ordered), ({'keyword': 'A'}, [roots[0]]), ({'keyword': 'a'}, [roots[1]]),
             ({'keyword': '%'}, [roots[0]]), ({'keyword': '_'}, [roots[0]]),
             ({'keyword': 'a%_甲'}, []), ({'keyword': 'req000002'}, [roots[1]]),
             ({'keyword': '不存在'}, []),
             ({'status': ['ACTIVE', 'COMPLETED'], 'requirement_type': ['NEW']},
              [r for r in ordered if r['status'] in ('ACTIVE', 'COMPLETED') and r['requirement_type'] == 'NEW'])]
    for _ in range(2):
        for filters, expected in cases:
            for page in (1, 2, 3, 4):
                query = urlencode({**filters, 'page': page}, doseq=True)
                result = await checker.request(client, 'GET', '/requirements?' + query)
                checker.check('F-L independent literal filter/page/reference ' + query,
                              [r['id'] for r in result['data']['items']] == [r['id'] for r in expected[(page-1)*20:page*20]]
                              and result['meta']['pagination'] == {'page': page, 'page_size': 20, 'total': len(expected),
                                                                   'total_pages': (len(expected)+19)//20})
        for root in roots:
            actual = (await checker.request(client, 'GET', f'/requirements/{root["id"]}'))['data']
            checker.check('All occupied/terminal root reads preserve exact own fields', actual == root)
    checker.check('Repeated F-L HTTP reads leave complete native database and network unchanged',
                  before == checker.database_facts(database) and network == (len(chat.receipts), len(counter.server.receipts)))
    checker.record['fl_fixture'] = {'requirements': 41, 'actual_public_creation': 41,
                                  'ordered_ids': [r['id'] for r in ordered], 'batch_id': batch['final_result']['suggestion_batch_id']}


def seed_message_history(database):
    catalog = ResourceCatalog(); at = timestamp()
    with database.transaction(write=True) as connection:
        req = entity_id(connection, EntityKind.REQUIREMENT)
        number = requirement_number(connection)
        prototype = dict(connection.execute('SELECT * FROM requirements ORDER BY id LIMIT 1').fetchone())
        prototype.update(id=req, requirement_no=number, title='历史消息查询', status='INITIALIZING',
                         document_work_state='IDLE', active_operation_type=None, active_operation_id=None,
                         state_started_at=None, created_at=at, updated_at=at, completed_at=None)
        connection.execute('INSERT INTO requirements(' + ','.join(prototype) + ') VALUES(' + ','.join('?' for _ in prototype) + ')', tuple(prototype.values()))
        template = catalog.template('NEW', 'new-requirement', 'v1')
        snapshot = create_snapshot(template.markdown, Provenance('SYSTEM', 'TEMPLATE', None), at, DocumentSources(connection, req, catalog))
        document = entity_id(connection, EntityKind.DOCUMENT)
        connection.execute("INSERT INTO requirement_documents VALUES (?,?,'CURRENT',?,?,1,?,?)", (document, req, snapshot.parsed.markdown, snapshot.state_json, at, at))
        original_card = None
        for sequence in range(1, 46):
            identity = entity_id(connection, EntityKind.MESSAGE)
            role, kind, structure, reply, key = 'ASSISTANT', 'TEXT', None, None, None
            if sequence == 40:
                kind = 'INTERACTION_CARDS'; structure = json.dumps(cards_fixture(), ensure_ascii=False); original_card = identity
            elif sequence == 42:
                kind = 'INTERACTION_CARDS'; structure = '{"legacy_corruption":"private-marker-should-not-leak"}'
            elif sequence == 43:
                role, kind, reply, key = 'USER', 'CARD_RESPONSE', original_card, str(uuid4())
                structure = '{"legacy_corruption":"private-answer-should-not-leak"}'
            connection.execute('INSERT INTO conversation_messages VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                               (identity, req, None, sequence, role, '消息'+str(sequence), kind, structure, reply, key, at))
    return req


async def reads_flow(checker, client, database, req, current, chat, counter):
    # Real revisions and run history span multiple fixed pages.
    for index in range(2, 24):
        await checker.request(client, 'POST', f'/requirements/{req}/revisions', status=201,
                              body={'expected_version': current['content_version'], 'description': '版本'+str(index)}, key=str(uuid4()))
    for _ in range(21):
        await guide(checker, client, chat, req, current['content_version'], 'ASK',
                    {'schema_version': 1, 'response_type': 'ANSWER', 'message': '这是只读历史夹具回答。'})
    comments = []
    for index in range(23):
        comments.append((await checker.request(client, 'POST', f'/requirements/{req}/comments', status=201,
                                body={'expected_content_version': current['content_version'], 'content': '评论'+str(index),
                                      'anchor_type': 'BLOCK', 'block_id': 5}, key=str(uuid4())))['data'])
    # Explicit isolated legacy missing-ID reference, so location must be computed
    # without correcting the persisted anchor. No valid comment creator bypass.
    with database.transaction(write=True) as connection:
        legacy = dict(connection.execute('SELECT * FROM comments WHERE id=?', (comments[0]['id'],)).fetchone())
        legacy_id = entity_id(connection, EntityKind.COMMENT)
        legacy.update(id=legacy_id, block_id=9999)
        connection.execute('INSERT INTO comments(' + ','.join(legacy) + ') VALUES(' + ','.join('?' for _ in legacy) + ')', tuple(legacy.values()))
    deleted = (await checker.request(client, 'DELETE', f'/comments/{comments[1]["id"]}', key=str(uuid4())))['data']
    checker.check('Soft delete retains readable tombstone', deleted['deleted_at'] is not None)
    batch_run = await guide(checker, client, chat, req, current['content_version'], 'MODIFY',
                 {'schema_version': 1, 'response_type': 'SUGGESTIONS', 'message': '请处理查询建议。',
                  'title': '只读批次', 'summary': '两条未处理项', 'suggestions': patches('审批人为部门经理😀。\n')})
    batch_id = batch_run['final_result']['suggestion_batch_id']
    # First original paragraph has confirmed facts, so the MODIFY fixture above
    # is adjusted by the caller before queuing in this branch (see run).
    other = await create(checker, client, chat, title='保持草稿占用')
    draft = (await checker.request(client, 'POST', f'/requirements/{other}/manual-draft', status=201,
                                  body={'expected_version': 1}, key=str(uuid4())))['data']['manual_draft']
    message_req = seed_message_history(database)
    with database.transaction() as connection:
        revisions = [dict(r) for r in connection.execute('SELECT id,version_no FROM revisions WHERE requirement_id=? ORDER BY version_no DESC', (req,))]
        runs = [dict(r) for r in connection.execute('SELECT id,created_at FROM guide_runs WHERE requirement_id=? ORDER BY created_at DESC,id DESC', (req,))]
        live_comments = [dict(r) for r in connection.execute('SELECT id,created_at FROM comments WHERE requirement_id=? AND deleted_at IS NULL ORDER BY created_at ASC,id ASC', (req,))]
    with database.transaction(write=True) as connection:
        terminal = dict(connection.execute('SELECT status,updated_at FROM guide_runs WHERE id=?', (batch_run['id'],)).fetchone())
        checker.check('Legacy occupancy points to a genuinely completed native C07 run', terminal['status'] == 'COMPLETED')
        connection.execute("UPDATE requirements SET document_work_state='GUIDE_ACTIVE',active_operation_type='GUIDE_RUN',active_operation_id=?,state_started_at=? WHERE id=?",
                           (batch_run['id'], terminal['updated_at'], req))
    checker.record['legacy_terminal_occupancy_fixture'] = 'Explicit stale GUIDE_ACTIVE pointer to actual completed C07 MODIFY after valid batch creation; Query must not run recovery or rewrite occupancy'
    before = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
    for _ in range(2):
        for path in (f'/requirements/{req}', f'/requirements/{req}/current-document',
                     f'/requirements/{other}/manual-draft', f'/requirements/{req}/comment-index',
                     f'/comments/{legacy_id}', f'/comments/{deleted["id"]}',
                     f'/guide-runs/{batch_run["id"]}', f'/suggestion-batches/{batch_id}'):
            result = await checker.request(client, 'GET', path)
            if path == f'/requirements/{req}':
                checker.check('Terminal stale occupancy remains unchanged by query', result['data']['document_work_state'] == 'GUIDE_ACTIVE'
                              and result['data']['active_operation_id'] == batch_run['id'])
            if path.endswith('/manual-draft'):
                checker.check('Existing manual draft query preserves exact pair/version', result['data'] == draft)
        await checker.request(client, 'GET', f'/requirements/{req}/manual-draft', status=404)
        for endpoint, expected in (('revisions', revisions), ('guide-runs', runs), ('comments', live_comments)):
            for page in (1, 2, 3):
                result = await checker.request(client, 'GET', f'/requirements/{req}/{endpoint}?page={page}')
                checker.check('Query fixed page/count/order ' + endpoint + str(page),
                              [r['id'] for r in result['data']['items']] == [r['id'] for r in expected[(page-1)*20:page*20]]
                              and result['meta']['pagination']['total'] == len(expected))
        for revision in revisions:
            result = await checker.request(client, 'GET', f'/revisions/{revision["id"]}')
            checker.check('Revision detail matches literal ordinal', result['data']['version_no'] == revision['version_no'])
        for cursor, sequences, more, next_cursor in ((None, list(range(26,46)), True, 26),
                                                    (26, list(range(6,26)), True, 6),
                                                    (6, list(range(1,6)), False, None), (1, [], False, None)):
            path = f'/requirements/{message_req}/messages' + ('' if cursor is None else '?before_sequence_no='+str(cursor))
            result = await checker.request(client, 'GET', path)
            checker.check('Exact F-M exclusive cursor window ' + str(cursor),
                          [r['sequence_no'] for r in result['data']['items']] == sequences
                          and result['meta']['pagination'] == {'page_size': 20, 'has_more': more, 'next_cursor': next_cursor})
            for message in result['data']['items']:
                checker.check('Historical original content remains visible', message['content'] == '消息'+str(message['sequence_no']))
                if message['sequence_no'] in (42,43):
                    checker.check('Corrupt structure degraded and card interaction disabled', message['structured_content'] is None and message['card_state'] is None)
            checker.check('Private corrupt structure never exposed', 'should-not-leak' not in json.dumps(result))
        filtered = await checker.request(client, 'GET', f'/requirements/{req}/guide-runs?action_type=MODIFY&status=COMPLETED')
        checker.check('Guide combined filter matches literal single completed MODIFY',
                      [r['id'] for r in filtered['data']['items']] == [batch_run['id']] and filtered['meta']['pagination']['total'] == 1)
    checker.check('All repeated Query endpoints leave full actual DB and count/Chat unchanged',
                  before == checker.database_facts(database) and network == (len(chat.receipts), len(counter.server.receipts)))
    checker.record['fm_fixture'] = 'Explicit separate historical root/full template/45 messages, original text and corrupt old structure retained; no model creation claim'
    checker.record['legacy_comment_fixture'] = 'Explicitly new-identified legacy orphan row inserted after valid public comments; immutable original rows/triggers retained; queries must not persist location'


async def run(checker, client, database, req, current, chat, counter, branch):
    if branch == 'LIST':
        await list_flow(checker, client, database, req, current, chat, counter)
    else:
        await reads_flow(checker, client, database, req, current, chat, counter)
    checker.record['query_branch'] = branch
    checker.record['actual_local_count_requests'] = len(counter.server.receipts)
    checker.record['actual_local_chat_requests'] = len(chat.receipts)
