"""Real Schema210 state transactions and persistent replay, without any provider."""

from contextlib import contextmanager
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from backend.app.formation.commands import update_state
from backend.app.formation.repository import FormationRepository
from backend.app.formation import state_commands
from backend.app.infrastructure.database import CommitOutcomeUnknown
from backend.app.infrastructure.idempotency import Scope
from backend.app.infrastructure.requirement_repository import RequirementRepository
from backend.tests.formation.test_v21_schema import database, head, released, workspace

__all__ = ['database', 'released', 'workspace']


def payload(workspace, action, **fields):
    with workspace[0].transaction() as connection:
        root = RequirementRepository(connection).get_for_document(1, 1)
    return {
        'requirement_id': 1,
        'document_id': 1,
        'expected_discussion_version': root['discussion_version'],
        'discussion_command': {'type': 'FORMATION', 'action': action, **fields},
        'idempotency_key': str(uuid4()),
    }


def begin(workspace):
    with workspace[0].transaction(write=True) as connection:
        head(connection)


def counts(db):
    with db.transaction() as connection:
        result = {
            table: connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in (
                'conversation_messages',
                'revisions',
                'document_change_audits',
                'formation_event_changes',
                'formation_event_members',
            )
        }
        result['D'] = connection.execute(
            'SELECT discussion_version FROM requirement_documents WHERE id=1'
        ).fetchone()[0]
        row = connection.execute('SELECT * FROM formation_heads WHERE document_id=1').fetchone()
        result['head'] = None if row is None else dict(row)
        result['sequences'] = [
            tuple(row) for row in connection.execute('SELECT * FROM sequences ORDER BY entity_kind')
        ]
        return result


def test_actual_state_commit_replay_and_same_key_changed_input(workspace):
    begin(workspace)
    request = payload(workspace, 'START_STEP', step_ref='s1')
    original = counts(workspace[0])
    result = update_state(workspace[1], request)
    assert result['code'] == 'UPDATED', result
    receipt = result['data']
    assert receipt['processing'] == 'PROGRAM'
    assert receipt['discussion_version'] == original['D'] + 1
    assert receipt['formation_version'] == 2
    assert receipt['content_version'] == 1
    assert receipt['effects'] == {
        'content_changed': False,
        'revision_id': None,
        'formation_changed': True,
        'proposal_disposition': None,
    }
    after = counts(workspace[0])
    assert after['conversation_messages'] == original['conversation_messages'] + 1
    assert after['revisions'] == original['revisions']
    assert update_state(workspace[1], request) == result
    assert counts(workspace[0]) == after
    changed = deepcopy(request)
    changed['discussion_command'] = {'type': 'FORMATION', 'action': 'SWITCH_STEP', 'step_ref': None}
    assert update_state(workspace[1], changed)['code'] == 'IDEMPOTENCY_CONFLICT'
    assert counts(workspace[0]) == after
    with workspace[0].transaction() as connection:
        event = connection.execute(
            'SELECT * FROM document_change_audits WHERE id=?', (receipt['event_ids'][0],)
        ).fetchone()
        public = json.loads(event['payload_json'])['event']
        stored_message = connection.execute(
            'SELECT content FROM conversation_messages WHERE id=?', (receipt['user_message_id'],)
        ).fetchone()[0]
        assert stored_message == '开始步骤：讨论方案'
        assert 'step_ref' not in stored_message
        assert json.loads(event['payload_json'])['command'] == request['discussion_command']
        assert public['actor'] == 'USER'
        assert public['action'] == 'STEP_STARTED'
        assert public['version_after']['formation_version'] == 2
        assert public['version_after']['discussion_version'] == original['D'] + 1
        assert (
            connection.execute('SELECT status FROM formation_steps WHERE document_id=1').fetchone()[
                0
            ]
            == 'IN_PROGRESS'
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM idempotency_records WHERE capability_id='formation.command' AND status='SUCCEEDED'"
            ).fetchone()[0]
            == 1
        )


def test_no_change_saves_only_receipt_without_consuming_business_ids_or_versions(workspace):
    begin(workspace)
    request = payload(workspace, 'SWITCH_STEP', step_ref=None)
    before = counts(workspace[0])
    result = update_state(workspace[1], request)
    assert result['code'] == 'NO_CHANGE', result
    assert result['data']['user_message_id'] is None
    assert result['data']['event_ids'] == []
    assert counts(workspace[0]) == before
    assert update_state(workspace[1], request) == result


def test_audit_failure_rolls_back_state_message_versions_ids_and_claim(workspace, monkeypatch):
    begin(workspace)
    before = counts(workspace[0])
    request = payload(workspace, 'START_STEP', step_ref='s1')
    original = state_commands.record_state_event

    def fail(*args, **kwargs):
        raise RuntimeError('injected audit failure')

    monkeypatch.setattr(state_commands, 'record_state_event', fail)
    assert update_state(workspace[1], request)['code'] == 'INTERNAL_ERROR'
    assert counts(workspace[0]) == before
    with workspace[0].transaction() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM idempotency_records WHERE capability_id='formation.command'"
            ).fetchone()[0]
            == 0
        )
    monkeypatch.setattr(state_commands, 'record_state_event', original)
    assert update_state(workspace[1], request)['code'] == 'UPDATED'


def test_durable_success_replays_after_lost_commit_ack_without_second_effect(
    workspace, monkeypatch
):
    begin(workspace)
    request = payload(workspace, 'START_STEP', step_ref='s1')
    db = workspace[0]
    transaction = db.transaction
    lost = False

    @contextmanager
    def lose_ack(*, write=False):
        nonlocal lost
        committed_success = False
        with transaction(write=write) as connection:
            yield connection
            committed_success = (
                connection.execute(
                    "SELECT 1 FROM idempotency_records WHERE capability_id='formation.command' "
                    "AND idempotency_key=? AND status='SUCCEEDED'",
                    (request['idempotency_key'],),
                ).fetchone()
                is not None
            )
        if write and committed_success and not lost:
            lost = True
            raise CommitOutcomeUnknown('injected lost acknowledgment after durable commit')

    monkeypatch.setattr(db, 'transaction', lose_ack)
    assert update_state(workspace[1], request)['code'] == 'STORAGE_UNAVAILABLE'
    after = counts(db)
    result = update_state(workspace[1], request)
    assert result['code'] == 'UPDATED', result
    assert counts(db) == after
    assert after['D'] == request['expected_discussion_version'] + 1


def test_missing_head_and_stale_discussion_are_rejected_without_creating_anything(workspace):
    request = payload(workspace, 'SWITCH_STEP', step_ref=None)
    result = update_state(workspace[1], request)
    assert result['code'] == 'STATE_CONFLICT'
    assert result['details']['reason'] == 'FORMATION_NOT_INITIALIZED'
    before = counts(workspace[0])
    begin(workspace)
    stale = {**request, 'expected_discussion_version': 100}
    result = update_state(workspace[1], stale)
    assert result['code'] == 'DISCUSSION_VERSION_CONFLICT'
    assert counts(workspace[0])['conversation_messages'] == before['conversation_messages']


def test_summary_false_uses_same_keys_and_real_counts_are_not_page_counts(workspace):
    db = workspace[0]
    with db.transaction() as connection:
        absent = FormationRepository(connection).summary(1)
    assert absent['exists'] is False
    assert absent['formation_version'] is absent['goal'] is None
    assert absent['counts']['steps'] == {
        'PLANNED': 0,
        'IN_PROGRESS': 0,
        'PAUSED': 0,
        'COMPLETED': 0,
        'CANCELLED': 0,
    }
    begin(workspace)
    with db.transaction() as connection:
        present = FormationRepository(connection).summary(1)
    assert present.keys() == absent.keys()
    assert present['exists'] is True
    assert present['counts']['steps']['PLANNED'] == 1
    assert present['current_step_ref'] is None


def test_scope_allows_only_the_three_registered_formation_capabilities():
    for capability in ('formation.command', 'formation.discuss', 'formation.card.apply'):
        assert Scope(capability, 'document:1', str(uuid4())).capability_id == capability
    with pytest.raises(ValueError):
        Scope('formation.arbitrary', 'document:1', str(uuid4()))
