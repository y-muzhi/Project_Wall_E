"""Actual independent process/token/watch, with program-admission ports only.

The port bypass is confined to this test module. It is NOT protected backend
program admission, SYSTEM deployment, LPAC/WFP or a production Guard server.
"""

from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_controller_owner as owners
from backend.app.infrastructure.guard_backend_program import POLICY_VERSION, BackendProgramAdmission
from backend.app.infrastructure.guard_control_git_actions import run_guard_control_git_action
from backend.app.infrastructure.guard_controller_binding import bind_guard_controller
from backend.app.infrastructure.guard_controller_records import GuardControllerRecords
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_pipe_peer import PipePeerError
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.test_v20_windows_pipe_peer import connection, peer
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.mark.parametrize('connection', ['CLIENT'], indirect=True)
def test_actual_controller_watch_survives_pipe_release_and_observes_original_source_exit(
    connection, tmp_path, monkeypatch
):
    root = create_private_package(tmp_path / 'controller-native-owner')
    with (
        peer(connection) as original_peer,
        LaunchJournal(root) as journal,
        GuardControllerRecords(journal) as actual_records,
    ):
        binding = bind_guard_controller(original_peer, str(uuid4()), 'a' * 64)
        metadata = actual_records.record_peer_facts(
            binding,
            peer=original_peer,
            backend_program_ref='TEST-ADMISSION-PORT-ONLY',
            backend_package_sha256='b' * 64,
        )
        # Real OS ownership tests deliberately replace program admission only;
        # the actual stored record remains metadata with no permission.
        admission = BackendProgramAdmission(
            POLICY_VERSION, metadata.backend_program_ref, metadata.backend_package_sha256, 'c' * 64
        )
        port_registration = replace(metadata, backend_admission=admission)

        class ProgramPort:
            peer = original_peer

            @contextmanager
            def admission(self, **boundary):
                yield admission

        class RecordsPort:
            _journal = journal

            def register_admitted(self, *args, **kwargs):
                return port_registration

            def read(self, *args):
                return port_registration

            def seal_controller(self, *args):
                return actual_records.seal_controller(*args)

        monkeypatch.setattr(owners, 'ProtectedBackendProgram', ProgramPort)
        monkeypatch.setattr(owners, 'GuardControllerRecords', RecordsPort)
        program = ProgramPort()
        owner = owners.GuardControllerOwner(
            RecordsPort(),
            binding,
            peer=original_peer,
            program=program,
            timeout_ms=3000,
            cancelled=lambda: False,
        )
        source = owner._source
        token = owner._token
        registry = owner.registry
        assert source is not original_peer._process
        assert token._controller is source
        assert source.identity == binding.controller
        from backend.app.infrastructure.guard_action_journal import GuardActionJournal
        from backend.app.infrastructure.guard_request_header import (
            PROTOCOL,
            parse_guard_request_header,
        )
        from backend.app.infrastructure.windows_job import OwnedJob

        action_request = parse_guard_request_header(
            {
                'protocol_version': PROTOCOL,
                'action': 'PREPARE',
                'controller_ref': binding.controller_ref,
                'owner_epoch': binding.owner_epoch,
                'operation_id': 17,
                'step_no': 2,
                'nonce': 'original-partial-preparation-001',
                'binding_ref': None,
                'input': {'fixture': 'MAY_ONLY_NO_NATIVE_DISPATCH'},
            },
            binding,
            peer=original_peer,
        )
        actions = GuardActionJournal(journal)
        start = actions.begin(action_request)
        preparation = registry.begin_preparation(actions, start)
        assert registry.begin_preparation(actions, actions.begin(action_request)) is preparation
        stop = parse_guard_request_header(
            {**action_request.wire, 'action': 'STOP', 'operation_id': 18, 'input': {}},
            binding,
            peer=original_peer,
        )
        allocated = {}
        try:
            boundary = {'peer': original_peer, 'timeout_ms': 3000, 'cancelled': lambda: False}
            with pytest.raises(owners.GuardControllerOwnerError, match='RECONNECT_DIFFERS'):
                run_guard_control_git_action(owner, stop, program=object(), **boundary)
            assert actions.find(stop.scope, 'STOP') is None
            stopped = run_guard_control_git_action(owner, stop, program=program, **boundary)
            assert stopped.phase == 'ACKNOWLEDGED'
            assert stopped.result['native']['fence']['stop_closed']
            assert run_guard_control_git_action(owner, stop, program=program, **boundary) == stopped
            original_peer.close()
            with pytest.raises(PipePeerError, match='PEER_CLOSED'):
                run_guard_control_git_action(owner, stop, program=program, **boundary)
            assert original_peer._process is None
            assert source.observe().state == 'RUNNING'
            from threading import Event, Thread

            completed = Event()
            observations = []

            def query_while_source_gate_is_held():
                try:
                    observations.append(registry.sweep_controller())
                finally:
                    completed.set()

            with source._gate:
                worker = Thread(target=query_while_source_gate_is_held)
                worker.start()
                observed_without_waiting_for_actor = completed.wait(1)
            worker.join(timeout=3)
            assert not worker.is_alive()
            assert observed_without_waiting_for_actor, 'Watch must not wait for actor source gate'
            assert observations == [None]
            assert registry.sweep_controller() is None
            with token.creation_handle():
                pass

            def late_job_after_source_exit():
                job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
                allocated['job'] = job
                allocated['stop_calls'] = []
                terminate = job.terminate_owned

                def terminate_original(code):
                    allocated['stop_calls'].append(job._handle)
                    return terminate(code)

                job.terminate_owned = terminate_original
                connection.job.terminate_owned(1)
                assert source._kernel.WaitForSingleObject(source._handle, 8000) == 0
                return job

            with pytest.raises(RuntimeError, match='ALLOCATION_UNVERIFIED') as allocation_error:
                preparation.allocate('JOB', late_job_after_source_exit)
            assert allocation_error.value.retained_owner is preparation
            assert preparation._slots['JOB'].value is allocated['job']
            assert allocated['job']._handle is not None
            assert registry.sweep_controller() == 'CONTROLLER_EXITED'
            assert allocated['stop_calls']
            assert journal.inspect(start.record.scope).stop_closed
            assert preparation.verify_no_activity()
            preparation.close_stopped_handles()
            assert allocated['job']._handle is None
            assert actions.find(start.record.scope, 'PREPARE').phase == 'MAY_HAVE_BEEN_SENT'
            assert registry._admission_closed
            assert (
                actual_records.read(binding.controller_ref, binding.owner_epoch).backend_admission
                is None
            )
        finally:
            from unittest.mock import patch

            watcher = registry._watch_source
            original_close = watcher._kernel.CloseHandle
            watcher_handle = watcher._handle

            def fail_watch_close(handle):
                if handle == watcher_handle:
                    return False
                return original_close(handle)

            with patch.object(watcher._kernel, 'CloseHandle', fail_watch_close):
                with pytest.raises(RuntimeError, match='PROCESS_HANDLE_CLOSE_FAILED') as caught:
                    owner.close()
            assert caught.value.retained_owner is owner
            assert registry._watch_source is watcher and watcher._handle == watcher_handle
            assert source._handle is not None and token._handle is not None
            owner.close()
            if allocated.get('job') is not None:
                if allocated['job']._handle:
                    allocated['job'].terminate_owned(1)
                allocated['job'].close()
        assert source._handle is None
        assert token._handle is None
        assert registry._watch_thread is not None and not registry._watch_thread.is_alive()
