"""Synthetic EV fixtures: fresh Schema210 only, normal editing and C01 compilation.

SQL creates explicitly declared historical preconditions; it is not evidence that
those historical commands/model calls ran. No user database or credentials.
"""

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from formation_evaluation_spec import BASE_BODY, EDITED_FIRST, FIXED_TIME, INITIAL_IDEA

from backend.app.documents.commands import (
    complete_manual_draft,
    create_document,
    save_manual_draft,
    start_manual_draft,
)
from backend.app.documents.snapshot import Provenance, assign_identities, validate_snapshot
from backend.app.documents.sources import DocumentSources
from backend.app.formation.artifact_links import create_links, verify_links
from backend.app.formation.commands import complete_step
from backend.app.guide.collaboration_context import compile_context, read_canonical
from backend.app.guide.commands import create_guide_run
from backend.app.infrastructure.formation_database import FormationDatabase
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.app.requirements.commands import create_requirement


def clock():
    return datetime.fromisoformat(FIXED_TIME.replace('Z', '+00:00')).astimezone(timezone.utc)


def key(label):
    return str(
        UUID(bytes=sha256(('walle/formation-ev60-1/' + label).encode()).digest()[:16], version=4)
    )


def checked(result, code):
    if result['code'] != code:
        raise RuntimeError(f'EV fixture expected {code}, got {result["code"]}')
    return result['data']


def sequence(connection, kind, previous):
    connection.execute(
        'INSERT INTO sequences(entity_kind,last_value) VALUES(?,?) '
        'ON CONFLICT(entity_kind) DO UPDATE SET last_value=excluded.last_value',
        (kind, previous),
    )


def edit(database, executor, catalog, label, markdown, identities):
    with database.transaction() as connection:
        version = connection.execute(
            'SELECT content_version FROM requirement_documents WHERE id=42'
        ).fetchone()[0]
    draft = checked(
        start_manual_draft(
            executor,
            {
                'requirement_id': 7,
                'document_id': 42,
                'expected_version': version,
                'idempotency_key': key(label + '/start'),
            },
            catalog=catalog,
            clock=clock,
        ),
        'DRAFT_STARTED',
    )['manual_draft']
    with database.transaction() as connection:
        sources = DocumentSources(connection, 7, catalog, document_id=42)
        prior = validate_snapshot(draft['markdown_content'], draft['block_state_json'], sources)
        high = max([prior.next_block_id, *(identity + 1 for identity in identities)])
        candidate = assign_identities(
            markdown,
            identities,
            high,
            prior,
            Provenance('USER', 'MANUAL_EDIT', draft['id']),
            FIXED_TIME,
            sources,
        )
    saved = checked(
        save_manual_draft(
            executor,
            {
                'requirement_id': 7,
                'document_id': 42,
                'draft_id': draft['id'],
                'expected_version': draft['content_version'],
                'markdown_content': markdown,
                'block_state_json': candidate.state,
                'idempotency_key': key(label + '/save'),
            },
            catalog=catalog,
            clock=clock,
        ),
        'DRAFT_SAVED',
    )
    checked(
        complete_manual_draft(
            executor,
            {
                'requirement_id': 7,
                'document_id': 42,
                'draft_id': draft['id'],
                'expected_version': saved['content_version'],
                'idempotency_key': key(label + '/finish'),
            },
            catalog=catalog,
            clock=clock,
        ),
        'DRAFT_COMPLETED',
    )


def seed(database, executor, catalog, sample):
    with database.transaction(write=True) as connection:
        sequence(connection, 'Requirement', 6)
        sequence(connection, 'RequirementDocument', 41)
        sequence(connection, 'Revision', 100 if sample.body == 'blank' else 397)
    checked(
        create_requirement(
            executor,
            {
                'title': '个人电影推荐方案',
                'requirement_type': 'NEW',
                'initial_idea': INITIAL_IDEA
                + (' 好友可帮忙推荐，先讨论是否纳入。' if sample.related_branch else ''),
                'idempotency_key': key('requirement'),
            },
            catalog=catalog,
            clock=clock,
        ),
        'CREATED',
    )
    checked(
        create_document(
            executor,
            {
                'requirement_id': 7,
                'name': '个人电影推荐方案',
                'document_kind': 'DESIGN',
                'template_ref': None,
                'idempotency_key': key('document'),
            },
            catalog=catalog,
            clock=clock,
        ),
        'CREATED',
    )
    if sample.body == 'fbase':
        edit(database, executor, catalog, 'v2', '准备讨论推荐需求。\n', [10])
        edit(database, executor, catalog, 'v3', '用户选择影片，系统给出推荐。\n', [11])
        edit(database, executor, catalog, 'v4', BASE_BODY, [12, 13])
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO formation_heads VALUES(42,12,1,?,\'[{"kind":"MESSAGE","message_id":1}]\',\'s2\',NULL,4,5,3,1)',
            ('形成个人电影推荐方案',),
        )
        connection.executemany(
            'INSERT INTO formation_steps VALUES(42,?,1,?,?,?, ?,NULL)',
            [
                ('s1', 2, 1, '明确目标', 'COMPLETED'),
                ('s2', 3, 2, '推荐流程与范围判断', 'IN_PROGRESS'),
                ('s3', 2, 3, '核对异常与验收', 'PLANNED'),
            ],
        )
        connection.executemany(
            'INSERT INTO formation_results VALUES(42,?,?,?,?)',
            [
                ('s1', 's1.o1', '明确首版目标', 'ANALYSIS'),
                ('s2', 's2.o1', '推荐流程', 'CONTENT'),
                ('s2', 's2.o2', '范围判断', 'ANALYSIS'),
                ('s3', 's3.o1', '异常与验收说明', 'CONTENT'),
            ],
        )
        connection.executemany(
            'INSERT INTO formation_step_edges VALUES(42,?,?,?)',
            [
                ('s2', 's1', 'DEPENDENCY'),
                ('s3', 's2', 'DEPENDENCY'),
            ],
        )
        connection.execute(
            'INSERT INTO document_change_audits(id,requirement_id,document_id,source_type,source_id,reason_code,'
            'before_content_version,after_content_version,created_at,event_type,revision_id,guide_run_id,payload_json)'
            " VALUES(900,7,42,'USER_ACTION',1,'CONTENT_ASSOCIATED',NULL,NULL,?,'DISCUSSION_UPDATED',NULL,NULL,?)",
            (
                FIXED_TIME,
                json.dumps(
                    {
                        'formation_event_type': 'CONTENT_ASSOCIATED',
                        'source_refs': [{'kind': 'MESSAGE', 'message_id': 1}],
                    }
                ),
            ),
        )
        if sample.related_branch:
            connection.execute(
                "INSERT INTO formation_branches VALUES(42,'b4','s1','s2',?,?,'OPEN',900,900,NULL,'[]',NULL)",
                ('好友可帮忙推荐，是否纳入首版范围', '影响s2推荐流程和范围判断'),
            )
        connection.executemany(
            'INSERT INTO formation_issues VALUES(42,?,?,?,?,?,0,?,?,?,NULL)',
            [
                (
                    'i1',
                    's2',
                    'b4' if sample.related_branch else None,
                    '好友可帮忙推荐，是否纳入首版范围'
                    if sample.related_branch
                    else '推荐失败与无候选时的处理',
                    '[{"kind":"MESSAGE","message_id":1}]',
                    'OPEN',
                    None,
                    '[]',
                ),
                (
                    'i2',
                    's2',
                    None,
                    '首版是否纳入跨设备同步',
                    '[{"kind":"MESSAGE","message_id":1}]',
                    'DEFERRED',
                    '本轮先聚焦推荐流程',
                    '[]',
                ),
            ],
        )
        if sample.body == 'fbase':
            root = RequirementRepository(connection).get_for_document(7, 42)
            verified = verify_links(
                connection,
                root,
                [
                    {
                        'step_ref': 's2',
                        'result_refs': ['s2.o1'],
                        'revision_id': 401,
                        'block_ids': [12],
                    }
                ],
                catalog,
            )
            create_links(connection, 42, verified, [900], {'s2': '已有推荐流程'})
        connection.execute('UPDATE requirement_documents SET discussion_version=30 WHERE id=42')
        sequence(connection, 'DocumentChangeAudit', 900)
        # Setup command receipts are immutable and retained. The EV C01 key is fresh.
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('EV fixture foreign-key violation')
    closure = None
    if sample.closed:
        completed = checked(
            complete_step(
                executor,
                {
                    'requirement_id': 7,
                    'document_id': 42,
                    'expected_discussion_version': 30,
                    'discussion_command': {
                        'type': 'FORMATION',
                        'action': 'COMPLETE_STEP',
                        'step_ref': 's2',
                        'expected_definition_version': 1,
                        'expected_goal_version': 1,
                        'expected_content_version': 1 if sample.body == 'blank' else 4,
                        'result_dispositions': [],
                        'issue_dispositions': [],
                        'branch_dispositions': [],
                        'next_step_ref': None,
                    },
                    'idempotency_key': key('closed-step'),
                },
                catalog=catalog,
                clock=clock,
            ),
            'UPDATED',
        )
        event = completed['event_ids'][0]
        with database.transaction() as connection:
            closure = closure_digest(connection, event)
    if sample.edited:
        markdown = EDITED_FIRST + '。\n\n用户可提交反馈。\n'
        # Blank variant gains its first real blocks; the others keep IDs 12/13.
        edit(database, executor, catalog, 'review-edit', markdown, [12, 13])
    return closure


def closure_digest(connection, event):
    rows = {
        name: [
            tuple(row)
            for row in connection.execute(
                'SELECT * FROM ' + name + ' WHERE event_id=? ORDER BY rowid', (event,)
            )
        ]
        for name in ('formation_closures', 'formation_closure_items', 'formation_closure_evidence')
    }
    return sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()


def prepare_sample(directory, catalog, sample):
    from backend.app.infrastructure.formation_schema_release import load_release

    database = FormationDatabase(Path(directory) / 'input.sqlite', formation_release=load_release())
    database.initialize()
    with ProcessLock.for_database(database.path) as lock:
        executor = Idempotency(database, lock)
        original_closure = seed(database, executor, catalog, sample)
        with database.transaction() as connection:
            document = dict(
                connection.execute('SELECT * FROM requirement_documents WHERE id=42').fetchone()
            )
            revision = connection.execute(
                'SELECT id FROM revisions WHERE document_id=42 AND source_content_version=?',
                (document['content_version'],),
            ).fetchone()[0]
        body = {
            'requirement_id': 7,
            'document_id': 42,
            'expected_discussion_version': document['discussion_version'],
            'operation': 'DISCUSS',
            'instruction': sample.instruction,
            'target': {
                'discussion_step_ref': 's2',
                'discussion_branch_ref': None,
                'branch_intent': None,
                'branch_resume_basis': None,
            },
            'scope': None,
            'source_refs': [],
            'proposal_ref': None,
            'proposal_intent': None,
            'acknowledge_source_changes': False,
            'idempotency_key': key(sample.sample_id),
        }
        accepted = checked(
            create_guide_run(executor, body, catalog=catalog, clock=clock), 'GUIDE_ACCEPTED'
        )
        with database.transaction() as connection:
            canonical = read_canonical(connection, accepted['guide_run_id'], catalog)
            if original_closure is not None:
                event = connection.execute(
                    "SELECT closure_event_id FROM formation_steps WHERE document_id=42 AND step_ref='s2'"
                ).fetchone()[0]
                if closure_digest(connection, event) != original_closure:
                    raise RuntimeError('EV edit/discussion rewrote the original Closure')
            if connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] != 0:
                raise RuntimeError('Preparation must not record a model attempt')
            if connection.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('EV prepared-input foreign-key violation')
        expected_version = (1 if sample.body == 'blank' else 4) + int(sample.edited)
        expected_revision = (101 if sample.body == 'blank' else 401) + int(sample.edited)
        if (document['content_version'], revision) != (expected_version, expected_revision):
            raise RuntimeError('EV V/Revision differs from the declared fixture')
        context = compile_context(canonical, catalog)
        formation = context.input['project_position']['formation']
        if formation['selected_step']['step_ref'] != 's2' or formation['goal']['version'] != 1:
            raise RuntimeError('EV selected step/Goal differs')
        if formation['selected_step']['status'] != (
            'COMPLETED' if sample.closed else 'IN_PROGRESS'
        ):
            raise RuntimeError('EV discussion changed an ended step lifecycle')
        expected_blocks = [] if sample.body == 'blank' and not sample.edited else [12, 13]
        blocks = [
            block['block_id']
            for value in context.input['documents']
            if value['document_id'] == 42
            for block in value['blocks']
        ]
        if blocks != expected_blocks:
            raise RuntimeError('EV actual Wire blocks differ from the declared fixture')
        branches = [item for item in formation['coverage']['included'] if item['kind'] == 'BRANCH']
        if bool(branches) != sample.related_branch:
            raise RuntimeError('EV existing-branch variant differs')
        artifacts = formation['artifacts']
        if sample.body == 'blank' and artifacts:
            raise RuntimeError('EV blank fixture cannot have fabricated landed content')
        if sample.body == 'fbase':
            if len(artifacts) != 1 or artifacts[0]['freshness'] != (
                'NEEDS_REVIEW' if sample.edited else 'CURRENT'
            ):
                raise RuntimeError('EV artifact freshness differs from the actual edit')
        if 'i2' not in context.input_json:
            raise RuntimeError('EV deferred decision source is missing; never pretend it was read')

        if (
            context.canonical['operation'] != 'DISCUSS'
            or context.input['current_request']['content'] != sample.instruction
        ):
            raise RuntimeError('EV operation was not preserved')
        return context, {
            'content_version': document['content_version'],
            'revision_id': revision,
            'edited': sample.edited,
            'closed': sample.closed,
            'related_branch': sample.related_branch,
        }
