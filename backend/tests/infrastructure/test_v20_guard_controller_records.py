"""Actual CLIENT registrations in an original private Guard root; not program admission."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_controller_records as records
from backend.app.infrastructure.guard_controller_binding import (
    GuardBindingError,
    bind_guard_controller,
)
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, _bytes
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.test_v20_windows_pipe_peer import connection, peer
from backend.tests.requirements.test_v15_foundation import tmp_path

pytestmark = pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
PROGRAM_REF = 'BACKEND-PACKAGE20-REGISTERED'
PACKAGE_SHA = 'd' * 64


@pytest.fixture
def context(connection, tmp_path):
    root = create_private_package(tmp_path / 'controller-records')
    with (
        peer(connection) as actual,
        LaunchJournal(root) as journal,
        records.GuardControllerRecords(journal) as store,
    ):
        binding = bind_guard_controller(actual, str(uuid4()), 'a' * 64)
        yield SimpleNamespace(
            peer=actual,
            journal=journal,
            store=store,
            binding=binding,
            root=root,
            original=connection,
        )


def register(context, **changed):
    return context.store.record_peer_facts(
        context.binding,
        peer=context.peer,
        **{'backend_program_ref': PROGRAM_REF, 'backend_package_sha256': PACKAGE_SHA, **changed},
    )


def test_original_actual_peer_and_image_are_immutable_private_registration_before_launch(context):
    result = register(context)
    assert result.binding == context.binding
    assert result.image == context.peer._program.verify()
    assert result.backend_program_ref == PROGRAM_REF
    assert result.backend_package_sha256 == PACKAGE_SHA
    filename = context.binding.controller_ref + '.controller.json'
    raw = (context.root / filename).read_bytes()
    assert raw == _bytes(result.facts)
    assert not list(context.root.glob('*.launch.json'))
    assert context.journal._package.verify_member(filename, directory=False).is_directory is False
    with patch.object(
        records, 'PrivateRecordAppend', side_effect=AssertionError('No duplicate write')
    ):
        assert register(context) == result
    assert not hasattr(result, 'admitted')
    assert not hasattr(result, 'recovery_authorized')


def test_serialized_peer_claim_cannot_produce_original_registration(context):
    with pytest.raises(GuardBindingError):
        context.store.record_peer_facts(
            context.binding,
            peer={'pid': context.binding.controller.pid},
            backend_program_ref=PROGRAM_REF,
            backend_package_sha256=PACKAGE_SHA,
        )
    assert not list(context.root.glob('*.controller.json'))


@pytest.mark.parametrize(
    'changed',
    [
        {'backend_program_ref': 'OTHER-REGISTERED-PROGRAM'},
        {'backend_package_sha256': 'e' * 64},
    ],
)
def test_existing_controller_program_or_package_cannot_be_rebound(context, changed):
    original = register(context)
    with pytest.raises(records.ControllerRecordError, match='REGISTRATION_CONFLICT'):
        register(context, **changed)
    assert (
        context.store.read(context.binding.controller_ref, context.binding.owner_epoch) == original
    )


def test_missing_controller_record_does_not_create_or_attest_old_owner(context):
    with pytest.raises(records.ControllerRecordError, match='RECORD_MISSING'):
        context.store.read(context.binding.controller_ref, context.binding.owner_epoch)
    assert not list(context.root.glob('*.controller.json'))


@pytest.mark.parametrize('stopped', [False, True])
def test_absent_controller_registration_cannot_be_backfilled_after_original_launch_history(
    context, stopped
):
    target = context.binding.scope(17, 2, 'original-controller-record-nonce-001')
    if stopped:
        context.journal.close_nonce(target)
    else:
        context.journal.prepare(target, 'b' * 64)
    with pytest.raises(records.ControllerRecordError, match='CANNOT_ATTEST_PRIOR_LAUNCH'):
        register(context)
    assert not list(context.root.glob('*.controller.json'))
    assert context.journal.inspect(target).stop_closed == stopped


def test_registration_requires_quiet_original_journal_before_any_scope_producer(context):
    scope = context.binding.scope(17, 2, 'original-controller-record-nonce-001')
    with context.journal._scope(scope):
        with pytest.raises(records.ControllerRecordError, match='QUIET_JOURNAL'):
            register(context)
    assert register(context).binding == context.binding


def test_another_registered_controller_history_does_not_attest_or_rewrite_this_controller(context):
    other = replace(context.binding, owner_epoch=str(uuid4()))
    target = other.scope(17, 2, 'original-controller-record-nonce-001')
    context.journal.close_nonce(target)
    with context.journal._scope(target):
        assert register(context).binding == context.binding
    assert context.journal.inspect(target).scope.controller_ref == other.controller_ref


@pytest.mark.parametrize(
    'mutation',
    [
        lambda value: value.update(schema_version=True),
        lambda value: value.update(extra='not original'),
        lambda value: value['binding']['controller'].update(pid=True),
        lambda value: value['binding']['controller'].update(is_elevated=0),
        lambda value: value['binding']['controller'].update(is_lpac=None),
        lambda value: value['image'].update(byte_count=True),
        lambda value: value['image']['file'].update(is_directory=0),
        lambda value: value['image'].update(architecture='AMD64'),
        lambda value: value.update(registered_at='2026-02-31T00:00:00.000Z'),
    ],
)
def test_persisted_registration_rejects_noncanonical_or_conflicting_native_facts(context, mutation):
    result = register(context)
    value = result.facts
    mutation(value)
    with pytest.raises((records.ControllerRecordError, ValueError, RuntimeError)):
        records.decode_controller_registration(
            _bytes(value), context.binding.controller_ref, context.binding.owner_epoch
        )


def test_old_epoch_or_controller_reference_cannot_read_another_original_registration(context):
    result = register(context)
    with pytest.raises(records.ControllerRecordError, match='BINDING_DIFFERS'):
        records.decode_controller_registration(
            _bytes(result.facts), context.binding.controller_ref, str(uuid4())
        )
    with pytest.raises(records.ControllerRecordError, match='BINDING_DIFFERS'):
        records.decode_controller_registration(
            _bytes(result.facts), 'b' * 64, context.binding.owner_epoch
        )


def test_registration_survives_guard_journal_restart_without_reopening_any_process(context):
    result = register(context)
    target = context.binding.scope(17, 2, 'original-controller-record-nonce-001')
    context.journal.prepare(target, 'b' * 64)
    context.store.close()
    context.journal.close()
    with patch(
        'backend.app.infrastructure.windows_process.ObservedProcess',
        side_effect=AssertionError('No PID reopen'),
    ):
        with (
            LaunchJournal(context.root) as restarted,
            records.GuardControllerRecords(restarted) as store,
        ):
            assert store.read(context.binding.controller_ref, context.binding.owner_epoch) == result
            assert restarted.inspect(target).stop_closed


def test_actual_old_controller_exit_does_not_destroy_registration_or_allow_new_attestation(context):
    result = register(context)
    context.original.job.terminate_owned(1)
    actual = context.original.process
    assert actual._kernel.WaitForSingleObject(actual._handle, 8000) == 0
    assert context.store.read(context.binding.controller_ref, context.binding.owner_epoch) == result
    with pytest.raises(RuntimeError):
        register(context)


def test_unknown_ack_reconciles_same_original_record_without_publish_retry(context):
    publish = records.PrivateRecordAppend.publish

    def lost(writer):
        publish(writer)
        raise OSError('Injected lost original publication acknowledgement')

    with patch.object(records.PrivateRecordAppend, 'publish', lost):
        with pytest.raises(records.ControllerRecordError, match='PUBLISH_UNVERIFIED') as error:
            register(context)
    assert error.value.retained_owner is context.store
    with pytest.raises(records.ControllerRecordError, match='REQUIRES_OBSERVATION'):
        register(context)
    with patch.object(
        records.PrivateRecordAppend, 'publish', side_effect=AssertionError('No publication retry')
    ):
        resolved = context.store.reconcile_pending()
        assert len(resolved) == 1
        assert register(context) == resolved[0]
    assert len(list(context.root.glob('*.controller.json'))) == 1


def test_registration_store_close_forbids_new_records_but_keeps_static_evidence(context):
    result = register(context)
    context.store.close()
    with pytest.raises(records.ControllerRecordError, match='REQUIRES_OBSERVATION'):
        register(context)
    assert context.store.read(context.binding.controller_ref, context.binding.owner_epoch) == result


def test_orphan_private_native_history_also_forbids_retroactive_controller_attestation(context):
    from dataclasses import asdict

    scope = context.binding.scope(17, 2, 'original-controller-record-nonce-001')
    name = scope.key + '.' + uuid4().hex + '.native.json'
    # A prior native receipt with a missing launch fence must remain unknown;
    # it is never used here as permission or as a reconstructed resource.
    with records.PrivateRecordAppend(
        context.journal._package,
        name,
        _bytes({'scope': asdict(scope)}),
        max_record_bytes=65536,
    ) as writer:
        writer.publish()
    with pytest.raises(records.ControllerRecordError, match='CANNOT_ATTEST_PRIOR_LAUNCH'):
        register(context)
    assert not list(context.root.glob('*.controller.json'))


def test_controller_record_capacity_does_not_publish_partial_registration(context, monkeypatch):
    monkeypatch.setattr(records, 'MAX_CONTROLLER_RECORDS', 0)
    with pytest.raises(records.ControllerRecordError, match='CAPACITY'):
        register(context)
    assert not list(context.root.glob('*.controller.json'))
    assert not list(context.root.glob('.record-*'))


@pytest.mark.parametrize('program', [None, {}, {'admitted': True}, 'registered-package'])
def test_serialized_program_admission_cannot_upgrade_private_peer_metadata(context, program):
    original = register(context)
    assert original.backend_admission is None
    with pytest.raises(records.ControllerRecordError, match='ACTUAL_PROTECTED'):
        context.store.register_admitted(
            context.binding,
            peer=context.peer,
            program=program,
            timeout_ms=3000,
            cancelled=lambda: False,
        )
    assert register(context) == original


@pytest.mark.parametrize(
    'admission',
    [
        {},
        {'policy_version': 'BACKEND20-PROTECTED-1'},
        {
            'policy_version': 'OTHER',
            'program_ref': PROGRAM_REF,
            'manifest_sha256': PACKAGE_SHA,
            'evidence_sha256': 'e' * 64,
        },
        {
            'policy_version': 'BACKEND20-PROTECTED-1',
            'program_ref': 'OTHER-PROGRAM',
            'manifest_sha256': PACKAGE_SHA,
            'evidence_sha256': 'e' * 64,
        },
    ],
)
def test_original_stored_admission_must_match_exact_policy_program_and_package(context, admission):
    original = register(context)
    value = original.facts
    value['backend_admission'] = admission
    with pytest.raises(records.ControllerRecordError):
        records.decode_controller_registration(
            _bytes(value), context.binding.controller_ref, context.binding.owner_epoch
        )


def test_durable_controller_seal_blocks_every_new_nonce_but_preserves_other_controller(context):
    original = register(context)
    scope = context.binding.scope(17, 2, 'original-controller-seal-nonce-001')
    context.journal.prepare(scope, 'b' * 64)
    seal = context.store.seal_controller(
        context.binding.controller_ref, context.binding.owner_epoch
    )
    assert seal.registration_sha256 == original.sha256
    assert (
        context.store.read_seal(context.binding.controller_ref, context.binding.owner_epoch) == seal
    )
    assert context.journal.verify_controller_closure(context.binding.controller_ref) == seal
    assert context.journal.inspect(scope).stop_closed
    new_scope = context.binding.scope(18, 1, 'replacement-controller-nonce-001')
    with pytest.raises(RuntimeError, match='CONTROLLER_ADMISSION_CLOSED'):
        context.journal.prepare(new_scope, 'b' * 64)
    assert context.journal.inspect(new_scope) is None
    assert (
        context.store.seal_controller(context.binding.controller_ref, context.binding.owner_epoch)
        == seal
    )
    other = replace(context.binding, owner_epoch=str(uuid4())).scope(
        19, 1, 'other-controller-nonce-00001'
    )
    assert not context.journal.prepare(other, 'b' * 64).stop_closed
    assert context.original.process.observe().state == 'RUNNING'


def test_controller_seal_survives_guard_restart_and_does_not_reconstruct_old_process(context):
    register(context)
    seal = context.store.seal_controller(
        context.binding.controller_ref, context.binding.owner_epoch
    )
    context.store.close()
    context.journal.close()
    with (
        LaunchJournal(context.root) as restarted,
        records.GuardControllerRecords(restarted) as store,
    ):
        assert store.read_seal(context.binding.controller_ref, context.binding.owner_epoch) == seal
        new_scope = context.binding.scope(18, 1, 'replacement-controller-nonce-001')
        with pytest.raises(RuntimeError, match='CONTROLLER_ADMISSION_CLOSED'):
            restarted.prepare(new_scope, 'b' * 64)
        assert restarted.inspect(new_scope) is None


def test_lost_seal_ack_uses_original_writer_and_marker_is_not_fence_closure(context):
    register(context)
    scope = context.binding.scope(17, 2, 'original-controller-seal-nonce-001')
    context.journal.prepare(scope, 'b' * 64)
    publish = records.PrivateRecordAppend.publish

    def lost(writer):
        publish(writer)
        raise OSError('Injected controller seal acknowledgement loss')

    with patch.object(records.PrivateRecordAppend, 'publish', lost):
        with pytest.raises(records.ControllerRecordError, match='SEAL_PUBLISH_UNVERIFIED'):
            context.store.seal_controller(
                context.binding.controller_ref, context.binding.owner_epoch
            )
    with pytest.raises(RuntimeError, match='SEAL_READ_UNVERIFIED'):
        context.journal.verify_controller_closure(context.binding.controller_ref)

    def forbid_new_seal(writer):
        if writer._filename.endswith('.controller-seal.json'):
            raise AssertionError('No seal re-publication')
        return publish(writer)

    with patch.object(records.PrivateRecordAppend, 'publish', forbid_new_seal):
        resolved = context.store.reconcile_pending()
        assert len(resolved) == 1
        with pytest.raises(RuntimeError, match='SCOPE_CLOSURE_UNVERIFIED'):
            context.journal.verify_controller_closure(context.binding.controller_ref)
        seal = context.store.seal_controller(
            context.binding.controller_ref, context.binding.owner_epoch
        )
        assert resolved[0] == seal
    assert context.journal.inspect(scope).stop_closed


def test_seal_during_original_callback_is_unknown_and_does_not_block_other_controller(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    register(context)
    scope = context.binding.scope(17, 2, 'original-controller-seal-nonce-001')
    context.journal.prepare(scope, 'b' * 64)
    entered, release = Event(), Event()
    calls = []

    def native_port():
        calls.append('original')
        entered.set()
        assert release.wait(5)
        return 'original-resource-binding-001'

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(context.journal.dispatch_create, scope, 'b' * 64, native_port)
        try:
            assert entered.wait(3)
            with pytest.raises(RuntimeError, match='STILL_IN_FLIGHT'):
                context.store.seal_controller(
                    context.binding.controller_ref, context.binding.owner_epoch
                )
            with pytest.raises(RuntimeError, match='CONTROLLER_ADMISSION_CLOSED'):
                context.journal.prepare(
                    context.binding.scope(18, 1, 'replacement-controller-nonce-001'), 'b' * 64
                )
            other = replace(context.binding, owner_epoch=str(uuid4())).scope(
                19, 1, 'other-controller-nonce-00001'
            )
            assert not context.journal.prepare(other, 'b' * 64).stop_closed
        finally:
            release.set()
        assert future.result(timeout=3).create_state == 'RESOURCE_RECORDED'
    context.store.seal_controller(context.binding.controller_ref, context.binding.owner_epoch)
    assert context.journal.inspect(scope).stop_closed
    context.journal.dispatch_create(scope, 'b' * 64, lambda: pytest.fail('No late dispatch'))
    assert calls == ['original']


def test_action_intent_is_durable_in_actual_private_root_before_new_read_package(context):
    from backend.app.infrastructure.guard_action_journal import GuardActionJournal
    from backend.app.infrastructure.guard_request_header import PROTOCOL, parse_guard_request_header
    from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
    from backend.app.infrastructure.windows_private_package import create_control_git_read_package

    register(context)
    value = {
        'protocol_version': PROTOCOL,
        'action': 'PREPARE',
        'controller_ref': context.binding.controller_ref,
        'owner_epoch': context.binding.owner_epoch,
        'operation_id': 17,
        'step_no': 2,
        'nonce': 'original-action-allocation-nonce-01',
        'binding_ref': None,
        'input': {'fixture': 'INTENT_ONLY_NO_DISPATCH'},
    }
    request = parse_guard_request_header(value, context.binding, peer=context.peer)
    store = GuardActionJournal(context.journal)
    intent = store.begin(request)
    assert intent.first_accepted
    assert not list(context.root.glob('control-git-*'))
    with context.peer.original_process() as source:
        with ControllerPrimaryToken(source, expected=source.identity) as token:
            directory = create_control_git_read_package(
                context.journal._package, intent.record.directory_nonce, token
            )
            assert directory.name == 'control-git-' + intent.record.directory_nonce
            repeated = store.begin(request)
            assert not repeated.first_accepted and repeated.record == intent.record
    # Only a partial directory was prepared. Keep MAY; no false PREPARE ACK,
    # Native Job/process, SYSTEM claim or private package cleanup success.
    assert store.find(request.target_scope, 'PREPARE').phase == 'MAY_HAVE_BEEN_SENT'
