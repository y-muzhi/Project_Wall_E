"""Original Guard mutation intent/ACK IO ports, never Native dispatch/admission."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_action_journal as actions
from backend.app.infrastructure import guard_action_records as records
from backend.app.infrastructure.guard_request_header import PROTOCOL, _parse
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.tests.infrastructure.test_v20_guard_recovery import facts
from backend.tests.infrastructure.test_v20_runtime_launch_journal import journal
from backend.tests.requirements.test_v15_foundation import tmp_path


def packet(binding=None, *, action='PREPARE', binding_ref=None, number=17, action_input=None):
    binding = facts()[0].binding if binding is None else binding
    return _parse(
        {
            'protocol_version': PROTOCOL,
            'action': action,
            'controller_ref': binding.controller_ref,
            'owner_epoch': binding.owner_epoch,
            'operation_id': number,
            'step_no': 1,
            'nonce': 'original-guard-action-nonce-0001',
            'binding_ref': binding_ref,
            'input': {'command_ref': 'TEST_ONLY_VERSION_PORT'}
            if action_input is None
            else action_input,
        },
        binding,
    )


@pytest.fixture
def context(journal):
    binding = facts()[0].binding
    request = packet(binding)
    store = actions.GuardActionJournal(journal)
    return store, journal, binding, request


def acknowledged_prepare(context):
    store, journal, binding, request = context
    start = store.begin(request)
    result = {'binding_ref': start.record.allocated_binding_ref, 'fixture': 'FACTS_ONLY_PORT'}
    return store.acknowledge(start.record, result)


def test_original_preparation_intent_precedes_any_allocation_and_repeat_never_grants_redispatch(
    context,
):
    store, journal, _, request = context
    first = store.begin(request)
    assert first.first_accepted
    assert first.record.phase == 'MAY_HAVE_BEEN_SENT'
    assert len(first.record.allocated_binding_ref) == 32
    assert len(first.record.directory_nonce) == 32
    assert not first.record.result
    assert journal.inspect(request.scope) is None
    assert not list(journal.root.glob('control-git-*'))
    repeat = store.begin(request)
    assert not repeat.first_accepted and repeat.record == first.record
    assert len(list(journal.root.glob('*.guard-action.json'))) == 1
    assert first.record.requested_by_controller_ref == request.scope.controller_ref


def test_ack_is_immutable_original_binding_and_result_returns_detached_snapshots(context):
    store, _, _, request = context
    first = store.begin(request)
    result = {'binding_ref': first.record.allocated_binding_ref, 'facts': {'count': 1}}
    completed = store.acknowledge(first.record, result)
    result['facts']['count'] = 2
    copied = completed.result
    copied['facts']['count'] = 3
    assert completed.result['facts']['count'] == 1
    assert not store.begin(request).first_accepted
    assert store.acknowledge(first.record, completed.result) == completed
    with pytest.raises(records.GuardActionError, match='RESULT_CONFLICT'):
        store.acknowledge(
            first.record, {'binding_ref': completed.result['binding_ref'], 'facts': {'count': 9}}
        )


def test_same_domain_different_input_never_changes_original_intent_or_allocation_refs(context):
    store, _, binding, request = context
    first = store.begin(request)
    with pytest.raises(records.GuardActionError, match='INPUT_CONFLICT'):
        store.begin(packet(binding, action_input={'command_ref': 'OTHER_REGISTERED_PORT'}))
    assert store.find(request.scope, request.action) == first.record


def test_concurrent_identical_begin_has_one_original_allocation_permission(context):
    store, _, _, request = context
    with ThreadPoolExecutor(max_workers=4) as executor:
        started = tuple(executor.map(lambda _: store.begin(request), range(8)))
    assert sum(item.first_accepted for item in started) == 1
    assert len({item.record.directory_nonce for item in started}) == 1
    assert len({item.record.allocated_binding_ref for item in started}) == 1


def test_lost_begin_ack_observes_original_may_record_and_does_not_reserve_replacement(context):
    store, _, _, request = context
    actual_replace = actions.os.replace

    def lost(source, target):
        actual_replace(source, target)
        raise OSError('Injected after exact metadata rename')

    with patch.object(actions.os, 'replace', lost):
        with pytest.raises(records.GuardActionError, match='SAVE_UNVERIFIED'):
            store.begin(request)
    observed = store.find(request.scope, request.action)
    assert observed.phase == 'MAY_HAVE_BEEN_SENT'
    replay = store.begin(request)
    assert not replay.first_accepted and replay.record == observed


def test_failed_ack_save_preserves_complete_original_bytes_and_leaves_no_stage(context):
    store, journal, _, request = context
    first = store.begin(request)
    path = store._path(request.scope, request.action)
    original = path.read_bytes()
    with patch.object(actions.os, 'fsync', side_effect=OSError('Injected flush failure')):
        with pytest.raises(records.GuardActionError, match='SAVE_UNVERIFIED'):
            store.acknowledge(first.record, {'binding_ref': first.record.allocated_binding_ref})
    assert path.read_bytes() == original
    assert not list(journal.root.glob('.guard-action-*'))
    assert store.find(request.scope, request.action).phase == 'MAY_HAVE_BEEN_SENT'


def test_create_resume_stop_and_release_keep_original_preparation_and_launch_fences(context):
    store, journal, binding, request = context
    prepared = acknowledged_prepare(context)
    reference = prepared.allocated_binding_ref
    journal.prepare(request.scope, 'b' * 64)
    create = packet(binding, action='CREATE_SUSPENDED', binding_ref=reference, action_input={})
    start = store.begin(create)
    native_calls = []
    journal.dispatch_create(
        request.scope,
        'b' * 64,
        lambda: native_calls.append('create') or 'original-root-resource-001',
    )
    store.acknowledge(
        start.record, {'binding_ref': reference, 'resource_ref': 'original-root-resource-001'}
    )
    resume = packet(binding, action='RESUME', binding_ref=reference, action_input={})
    resume_start = store.begin(resume)
    journal.dispatch_resume(
        request.scope, 'original-root-resource-001', lambda: native_calls.append('resume')
    )
    store.acknowledge(resume_start.record, {'binding_ref': reference, 'fixture': 'RESUME_PORT'})
    stop = packet(binding, action='STOP', binding_ref=reference, action_input={})
    stop_start = store.begin(stop)
    journal.close_nonce(request.scope)
    store.acknowledge(stop_start.record, {'binding_ref': reference, 'fixture': 'CLOSED_PORT'})
    release = packet(binding, action='RELEASE', binding_ref=reference, action_input={})
    release_start = store.begin(release)
    store.acknowledge(release_start.record, {'binding_ref': reference, 'fixture': 'RELEASE_PORT'})
    for original in (request, create, resume, stop, release):
        replay = store.begin(original)
        assert not replay.first_accepted
        assert replay.record.phase == 'ACKNOWLEDGED'
    assert native_calls == ['create', 'resume']  # Explicit ports, no actual Native API.


def test_missing_original_prepare_or_native_fence_cannot_be_backfilled(context):
    store, journal, binding, request = context
    journal.prepare(request.scope, 'b' * 64)
    with pytest.raises(records.GuardActionError, match='PREPARATION_INTENT_MISSING'):
        store.begin(request)
    create = packet(
        binding, action='CREATE_SUSPENDED', binding_ref='original-binding-ref-001', action_input={}
    )
    with pytest.raises(records.GuardActionError, match='PREPARATION_UNVERIFIED'):
        store.begin(create)


def test_prepare_may_is_not_prepare_ack_and_release_needs_original_stop_closure(context):
    store, journal, binding, request = context
    first = store.begin(request)
    reference = first.record.allocated_binding_ref
    journal.prepare(request.scope, 'b' * 64)
    with pytest.raises(records.GuardActionError, match='PREPARATION_UNVERIFIED'):
        store.begin(
            packet(binding, action='CREATE_SUSPENDED', binding_ref=reference, action_input={})
        )
    with pytest.raises(records.GuardActionError, match='STOP_CLOSURE_REQUIRED'):
        store.begin(packet(binding, action='RELEASE', binding_ref=reference, action_input={}))
    journal.close_nonce(request.scope)
    assert store.begin(
        packet(binding, action='RELEASE', binding_ref=reference, action_input={})
    ).first_accepted


def test_capacity_and_unknown_queries_do_not_allocate_record_or_directory(context, monkeypatch):
    store, journal, binding, request = context
    monkeypatch.setattr(actions, 'MAX_ACTION_RECORDS', 1)
    store.begin(request)
    with pytest.raises(records.GuardActionError, match='CAPACITY'):
        store.begin(packet(binding, number=18))
    with pytest.raises(records.GuardActionError, match='MUTATION_REQUIRED'):
        store.find(request.scope, 'OBSERVE')
    assert len(list(journal.root.glob('*.guard-action.json'))) == 1
    assert not list(journal.root.glob('control-git-*'))


def test_ack_cannot_rebind_original_resource_or_stale_mutation_identity(context):
    store, _, _, request = context
    first = store.begin(request)
    with pytest.raises(records.GuardActionError, match='RESULT_BINDING_DIFFERS'):
        store.acknowledge(first.record, {'binding_ref': 'other-binding-ref-0001'})
    with pytest.raises(records.GuardActionError, match='RECORD_DIFFERS'):
        store.acknowledge(
            replace(first.record, input_sha256='f' * 64),
            {'binding_ref': first.record.allocated_binding_ref},
        )
    assert store.find(request.scope, request.action) == first.record


@pytest.mark.parametrize('action', ['STOP', 'RELEASE'])
def test_new_caller_header_keeps_same_original_mutation_digest(
    action,
):
    original, new_caller, _ = facts()
    source = packet(
        original.binding, action=action, binding_ref='original-binding-ref-001', action_input={}
    )
    recovery = packet(
        new_caller.binding,
        action=action,
        binding_ref=source.binding_ref,
        action_input={
            'recovery': {
                'controller_ref': original.binding.controller_ref,
                'owner_epoch': original.binding.owner_epoch,
            },
        },
    )
    assert source.target_scope == recovery.target_scope
    assert source.scope != recovery.scope
    assert records.mutation_input_sha256(source) == records.mutation_input_sha256(recovery)


@pytest.mark.parametrize(
    'change',
    [
        lambda value: value.update(schema_version=True),
        lambda value: value.update(revision=True),
        lambda value: value.update(phase='SUCCESS'),
        lambda value: value.update(result_json='{}'),
        lambda value: value.update(directory_nonce='0' * 32),
        lambda value: value.update(allocated_binding_ref=None),
        lambda value: value.update(extra='not original'),
        lambda value: value.update(updated_at='2026-02-31T00:00:00.000Z'),
    ],
)
def test_strict_mutation_record_rejects_corrupt_noncanonical_or_unverifiable_state(context, change):
    store, _, _, request = context
    first = store.begin(request)
    value = asdict(first.record)
    change(value)
    with pytest.raises((RuntimeError, ValueError)):
        records.decode_action_record(_bytes(value), request.scope, request.action)


def test_result_capacity_is_bounded_without_overwriting_original_pending_state(context):
    store, _, _, request = context
    first = store.begin(request)
    with pytest.raises(records.GuardActionError, match='RESULT_CAPACITY'):
        store.acknowledge(
            first.record,
            {'binding_ref': first.record.allocated_binding_ref, 'too_large': 'x' * 17000},
        )
    assert store.find(request.scope, request.action) == first.record


def test_recovery_header_reuses_original_effect_record_without_overwriting_first_caller(context):
    store, _, original_binding, _ = context
    source = packet(original_binding, action='STOP', action_input={})
    first = store.begin(source)
    new_binding = replace(original_binding, owner_epoch=str(uuid4()))
    restored = packet(
        new_binding,
        action='STOP',
        action_input={
            'recovery': {
                'controller_ref': original_binding.controller_ref,
                'owner_epoch': original_binding.owner_epoch,
            },
        },
    )
    replay = store.begin(restored)
    assert not replay.first_accepted and replay.record == first.record
    assert replay.record.scope == source.scope
    assert replay.record.requested_by_controller_ref == original_binding.controller_ref
    assert replay.record.requested_by_owner_epoch == original_binding.owner_epoch
