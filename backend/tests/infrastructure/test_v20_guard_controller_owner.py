"""Explicit lifecycle ports, not a protected backend/Native Guard admission."""

from contextlib import contextmanager
from dataclasses import replace
from threading import Thread
from types import SimpleNamespace

import pytest

from backend.app.infrastructure import guard_controller_owner as owners
from backend.app.infrastructure.guard_controller_binding import GuardControllerBinding
from backend.tests.infrastructure.test_v20_guard_recovery import facts


@pytest.fixture
def port(monkeypatch):
    registration, _, _ = facts()
    events = []
    created = []
    controls = SimpleNamespace(record_failure=False, watch_failure=False)

    class SourcePort:
        identity = registration.binding.controller
        closed = False
        state = 'RUNNING'

        def duplicate(self):
            events.append('source-duplicate')
            copied = SourcePort()
            created.append(copied)
            return copied

        def close(self):
            events.append('source-close')
            self.closed = True

    class PeerPort:
        def __init__(self):
            self.source = SourcePort()
            self.closed = False
            self._program = SimpleNamespace(verify=lambda: registration.image)

        @contextmanager
        def original_process(self):
            assert not self.closed
            yield self.source

        def close(self):
            self.closed = True
            self.source.closed = True

    class ProgramPort:
        def __init__(self, peer):
            self.peer = peer
            self.active = 0
            self.value = registration.backend_admission

        @contextmanager
        def admission(self, **boundary):
            self.active += 1
            try:
                yield self.value
            finally:
                self.active -= 1

    class RecordsPort:
        _journal = object()

        def register_admitted(self, binding, *, peer, program, **boundary):
            events.append('record')
            if controls.record_failure:
                raise RuntimeError('Original admitted record unavailable')
            with program.admission(**boundary):
                return registration

        def read(self, controller_ref, epoch):
            assert controller_ref == registration.binding.controller_ref
            assert epoch == registration.binding.owner_epoch
            return registration

        def seal_controller(self, controller_ref, epoch):
            events.append('seal')
            assert controller_ref == registration.binding.controller_ref

    class TokenPort:
        def __init__(self, source, *, expected):
            assert source.identity == expected and not source.closed
            events.append('token-create')
            self.source = source
            self.closed = False

        @contextmanager
        def creation_handle(self):
            if self.closed or self.source.closed or self.source.state != 'RUNNING':
                raise RuntimeError('Original source unavailable')
            yield 1

        def close(self):
            events.append('token-close')
            self.closed = True

    class RegistryPort:
        def __init__(self, journal, token, *, controller_ref):
            events.append('registry-create')
            assert journal is RecordsPort._journal
            self.token = token
            self._entries = {}
            self.active = False
            self.watch_closed = False

        def start_controller_watch(self):
            events.append('watch-start')
            if controls.watch_failure:
                raise RuntimeError('Watch initialization failed')

        @contextmanager
        def pause_task_watch_for_close(self):
            yield

        def close_watch(self):
            events.append('watch-close')
            if self.active:
                raise RuntimeError('Original native Job still active')
            self.watch_closed = True

    peer = PeerPort()
    program = ProgramPort(peer)
    records = RecordsPort()
    monkeypatch.setattr(owners, 'GuardControllerRecords', RecordsPort)
    monkeypatch.setattr(owners, 'ProtectedBackendProgram', ProgramPort)
    monkeypatch.setattr(owners, 'ControllerPrimaryToken', TokenPort)
    monkeypatch.setattr(owners, 'ControlGitRegistry', RegistryPort)

    def assert_peer(binding, actual):
        assert not actual.closed
        assert actual.source.identity == binding.controller

    monkeypatch.setattr(GuardControllerBinding, 'assert_peer', assert_peer)

    def create(**changed):
        return owners.GuardControllerOwner(
            records,
            registration.binding,
            **{
                'peer': peer,
                'program': program,
                'timeout_ms': 3000,
                'cancelled': lambda: False,
                **changed,
            },
        )

    return SimpleNamespace(
        records=records,
        peer=peer,
        program=program,
        binding=registration.binding,
        registration=registration,
        create=create,
        events=events,
        controls=controls,
        created=created,
        PeerPort=PeerPort,
        ProgramPort=ProgramPort,
    )


def test_owner_records_original_admission_before_owning_process_token_or_watch(port):
    owner = port.create()
    try:
        assert port.events == [
            'record',
            'source-duplicate',
            'token-create',
            'registry-create',
            'watch-start',
        ]
        assert owner.binding == port.binding
        assert owner.registration == port.registration
        assert owner._source is not port.peer.source
    finally:
        owner.close()
    assert port.events[-4:] == ['seal', 'watch-close', 'token-close', 'source-close']
    assert owner._closed
    count = len(port.events)
    owner.close()
    assert len(port.events) == count


def test_record_failure_cannot_allocate_token_process_copy_or_watch(port):
    port.controls.record_failure = True
    with pytest.raises(RuntimeError, match='record unavailable'):
        port.create()
    assert port.events == ['record']
    assert port.created == []


def test_initialization_failure_releases_only_unpublished_original_owners(port):
    port.controls.watch_failure = True
    with pytest.raises(RuntimeError, match='initialization failed'):
        port.create()
    assert port.created[0].closed
    assert 'seal' not in port.events
    assert port.events[-3:] == ['watch-close', 'token-close', 'source-close']


def test_pipe_release_does_not_release_independent_controller_source_and_reconnect_uses_same_owner(
    port,
):
    owner = port.create()
    original = owner._source
    port.peer.close()
    assert not original.closed
    replacement = port.PeerPort()
    program = port.ProgramPort(replacement)
    try:
        with owner.current_registry(
            port.binding,
            peer=replacement,
            program=program,
            timeout_ms=3000,
            cancelled=lambda: False,
        ) as registry:
            assert registry is owner.registry
            assert owner._source is original
            with pytest.raises(owners.GuardControllerOwnerError, match='ACTION_STILL_ACTIVE'):
                owner.close()
        assert program.active == 0
    finally:
        owner.close()
    assert original.closed


def test_new_epoch_cannot_rebind_old_owner_as_current_controller(port):
    owner = port.create()
    try:
        from uuid import uuid4

        with pytest.raises(owners.GuardControllerOwnerError, match='RECONNECT_DIFFERS'):
            with owner.current_registry(
                replace(port.binding, owner_epoch=str(uuid4())),
                peer=port.peer,
                program=port.program,
                timeout_ms=3000,
                cancelled=lambda: False,
            ):
                pytest.fail('No new epoch as current old owner')
    finally:
        owner.close()


def test_changed_program_admission_cannot_replace_original_private_record(port):
    owner = port.create()
    try:
        port.program.value = replace(port.registration.backend_admission, evidence_sha256='f' * 64)
        with pytest.raises(owners.GuardControllerOwnerError, match='PROGRAM_RECORD_DIFFERS'):
            with owner.current_registry(
                port.binding,
                peer=port.peer,
                program=port.program,
                timeout_ms=3000,
                cancelled=lambda: False,
            ):
                pytest.fail('No current action after program evidence changed')
        assert owner._users == 0 and port.program.active == 0
    finally:
        owner.close()


def test_active_original_job_refuses_close_and_keeps_token_source_and_registry_for_cleanup(port):
    owner = port.create()
    original_source, original_token = owner._source, owner._token
    owner.registry.active = True
    with pytest.raises(RuntimeError, match='Job still active') as caught:
        owner.close()
    assert caught.value.retained_owner is owner
    assert owner._closing and not owner._closed
    assert owner._source is original_source and not original_source.closed
    assert owner._token is original_token and not original_token.closed
    with pytest.raises(owners.GuardControllerOwnerError, match='ADMISSION_CLOSED'):
        with owner.current_registry(
            port.binding,
            peer=port.peer,
            program=port.program,
            timeout_ms=3000,
            cancelled=lambda: False,
        ):
            pytest.fail('No new current actions while closing')
    owner.registry.active = False
    owner.close()
    assert original_source.closed and original_token.closed


def test_actor_mismatch_refuses_before_native_owner_or_record_side_effects(port):
    owner = port.create()
    before = list(port.events)
    errors = []

    def foreign():
        try:
            owner.close()
        except Exception as error:
            errors.append(error)

    worker = Thread(target=foreign)
    worker.start()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], owners.GuardControllerOwnerError)
    assert 'ACTOR_THREAD_DIFFERS' in str(errors[0])
    assert port.events == before
    owner.close()


@pytest.mark.parametrize('claimed', [None, {}, {'admitted': True}])
def test_program_claim_cannot_produce_native_controller_owner(port, claimed):
    with pytest.raises(owners.GuardControllerOwnerError, match='ACTUAL_CONTROLLER_PROGRAM'):
        port.create(program=claimed)
    assert port.events == []
