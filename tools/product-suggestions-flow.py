"""Actual producer -> decisions -> application/no-change/pending/discard.

Stale/version and conflicting storage faults are explicit diagnostic injections
after actual valid C07 production. Tables are created by real manual save/complete;
row replacement and whole-table append have independent literal reference text.
"""
from copy import deepcopy
import json
from uuid import uuid4
from backend.app.infrastructure.identifiers import entity_id, EntityKind


async def run(checker, client, database, req, current, chat, counter, branch):
    table_text = '| 项目 | 说明 |\n| --- | --- |\n| 原行 | 保留 |\n| 尾行 | 必须保留 |\n'
    table_branch = branch in ('TABLE_ROW', 'TABLE_APPEND')
    saved = await checker.edit_and_save(client, req, current, '审批人为部门经理。',
                                        append_table=table_text if table_branch else None)
    base = (await checker.request(client, 'POST', f'/requirements/{req}/manual-draft/complete',
                                  body={'expected_version': 2}, key=str(uuid4())))['data']
    checker.check('Suggestions native F-A precondition CURRENT3', base['content_version'] == 3
                  and base['markdown_content'] == saved['markdown_content'])
    replacement = {'title': '修改审批人', 'explanation': '待用户决定', 'impact': None,
                   'target_ref': {'block_id': 3}, 'original_content': '审批人为部门经理。\n',
                   'patch_operation': 'REPLACE_BLOCK', 'selector_json': None,
                   'proposed_markdown': '审批人为财务负责人。\n', 'proposed_data_json': None}
    deletion = {'title': '删除待确认段落', 'explanation': '仅供决定', 'impact': None,
                'target_ref': {'block_id': 5}, 'original_content': '待确认。\n',
                'patch_operation': 'DELETE_BLOCK', 'selector_json': None,
                'proposed_markdown': None, 'proposed_data_json': None}
    patches = [replacement, deletion]
    if table_branch:
        table_id = saved['block_state_json']['blocks'][-1]['block_id']
        checker.check('Native allocated table identity/high-water survive completion', table_id == 26
                      and base['block_state_json']['next_block_id'] == 27)
        table_patch = {'title': '表格行变更', 'explanation': '待决定表格建议', 'impact': None,
                       'target_ref': {'block_id': table_id},
                       'original_content': '| 原行 | 保留 |\n' if branch == 'TABLE_ROW' else table_text,
                       'patch_operation': 'REPLACE_TABLE_ROW' if branch == 'TABLE_ROW' else 'REPLACE_BLOCK',
                       'selector_json': {'key_column_index': 0, 'key_value': '原行'} if branch == 'TABLE_ROW' else None,
                       'proposed_markdown': None if branch == 'TABLE_ROW' else table_text + '| 新行 | 新增😀 |\n',
                       'proposed_data_json': {'cells': ['原行', '新值😀']} if branch == 'TABLE_ROW' else None}
        patches = [table_patch, replacement]
    checker.queue_output(chat, {'schema_version': 1, 'response_type': 'SUGGESTIONS',
                               'message': '请逐项决定建议', 'title': '审批改进', 'summary': '两项待决定变更',
                               'suggestions': patches})
    accepted = (await checker.request(client, 'POST', f'/requirements/{req}/guide-runs', status=202,
                                     body={'expected_version': 3, 'action_type': 'MODIFY',
                                           'instruction': '提出审批人修改及段落删除建议', 'scope_type': 'DOCUMENT',
                                           'source_type': 'USER_INSTRUCTION'}, key=str(uuid4())))['data']
    run_id = accepted['guide_run']['id']
    status = await checker.wait_run(client, run_id, 'COMPLETED')
    batch_id = status['final_result']['suggestion_batch_id']
    checker.check('Actual C07 MODIFY produces native batch identity', type(batch_id) is int)
    batch = (await checker.request(client, 'GET', f'/suggestion-batches/{batch_id}'))['data']
    checker.check('Native producer creates exactly two pending suggestions', batch['base_content_version'] == 3
                  and batch['status'] == 'PENDING' and len(batch['suggestions']) == 2
                  and all(s['status'] == 'PENDING' for s in batch['suggestions']))
    unchanged = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
    checker.check('Model-generated suggestions leave entire CURRENT unchanged', unchanged == base)
    if branch == 'COMBINATION':
        # Preserve immutable UPDATE guards. A separately identified stored-data
        # fault appends a conflicting row after a fully valid native C07; this
        # is not a claim the validator accepted incompatible AI output.
        with database.transaction(write=True) as connection:
            faulty = dict(connection.execute('SELECT * FROM suggestions WHERE id=?', (batch['suggestions'][0]['id'],)).fetchone())
            faulty.update(id=entity_id(connection, EntityKind.SUGGESTION), order_no=3)
            connection.execute('INSERT INTO suggestions(' + ','.join(faulty) + ') VALUES (' + ','.join('?' for _ in faulty) + ')', tuple(faulty.values()))
        checker.record['storage_fault'] = 'Explicit duplicate target row appended after valid C07, immutable original rows/triggers retained; not model acceptance evidence'
        batch = (await checker.request(client, 'GET', f'/suggestion-batches/{batch_id}'))['data']
    decisions = ['EDITED', 'ACCEPTED'] if branch == 'APPLY' else ['ACCEPTED', 'EDITED'] if table_branch else ['REJECTED', 'REJECTED'] if branch == 'NOCHANGE' else ['ACCEPTED'] if branch == 'PENDING' else ['ACCEPTED'] * len(batch['suggestions'])
    edited = '审批人为项目负责人。\n'
    for item, decision in zip(batch['suggestions'], decisions):
        body = {'decision': decision}
        if decision == 'EDITED':
            body['edited_content'] = edited
        await checker.request(client, 'PUT', f'/suggestions/{item["id"]}/decision', body=body, key=str(uuid4()))
        actual = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        checker.check('Individual decision does not write CURRENT', actual == base)
    decided = (await checker.request(client, 'GET', f'/suggestion-batches/{batch_id}'))['data']
    checker.check('GET retains exact decided statuses and edited content',
                  [s['status'] for s in decided['suggestions']] == (['ACCEPTED', 'PENDING'] if branch == 'PENDING' else decisions)
                  and decided['suggestions'][0]['user_edited_content'] == (edited if branch == 'APPLY' else None))
    if table_branch:
        checker.check('Second table-batch suggestion retains exact user edited paragraph', decided['suggestions'][1]['user_edited_content'] == edited)
    path = f'/suggestion-batches/{batch_id}/complete'
    if branch in ('VERSIONS', 'STALE', 'TARGET', 'COMBINATION'):
        if branch == 'VERSIONS':
            before = checker.database_facts(database)
            failed = await checker.request(client, 'POST', path, status=409, body={'expected_content_version': 4}, key=str(uuid4()))
            checker.check('Wrong request version rejects without native effect', failed['error']['code'] == 'CONTENT_VERSION_CONFLICT'
                          and before == checker.database_facts(database))
            with database.transaction(write=True) as connection:
                connection.execute("UPDATE requirement_documents SET content_version=4 WHERE requirement_id=? AND document_type='CURRENT'", (req,))
            checker.record['storage_fault'] = 'Explicit out-of-band current version drift after valid C07; no normal DB/public version downgrade'
            variants = (3, 4)
        else:
            variants = (3,)
            if branch == 'STALE':
                with database.transaction(write=True) as connection:
                    changed = base['markdown_content'].replace(replacement['original_content'], '审批人为其他负责人。\n', 1)
                    connection.execute("UPDATE requirement_documents SET markdown_content=? WHERE requirement_id=? AND document_type='CURRENT'", (changed, req))
                checker.record['storage_fault'] = 'Explicit out-of-band original text drift at unchanged version after valid C07; same identities/type/sections retained'
            elif branch == 'TARGET':
                state = deepcopy(base['block_state_json'])
                state['blocks'] = [b for b in state['blocks'] if b['block_id'] != 3]
                changed = base['markdown_content'].replace(replacement['original_content'], '', 1)
                with database.transaction(write=True) as connection:
                    connection.execute("UPDATE requirement_documents SET markdown_content=?,block_state_json=? WHERE requirement_id=? AND document_type='CURRENT'",
                                       (changed, json.dumps(state, ensure_ascii=False), req))
                checker.record['storage_fault'] = 'Explicit out-of-band target identity deletion after valid C07; unchanged content version/high-water, original immutable suggestion retained'

        code = 'CONTENT_VERSION_CONFLICT' if branch == 'VERSIONS' else 'TARGET_STALE' if branch in ('STALE', 'TARGET') else 'PATCH_INVALID'
        for expected_version in variants:
            before = checker.database_facts(database)
            failed = await checker.request(client, 'POST', path, status=422 if code == 'PATCH_INVALID' else 409,
                                           body={'expected_content_version': expected_version}, key=str(uuid4()))
            checker.check(branch + ' returns expected safe error and preserves all actual stored facts/decisions',
                          failed['error']['code'] == code and before == checker.database_facts(database))
        actual = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        checker.check('Refused batch remains PENDING and decisions are retained',
                      (await checker.request(client, 'GET', f'/suggestion-batches/{batch_id}'))['data'] == decided)
        result = await checker.request(client, 'POST', f'/suggestion-batches/{batch_id}/discard', key=str(uuid4()))
        checker.check('Faulted batch can be discarded without body changes', result['data']['batch']['status'] == 'DISCARDED'
                      and (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data'] == actual)
    elif branch == 'PENDING':
        before = checker.database_facts(database)
        failed = await checker.request(client, 'POST', path, status=422,
                                       body={'expected_content_version': 3}, key=str(uuid4()))
        checker.check('Pending completion rejected without partial application or decision loss', failed['error']['code'] == 'BATCH_PENDING'
                      and before == checker.database_facts(database))
        result = await checker.request(client, 'POST', f'/suggestion-batches/{batch_id}/discard', key=str(uuid4()))
        checker.check('Discard terminates batch retaining decisions', result['data']['batch']['status'] == 'DISCARDED')
        actual = (await checker.request(client, 'GET', f'/requirements/{req}/current-document'))['data']
        checker.check('Discard preserves entire CURRENT', actual == base)
        discarded = (await checker.request(client, 'GET', f'/suggestion-batches/{batch_id}'))['data']
        checker.check('Discard retains original suggestion decision records', discarded['suggestions'] == decided['suggestions'])
    else:
        completion_key = str(uuid4())
        result = await checker.request(client, 'POST', path, body={'expected_content_version': 3}, key=completion_key)
        data = result['data']; actual = data['current_document']; metadata = data['batch']
        if branch == 'APPLY' or table_branch:
            # Independent raw text reference, not preview_patches/apply_adoptions.
            expected = base['markdown_content'].replace(replacement['original_content'], edited, 1)
            if branch == 'APPLY':
                expected = expected.replace(deletion['original_content'], '', 1)
            elif branch == 'TABLE_ROW':
                expected = expected.replace('| 原行 | 保留 |\n', '| 原行 | 新值😀 |\n', 1)
            else:
                expected = expected.replace(table_text, table_patch['proposed_markdown'], 1)
            checker.check('Apply edits/deletion exactly once in same CURRENT', actual['id'] == base['id']
                          and actual['content_version'] == 4 and actual['markdown_content'] == expected
                          and metadata['completion_result'] == 'CHANGES_APPLIED' and metadata['applied_content_version'] == 4)
            old_state, new_state = base['block_state_json'], actual['block_state_json']
            checker.check('Deletion removes only target identity; high-water preserved', new_state['next_block_id'] == old_state['next_block_id']
                          and [b['block_id'] for b in new_state['blocks']] == [b['block_id'] for b in old_state['blocks'] if table_branch or b['block_id'] != 5])
            for old in old_state['blocks']:
                if old['block_id'] == 5 and not table_branch:
                    continue
                new = next(b for b in new_state['blocks'] if b['block_id'] == old['block_id'])
                if old['block_id'] == 3:
                    checker.check('Edited replacement attributed to actual user batch while preserving creation',
                                  new['last_modified_by_type'] == 'USER' and new['last_modified_source_type'] == 'SUGGESTION_BATCH'
                                  and new['last_modified_source_id'] == batch_id
                                  and all(new[k] == old[k] for k in ('created_at', 'created_by_type', 'created_source_type', 'created_source_id')))
                elif table_branch and old['block_id'] == table_id:
                    checker.check('Accepted table change preserves creation and is attributed to actual AI batch',
                                  new['last_modified_by_type'] == 'AI' and new['last_modified_source_type'] == 'SUGGESTION_BATCH'
                                  and new['last_modified_source_id'] == batch_id
                                  and all(new[k] == old[k] for k in ('created_at', 'created_by_type', 'created_source_type', 'created_source_id')))
                else:
                    checker.check('Unselected block metadata unchanged ' + str(old['block_id']), new == old)
        else:
            checker.check('All rejected yields NO_CHANGE, null applied version and exact CURRENT', metadata['completion_result'] == 'NO_CHANGE'
                          and metadata['applied_content_version'] is None and actual == base)
        before = checker.database_facts(database); network = (len(chat.receipts), len(counter.server.receipts))
        replay = await checker.request(client, 'POST', path, body={'expected_content_version': 3}, key=completion_key)
        checker.check('Completion replay returns original data/new request ID, no body/network side effect', replay['data'] == data
                      and replay['meta']['request_id'] != result['meta']['request_id']
                      and before == checker.database_facts(database) and network == (len(chat.receipts), len(counter.server.receipts)))
    root = (await checker.request(client, 'GET', f'/requirements/{req}'))['data']
    checker.check('Terminal suggestion branch releases occupancy', root['document_work_state'] == 'IDLE'
                  and root['active_operation_type'] is None and root['active_operation_id'] is None)
    checker.check('Actual producer has only one additional count/Chat attempt', len(chat.receipts) == len(counter.server.receipts) == 2)
    checker.record['actual_local_count_requests'] = len(counter.server.receipts)
    checker.record['actual_local_chat_requests'] = len(chat.receipts)
    checker.record['suggestion_branch'] = branch
    checker.record['tc_e2e_03_coverage'] = 'Independent replacement/deletion/row replacement/whole-table append/apply/no-change/pending/discard and explicit downstream version/text/conflict storage faults; interpret together with the other TC-E2E-03 branch records.'
