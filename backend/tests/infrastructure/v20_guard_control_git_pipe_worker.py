"""Backend fixture for real Control Git transport. Invoked in an owned test Job."""

import hashlib
import json
import os
import sys
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic, sleep

from backend.app.infrastructure.sqlite_runtime import activate

activate()

from backend.app.infrastructure.git_config_command import parse_original_config_output
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.guard_control_git_input import (
    config_prepare_input,
    version_prepare_input,
)
from backend.app.infrastructure.guard_control_git_transport import (
    GuardExchangeUnknown,
    exchange_guard_control_git,
    exchange_guard_task_files,
)
from backend.app.infrastructure.guard_controller_binding import bind_backend_controller
from backend.app.infrastructure.guard_git_config_source import open_config_export
from backend.app.infrastructure.guard_pipe_frames import GuardFrameError, GuardPipeFrames
from backend.app.infrastructure.guard_request_header import build_guard_request_header
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_guard_pipe import GuardPipeClient
from backend.app.infrastructure.windows_guard_pipe_io import GuardPipeIO
from backend.app.infrastructure.windows_pipe_capture import BoundedOutputCapture
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.app.infrastructure.windows_process_input import (
    MAX_TYPED_INPUT_BYTES,
    OriginalProcessInput,
)
from backend.app.infrastructure.windows_stdio import BackendStandardIO, GuardStdioBinding
from backend.tests.infrastructure.v20_stdio_worker import publish, wait

NONCE = 'guard-pipe-control-git-test'
TASK_RECOVERY_NONCE = 'd' * 32


def run_task_controller_recovery(root, frames, binding, lock):
    from backend.app.code_tasks.task_runtime_recovery import (
        RuntimeTaskRecovery,
        TaskRecoveryReceipt,
    )
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

    with PrivatePackageGuard(root.parent / 'task-workspace-source') as package:
        receipt = TaskRecoveryReceipt(package, 17, TASK_RECOVERY_NONCE)
        old = receipt.owner()
        assert old.scope.controller_ref != binding.controller_ref
        recovery = RuntimeTaskRecovery(frames, binding, lock, receipt)
        options = {'timeout_ms': 30000, 'cancelled': lambda: False}
        wrong = build_guard_request_header(
            binding,
            lock,
            action='OBSERVE',
            operation_id=17,
            step_no=4,
            nonce=TASK_RECOVERY_NONCE,
            binding_ref='f' * 32,
            action_input={
                'observed_action': 'STOP',
                'recovery': {
                    'controller_ref': old.scope.controller_ref,
                    'owner_epoch': old.owner_epoch,
                },
            },
        )
        assert (
            exchange_guard_task_files(frames, binding, lock, wrong, **options).status == 'UNKNOWN'
        )
        before = recovery.observe('STOP', **options)
        assert before['resource']['process_state'] == 'EXITED'
        assert before['acknowledgement'] is None
        stopped = recovery.stop(**options)
        assert stopped.status == 'ACKNOWLEDGED'
        assert recovery.observe('STOP', **options)['acknowledgement'] == stopped.result
        assert recovery.release(**options).status == 'UNKNOWN'
        released = recovery.release(**options)
        assert released.status == 'ACKNOWLEDGED'
        observed = recovery.observe('RELEASE', **options)
        assert observed['preparation']['cleanup_state'] == 'COMPLETE'
        assert observed['acknowledgement'] == released.result
        assert recovery.release(**options).result == released.result
        publish(root / 'control-git-pipe-result.json', {'recovered': True})


def run_task_workspace_transfer(root, frames, binding, lock, *, outcome):
    import socket

    from backend.app.code_tasks.task_basis import BasisOriginal
    from backend.app.code_tasks.task_basis_package import (
        basis_digest,
        basis_source,
        publish_basis_package,
        runtime_basis_plan,
    )
    from backend.app.code_tasks.task_runtime_basis import RuntimeBasisTransfer
    from backend.app.code_tasks.task_runtime_files import RuntimeFilesTransfer
    from backend.app.code_tasks.task_runtime_workspace import (
        RuntimeWorkspaceTransfer,
        WorkspacePublicationUnknown,
        publish_runtime_workspace,
    )
    from backend.app.code_tasks.workspace_materialization import WorkspaceMaterializationError
    from backend.app.infrastructure.guard_action_records import mutation_input_sha256
    from backend.app.infrastructure.guard_task_sources import TaskSourcePins
    from backend.app.infrastructure.guard_task_workspace_protocol import workspace_stage_destination
    from backend.app.infrastructure.opencode_binary import VERSION
    from backend.app.infrastructure.opencode_task_launch import TaskExecutionError
    from backend.app.infrastructure.windows_local_paths import FileIdentity
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.infrastructure.windows_task_runtime_bundle import TaskRuntimeFilesError
    from backend.app.infrastructure.windows_task_workspace_lease import (
        BackendWorkspaceWriteLease,
        WorkspaceWriteError,
    )
    from backend.tests.code_tasks.test_task_runtime_workspace import LIMITS, _original_workspace

    recovery_case = outcome == 'execution_pipe_recover'
    scope = binding.scope(17, 4, TASK_RECOVERY_NONCE if recovery_case else NONCE + '-workspace')
    parent_path = root / 'task-workspace-source'
    execution_case = outcome.startswith('execution_')
    runtime_case = outcome.startswith('runtime_') or execution_case
    runtime_ref = (
        (root / 'runtime-bundle-ref').read_text(encoding='ascii') if runtime_case else None
    )

    def send(action, *, data=None, reference=None):
        request = build_guard_request_header(
            binding,
            lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=reference,
            action_input={} if data is None else data,
        )
        reply = exchange_guard_task_files(
            frames, binding, lock, request, timeout_ms=30000, cancelled=lambda: False
        )
        return request, reply

    with ExitStack() as held:
        execution = network = None
        if execution_case:
            model = held.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            model.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            model.bind(('127.0.0.1', 0))
            model.listen()
            publish(root / 'registered-task-listener.json', {'model_port': model.getsockname()[1]})
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as choice:
                choice.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                choice.bind(('127.0.0.1', 0))
                control_port = choice.getsockname()[1]
            if outcome == 'execution_busy':
                control = held.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
                control.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                control.bind(('127.0.0.1', control_port))
                control.listen()
            execution = {
                'version': VERSION,
                'binary_ref': 'test-executor',
                'active_process_limit': 2,
                'job_memory_limit_bytes': 128 * 1024 * 1024,
            }
            network = {
                'model': [{'address': '127.0.0.1', 'port': model.getsockname()[1]}],
                'forward': [],
                'control': [{'address': '127.0.0.1', 'port': control_port}],
                'application': [],
            }
        parent = held.enter_context(PrivatePackageGuard(parent_path))
        allocation, receipt = _original_workspace(parent)
        metadata = json.loads(receipt)
        manifest = metadata['content_sha256']
        documents = (BasisOriginal(3, 9, '共同设计\r\n'.encode()),)
        basis_binding = {
            'operation_id': scope.operation_id,
            'task_id': allocation.task_id,
            'workspace_id': allocation.workspace_id,
            'generation': allocation.generation,
            'nonce': allocation.nonce,
            'document_count': len(documents),
            'source_sha256': basis_digest(basis_source(documents)),
        }
        basis = publish_basis_package(parent, basis_binding, documents, lock.assert_owned)
        basis_plan = runtime_basis_plan(parent, basis_binding, basis, lock.assert_owned)
        pins = held.enter_context(
            TaskSourcePins(
                parent.verify(),
                allocation.nonce,
                workspace=FileIdentity(**metadata['directory']),
                workspace_tree=FileIdentity(**metadata['tree_record']['file']),
                basis_seal=FileIdentity(**basis['file']),
            )
        )
        original, pending = send(
            'PREPARE',
            data=pins.request_data(
                basis_plan_sha256=basis_plan.sha256,
                reserve_files=True,
                workspace_manifest_sha256=manifest,
                runtime_bundle_ref=runtime_ref,
                execution=execution,
                network=network,
            ),
        )
        assert pending.status == 'UNKNOWN'
        _, observation = send('OBSERVE', data={'observed_action': 'PREPARE'})
        reference = observation.result['binding_ref']
        assert observation.result['preparation']['directory_state'] == 'HELD'

        def reject_runtime(stage):
            _, reply = send(
                'PREPARE',
                data={
                    'run_kind': 'TASK',
                    'runtime_files_stage': stage,
                    'runtime_binding_ref': reference,
                    'prepare_input_sha256': mutation_input_sha256(original),
                    'runtime_bundle_ref': runtime_ref,
                },
            )
            assert reply.status == 'UNKNOWN'

        if runtime_case:
            reject_runtime('PREPARE_FILES')
        if outcome == 'cohort' or runtime_case:
            basis_transfer = RuntimeBasisTransfer(frames, binding, lock, original, reference)
            evidence = basis_transfer.publish(
                parent,
                basis_binding,
                basis,
                lock.assert_owned,
                timeout_ms=30000,
                cancelled=lambda: False,
            )
            assert (
                basis_transfer.verify(evidence, timeout_ms=30000, cancelled=lambda: False)
                == evidence
            )
        if runtime_case:
            reject_runtime('PREPARE_FILES')
        transfer = RuntimeWorkspaceTransfer(frames, binding, lock, original, reference)

        def stage(name, payload):
            return transfer._stage(
                name, payload, deadline=monotonic() + 30, cancelled=lambda: False
            )

        def rejected(name, payload):
            try:
                stage(name, payload)
            except WorkspaceWriteError as error:
                assert str(error) == 'ORIGINAL_WORKSPACE_STAGE_UNVERIFIED'
            else:
                raise AssertionError('Unexpected workspace stage result')

        transfer._manifest = 'b' * 64 if manifest != 'b' * 64 else 'c' * 64
        rejected('BEGIN', {})
        transfer._manifest = manifest
        if outcome in ('stop_writer', 'lost_offer'):
            try:
                offered = stage('BEGIN', {})
            except GuardExchangeUnknown:
                assert outcome == 'lost_offer'
                publish(root / 'control-git-pipe-result.json', {'offer_disconnected': True})
                wait(root / 'stop')
                return
            assert outcome == 'stop_writer'
            target = workspace_stage_destination(scope, offered)

            def stop_during_copy():
                if not any(
                    path.is_file() for path in Path(target.directory.canonical_path).rglob('*')
                ):
                    return
                _, pending_stop = send('STOP', reference=reference)
                assert pending_stop.status == 'UNKNOWN'
                _, observed = send('OBSERVE', data={'observed_action': 'STOP'}, reference=reference)
                assert observed.result['fence']['stop_closed']
                assert observed.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                rejected('BEGIN', {})
                raise WorkspaceMaterializationError('original workspace publication stopped')

            try:
                with BackendWorkspaceWriteLease(offered['writer']):
                    publish_runtime_workspace(
                        parent, allocation, receipt, target, stop_during_copy, LIMITS
                    )
            except WorkspaceMaterializationError as error:
                assert str(error) == 'original workspace publication stopped'
            else:
                raise AssertionError('Workspace copy was not stopped')
        else:
            try:
                result = transfer.publish(
                    parent,
                    allocation,
                    receipt,
                    lock.assert_owned,
                    LIMITS,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )
            except WorkspacePublicationUnknown as error:
                assert outcome == 'finish_unknown'
                result = error.expected
            else:
                assert outcome in ('success', 'cohort') or runtime_case
            assert (
                transfer.verify(
                    parent,
                    allocation,
                    receipt,
                    result,
                    lock.assert_owned,
                    LIMITS,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )
                == result
            )
            rejected('BEGIN', {})
        if outcome == 'runtime_unregistered':
            reject_runtime('PREPARE_FILES')
            reject_runtime('VERIFY_FILES')
            reject_runtime('PREPARE_FILES')
        elif runtime_case:
            runtime = RuntimeFilesTransfer(frames, binding, lock, original, reference)
            try:
                prepared = runtime.prepare(
                    evidence, result, timeout_ms=30000, cancelled=lambda: False
                )
            except TaskRuntimeFilesError as error:
                assert outcome == 'runtime_unknown'
                assert str(error) == 'ORIGINAL_RUNTIME_FILE_EVIDENCE_UNVERIFIED'
                prepared = None
            else:
                assert outcome == 'runtime_success' or execution_case
            checked = runtime.verify(evidence, result, timeout_ms=30000, cancelled=lambda: False)
            assert checked['runtime_member_count'] == 6
            assert checked['runtime_bundle_ref'] == runtime_ref
            assert prepared is None or checked == prepared
            reject_runtime('PREPARE_FILES')
        watch_case = outcome in ('execution_pipe_watch', 'execution_pipe_recover')
        launch_case = outcome == 'execution_pipe_launch' or watch_case
        network_case = outcome == 'execution_profile_network' or launch_case
        profile_case = outcome == 'execution_profile' or network_case
        if execution_case:
            options = {'timeout_ms': 30000, 'cancelled': lambda: False}
            if outcome in ('execution_busy', 'execution_unregistered'):
                try:
                    runtime.prepare_execution(checked, **options)
                except TaskExecutionError as error:
                    assert str(error) == 'ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED'
                else:
                    raise AssertionError('Occupied control port was accepted')
            else:
                prepared_execution = runtime.prepare_execution(checked, **options)
                assert prepared_execution['network_state'] == 'UNKNOWN'
                assert runtime.verify_execution(checked, **options) == prepared_execution

                def reject_execution(attempt):
                    try:
                        attempt(checked, **options)
                    except TaskExecutionError as error:
                        assert str(error) == 'ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED'
                    else:
                        raise AssertionError('Unexpected execution preparation evidence')

                reject_execution(runtime.prepare_execution)
                reject_execution(runtime.install_network)
                if profile_case:
                    reject_execution(runtime.verify_profile)
                    profile = runtime.prepare_profile(checked, **options)
                    assert {key: profile[key] for key in prepared_execution} == prepared_execution
                    reject_execution(runtime.prepare_profile)
                    assert runtime.verify_profile(checked, **options) == profile
                    if network_case:
                        installed = runtime.install_network(checked, **options)
                        assert installed == {**profile, 'network_state': 'RULES_VERIFIED'}
                        assert runtime.verify_profile_network(checked, **options) == installed
                        assert runtime.verify_network_policy(checked, **options) == {
                            **installed,
                            'policy_state': 'NO_EXTERNAL_BYPASS_SEEN',
                        }
                        credential = runtime.issue_control_credential()
                        control = runtime.bind_control_credential(checked, credential, **options)
                        launch_input = runtime.verify_launch_input(checked, **options)
                        assert launch_input['job_ref'] == installed['job_ref']
                        assert launch_input['credential_sha256'] == control['credential_sha256']
                        assert len(launch_input['deployment_sha256']) == 64
                        assert len(launch_input['launch_input_sha256']) == 64
                        assert runtime.verify_launch_input(checked, **options) == launch_input
                        if launch_case:
                            from backend.app.code_tasks.task_runtime_launch import RuntimeTaskLaunch
                            from backend.app.infrastructure.windows_stdio import BackendStandardIO

                            if recovery_case:
                                from backend.app.code_tasks.task_runtime_recovery import (
                                    TaskRecoveryReceipt,
                                )

                                receipt = TaskRecoveryReceipt(
                                    parent, scope.operation_id, scope.nonce
                                )
                                receipt.remember(original)
                                receipt.remember_binding(reference)

                            with BackendStandardIO(scope) as stdio:
                                launch = RuntimeTaskLaunch(
                                    frames, binding, lock, original, reference, stdio, parent
                                )
                                confirm = launch.confirm(launch_input, **options)
                                observed = launch.observe('PREPARE', **options)
                                assert observed['acknowledgement'] == confirm
                                assert observed['resource']['process_state'] == 'NOT_CREATED'
                                _, rejected = send(
                                    'CREATE_SUSPENDED',
                                    data={'launch_input_sha256': '0' * 64},
                                    reference=reference,
                                )
                                assert rejected.status == 'UNKNOWN'
                                acknowledge = launch._evidence.acknowledge

                                def lose_ack(action, value):
                                    if action == 'CREATE_SUSPENDED':
                                        raise OSError('fixture lost backend receipt write')
                                    return acknowledge(action, value)

                                launch._evidence.acknowledge = lose_ack
                                try:
                                    launch.create(**options)
                                except OSError as error:
                                    assert str(error) == 'fixture lost backend receipt write'
                                else:
                                    raise AssertionError('Backend receipt failure was ignored')
                                finally:
                                    launch._evidence.acknowledge = acknowledge
                                assert launch._evidence.read_ack('CREATE_SUSPENDED') is None
                                if not watch_case:
                                    client = frames._io._endpoint
                                    expected = client._peer.verify()
                                    program_pin = client._peer._program
                                    frames.close()
                                    client.close()
                                    publish(root / 'old-task-connection-closed', {'closed': True})
                                    wait(root / 'task-reconnect-ready')
                                    replacement = held.enter_context(
                                        GuardPipeClient(
                                            binding.installation_ref,
                                            backend_sid=binding.controller.user_sid,
                                            server_sid=expected.user_sid,
                                            expected_guard=expected,
                                            program=program_pin,
                                        )
                                    )
                                    replacement_io = held.enter_context(GuardPipeIO(replacement))
                                    frames = GuardPipeFrames(replacement_io)
                                    launch.reconnect(frames)
                                observed = launch.observe('CREATE_SUSPENDED', **options)
                                created = observed['resource']
                                assert created['process_state'] == 'SUSPENDED'
                                assert (
                                    launch._evidence.read_ack('CREATE_SUSPENDED')['native']
                                    == created
                                )
                                if not watch_case:
                                    _, rejected_model = send(
                                        'VERIFY_MODEL_SOURCE',
                                        data={
                                            'address_family': 'IPv4',
                                            'protocol': 'TCP',
                                            'client': ['127.0.0.1', 1],
                                            'server': ['127.0.0.1', model.getsockname()[1]],
                                        },
                                        reference=reference,
                                    )
                                    assert rejected_model.status == 'UNKNOWN'
                                    assert created['process_identity']['is_appcontainer'] is True
                                if watch_case:
                                    credential.close()
                                    publish(
                                        root / 'control-git-pipe-result.json', {'verified': True}
                                    )
                                    return
                                try:
                                    launch.resume('0' * 64, **options)
                                except TaskExecutionError as error:
                                    assert str(error) == 'ORIGINAL_TASK_DURABLE_RECEIPT_REQUIRED'
                                else:
                                    raise AssertionError('Wrong receipt was resumed')
                                _, rejected = send(
                                    'RESUME', data={'receipt_sha256': '0' * 64}, reference=reference
                                )
                                assert rejected.status == 'UNKNOWN'
                                running = launch.resume(created['receipt_sha256'], **options)
                                assert running['fence']['resume_state'] == 'ACKNOWLEDGED'
                                observed = launch.observe('RESUME', **options)
                                assert observed['acknowledgement']['native'] == running
                                _, rejected_model = send(
                                    'VERIFY_MODEL_SOURCE',
                                    data={
                                        'address_family': 'IPv4',
                                        'protocol': 'TCP',
                                        'client': ['127.0.0.1', 1],
                                        'server': ['127.0.0.1', model.getsockname()[1]],
                                    },
                                    reference=reference,
                                )
                                assert rejected_model.status == 'UNKNOWN'
                                stopped = launch.stop(**options)
                                try:
                                    launch.running_receipt()
                                except TaskExecutionError as error:
                                    assert str(error) == 'ORIGINAL_TASK_RUNNING_RECEIPT_REQUIRED'
                                else:
                                    raise AssertionError(
                                        'Stopped original instance remained usable'
                                    )
                                assert stopped['process_state'] == 'EXITED'
                                observed = launch.observe('STOP', **options)
                                assert observed['job_activity'] == {
                                    'process_ids': [],
                                    'assigned_count': 0,
                                    'complete': True,
                                }
                                assert launch.stop(**options) == stopped
                                try:
                                    launch.release(**options)
                                except TaskExecutionError as error:
                                    assert str(error) == 'ORIGINAL_TASK_LAUNCH_REQUIRES_OBSERVATION'
                                else:
                                    raise AssertionError('Unverified WFP cleanup was acknowledged')
                                release = launch.release(**options)
                                assert len(release['cleanup_ref']) == 64
                                assert launch.release(**options) == release
                                cleanup = launch.observe('RELEASE', **options)
                                assert cleanup['action_phase'] == 'ACKNOWLEDGED'
                                assert cleanup['acknowledgement'] == release
                                assert cleanup['preparation']['cleanup_state'] == 'COMPLETE'
                            credential.close()
                            publish(root / 'control-git-pipe-result.json', {'verified': True})
                            wait(root / 'stop')
                            return
                        credential.close()
                    else:
                        reject_execution(runtime.install_network)
                        reject_execution(runtime.verify_profile_network)
                    _, early_release = send('RELEASE', reference=reference)
                    assert early_release.status == 'UNKNOWN'
                assert runtime.verify(evidence, result, **options) == checked
                _, observed = send(
                    'OBSERVE', data={'observed_action': 'PREPARE'}, reference=reference
                )
                assert observed.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                assert observed.result['acknowledgement'] is None
                expected_network = 'PRESENT' if network_case else 'UNKNOWN'
                assert observed.result['preparation']['network_state'] == expected_network
                if outcome == 'execution_success':
                    credential = runtime.issue_control_credential()
                    bound = runtime.bind_control_credential(checked, credential, **options)
                    assert bound['credential_ref'] == credential.reference
                    assert (
                        runtime.verify_control_credential(checked, credential, **options) == bound
                    )
                    reject_execution(
                        lambda files, **opts: runtime.bind_control_credential(
                            files, credential, **opts
                        )
                    )
                    reject_execution(runtime.verify_execution)
                    assert runtime.verify_execution(checked, **options) == prepared_execution
                    reject_execution(runtime.verify_launch_input)
        _, stopped = send('STOP', reference=reference)
        if outcome == 'execution_active' or profile_case:
            assert stopped.status == 'UNKNOWN'
            _, pending = send('OBSERVE', data={'observed_action': 'STOP'}, reference=reference)
            assert pending.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
            assert pending.result['fence']['stop_closed']
            _, stopped = send('STOP', reference=reference)
        assert stopped.status == 'ACKNOWLEDGED' and stopped.result['native']['scope_unlaunched']
        rejected('VERIFY', {})
        if runtime_case:
            reject_runtime('VERIFY_FILES')
        if outcome in ('execution_success', 'execution_active') or profile_case:
            try:
                runtime.verify_execution(checked, **options)
            except TaskExecutionError as error:
                assert str(error) == 'ORIGINAL_TASK_EXECUTION_EVIDENCE_UNVERIFIED'
            else:
                raise AssertionError('Stopped execution preparation was reopened')
        if outcome == 'execution_success':
            reject_execution(
                lambda files, **opts: runtime.verify_control_credential(files, credential, **opts)
            )
            credential.close()
        if profile_case:
            reject_execution(runtime.verify_profile)
            _, wrong = send('RELEASE', reference='f' * 32)
            assert wrong.status == 'UNKNOWN'
            for _ in range(2):
                _, released = send('RELEASE', reference=reference)
                assert released.status == 'UNKNOWN'
            _, observed_release = send(
                'OBSERVE', data={'observed_action': 'RELEASE'}, reference=reference
            )
            assert observed_release.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
            assert observed_release.result['acknowledgement'] is None
            expected_network = 'ABSENT' if network_case else 'UNKNOWN'
            assert observed_release.result['preparation']['network_state'] == expected_network
    publish(root / 'control-git-pipe-result.json', {'verified': True})
    wait(root / 'stop')


def run_task_basis_transfer(root, frames, binding, lock, *, outcome):
    from backend.app.code_tasks.task_basis import BasisOriginal, TaskBasisUnavailable
    from backend.app.code_tasks.task_basis_package import (
        basis_digest,
        basis_source,
        publish_basis_package,
        runtime_basis_plan,
        write_runtime_basis,
    )
    from backend.app.code_tasks.task_runtime_basis import (
        RuntimeBasisTransfer,
        TaskBasisCompletionUnknown,
    )
    from backend.app.infrastructure.guard_task_basis_protocol import (
        basis_file_identity,
        basis_plan_header,
        basis_plan_members,
    )
    from backend.app.infrastructure.guard_task_sources import TaskSourcePins
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.infrastructure.windows_task_basis import (
        BasisCopyReceipt,
        BasisWriteOffer,
        TaskBasisTransferError,
    )

    nonce = '1' * 32
    scope = binding.scope(27, 4, NONCE + '-basis')
    parent = root / 'task-basis-source'
    originals = (BasisOriginal(3, 9, '设计\r\n'.encode()), BasisOriginal(4, 11, b''))
    source_binding = {
        'operation_id': scope.operation_id,
        'task_id': 1,
        'workspace_id': 2,
        'generation': 3,
        'nonce': nonce,
        'document_count': len(originals),
        'source_sha256': basis_digest(basis_source(originals)),
    }

    def send(action, *, data=None, reference=None):
        request = build_guard_request_header(
            binding,
            lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=reference,
            action_input={} if data is None else data,
        )
        reply = exchange_guard_task_files(
            frames, binding, lock, request, timeout_ms=30000, cancelled=lambda: False
        )
        return request, reply

    with ExitStack() as held:
        source = held.enter_context(PrivatePackageGuard(parent))
        seal = publish_basis_package(source, source_binding, originals, lock.assert_owned)
        plan = runtime_basis_plan(source, source_binding, seal, lock.assert_owned)
        workspace = held.enter_context(
            LocalPathGuard(parent / ('working-' + nonce), directory=True)
        )
        tree = held.enter_context(
            LocalPathGuard(parent / (nonce + '.workspace-tree.json'), directory=False)
        )
        basis = held.enter_context(
            LocalPathGuard(parent / (nonce + '.basis-seal.json'), directory=False)
        )
        pins = held.enter_context(
            TaskSourcePins(
                source.verify(),
                nonce,
                workspace=workspace.verify(),
                workspace_tree=tree.verify(),
                basis_seal=basis.verify(),
            )
        )
        original, pending = send(
            'PREPARE', data=pins.request_data(basis_plan_sha256=plan.sha256, reserve_files=True)
        )
        assert pending.status == 'UNKNOWN'
        _, observation = send('OBSERVE', data={'observed_action': 'PREPARE'})
        reference = observation.result['binding_ref']
        assert observation.result['preparation']['directory_state'] == 'HELD'
        transfer = RuntimeBasisTransfer(frames, binding, lock, original, reference)
        deadline = monotonic() + 30

        def stage(name, payload):
            return transfer._stage(name, payload, deadline=deadline, cancelled=lambda: False)

        def rejected(name, payload):
            try:
                stage(name, payload)
            except TaskBasisTransferError as error:
                assert str(error) == 'ORIGINAL_BASIS_STAGE_UNVERIFIED'
            else:
                raise AssertionError('Unexpected basis stage result')

        if outcome in ('stop_writer', 'lost_offer'):
            stage('BEGIN', {'plan': basis_plan_header(plan)})
            first = {'members': basis_plan_members(plan.members[:1])}
            stage('PLAN', first)
            rejected('OFFER', {'number': 1})
            rejected('PLAN', first)
            stage('PLAN', {'members': basis_plan_members(plan.members[1:])})
            try:
                offered = stage('OFFER', {'number': 1})
            except GuardExchangeUnknown:
                assert outcome == 'lost_offer'
                publish(root / 'control-git-pipe-result.json', {'offer_disconnected': True})
                wait(root / 'stop')
                return
            assert outcome == 'stop_writer'
            rejected('OFFER', {'number': 1})
            rejected('PIN', {'number': 1})
            _, stopping = send('STOP', reference=reference)
            assert stopping.status == 'UNKNOWN'
            _, observed_stop = send(
                'OBSERVE', data={'observed_action': 'STOP'}, reference=reference
            )
            assert observed_stop.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
            assert observed_stop.result['fence']['stop_closed']
            rejected('OFFER', {'number': 2})
            offer = BasisWriteOffer(
                binding.controller,
                BasisCopyReceipt(
                    scope, reference, plan.members[0], basis_file_identity(offered['file'])
                ),
                offered['writer'],
            )

            def cancelled_write():
                raise TaskBasisUnavailable('STOP already closed the original scope')

            try:
                write_runtime_basis(
                    source, source_binding, seal, offer, scope, reference, cancelled_write
                )
            except TaskBasisUnavailable:
                pass
            else:
                raise AssertionError('STOP did not cancel write')
        else:
            try:
                evidence = transfer.publish(
                    source,
                    source_binding,
                    seal,
                    lock.assert_owned,
                    timeout_ms=30000,
                    cancelled=lambda: False,
                )
            except TaskBasisCompletionUnknown as error:
                assert outcome == 'finish_unknown'
                evidence = error.expected
            else:
                assert outcome == 'success'
            assert evidence.document_count == 2
            assert evidence.byte_count == len(originals[0].utf8)
            assert transfer.verify(evidence, timeout_ms=30000, cancelled=lambda: False) == evidence
            rejected('FINISH', {})
        _, stopped = send('STOP', reference=reference)
        assert stopped.status == 'ACKNOWLEDGED' and stopped.result['native']['scope_unlaunched']
        rejected('VERIFY', {})
        _, final = send('OBSERVE', data={'observed_action': 'PREPARE'}, reference=reference)
        assert final.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
        assert final.result['acknowledgement'] is None
        assert final.result['preparation']['directory_state'] == 'UNKNOWN'
    publish(root / 'control-git-pipe-result.json', {'verified': True})
    wait(root / 'stop')


def run_task_file_reservation(root, frames, binding, lock, *, held_receipt):
    from backend.app.infrastructure.guard_action_records import mutation_input_sha256
    from backend.app.infrastructure.guard_task_sources import TaskSourcePins
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard

    parent = root / 'task-source'
    nonce = '1' * 32
    scope = binding.scope(23, 4, NONCE + '-files')
    stop_first = binding.scope(24, 4, NONCE + '-stop-first')
    invalid = binding.scope(25, 4, NONCE + '-bad-files')

    def request(action, *, data=None, reference=None, actual=scope):
        return build_guard_request_header(
            binding,
            lock,
            action=action,
            operation_id=actual.operation_id,
            step_no=actual.step_no,
            nonce=actual.nonce,
            binding_ref=reference,
            action_input={} if data is None else data,
        )

    def send(original):
        return exchange_guard_task_files(
            frames, binding, lock, original, timeout_ms=30000, cancelled=lambda: False
        )

    with ExitStack() as held:
        identities = {}
        for role, path, directory in (
            ('parent', parent, True),
            ('workspace', parent / ('working-' + nonce), True),
            ('workspace_tree', parent / (nonce + '.workspace-tree.json'), False),
            ('basis_seal', parent / (nonce + '.basis-seal.json'), False),
        ):
            identities[role] = held.enter_context(
                LocalPathGuard(path, directory=directory)
            ).verify()
        pins = held.enter_context(TaskSourcePins(identities.pop('parent'), nonce, **identities))
        plan_digest = 'a' * 64
        data = pins.request_data(basis_plan_sha256=plan_digest, reserve_files=True)
        assert (
            send(
                request('PREPARE', data={**data, 'basis_plan_sha256': 'bad'}, actual=invalid)
            ).status
            == 'UNKNOWN'
        )
        prepared = request('PREPARE', data=data)
        assert send(prepared).status == 'UNKNOWN'
        observe_prepare = {'observed_action': 'PREPARE'}
        observation = send(request('OBSERVE', data=observe_prepare))
        original = observation.result
        reference = original['binding_ref']
        assert observation.status == 'OBSERVED'
        assert original['action_phase'] == 'MAY_HAVE_BEEN_SENT'
        assert original['input_sha256'] == mutation_input_sha256(prepared)
        assert original['fence'] is original['acknowledgement'] is original['resource'] is None
        assert original['preparation'] == {
            'binding_ref': reference,
            'run_kind': 'TASK',
            'basis_plan_sha256': plan_digest,
            'directory_state': 'HELD' if held_receipt else 'UNKNOWN',
        }
        assert send(prepared).status == 'UNKNOWN'
        assert (
            send(request('PREPARE', data={**data, 'basis_plan_sha256': 'b' * 64})).status
            == 'UNKNOWN'
        )
        assert (
            send(request('OBSERVE', data=observe_prepare, reference='c' * 32)).status == 'UNKNOWN'
        )
        assert (
            send(request('OBSERVE', data=observe_prepare, reference=reference)).result == original
        )
        assert send(request('STOP', reference='c' * 32)).status == 'UNKNOWN'
        stopped = send(request('STOP', reference=reference))
        assert stopped.status == 'ACKNOWLEDGED' and stopped.result['native']['scope_unlaunched']
        assert send(request('STOP', reference=reference)) == stopped
        after_stop = send(request('OBSERVE', data=observe_prepare, reference=reference)).result
        assert after_stop['fence']['stop_closed'] is True
        assert after_stop['preparation']['directory_state'] == 'UNKNOWN'
        assert send(request('RELEASE', reference=reference)).status == 'UNKNOWN'
        assert send(prepared).status == 'UNKNOWN'
        assert send(request('STOP', actual=stop_first)).status == 'ACKNOWLEDGED'
        assert send(request('PREPARE', data=data, actual=stop_first)).status == 'UNKNOWN'
        pins.verify()
    publish(root / 'control-git-pipe-result.json', {'verified': True})
    wait(root / 'stop')


def capture_command(streams, scope, send, reference, *, body=None, maximum=4096):
    with BoundedOutputCapture(streams, scope=scope, max_output_bytes=maximum) as capture:
        resumed = send('RESUME', reference=reference)
        assert resumed.result['native']['fence']['resume_state'] == 'ACKNOWLEDGED'
        deadline = monotonic() + 10
        writer = None if body is None else OriginalProcessInput(streams)
        offset = 0
        while True:
            if writer is not None:
                if offset < len(body):
                    offset += writer.write_available(body[offset : offset + MAX_TYPED_INPUT_BYTES])
                if offset == len(body):
                    streams.close_input()
                    writer = None
            progress = capture.poll()
            if progress.complete:
                return capture.snapshot()
            if progress.limit_exceeded or monotonic() >= deadline:
                raise RuntimeError('Owned command capture incomplete')
            sleep(0.002)


def run_command(
    scope,
    send,
    export=None,
    *,
    replay_release=True,
    prepare=None,
    body=None,
    maximum=4096,
    expected_exit_code=0,
):
    with BackendStandardIO(scope) as streams:
        stdio = streams.begin_handoff()
        if prepare is not None:
            data = prepare(stdio)
        elif export is not None:
            data = config_prepare_input(stdio, export)
        else:
            data = version_prepare_input(stdio)
        prepared = send('PREPARE', data=data)
        if export is not None:
            assert prepared.result['config_export']['sha256'] == export.sha256
        reference = prepared.result['binding_ref']
        copied = prepared.result['stdio_binding']
        streams.acknowledge_copy(
            GuardStdioBinding(
                NativeProcessIdentity(**copied['owner']),
                LaunchScope(**copied['scope']),
                copied['io_nonce'],
                copied['guard_io_ref'],
            )
        )
        streams.release_child_copies()
        created = send('CREATE_SUSPENDED', reference=reference)
        assert created.result['native']['fence']['create_state'] == 'RESOURCE_RECORDED'
        captured = capture_command(streams, scope, send, reference, body=body, maximum=maximum)
        observed = send('OBSERVE', data={'observed_action': 'RESUME'}, reference=reference)
        assert observed.result['action_phase'] == 'ACKNOWLEDGED'
        process = observed.result['resource']['observation']
        assert process['state'] == 'EXITED' and process['exit_code'] == expected_exit_code
        stopped = send('STOP', reference=reference)
        assert stopped.result['native']['fence']['stop_closed']
        released = send('RELEASE', reference=reference)
        assert released.result['native']['cleanup_verified']
        if replay_release:
            assert send('RELEASE', reference=reference).result == released.result
        return captured, process['exit_code']


def run_candidate_package(root, binding, send):
    from backend.app.infrastructure.content_manifest import ContentLimits
    from backend.app.infrastructure.content_package import (
        CandidatePackageBinding,
        seal_candidate_package,
    )
    from backend.app.infrastructure.content_package_publish import (
        create_candidate_stage,
        publish_candidate_package,
    )
    from backend.app.infrastructure.content_secret_policy import REFERENCE, load_secret_policy
    from backend.app.infrastructure.content_selection import ContentSelection
    from backend.app.infrastructure.git_commit_closure import ClosureLimits
    from backend.app.infrastructure.git_content_command import hold_content_git_source
    from backend.app.infrastructure.guard_control_git_input import content_prepare_input
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_pipe_capture import require_complete_output
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )
    from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceLimits

    content = CandidatePackageBinding(17, 11, 1, '3' * 32, 1, 'sha1')
    source = root / 'candidate-source'
    source.mkdir()
    raw = bytes(range(256)) * 40
    with (source / 'source.bin').open('xb') as file:
        file.write(raw)
    with LocalPathGuard(source, directory=True) as path:
        original = path.verify()
    limits = ContentLimits(16384, 32768, 4, 4096)
    reads = ClosureLimits(64, 64, 16384, 65536, 90)
    numbers = []
    with PrivatePackageGuard(root / 'task-source') as parent:
        store_path = create_private_package(parent.path / 'candidate-store')
        with PrivatePackageGuard(store_path) as store:
            stage = create_candidate_stage(store, content)

            def exchange(intent, repo, body, maximum, remaining):
                assert intent.paths(parent.path)['repository'] == repo
                intent.verify_input(body)
                numbers.append(intent.kind)
                scope = binding.scope(
                    content.operation_id, 2, 'candidate-command-' + str(len(numbers))
                )
                with hold_content_git_source(parent, intent) as pins:
                    output, code = run_command(
                        scope,
                        lambda action, **kwargs: send(
                            action,
                            scope_override=scope,
                            content_parent=parent.verify(),
                            **kwargs,
                        ),
                        replay_release=False,
                        body=body,
                        maximum=maximum,
                        prepare=lambda stdio: content_prepare_input(
                            stdio,
                            intent,
                            pins,
                            expected_parent=parent.verify(),
                        ),
                    )
                return require_complete_output(
                    output,
                    scope=scope,
                    io_nonce=output.progress.io_nonce,
                    exit_code=code,
                    max_output_bytes=maximum,
                ).stdout

            with PrivatePackageGuard(stage) as package:
                seal = seal_candidate_package(
                    package,
                    content,
                    source_path=source,
                    source_identity=original,
                    selection=ContentSelection(
                        product_include_paths=['.'],
                        nonproduct_exclude_paths=[],
                        new_file_mode='100644',
                        baseline_entries=[],
                    ),
                    secret_policy=load_secret_policy(REFERENCE),
                    workspace_limits=CandidateWorkspaceLimits(limits, 64, 512, 90),
                    git_limits=reads,
                    started_at=monotonic(),
                    quiescent=lambda: None,
                    exchange=exchange,
                    materialization_root=root / 'check',
                )
            published = publish_candidate_package(
                store,
                content,
                limits=limits,
                git_limits=reads,
                started_at=monotonic(),
                active=lambda: None,
                materialization_root=root / 'check',
                expected=seal,
            )
            assert published.seal.manifest.byte_count == len(raw)
    publish(
        root / 'control-git-pipe-result.json',
        {'commands': numbers, 'sha256': hashlib.sha256(raw).hexdigest()},
    )
    wait(root / 'stop')


def fixture_project_admission(*, missing=False):
    from backend.app.code_tasks.coding_project_check_scope import CodingProjectCheckAdmission
    from backend.app.infrastructure.idempotency import canonical_input
    from backend.tests.infrastructure.test_v20_check_runner_bundle import document
    from backend.tests.infrastructure.test_v20_windows_lpac_profile import check_definition

    return CodingProjectCheckAdmission(
        'fixture:project-runner',
        hashlib.sha256(canonical_input(document()).encode()).hexdigest(),
        (),
        check_definition(timeout_seconds=30, missing=missing),
        2,
        128 * 1024 * 1024,
    )


def seed_candidate_capture(root, database, *, project_check=False, multi=False, handoff=False):
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from backend.app.code_tasks import task_start, task_start_workspace
    from backend.app.code_tasks.task_instance_driver import CaptureTurnEvidence
    from backend.app.code_tasks.task_model_ingress import ModelWindow
    from backend.app.code_tasks.task_start_basis import advance_start_basis
    from backend.app.code_tasks.task_start_instance import advance_start_instance
    from backend.app.code_tasks.task_start_session import advance_start_session
    from backend.app.infrastructure.content_secret_policy import REFERENCE
    from backend.app.infrastructure.idempotency import canonical_input
    from backend.app.infrastructure.opencode_instance_control import NativeTurnCompletion
    from backend.app.infrastructure.windows_local_paths import LocalPathGuard
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.service import create_app
    from backend.tests.code_tasks import test_task_stop
    from backend.tests.code_tasks.test_execution_profile_versions import (
        body,
        fixture_snapshot,
        resources,
    )
    from backend.tests.code_tasks.test_execution_profile_versions import (
        publish as publish_profile,
    )
    from backend.tests.code_tasks.test_task_capture_quiescence import _capture_operation
    from backend.tests.code_tasks.test_task_start_basis import prepare
    from backend.tests.code_tasks.test_task_start_instance import _evidence
    from backend.tests.code_tasks.test_task_start_session import NativeDriver

    profile = body()
    if handoff:
        profile['executor']['runtime_bundle_ref'] = 'opencode-bundle:sha256:' + 'a' * 64
    profile['capture_rules']['secret_policy_ref'] = REFERENCE
    profile['limits'].update(
        max_manifest_bytes=4096,
        max_git_output_bytes=65536,
        max_file_bytes=32768,
        max_snapshot_bytes=32768,
    )
    from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
        check_definition,
        check_limits,
    )
    from backend.tests.infrastructure.v20_coding_repair_worker import seed_flat_model_price

    seed_price = seed_flat_model_price if handoff else test_task_stop.seed_price
    stages = ['BACKEND', 'FRONTEND', 'INTEGRATION'] if handoff else ['BACKEND']
    active_limit = 1200 if handoff else 240
    definitions = [check_definition(timeout_seconds=30)]
    if multi:
        definitions.append(check_definition(timeout_seconds=30, missing=True))
    if project_check:
        limits, _ = check_limits()
        profile['limits'].update(asdict(limits), max_active_seconds=active_limit)
        profile['commands'] = [json.loads(json.dumps(asdict(part))) for part in definitions]
    snapshot = fixture_snapshot(profile)
    parents = test_task_stop.parents
    default_scope = test_task_stop.scope

    def configured_parents(client):
        from uuid import uuid4

        from backend.tests.code_tasks.test_check_set_content import (
            body as check_body,
        )
        from backend.tests.code_tasks.test_check_set_content import (
            command,
            integrity,
        )

        for path in ('/api/v1/code-execution-profiles', '/api/v1/code-check-sets'):
            response = client.post(
                path, json={'name': '隔离自检'}, headers={'Idempotency-Key': str(uuid4())}
            )
            assert response.status_code == 201, response.text
        check_set = check_body(
            [
                integrity(runner_ref='fixture:project-runner', stages=stages),
                *(
                    {
                        **command(runner_ref='fixture:project-runner', timeout_seconds=30),
                        'check_id': f'project-{index + 1}',
                        'stages': stages,
                        'command_id': part.command_id,
                        'required': index == 0,
                    }
                    for index, part in enumerate(definitions)
                ),
            ],
            [],
        )
        with resources(snapshot):
            response = client.post(
                '/api/v1/code-check-sets/1/versions',
                json=check_set,
                headers={'Idempotency-Key': str(uuid4())},
            )
        assert response.status_code == 201, response.text

    def configured_scope():
        original = default_scope()
        return {
            **original,
            'limits': {
                **{
                    key: min(value, profile['limits'][key])
                    for key, value in original['limits'].items()
                },
                **{
                    key: profile['limits'][key]
                    for key in (
                        'max_file_bytes',
                        'max_snapshot_bytes',
                        'max_snapshot_files',
                        'max_capture_entries',
                        'max_capture_seconds',
                        'max_manifest_bytes',
                        'max_git_seconds',
                        'max_git_output_bytes',
                    )
                },
                'max_git_seconds': min(15, profile['limits']['max_git_seconds'])
                if handoff
                else profile['limits']['max_git_seconds'],
                'max_active_seconds': active_limit,
            },
            'allowed_command_ids': [part.command_id for part in definitions],
        }

    if handoff:
        for kind in ('MODEL', 'CAPABILITY', 'PRICE'):
            snapshot[kind][0]['ready'] = True
    if project_check:
        for command_resource in snapshot['COMMAND']:
            command_resource['ready'] = True
        snapshot['RUNNER'] = [
            {
                'ready': True,
                'value': {
                    'runner_ref': 'fixture:project-runner',
                    'protocol_version': 'CHECK20-CONTROL-1',
                    'capabilities': ['CLI', 'CONTENT_INTEGRITY'],
                    'protected_input_refs': [],
                },
            }
        ]
    source = root / 'candidate-source'
    source.mkdir()
    raw = b'WALLE\xff\0\r\n' if project_check else bytes(range(256)) * 40
    path = source / ('src/input.bin' if project_check else 'source.bin')
    if project_check:
        path.parent.mkdir()
    with path.open('xb') as file:
        file.write(raw)
    with LocalPathGuard(source, directory=True) as path:
        identity = path.verify()

    class Driver:
        def start(self, original, checkpoint, *, cancelled):
            checkpoint()
            return _evidence(original.claim)

        def observe_capture_turn(self, scope, window, ref, checkpoint):
            checkpoint()
            return CaptureTurnEvidence(
                NativeTurnCompletion(
                    window.native_session_id, window.trigger_message_id, 'msg_done', 'COMPLETED'
                ),
                'c' * 64,
                1,
                identity,
            )

    driver = Driver()
    with (
        TestClient(create_app(database=database)) as client,
        PrivatePackageGuard(root / 'task-source') as parent,
        patch.object(test_task_stop, 'resources', lambda: resources(snapshot)),
        patch.object(test_task_stop, 'parents', configured_parents if project_check else parents),
        patch.object(test_task_stop, 'scope', configured_scope if project_check else default_scope),
        patch.object(test_task_stop, 'publish', lambda client: publish_profile(client, profile)),
        patch.object(test_task_stop, 'seed_price', seed_price),
        patch.object(task_start, '_check_start_readiness', lambda *args: None),
        patch.object(task_start_workspace, '_check_start_readiness', lambda *args: None),
    ):
        app = client.app
        runtime = app.state.walle_runtime
        task_id, _, _, _, receipt = prepare(database, app, client, parent)
        assert advance_start_basis(runtime, parent, cancelled=lambda: False)
        with database.transaction(write=True) as connection:
            at = connection.execute(
                'SELECT ended_at FROM code_operation_steps WHERE operation_id=? AND step_no=2',
                (receipt['operation_id'],),
            ).fetchone()[0]
            facts = {
                'fixed_content_verified': True,
                'capability_codes': [],
                'system_config_clear': True,
                'runtime_launch_admission': True,
            }
            connection.execute(
                """UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,
                   ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=3""",
                (canonical_input(facts), at, at, at, receipt['operation_id']),
            )
        assert advance_start_instance(runtime, parent, cancelled=lambda: False, driver=driver)

        class ProjectNativeDriver(NativeDriver):
            def create_session(self, scope, checkpoint):
                from backend.app.code_tasks.task_initial_configuration import (
                    InitialConfigurationObservation,
                    InitialNativeSession,
                )

                return InitialNativeSession(
                    super().create_session(scope, checkpoint),
                    InitialConfigurationObservation(
                        'opencode-bundle:sha256:' + 'a' * 64, 'e' * 64, 'f' * 64, 'test-agent'
                    ),
                )

        native = ProjectNativeDriver() if project_check else NativeDriver()
        assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=native)
        assert advance_start_session(runtime, parent, cancelled=lambda: False, driver=native)
        scope = native.calls[-1][1]
        window = ModelWindow(
            task_id,
            scope.instance_id,
            scope.control_generation,
            scope.session_id,
            'ses_original',
            receipt['operation_id'],
            'msg_original',
        )
        if project_check:
            from types import SimpleNamespace
            from uuid import uuid4

            task_path = f'/api/v1/code-tasks/{task_id}'
            current = client.get(task_path)
            assert current.status_code == 200, current.text
            state = current.json()['data']['state_version']
            path = task_path + '/candidates'
            body = {'purpose': 'HANDOFF', 'expected_state_version': state}
            key = str(uuid4())
            headers = {'Idempotency-Key': key}
            assert (
                client.post(
                    path, json={**body, 'purpose': 'ACCEPTANCE'}, headers=headers
                ).status_code
                == 422
            )
            not_ready = client.post(path, json=body, headers=headers)
            assert (
                not_ready.status_code == 503
                and not_ready.json()['error']['code'] == 'CONFIG_NOT_READY'
            ), not_ready.text
            app.state.walle_repository_registration = SimpleNamespace(
                accepts_candidate_capture=True,
                project_check_admissions=tuple(
                    fixture_project_admission(missing=index != 0)
                    for index in range(len(definitions))
                ),
                wake=lambda: None,
            )
            with resources(snapshot):
                response = client.post(path, json=body, headers=headers)
            assert response.status_code == 202, response.text
            original = response.json()['data']
            operation = original['operation_id']
            assert client.post(path, json=body, headers=headers).json()['data'] == original
            running = client.get(task_path)
            assert running.status_code == 200, running.text
            assert running.json()['data']['active_operations'] == [
                {
                    'id': operation,
                    'status': 'PENDING',
                    'operation_type': 'CAPTURE_AND_CHECK',
                }
            ]
            conflict = client.post(
                path,
                json={**body, 'expected_state_version': state + 1},
                headers={'Idempotency-Key': str(uuid4())},
            )
            assert (
                conflict.status_code == 409
                and conflict.json()['error']['code'] == 'OPERATION_CONFLICT'
            ), conflict.text
            receipt = client.get(
                '/api/v1/code-command-receipts',
                params={'method': 'POST', 'path': path, 'request_key': key},
            )
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()['data']['original_outcome']['data'] == original
        else:
            operation = _capture_operation(database, window)
    return (driver, operation, raw, snapshot) if project_check else (driver, operation, raw)


def run_durable_candidate(root, database, lock, frames, binding, fixture, *, lost_result=False):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import patch

    from backend.app.code_tasks.task_candidate_git import CandidateGitDispatch
    from backend.app.code_tasks.task_candidate_runtime import reconcile_original_candidate
    from backend.app.code_tasks.task_candidate_worker import CandidateCaptureWorker
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )

    driver, operation, raw = fixture
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, commands=lambda: executor)

    @contextmanager
    def connected_frames():
        yield frames

    with (
        PrivatePackageGuard(root / 'task-source') as parent,
        LaunchJournal(create_private_package(root / 'candidate-evidence')) as journal,
    ):
        worker = CandidateCaptureWorker(
            runtime,
            driver,
            parent,
            binding,
            journal,
            connected_frames,
            cancelled=lambda: False,
            cleanup_timeout_ms=30000,
        )
        assert worker.advance()
        if lost_result:
            with patch.object(CandidateGitDispatch, '_complete', side_effect=OSError('lost write')):
                assert worker.advance()
            assert worker.has_retained_command
            worker._dispatch._run.close()

            def unexpected_connection():
                raise AssertionError('Released original must be reconciled from private records')

            worker = CandidateCaptureWorker(
                runtime,
                driver,
                parent,
                binding,
                journal,
                unexpected_connection,
                cancelled=lambda: False,
                cleanup_timeout_ms=30000,
            )
            assert worker.advance()
            with database.transaction() as connection:
                row = connection.execute(
                    """SELECT status,exit_code,process_identity,runtime_binding
                       FROM code_commands WHERE operation_id=?""",
                    (operation,),
                ).fetchone()
                assert (row['status'], row['exit_code']) == ('FAILED', 0)
                assert json.loads(row['process_identity'])['pid'] > 0
                assert json.loads(row['runtime_binding'])['run_kind'] == 'CONTROL_GIT'
                assert (
                    connection.execute(
                        'SELECT status FROM code_operations WHERE id=?', (operation,)
                    ).fetchone()[0]
                    == 'UNKNOWN'
                )
                assert (
                    connection.execute(
                        'SELECT 1 FROM code_candidates WHERE capture_operation_id=?', (operation,)
                    ).fetchone()
                    is None
                )
            assert worker.advance()
            assert not worker.advance()
            publish(
                root / 'control-git-pipe-result.json',
                {'commands': 1, 'sha256': hashlib.sha256(raw).hexdigest()},
            )
            wait(root / 'stop')
            return
        assert worker.advance()
        assert not worker.has_retained_command
        assert not worker.advance()
        with database.transaction() as connection:
            candidate = connection.execute(
                'SELECT id FROM code_candidates WHERE capture_operation_id=?',
                (operation,),
            ).fetchone()[0]
        with PrivatePackageGuard(parent.path / 'candidate-store') as store:
            assert (
                reconcile_original_candidate(
                    runtime,
                    operation,
                    store=store,
                    materialization_root=root / 'check',
                    cancelled=lambda: False,
                )
                == candidate
            )
    with database.transaction() as connection:
        rows = connection.execute(
            'SELECT status,exit_code,runtime_binding FROM code_commands WHERE operation_id=? ORDER BY id',
            (operation,),
        ).fetchall()
        assert len(rows) == 7
        assert all(row['status'] == 'SUCCEEDED' and row['exit_code'] == 0 for row in rows)
        assert all(json.loads(row['runtime_binding'])['run_kind'] == 'CONTROL_GIT' for row in rows)
        row = connection.execute(
            'SELECT file_count,byte_count FROM code_candidates WHERE id=?', (candidate,)
        ).fetchone()
        assert tuple(row) == (1, len(raw))
    publish(
        root / 'control-git-pipe-result.json',
        {'commands': len(rows), 'sha256': hashlib.sha256(raw).hexdigest()},
    )
    wait(root / 'stop')


def export_original_config(root, scope):
    with RepositoryLocationLease(
        root / 'source.git',
        private_roots=(root / 'private',),
        max_file_bytes=4096,
        max_open_handles=256,
        max_metadata_entries=4096,
    ) as location:
        source, descriptor = open_config_export(location, scope)
        try:
            assert source._handle != location.config_source._handle
            publish(root / 'config-export.json', asdict(descriptor))
            wait(root / 'config-copied')
            original = location.config_source.verify()
            publish(root / 'original-config-verified.json', {'sha256': original.sha256})
        finally:
            source.close()


def export_original_metadata_directories(root, scope):
    import ctypes

    from backend.app.infrastructure.guard_git_metadata_source import export_metadata_directories
    from backend.app.infrastructure.windows_stdio import _handle_text

    with (
        RepositoryLocationLease(
            root / 'source.git',
            private_roots=(root / 'private',),
            max_file_bytes=4096,
            max_open_handles=256,
            max_metadata_entries=4096,
        ) as location,
        export_metadata_directories(location, scope) as descriptor,
    ):
        kernel = location._kernel
        list_handle = kernel.CreateFileW(
            '\\\\?\\' + str(root / 'source.git'), 0x81, 3, None, 3, 0x02000000, None
        )
        assert list_handle and list_handle != ctypes.c_void_p(-1).value
        try:
            publish(
                root / 'metadata-directory-export.json',
                {
                    **asdict(descriptor),
                    'list_handle': _handle_text(list_handle),
                },
            )
            wait(root / 'metadata-directories-copied')
            publish(
                root / 'metadata-directories-verified.json',
                {
                    'location_sha256': location.verify().fingerprint_sha256,
                },
            )
        finally:
            assert kernel.CloseHandle(list_handle)


def run_config_parse(root, scope, send):
    with RepositoryLocationLease(
        root / 'source.git',
        private_roots=(root / 'private',),
        max_file_bytes=4096,
        max_open_handles=256,
        max_metadata_entries=4096,
    ) as location:
        original = location.verify()
        source, export = open_config_export(location, scope)
        try:
            captured, exit_code = run_command(scope, send, export)
            assert location.verify() == original
            parsed = parse_original_config_output(
                captured,
                location,
                scope=scope,
                io_nonce=captured.progress.io_nonce,
                exit_code=exit_code,
                max_output_bytes=4096,
                max_entries=128,
            )
            return {
                'object_format': parsed.local.object_format,
                'bare': parsed.local.bare,
                'stderr': captured.stderr.hex(),
            }
        finally:
            source.close()


def observation_request(root, database, object_format):
    from types import SimpleNamespace
    from uuid import uuid4

    from backend.app.code_tasks.command_registry import registered_command
    from backend.app.shared.command_execution import operation_time

    root_path = str(root / 'repository')
    common = str(root / 'repository' / '.git')
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
            ('owned-metadata-fixture', root_path, common, object_format, operation_time(None)),
        )
    command = registered_command('POST', '/api/v1/code-repositories/1/refresh', str(uuid4()))
    return SimpleNamespace(
        command=command,
        idempotency_key=command.key,
        repository_id=1,
        business_input=lambda: {'repository_id': 1},
    )


def observation_dispatch(root, database, lock, frames, binding, owners, object_format):
    from types import SimpleNamespace

    from backend.app.code_tasks.repository_acceptance import accept_repository_operation
    from backend.app.code_tasks.repository_git_dispatch import ObservationGitDispatch
    from backend.app.code_tasks.repository_observation_publish import start_repository_observation
    from backend.app.infrastructure.database import StorageUnavailable
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
    from backend.app.infrastructure.windows_private_package import create_private_package

    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, commands=lambda: executor)
    request = observation_request(root, database, object_format)
    accepted = accept_repository_operation(runtime, request)
    operation_id = accepted['data']['operation_id']
    started = start_repository_observation(runtime, operation_id)
    assert (started.root, started.common_directory, started.object_format) == (
        str(root / 'repository'),
        str(root / 'repository' / '.git'),
        object_format,
    )
    journal = owners.enter_context(
        LaunchJournal(create_private_package(root / 'backend-metadata-evidence'))
    )
    dispatcher = ObservationGitDispatch(runtime, frames, binding, journal)
    owners.callback(dispatcher.close)
    scopes = dispatcher.reserve(operation_id)
    assert dispatcher.original(operation_id) == scopes
    try:
        dispatcher.reserve(operation_id)
    except StorageUnavailable as error:
        assert 'require observation' in str(error)
    else:
        raise AssertionError('Observation scope reservation was repeated')
    return dispatcher, scopes, request


def run_observation_queue(root, frames, binding, dispatcher, original):
    from uuid import uuid4

    from backend.app.code_tasks.command_registry import registered_command
    from backend.app.code_tasks.repository_acceptance import accept_repository_operation
    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.code_tasks.repository_observation_publish import publish_repository_observation
    from backend.app.code_tasks.repository_registration_actor import RepositoryRegistrationActor

    runtime = dispatcher._runtime
    original.command = registered_command(
        'POST', '/api/v1/code-repositories/1/refresh', str(uuid4())
    )
    original.idempotency_key = original.command.key
    accepted = accept_repository_operation(runtime, original)
    operation_id = accepted['data']['operation_id']
    actor = RepositoryRegistrationActor(
        runtime,
        binding,
        dispatcher._journal,
        private_roots=(root / 'private',),
        limits=RegistrationReadLimits(65536, 1000, 20000, 1024 * 1024, 4096, 120),
    )
    assert actor.has_work()
    outcome = actor.run_next(frames, cancelled=lambda: False)
    assert outcome.operation_id == operation_id
    assert publish_repository_observation(runtime, operation_id) == outcome.observation_id
    assert accept_repository_operation(runtime, original) == accepted
    assert not actor.has_work()
    actor.close()
    return outcome.observation_id


def run_metadata_pair(root, scopes, send, dispatcher):
    import json
    from dataclasses import replace
    from functools import partial
    from uuid import uuid4

    from backend.app.code_tasks.repository_observation_publish import publish_repository_observation
    from backend.app.infrastructure.database import StorageUnavailable
    from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
    from backend.app.infrastructure.guard_control_git_input import repository_read_prepare_input
    from backend.app.infrastructure.guard_git_metadata_source import export_metadata_directories
    from backend.app.infrastructure.runtime_launch_journal import LaunchFence
    from backend.app.infrastructure.windows_pipe_capture import OutputCaptureError

    config_scope, worktrees_scope, branches_scope = (item.scope for item in scopes)
    private = root / 'private'
    with RepositoryLocationLease(
        root / 'repository',
        private_roots=(private,),
        max_file_bytes=65536,
        max_open_handles=4096,
        max_metadata_entries=4096,
    ) as location:
        config_source, config = open_config_export(location, config_scope)
        with config_source:
            captured, exit_code = run_command(
                config_scope,
                partial(send, scope_override=config_scope, dispatcher=dispatcher),
                config,
                replay_release=False,
            )
            parsed = parse_original_config_output(
                captured,
                location,
                scope=config_scope,
                io_nonce=captured.progress.io_nonce,
                exit_code=exit_code,
                max_output_bytes=4096,
                max_entries=128,
            )
        with RepositoryMetadataLease(
            location,
            format=parsed.local.object_format,
            max_entries=1000,
            max_open_handles=20000,
            max_file_bytes=65536,
            max_metadata_bytes=1024 * 1024,
        ) as metadata:

            def read(kind, original, *, invalid=False, out_of_order=False):
                source, export = open_config_export(location, original)
                with source, export_metadata_directories(location, original) as directories:

                    def prepare(stdio):
                        return repository_read_prepare_input(
                            stdio, directories, export, parsed, metadata, kind=kind
                        )

                    if out_of_order:
                        with BackendStandardIO(original) as streams:
                            data = prepare(streams.descriptor())
                            try:
                                send(
                                    'PREPARE',
                                    data=data,
                                    scope_override=original,
                                    dispatcher=dispatcher,
                                )
                            except StorageUnavailable as error:
                                assert 'previous Git cleanup' in str(error)
                            else:
                                raise AssertionError(
                                    'Branches dispatched before the original worktree query'
                                )
                        return
                    if invalid:
                        with BackendStandardIO(original) as streams:
                            data = prepare(streams.begin_handoff())
                            data['metadata']['config_io_nonce'] = str(uuid4())
                            reply = send('PREPARE', data=data, scope_override=original)
                            assert reply.status == 'UNKNOWN'
                            stopped = send('STOP', scope_override=original)
                            fence = stopped.result['native']['fence']
                            assert fence['create_state'] == 'NONE'
                            streams.acknowledge_closed_scope(
                                LaunchFence(**{**fence, 'scope': original})
                            )
                            return

                    output, _ = run_command(
                        original,
                        partial(send, scope_override=original, dispatcher=dispatcher),
                        export,
                        prepare=prepare,
                        replay_release=False,
                    )
                return output

            read('WORKTREES', replace(config_scope, nonce=uuid4().hex), invalid=True)
            read('LOCAL_BRANCHES', branches_scope, out_of_order=True)
            trees = read('WORKTREES', worktrees_scope)
            branches = read('LOCAL_BRANCHES', branches_scope)
            for original in scopes:
                release = dispatcher.read_action(original, 'RELEASE', 'ACKNOWLEDGED')
                assert release['result']['native']['cleanup_verified'] is True
            operation_id = config_scope.operation_id
            limits = {
                'private_roots': (private,),
                'max_file_bytes': 65536,
                'max_open_handles': 20000,
                'max_output_bytes': 4096,
            }
            try:
                dispatcher.publish_observation(
                    operation_id,
                    metadata,
                    parsed,
                    worktrees_output=branches,
                    branches_output=trees,
                    **limits,
                )
            except OutputCaptureError:
                pass
            else:
                raise AssertionError('Original command outputs were interchangeable')
            runtime = dispatcher._runtime
            with runtime.database.transaction() as connection:
                assert (
                    connection.execute(
                        'SELECT count(*) FROM code_repository_observations'
                    ).fetchone()[0]
                    == 0
                )
                assert [
                    row[0]
                    for row in connection.execute(
                        'SELECT status FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                        (operation_id,),
                    )
                ] == ['RUNNING', 'PENDING']
            observation_id = dispatcher.publish_observation(
                operation_id,
                metadata,
                parsed,
                worktrees_output=trees,
                branches_output=branches,
                **limits,
            )
            assert publish_repository_observation(runtime, operation_id) == observation_id
            with runtime.database.transaction() as connection:
                data = connection.execute(
                    'SELECT * FROM code_repository_observations WHERE id=? AND operation_id=?',
                    (observation_id, operation_id),
                ).fetchone()
                status = connection.execute(
                    'SELECT status FROM code_operations WHERE id=?', (operation_id,)
                ).fetchone()[0]
                assert status == 'SUCCEEDED'
            return {
                'format': parsed.local.object_format,
                'original_operation': operation_id,
                'observation_id': observation_id,
                'head_commit': data['head_commit'],
                'branches': [row['full_ref'] for row in json.loads(data['local_branches'])],
                'worktrees': len(json.loads(data['worktrees'])),
            }


def registration_request(root):
    from types import SimpleNamespace
    from uuid import uuid4

    from backend.app.code_tasks.command_registry import registered_command

    command = registered_command('POST', '/api/v1/code-repositories', str(uuid4()))
    return SimpleNamespace(
        command=command,
        idempotency_key=command.key,
        business_input=lambda: {
            'name': 'actual-pipe-repository',
            'root_path': str(root / 'source.git'),
        },
    )


def registration_actor(root, binding, lock, owners, database):
    from types import SimpleNamespace

    from backend.app.code_tasks.repository_acceptance import accept_repository_operation
    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.code_tasks.repository_registration_actor import RepositoryRegistrationActor
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
    from backend.app.infrastructure.windows_private_package import create_private_package

    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, commands=lambda: executor)
    request = registration_request(root)
    receipt = accept_repository_operation(runtime, request)
    operation_id = receipt['data']['operation_id']
    journal = owners.enter_context(
        LaunchJournal(create_private_package(root / 'backend-git-evidence'))
    )
    actor = RepositoryRegistrationActor(
        runtime,
        binding,
        journal,
        private_roots=(root / 'private', journal.root),
        limits=RegistrationReadLimits(4096, 4096, 4096, 1024 * 1024, 4096, 30),
    )
    return actor, runtime, request, operation_id


def exercise_task_stop(database, client, task_id):
    from time import monotonic, sleep
    from unittest.mock import patch
    from uuid import uuid4

    from backend.app.code_tasks import task_stop

    path = f'/api/v1/code-tasks/{task_id}/terminate'
    detail = f'/api/v1/code-tasks/{task_id}'
    original_key, repeat_key = str(uuid4()), str(uuid4())
    body = {'expected_state_version': 1, 'reason': 'isolated private stop reason'}

    def post(key, value):
        return client.post(path, json=value, headers={'Idempotency-Key': key})

    bad = post(str(uuid4()), {'expected_state_version': 3})
    assert bad.status_code == 409 and bad.json()['error']['code'] == 'VERSION_CONFLICT', bad.text
    assert post(str(uuid4()), {'expected_state_version': 1, 'reason': None}).status_code == 422
    with patch.object(task_stop, 'advance_pending_stops', lambda runtime: False):
        accepted = post(original_key, body)
        assert accepted.status_code == 202, accepted.text
        pending = accepted.json()['data']
        operation_id = pending['operation_id']
        assert pending == {
            'task_id': task_id,
            'operation_id': operation_id,
            'operation_status': 'PENDING',
            'task_status': 'STOPPING',
            'state_version': 2,
        }
        repeat = post(repeat_key, {'expected_state_version': 1})
        assert repeat.status_code == 202 and repeat.json()['data'] == pending, repeat.text
        conflict = post(original_key, {'expected_state_version': 2})
        assert (
            conflict.status_code == 409 and conflict.json()['error']['code'] == 'OPERATION_CONFLICT'
        )
        waiting = client.get(detail)
        assert waiting.status_code == 200, waiting.text
        state = waiting.json()['data']
        assert state['status'] == 'STOPPING' and state['termination_operation_id'] == operation_id
        assert state['runtime']['active_process_count'] is None
        assert state['runtime']['cleanup_status'] == 'NOT_STARTED'
        raw = client.get(f'/api/v1/code-operations/{operation_id}')
        assert raw.status_code == 200 and raw.json()['data']['status'] == 'PENDING', raw.text
        assert 'isolated private stop reason' not in raw.text
    deadline = monotonic() + 8
    while True:
        finished = client.get(detail)
        assert finished.status_code == 200, finished.text
        final = finished.json()['data']
        if final['status'] == 'TERMINATED':
            break
        assert monotonic() < deadline, finished.text
        sleep(0.1)
    assert final['state_version'] == 3 and final['control_generation'] == 2
    assert final['runtime']['activity_status'] == 'NOT_STARTED'
    assert final['runtime']['stop_status'] == final['runtime']['cleanup_status'] == 'VERIFIED'
    assert final['runtime']['active_process_count'] == 0
    raw = client.get(f'/api/v1/code-operations/{operation_id}')
    assert raw.status_code == 200, raw.text
    original = raw.json()['data']
    assert original['status'] == 'SUCCEEDED'
    assert all(step['status'] == 'SUCCEEDED' for step in original['steps'])
    assert set(original['steps'][3]['result_ref']) == {
        'stop_observation_id',
        'cleanup_observation_id',
    }
    assert 'CODE20-EMPTY-STOP-1' not in raw.text and 'evidence_ref' not in raw.text
    for key, value in ((original_key, body), (repeat_key, {'expected_state_version': 1})):
        same = post(key, value)
        assert same.status_code == 202 and same.json()['data'] == pending, same.text
        receipt = client.get(
            '/api/v1/code-command-receipts',
            params={
                'method': 'POST',
                'path': path,
                'request_key': key,
            },
        )
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()['data']['operation_id'] == operation_id
    repeated = post(str(uuid4()), {'expected_state_version': 1})
    assert repeated.status_code == 200 and repeated.json()['data'] == final, repeated.text
    with database.transaction() as connection:
        observations = connection.execute(
            """SELECT kind,result,instance_id,command_id,active_process_count
               FROM code_runtime_observations ORDER BY id"""
        ).fetchall()
        assert [tuple(row) for row in observations] == [
            ('STOP', 'VERIFIED', None, None, 0),
            ('CLEANUP', 'VERIFIED', None, None, 0),
        ]
        assert (
            connection.execute(
                'SELECT count(*) FROM code_operations WHERE task_id=?', (task_id,)
            ).fetchone()[0]
            == 1
        )
        assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM code_commands').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def exercise_fixed_task_creation(
    root, database, app, client, snapshot, observed_connections, *, start_workspace=False
):
    from concurrent.futures import ThreadPoolExecutor
    from copy import deepcopy
    from uuid import uuid4

    from backend.tests.code_tasks.test_authorizations import approve, scope
    from backend.tests.code_tasks.test_execution_profile_versions import fixture_snapshot, resources
    from backend.tests.documents.test_v15_documents import document, metadata
    from backend.tests.documents.test_v15_editing import candidate, finish, save, start
    from backend.tests.infrastructure.test_v20_command_http import close
    from backend.tests.requirements.test_v15_foundation import create

    runtime = app.state.walle_runtime
    workspace = (database, runtime.commands(), runtime.catalog)
    create(runtime.commands())
    main = document(workspace, kind='DESIGN')['data']
    material = document(workspace, kind='DESIGN', name='测试用固定材料')['data']
    main_id = main['document']['id']
    material_id = material['document']['id']

    def edit(version, text):
        draft = start(workspace, identity=main_id, version=version)['data']['manual_draft']
        saved = save(workspace, draft, candidate(workspace, draft, text))
        assert saved['code'] == 'DRAFT_SAVED', saved
        completed = finish(workspace, saved['data'])
        assert completed['code'] == 'DRAFT_COMPLETED', completed
        return completed['data']['revision_id']

    fixed = edit(1, '固定设计\n')
    for doc_id, version, revision in (
        (main_id, 2, fixed),
        (material_id, 1, material['revision_id']),
    ):
        confirmed = metadata(
            workspace,
            doc_id,
            1,
            {'type': 'CONFIRM', 'expected_content_version': version, 'revision_id': revision},
        )
        assert confirmed['code'] == 'UPDATED', confirmed
    latest = edit(2, '新版仍未确认\n')

    profile = client.get('/api/v1/code-execution-profile-versions/1')
    assert profile.status_code == 200, profile.text
    profile = profile.json()['data']
    grant_scope = scope()
    grant_scope['limits'] = deepcopy(profile['limits'])
    with resources(fixture_snapshot(profile)):
        grant = approve(client, {'profile_version_id': 1, 'scope': grant_scope})
    assert grant.status_code == 201, grant.text
    authorization_id = grant.json()['data']['resource_id']
    path = f'/api/v1/documents/{main_id}/code-tasks'
    body = {
        'design_revision_id': fixed,
        'material_refs': [{'document_id': material_id, 'revision_id': material['revision_id']}],
        'repository_id': 1,
        'base_snapshot_id': snapshot,
        'target_branch': 'refs/heads/main',
        'execution_profile_version_id': 1,
        'authorization_id': authorization_id,
        'budget_limit_cny': '0.01',
    }

    def post(value=body, key=None):
        return client.post(path, json=value, headers={'Idempotency-Key': key or str(uuid4())})

    assert post({**body, 'budget_limit_cny': 0.01}).status_code == 422
    assert (
        post(
            {**body, 'material_refs': [{'document_id': main_id, 'revision_id': fixed}]}
        ).status_code
        == 422
    )
    assert post({**body, 'base_snapshot_id': 999}).status_code == 404
    closed = str(uuid4())
    assert close(client, {'method': 'POST', 'path': path, 'request_key': closed}).status_code == 200
    assert post(key=closed).json()['error']['code'] == 'COMMAND_CLOSED'
    assert observed_connections() == 6

    empty = client.get(path).json()
    assert empty['data']['items'] == [] and empty['meta']['pagination']['total'] == 0
    keys = [str(uuid4()), str(uuid4())]
    with resources(fixture_snapshot(profile)), ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [(key, pool.submit(post, key=key)) for key in keys]
        results = [(key, result.result()) for key, result in attempts]
    assert sorted(result.status_code for _, result in results) == [201, 409], [
        result.text for _, result in results
    ]
    (key, response), (_, competing) = sorted(results, key=lambda item: item[1].status_code)
    assert competing.json()['error']['code'] == 'ACTIVE_TASK_EXISTS', competing.text
    initial = response.json()['data']
    assert initial['status'] == 'PENDING' and initial['phase'] == 'PREPARING'
    assert initial['workspace_id'] is None and initial['active_session_id'] is None
    assert initial['current_basis_difference'] == [
        {'document_id': main_id, 'fixed_revision_id': fixed, 'current_revision_id': latest}
    ]
    assert initial['material_refs'] == body['material_refs']
    assert initial['budget']['available_cny'] == '0.010000'
    assert initial['runtime']['active_process_count'] is None
    assert initial['runtime']['environment_status'] == 'NOT_PREPARED'
    assert initial['available_actions'][0]['reason_code'] == 'CONFIG_NOT_READY'

    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={'method': 'POST', 'path': path, 'request_key': key},
    )
    assert receipt.status_code == 200, receipt.text
    original = receipt.json()['data']
    assert original['task_id'] == initial['id'] and original['operation_id'] is None
    assert original['original_http_status'] == 201
    assert original['original_outcome']['data'] == initial
    assert observed_connections() == 8
    assert competing.json()['error']['details']['task_id'] == initial['id']

    listed = client.get(
        path + f'?status=PENDING&status=PENDING&status=RUNNING&design_revision_id={fixed}'
    )
    assert listed.status_code == 200, listed.text
    (summary,) = listed.json()['data']['items']
    assert summary == {
        field: initial[field]
        for field in (
            'id',
            'document_id',
            'status',
            'phase',
            'state_version',
            'created_at',
            'updated_at',
            'current_candidate_id',
        )
    }
    beyond = client.get(path + '?page=2').json()
    assert beyond['data']['items'] == [] and beyond['meta']['pagination']['total'] == 1
    filtered = client.get(path + '?status=RUNNING').json()
    assert filtered['data']['items'] == [] and filtered['meta']['pagination']['total'] == 0
    assert client.get(path + '?status=').status_code == 422
    assert client.get(path + f'?design_revision_id={material["revision_id"]}').status_code == 404

    target = root / 'repository/.git/refs/walle/baselines/1'
    unavailable = root / 'owned-unavailable-create-ref'
    target.rename(unavailable)
    try:
        replay = post(key=key)
        assert replay.status_code == 201 and replay.json()['data'] == initial, replay.text
        assert (
            post({**body, 'budget_limit_cny': '0.02'}, key=key).json()['error']['code']
            == 'OPERATION_CONFLICT'
        )
        assert observed_connections() == 8
        rejected_key = str(uuid4())
        lost = post(key=rejected_key)
        assert lost.status_code == 409, lost.text
        assert lost.json()['error']['code'] == 'CONTENT_NOT_READY'
        assert lost.json()['error']['details']['related_entity_id'] == snapshot
        assert post(key=rejected_key).json()['error'] == lost.json()['error']

        current = edit(3, '创建后的新文档版本\n')
        detail_path = '/api/v1/code-tasks/' + str(initial['id'])
        detail = client.get(detail_path)
        assert detail.status_code == 200, detail.text
        assert detail.json()['data'] == {
            **initial,
            'current_basis_difference': [
                {'document_id': main_id, 'fixed_revision_id': fixed, 'current_revision_id': current}
            ],
        }
        assert post(key=key).json()['data'] == initial
        assert client.get('/api/v1/code-tasks/999').status_code == 404
        assert client.get(detail_path + '?view=history').status_code == 422
        assert observed_connections() == 9
    finally:
        unavailable.rename(target)

    with database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks').fetchall()
        assert len(task) == 1 and task[0]['authorization_id'] == authorization_id
        binding = connection.execute('SELECT status,task_id FROM code_authorizations').fetchone()
        assert tuple(binding) == ('BOUND_PENDING_APPLY', initial['id'])
        assert connection.execute('SELECT count(*) FROM code_task_materials').fetchone()[0] == 1
        assert connection.execute('SELECT count(*) FROM code_workspaces').fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM code_operations WHERE resource_kind='TASK'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
    if not start_workspace:
        exercise_task_stop(database, client, initial['id'])
    return initial['id']


def exercise_original_workspace_start(root, database, client, task_id):
    from time import monotonic, sleep
    from unittest.mock import patch
    from uuid import uuid4

    from backend.app.code_tasks import task_start, task_start_workspace
    from backend.app.shared.validation import strict_json_object

    def isolated_admission(_connection, _catalog, _task, workspace_available):
        assert workspace_available

    key = str(uuid4())
    headers = {'Idempotency-Key': key}
    body = {'expected_state_version': 1}
    task_path = f'/api/v1/code-tasks/{task_id}'
    path = task_path + '/start'
    with (
        patch.object(task_start, '_check_start_readiness', isolated_admission),
        patch.object(task_start_workspace, '_check_start_readiness', isolated_admission),
    ):
        accepted = client.post(path, json=body, headers=headers)
        assert accepted.status_code == 202, accepted.text
        data = accepted.json()['data']
        assert data['task_status'] == 'PENDING' and data['state_version'] == 2
        operation_path = f'/api/v1/code-operations/{data["operation_id"]}'
        deadline = monotonic() + 80
        while True:
            operation = client.get(operation_path)
            assert operation.status_code == 200, operation.text
            steps = operation.json()['data']['steps']
            if steps[2]['status'] == 'FAILED':
                break
            assert steps[0]['status'] in ('PENDING', 'RUNNING', 'SUCCEEDED'), operation.text
            assert steps[1]['status'] in ('PENDING', 'RUNNING', 'SUCCEEDED'), operation.text
            assert monotonic() < deadline
            sleep(0.1)
        detail = client.get(task_path)
        assert detail.status_code == 200, detail.text
        assert detail.json()['data']['workspace_id'] == steps[0]['result_ref']['workspace_id']
        assert detail.json()['data']['status'] == 'PENDING'
        assert steps[0]['external_identity'] == {} and steps[1]['external_identity'] == {}
        assert steps[1]['result_ref'] == {'document_count': 2}
        assert steps[2]['result_ref']['fixed_content_verified'] is True
        assert {'Q20-OC', 'Q20-WINDOWS'} <= set(steps[2]['result_ref']['capability_codes'])
        assert operation.json()['data']['failure_code'] == 'CONFIG_NOT_READY'
        assert steps[3]['status'] == 'PENDING'
        assert client.post(path, json=body, headers=headers).json()['data'] == data

    workspace_root = root / 'task-workspaces'
    (work,) = workspace_root.glob('working-*')
    (receipt,) = workspace_root.glob('*.workspace-stage.json')
    evidence = strict_json_object(receipt.read_bytes())
    assert (work / 'fixture.txt').read_bytes() == b'owned fixed source\n'
    assert evidence['operation_id'] == data['operation_id']
    assert (workspace_root / (evidence['nonce'] + '.b1.md')).read_bytes() == '固定设计\n'.encode()
    assert (workspace_root / (evidence['nonce'] + '.b2.md')).read_bytes() == b''
    assert (
        root
        / 'backend-git-evidence'
        / (evidence['baseline_query_id'] + '.snapshot-query-closed.json')
    ).is_file()
    with database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM code_instances').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0


def threaded_repository(
    root,
    reference,
    sid,
    guard_pid,
    database,
    *,
    refresh=False,
    baseline_catalog=None,
    snapshot_reads=False,
    start_workspace=False,
):
    import json
    from contextlib import contextmanager
    from unittest.mock import patch
    from uuid import uuid4

    from backend.app.code_tasks import repository_registration_worker as service
    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.infrastructure.windows_private_package import create_private_package

    connection_count = 0

    @contextmanager
    def owned_test_connection(installation_ref, *, backend_sid, program):
        nonlocal connection_count
        assert installation_ref == reference
        assert backend_sid == sid
        connection_count += 1
        current = connection_count
        try:
            with (
                ObservedProcess(guard_pid) as expected,
                GuardPipeClient(
                    reference,
                    backend_sid=sid,
                    server_sid=sid,
                    expected_guard=expected.identity,
                    program=program,
                ) as endpoint,
            ):
                if current == 1:
                    publish(root / 'io-peer-ready', os.getpid())
                yield endpoint
        finally:
            if snapshot_reads:
                (root / f'owned-connection-{current}-closed').touch(exist_ok=False)

    from fastapi.testclient import TestClient

    from backend.app.service import create_app
    from backend.tests.code_tasks.test_repository_baseline_acceptance import BaselineInput

    with ObservedProcess(guard_pid) as expected:
        path = Path(expected.identity.image_path)
        raw = path.read_bytes()
    baseline = baseline_catalog is not None
    if baseline:
        limits = RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75)
    elif refresh:
        limits = RegistrationReadLimits(65536, 1000, 20000, 1024 * 1024, 4096, 120)
    else:
        limits = RegistrationReadLimits(4096, 4096, 4096, 1024 * 1024, 4096, 30)
    installation = service.RegistrationInstallation(
        reference,
        sid,
        path,
        len(raw),
        hashlib.sha256(raw).hexdigest(),
        create_private_package(root / 'backend-git-evidence'),
        (root / 'private',),
        limits,
        workspace_root=create_private_package(root / 'task-workspaces')
        if start_workspace
        else None,
    )
    app = create_app(
        database=database, catalog=baseline_catalog, registration_installation=installation
    )
    if baseline:
        expected = json.loads((root / 'setup-result.json').read_bytes())['oid']
        format = 'sha1' if len(expected) == 40 else 'sha256'
        observation_request(root, database, format)
        request = BaselineInput(1, expected, key=str(uuid4()))
        body = {'commit_oid': expected, 'execution_profile_version_id': 1}
    else:
        request = (
            observation_request(root, database, 'sha1') if refresh else registration_request(root)
        )
        body = {} if refresh else request.business_input()
    with (
        patch.object(service, 'connect_registered_guard', owned_test_connection),
        TestClient(app) as client,
    ):
        assert not (root / 'io-peer-ready').exists()
        headers = {'Idempotency-Key': request.idempotency_key}
        worker = app.state.walle_repository_registration
        # Observe the HTTP wake without delivering it. The durable row must
        # still be found if the service loses the post-commit signal.
        with patch.object(worker, 'wake') as wake:
            response = client.post(request.command.path, json=body, headers=headers)
            assert response.status_code == 202, response.text
            wake.assert_called_once_with()
        receipt = response.json()
        operation_id = receipt['data']['operation_id']
        deadline = monotonic() + (150 if baseline else 100 if refresh else 20)
        while True:
            with database.transaction() as connection:
                operation = connection.execute(
                    'SELECT status,failure_code FROM code_operations WHERE id=?', (operation_id,)
                ).fetchone()
            if operation['status'] == 'SUCCEEDED':
                break
            assert operation['status'] not in ('FAILED', 'UNKNOWN'), tuple(operation)
            if monotonic() >= deadline:
                raise AssertionError('Dedicated repository worker did not publish the original')
            sleep(0.02)
        replay = client.post(request.command.path, json=body, headers=headers)
        assert replay.status_code == 202 and replay.json()['data'] == receipt['data']
        observed = client.get('/api/v1/code-operations/' + str(operation_id))
        assert observed.status_code == 200, observed.text
        assert observed.json()['data']['status'] == 'SUCCEEDED'
        operation_view = observed.json()['data']
        assert operation_view['idempotency_key'] == request.idempotency_key
        if baseline:
            assert [step['status'] for step in operation_view['steps']] == ['SUCCEEDED'] * 4
            snapshot = operation_view['steps'][-1]['result_ref']['snapshot_id']
            assert (
                root / 'repository/.git/refs/walle/baselines/1'
            ).read_bytes() == expected.encode('ascii') + b'\n'
            result = {'snapshot_id': snapshot, 'operation_status': operation_view['status']}
            if snapshot_reads:

                def business_rows():
                    with database.transaction() as connection:
                        return [
                            [tuple(row) for row in connection.execute('SELECT * FROM ' + table)]
                            for table in (
                                'code_operations',
                                'code_operation_steps',
                                'code_snapshots',
                                'idempotency_records',
                            )
                        ]

                original_rows = business_rows()
                path = f'/api/v1/code-snapshots/{snapshot}'
                detail = client.get(path)
                assert detail.status_code == 200, detail.text
                assert detail.json()['data']['ready'] is True
                assert detail.json()['data']['reason_codes'] == []
                assert detail.json()['data']['commit_oid'] == expected
                assert 'retention_ref' not in detail.text and 'canonical_root' not in detail.text
                recorded = {}
                read_snapshot = worker.read_snapshot

                def capture_files(snapshot_id, *, cancelled, finish=None):
                    def consume(entry, raw):
                        recorded[entry.path] = (entry.sha256, raw)

                    return read_snapshot(
                        snapshot_id, cancelled=cancelled, finish=finish, consume_file=consume
                    )

                with patch.object(worker, 'read_snapshot', capture_files):
                    files = client.get(path + '/files')
                digest, bytes_read = recorded['fixture.txt']
                assert len(bytes_read) == 19 and hashlib.sha256(bytes_read).hexdigest() == digest
                assert files.status_code == 200, files.text
                (item,) = files.json()['data']['items']
                assert item['path'] == 'fixture.txt' and item['byte_count'] == 19
                assert set(item) == {'path', 'mode', 'blob_oid', 'byte_count'}
                assert files.json()['meta']['pagination']['total'] == 1
                beyond = client.get(path + '/files?page=2')
                assert beyond.status_code == 200 and beyond.json()['data']['items'] == []
                assert beyond.json()['meta']['pagination']['total'] == 1

                target = root / 'repository/.git/refs/walle/baselines/1'
                unavailable = root / 'owned-unavailable-snapshot-ref'
                target.rename(unavailable)
                try:
                    lost = client.get(path)
                    assert lost.status_code == 200, lost.text
                    assert lost.json()['data']['ready'] is False
                    assert lost.json()['data']['reason_codes'] == ['CONTENT_NOT_READY']
                    lost_files = client.get(path + '/files')
                    assert lost_files.status_code == 409, lost_files.text
                    error = lost_files.json()['error']
                    assert error['code'] == 'CONTENT_NOT_READY', lost_files.text
                    assert error['details']['related_entity_kind'] == 'SNAPSHOT'
                    assert error['details']['related_entity_id'] == snapshot
                finally:
                    unavailable.rename(target)
                assert client.get(path + '/files?page=1&page=2').status_code == 422
                assert client.get('/api/v1/code-snapshots/999').status_code == 404
                assert business_rows() == original_rows
                assert connection_count == 6
                result['snapshot_reads'] = True
                result['task_id'] = exercise_fixed_task_creation(
                    root,
                    database,
                    app,
                    client,
                    snapshot,
                    lambda: connection_count,
                    start_workspace=start_workspace,
                )
                assert connection_count == 9
                if start_workspace:
                    exercise_original_workspace_start(root, database, client, result['task_id'])
                    assert connection_count == 10
                    result['workspace_start'] = True

        elif refresh:
            original = operation_view['steps'][1]['result_ref']['observation_id']
            saved = client.get(f'/api/v1/code-repositories/1/observations/{original}')
            assert saved.status_code == 200, saved.text
            data = saved.json()['data']
            expected = json.loads((root / 'setup-result.json').read_bytes())['oid']
            assert data['head_commit'] == expected and data['status'] == 'READABLE'
            assert (data['id'], data['repository_id'], data['operation_id']) == (
                original,
                1,
                operation_id,
            )
            result = {
                'observation_id': original,
                'operation_status': operation_view['status'],
                'head_commit': data['head_commit'],
            }
        else:
            saved = client.get(request.command.path + '/' + str(receipt['data']['resource_id']))
            assert saved.status_code == 200, saved.text
            assert saved.json()['data']['object_format'] == 'sha1'
            assert saved.json()['data']['root_path'] == str(root / 'source.git')
            result = {
                'object_format': 'sha1',
                'bare': True,
                'stderr': '',
                'repository_id': receipt['data']['resource_id'],
                'operation_status': operation['status'],
            }
    assert app.state.walle_repository_registration._task.done()
    with ProcessLock.for_database(database.path):
        pass
    publish(root / 'control-git-pipe-result.json', result)
    wait(root / 'stop')


def recover_registration(root, database, lock, frames, binding):
    from types import SimpleNamespace

    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.code_tasks.repository_registration_actor import RepositoryRegistrationActor
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal

    original = root.parent / 'crashed'
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, commands=lambda: executor)
    with LaunchJournal(original / 'backend-git-evidence') as journal:

        def new_actor():
            return RepositoryRegistrationActor(
                runtime,
                binding,
                journal,
                private_roots=(original / 'private', journal.root),
                limits=RegistrationReadLimits(4096, 4096, 4096, 1024 * 1024, 4096, 30),
            )

        actor = new_actor()
        assert actor.has_work()
        assert actor.run_next(frames, cancelled=lambda: False) is None
        assert not actor.has_work()
        actor.close()
        reopened = new_actor()
        assert not reopened.has_work()
        assert reopened.run_next(None, cancelled=lambda: False) is None
        reopened.close()
    with database.transaction() as connection:
        row = connection.execute(
            'SELECT status, failure_code FROM code_operations WHERE id=1'
        ).fetchone()
        assert tuple(row) == ('UNKNOWN', 'EXTERNAL_RESULT_UNKNOWN')
        assert connection.execute('SELECT count(*) FROM code_repositories').fetchone()[0] == 0
    return {'controller_ref': binding.controller_ref, 'operation_status': row['status']}


def seed_baseline_configuration(database):
    from fastapi.testclient import TestClient

    from backend.app.infrastructure.content_secret_policy import REFERENCE
    from backend.app.infrastructure.resources import ResourceCatalog
    from backend.app.service import create_app
    from backend.tests.code_tasks.test_execution_profile_content import body
    from backend.tests.code_tasks.test_execution_profile_versions import (
        fixture_snapshot,
        parents,
        resources,
        seed_price,
    )
    from backend.tests.code_tasks.test_execution_profile_versions import (
        publish as publish_profile,
    )

    catalog = ResourceCatalog()
    (git,) = catalog.code_configuration_options('GIT')
    version = body()
    version['git'] = git['value']
    version['capture_rules']['secret_policy_ref'] = REFERENCE
    version['limits'].update(
        max_file_bytes=65536,
        max_snapshot_bytes=1024 * 1024,
        max_git_output_bytes=1024 * 1024,
        max_capture_entries=1000,
        max_manifest_bytes=65536,
    )
    with TestClient(create_app(database=database, catalog=catalog)) as client:
        parents(client)
        seed_price(database)
        with resources(fixture_snapshot(version)):
            saved = publish_profile(client, value=version)
            assert saved.status_code == 201, saved.text
    return catalog


def run_baseline_validation(root, database, catalog, lock, frames, binding, mode):
    import json
    from types import SimpleNamespace
    from unittest.mock import patch
    from uuid import uuid4

    import pytest

    from backend.app.code_tasks.repository_acceptance import accept_repository_operation
    from backend.app.code_tasks.repository_baseline_query import BaselineQueryGitDispatch
    from backend.app.code_tasks.repository_git_runner import (
        RegistrationReadLimits,
        RepositoryBaselinePinRun,
        RepositoryBaselineQueryRun,
        RepositoryBaselineValidationRun,
        RepositoryBaselineVerifyRun,
        _FixedGitRun,
    )
    from backend.app.code_tasks.repository_operations import read_repository_operation
    from backend.app.code_tasks.repository_registration_actor import (
        BaselineOutcome,
        RepositoryRegistrationActor,
    )
    from backend.app.infrastructure.git_baseline_ref_guard import BaselineRefConflict
    from backend.app.infrastructure.git_object_read import GitObjectReadError
    from backend.app.infrastructure.git_ref_metadata import RefMetadataError
    from backend.app.infrastructure.guard_control_git_input import (
        BASELINE_REF_COMMAND_REF,
        OBJECT_BATCH_COMMAND_REF,
    )
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import (
        LaunchJournal,
        LaunchOutcomeUnknown,
    )
    from backend.app.infrastructure.windows_private_package import create_private_package
    from backend.app.shared.command_execution import operation_time
    from backend.tests.code_tasks.test_repository_baseline_acceptance import BaselineInput

    original_oid = json.loads((root / 'setup-result.json').read_bytes())['oid']
    missing = mode.startswith('BASELINE_MISSING_')
    malformed_ref = mode.startswith('BASELINE_MALFORMED_REF_')
    tampered = mode.startswith('BASELINE_SAVE_TAMPERED_')
    crash = mode.startswith('BASELINE_CRASH_')
    recover = mode.startswith('BASELINE_RECOVERY_')
    recover_packed = mode.startswith('BASELINE_RECOVERY_PACKED_')
    query = mode.startswith('BASELINE_QUERY_')
    query_crash = mode.startswith('BASELINE_QUERY_CRASH_')
    restore = mode.startswith('BASELINE_QUERY_RESTORE_')
    publish = query or recover or mode.startswith('BASELINE_SAVE_')
    pin = publish or crash or mode.startswith('BASELINE_PIN_')
    snapshot_id = None
    conflict = mode.startswith('BASELINE_PIN_CONFLICT_')
    uncertain = recover or mode.startswith('BASELINE_PIN_UNKNOWN_')
    pin_status = 'PENDING'
    commit_oid = 'e' * len(original_oid) if missing else original_oid
    object_format = mode.rsplit('_', 1)[1].lower()
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, catalog=catalog, commands=lambda: executor)
    repository = root / 'repository'
    with database.transaction(write=True) as connection:
        connection.execute(
            'INSERT INTO code_repositories VALUES(1,?,?,?,?,?)',
            (
                'owned baseline',
                str(repository),
                str(repository / '.git'),
                object_format,
                operation_time(None),
            ),
        )
    request = BaselineInput(1, commit_oid, key=str(uuid4()))
    accepted = accept_repository_operation(runtime, request)
    assert accepted['code'] == 'OPERATION_ACCEPTED', accepted
    operation_id = accepted['data']['operation_id']
    with (
        LaunchJournal(create_private_package(root / 'baseline-evidence')) as journal,
        ExitStack() as actor_lifetime,
    ):
        if recover or restore:
            actor = RepositoryRegistrationActor(
                runtime,
                binding,
                journal,
                private_roots=(root / 'private', journal.root),
                limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
            )
            actor_lifetime.callback(actor.close)
        runner = RepositoryBaselineValidationRun(
            runtime,
            operation_id,
            frames,
            binding,
            journal,
            private_roots=(root / 'private', journal.root),
            limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
        )
        try:
            result = runner.run(cancelled=lambda: False)
        except GitObjectReadError as error:
            assert missing and error.args == ('ORIGINAL_BATCH_OBJECT_MISSING',)
            result = None
        except RefMetadataError:
            assert malformed_ref
            result = None
        finally:
            runner.close()
        if pin:
            runner = RepositoryBaselinePinRun(
                runtime,
                operation_id,
                frames,
                binding,
                journal,
                private_roots=(root / 'private', journal.root),
                limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
            )
            if crash:
                original_cleanup = _FixedGitRun._stop_and_release

                def lose_before_cleanup(command):
                    if command._actions.original.command_ref == BASELINE_REF_COMMAND_REF:
                        raise LaunchOutcomeUnknown('FIXTURE_EXIT_BEFORE_REF_SCOPE_RELEASE')
                    original_cleanup(command)

                with patch.object(_FixedGitRun, '_stop_and_release', lose_before_cleanup):
                    try:
                        runner.run(cancelled=lambda: False)
                    except LaunchOutcomeUnknown as error:
                        assert error.args == ('FIXTURE_EXIT_BEFORE_REF_SCOPE_RELEASE',)
                        assert runner._command.cleanup_required
                    else:
                        raise AssertionError('Expected loss before original cleanup')
                with database.transaction() as connection:
                    state = connection.execute(
                        'SELECT status FROM code_operations WHERE id=?', (operation_id,)
                    ).fetchone()
                    assert state[0] == 'UNKNOWN'
                    assert (
                        connection.execute('SELECT count(*) FROM code_snapshots').fetchone()[0] == 0
                    )
                publish_marker = root / 'owned-baseline-original-unknown'
                publish_marker.touch(exist_ok=False)
                wait(root / 'exit-original-backend')
                os._exit(0)
            try:
                if uncertain:
                    with patch.object(
                        runner._dispatch,
                        'confirm_commit',
                        side_effect=LaunchOutcomeUnknown('FIXTURE_LOST_CONFIRMED_RESULT'),
                    ):
                        runner.run(cancelled=lambda: False)
                else:
                    receipt = runner.run(cancelled=lambda: False)
                assert not conflict and not uncertain
                pin_status = 'SUCCEEDED'
            except BaselineRefConflict:
                assert conflict
                pin_status = 'FAILED'
            except LaunchOutcomeUnknown as error:
                assert uncertain and error.args == ('FIXTURE_LOST_CONFIRMED_RESULT',)
                original_receipts = runner._dispatch._receipts
                assert original_receipts.read_phase('PREPARED') is not None
                assert original_receipts.read_phase('COMMIT_MAY_BE_SENT') is not None
                assert original_receipts.read_phase('COMMIT_ACK') is None
                try:
                    runner.run(cancelled=lambda: False)
                except LaunchOutcomeUnknown as replay:
                    assert replay.args == ('ORIGINAL_REPOSITORY_RUN_REQUIRES_OBSERVATION',)
                else:
                    raise AssertionError('Original uncertain write was sent again')
                pin_status = 'UNKNOWN'
            finally:
                runner.close()
        if publish:
            if tampered:
                (repository / '.git/refs/walle/baselines/1').write_bytes(
                    b'e' * len(commit_oid) + b'\n'
                )
            if recover:
                target = repository / '.git/refs/walle/baselines/1'
                unavailable = root / 'owned-unavailable-ref'
                target.rename(unavailable)
                try:
                    actor.request_pin_observation(operation_id)
                    actor.request_pin_observation(operation_id)
                    with pytest.raises(GitObjectReadError, match='ORIGINAL_BASELINE_REF_MISSING'):
                        actor.run_next(frames, cancelled=lambda: False)
                    assert not actor.has_work()
                    with database.transaction() as connection:
                        state = connection.execute(
                            'SELECT status,external_identity FROM code_operation_steps '
                            'WHERE operation_id=? AND step_no=3',
                            (operation_id,),
                        ).fetchone()
                        assert tuple(state) == ('PENDING', None)
                finally:
                    if recover_packed:
                        with (repository / '.git/packed-refs').open('ab') as packed:
                            packed.write(commit_oid.encode('ascii') + b' refs/walle/baselines/1\n')
                    else:
                        unavailable.rename(target)
                actor.request_pin_observation(operation_id)
                assert actor.run_next(frames, cancelled=lambda: False) == BaselineOutcome(
                    operation_id, 1
                )
                assert not actor.has_work()
                snapshot_id, pin_status = 1, 'SUCCEEDED'
            else:
                runner = RepositoryBaselineVerifyRun(
                    runtime,
                    operation_id,
                    frames,
                    binding,
                    journal,
                    private_roots=(root / 'private', journal.root),
                    limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
                )
                try:
                    snapshot_id = runner.run(cancelled=lambda: False)
                    assert not tampered
                except BaselineRefConflict:
                    assert tampered
                finally:
                    runner.close()
        if query:

            def business_rows():
                with database.transaction() as connection:
                    return [
                        [tuple(row) for row in connection.execute('SELECT * FROM ' + table)]
                        for table in (
                            'code_operations',
                            'code_operation_steps',
                            'code_snapshots',
                            'idempotency_records',
                        )
                    ]

            def snapshot_reader():
                return RepositoryBaselineQueryRun(
                    runtime,
                    snapshot_id,
                    frames,
                    binding,
                    journal,
                    private_roots=(root / 'private', journal.root),
                    limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
                )

            before = business_rows()
            target = repository / '.git/refs/walle/baselines/1'
            unavailable = root / 'owned-query-unavailable-ref'
            target.rename(unavailable)
            unavailable_query = snapshot_reader()
            try:
                with pytest.raises(GitObjectReadError, match='ORIGINAL_BASELINE_REF_MISSING'):
                    unavailable_query.run(cancelled=lambda: False)
                assert BaselineQueryGitDispatch.saved_ids(journal) == ()
            finally:
                unavailable_query.close()
                unavailable.rename(target)
            if query_crash:
                original_cleanup = _FixedGitRun._stop_and_release

                def interrupt_query_cleanup(command):
                    if (
                        type(command._dispatch) is BaselineQueryGitDispatch
                        and command._actions.original.command_ref == OBJECT_BATCH_COMMAND_REF
                    ):
                        raise LaunchOutcomeUnknown('FIXTURE_EXIT_BEFORE_QUERY_SCOPE_RELEASE')
                    original_cleanup(command)

                interrupted = snapshot_reader()
                with (
                    patch.object(_FixedGitRun, '_stop_and_release', interrupt_query_cleanup),
                    pytest.raises(
                        LaunchOutcomeUnknown, match='FIXTURE_EXIT_BEFORE_QUERY_SCOPE_RELEASE'
                    ),
                ):
                    interrupted.run(cancelled=lambda: False)
                assert interrupted._command.cleanup_required and business_rows() == before
                (root / 'owned-baseline-original-unknown').touch(exist_ok=False)
                wait(root / 'exit-original-backend')
                os._exit(0)
            if restore:
                from backend.app.infrastructure.git_repository_location import (
                    RepositoryLocationError,
                )
                from backend.app.infrastructure.windows_private_package import PrivatePackageGuard

                with PrivatePackageGuard(
                    create_private_package(repository / 'owned-overlap')
                ) as overlap:
                    with pytest.raises(
                        RepositoryLocationError, match='REPOSITORY_PRIVATE_SCOPE_OVERLAP'
                    ):
                        actor.restore_snapshot(
                            snapshot_id,
                            frames,
                            parent=overlap,
                            nonce=uuid4().hex,
                            check_active=lambda: None,
                            cancelled=lambda: False,
                        )
                    assert list(overlap.path.iterdir()) == []
                    assert BaselineQueryGitDispatch.saved_ids(journal) == ()

                with PrivatePackageGuard(
                    create_private_package(root / 'owned-workspace')
                ) as parent:
                    restored = actor.restore_snapshot(
                        snapshot_id,
                        frames,
                        parent=parent,
                        nonce=uuid4().hex,
                        check_active=lambda: None,
                        cancelled=lambda: False,
                    )
                    assert restored.snapshot_id == snapshot_id
                    target = parent.path / restored.location_key
                    assert [(entry.path, entry.mode) for entry in restored.entries] == [
                        ('empty', '100644'),
                        ('fixture.txt', '100644'),
                        ('sub/run.bin', '100755'),
                    ]
                    assert (target / 'fixture.txt').read_bytes() == b'owned fixed source\n'
                    assert (target / 'empty').read_bytes() == b''
                    assert (target / 'sub/run.bin').read_bytes() == b'\xef\xbb\xbfraw\r\n\x00\xff'
                    assert (
                        repository / 'fixture.txt'
                    ).read_bytes() == b'uncommitted fixture change'
                    assert not (target / '.git').exists()
            else:
                runner = snapshot_reader()
                try:
                    queried = runner.run(cancelled=lambda: False)
                    assert queried.snapshot['id'] == snapshot_id
                    assert queried.snapshot['commit_oid'] == commit_oid
                    assert queried.snapshot['content_tree_oid'] == result.tree_oid
                    (entry,) = queried.entries
                    assert (entry.path, entry.mode, entry.byte_count) == (
                        'fixture.txt',
                        '100644',
                        19,
                    )
                finally:
                    runner.close()
            (query_id,) = BaselineQueryGitDispatch.saved_ids(journal)
            closed = BaselineQueryGitDispatch(runtime, frames, binding, journal)
            try:
                closed.reopen(query_id)
                assert closed.operation_id == operation_id
                assert closed.snapshot_id == snapshot_id
                assert closed.already_closed()
            finally:
                closed.close()
            assert business_rows() == before
    with database.transaction() as connection:
        operation = connection.execute(
            'SELECT status,failure_code FROM code_operations WHERE id=?', (operation_id,)
        ).fetchone()
        steps = connection.execute(
            'SELECT status,result_ref,external_identity FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
            (operation_id,),
        ).fetchall()
        snapshots = connection.execute('SELECT * FROM code_snapshots').fetchall()
        if publish and not tampered:
            (saved,) = snapshots
            assert (
                saved['id'],
                saved['repository_id'],
                saved['registration_operation_id'],
                saved['content_profile_version_id'],
                saved['commit_oid'],
                saved['content_tree_oid'],
                saved['retention_ref'],
                saved['content_policy_version'],
            ) == (
                snapshot_id,
                1,
                operation_id,
                1,
                commit_oid,
                result.tree_oid,
                'refs/walle/baselines/1',
                'GIT20-BASELINE-1',
            )
            assert saved['registered_at'] <= saved['created_at']
        else:
            assert not snapshots
    expected = 'FAILED' if missing or malformed_ref else 'SUCCEEDED'
    assert [step['status'] for step in steps] == [
        expected,
        pin_status,
        'FAILED' if tampered else 'SUCCEEDED' if publish else 'PENDING',
        'SUCCEEDED' if publish and not tampered else 'PENDING',
    ]
    if pin_status == 'SUCCEEDED':
        ref_transaction = json.loads(steps[1]['result_ref'])
        if recover:
            observed_path = root / 'baseline-evidence' / ref_transaction['committed']['filename']
            observed = json.loads(observed_path.read_bytes())
            assert observed['phase'] == 'OBSERVED'
            assert observed['facts']['commit_ack'] is None
            assert observed['facts']['ref_observation']['oid'] == commit_oid
        else:
            assert ref_transaction['committed'] == asdict(receipt)
        assert set(json.loads(steps[1]['external_identity'])) == {'git_baseline_pin'}
        assert (
            len({ref_transaction[key]['sha256'] for key in ('prepared', 'dispatch', 'committed')})
            == 3
        )
    if missing or malformed_ref:
        code = 'CONTENT_NOT_READY' if missing else 'REPOSITORY_UNSUPPORTED'
        assert tuple(operation) == ('FAILED', code)
        assert all(step['result_ref'] is None for step in steps)
    else:
        if conflict or tampered:
            assert tuple(operation) == ('FAILED', 'RESOURCE_CONFLICT')
        elif uncertain and not recover:
            assert tuple(operation) == ('UNKNOWN', 'EXTERNAL_RESULT_UNKNOWN')
        elif publish:
            assert tuple(operation) == ('SUCCEEDED', None)
        else:
            assert tuple(operation) == ('RUNNING', None)
        if conflict or (uncertain and not recover):
            assert steps[1]['result_ref'] is None
        assert json.loads(steps[0]['result_ref']) == asdict(result)
        assert result.commit_oid == commit_oid
    view = read_repository_operation(runtime, SimpleNamespace(operation_id=operation_id))
    assert view['data'] is not None, view
    assert [step['result_ref'] for step in view['data']['steps']] == [
        None,
        None,
        None,
        {'snapshot_id': snapshot_id} if snapshot_id is not None else None,
    ]
    assert accept_repository_operation(runtime, request) == accepted
    return {
        'validation_status': expected,
        'proof': None if result is None else asdict(result),
        'pin_status': pin_status,
        'snapshot_id': snapshot_id,
    }


def recover_baseline_after_restart(root, database, catalog, lock, frames, binding, *, query=False):
    from types import SimpleNamespace

    from backend.app.code_tasks.repository_baseline_query import BaselineQueryGitDispatch
    from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
    from backend.app.code_tasks.repository_registration_actor import (
        BaselineOutcome,
        RepositoryRegistrationActor,
    )
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal

    original = root.parent / 'crashed'
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, catalog=catalog, commands=lambda: executor)
    with LaunchJournal(original / 'baseline-evidence') as journal:
        actor = RepositoryRegistrationActor(
            runtime,
            binding,
            journal,
            private_roots=(original / 'private', journal.root),
            limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
        )
        try:
            assert actor.has_work()
            assert actor.run_next(frames, cancelled=lambda: False) is None
            if query:
                assert not actor.has_work()
                (query_id,) = BaselineQueryGitDispatch.saved_ids(journal)
                closed = BaselineQueryGitDispatch(runtime, frames, binding, journal)
                try:
                    closed.reopen(query_id)
                    assert closed.already_closed()
                    with database.transaction() as connection:
                        row = connection.execute(
                            'SELECT status FROM code_operations WHERE id=?', (closed.operation_id,)
                        ).fetchone()
                        assert row[0] == 'SUCCEEDED'
                        assert (
                            connection.execute('SELECT count(*) FROM code_operations').fetchone()[0]
                            == 1
                        )
                    return {
                        'operation_id': closed.operation_id,
                        'snapshot_id': closed.snapshot_id,
                        'controller_ref': binding.controller_ref,
                    }
                finally:
                    closed.close()
            assert actor.has_work()
            outcome = actor.run_next(frames, cancelled=lambda: False)
            assert type(outcome) is BaselineOutcome
            assert not actor.has_work()
        finally:
            actor.close()
    return {**asdict(outcome), 'controller_ref': binding.controller_ref}


def run_project_check(
    root,
    binding,
    lock,
    frames,
    *,
    reject_capsule,
    interrupt=False,
    testing=False,
    snapshot=False,
    stdin=False,
    fixture=False,
):
    from backend.app.infrastructure.check_input_transfer import (
        SnapshotCheckSource,
        export_check_input,
    )
    from backend.app.infrastructure.content_manifest import fixed_entries_sha256
    from backend.app.infrastructure.guard_control_git_transport import exchange_guard_project_check
    from backend.app.infrastructure.guard_task_launch_protocol import task_launch_fence
    from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
    from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, TestingLaunchScope
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )
    from backend.app.infrastructure.windows_task_directories import (
        ProjectCheckInput,
        SnapshotCheckInput,
    )
    from backend.tests.infrastructure.test_v20_windows_lpac_profile import (
        FIXED_FIXTURE_BYTES,
        check_definition,
        check_limits,
        make_check_candidate,
    )

    fixed_fixture = None
    if fixture:
        fixed_fixture = hashlib.sha256(
            (root / 'fixed-testing-input' / 'manifest.json').read_bytes()
        ).hexdigest()
    candidate, _, raw = make_check_candidate(root)
    limits, git_limits = check_limits()
    definition = check_definition(stdin=stdin, fixture=fixture)
    payload = b'WALLE\r\n' * 10000 if stdin else b''
    output_limit = 128 * 1024 if stdin else 4096
    scope = (
        TestingLaunchScope(binding.controller_ref, 17, 3, NONCE, 9, 2)
        if testing
        else binding.scope(17, 3, NONCE)
    )
    deadline = monotonic() + 55
    reference = None
    check = ProjectCheckInput(
        'TESTING' if testing else 'CODING',
        9,
        2,
        13,
        14,
        candidate.seal.binding.candidate_id,
        candidate.seal.manifest_sha256,
    )
    if snapshot:
        manifest = candidate.seal.manifest
        check = SnapshotCheckInput(
            'TESTING',
            9,
            2,
            13,
            14,
            27,
            'e' * 40,
            manifest.content_tree_oid,
            manifest.object_format,
            manifest.content_profile_version_id,
            fixed_entries_sha256(manifest.entries),
        )

        def original_files(append, checkpoint):
            checkpoint()
            append(manifest.entries[0], raw)
            checkpoint()

        candidate = SnapshotCheckSource(check, manifest, original_files)
    if not reject_capsule:
        with (
            PrivatePackageGuard(root / 'task-source') as source,
            LaunchJournal(create_private_package(root / 'check-evidence')) as journal,
        ):
            evidence = ProjectCheckJournal(journal, scope, binding.owner_epoch, lambda: None)

            class ExitOriginalCheck(ProjectCheckDispatch):
                def _wait_exit(self, frames, deadline, cancelled):
                    publish(
                        root / 'check-owner-exit.json',
                        {
                            'scope': asdict(scope),
                            'check': asdict(check),
                            'owner_epoch': binding.owner_epoch,
                        },
                    )
                    os._exit(0)

            dispatch_type = ExitOriginalCheck if interrupt else ProjectCheckDispatch
            dispatch = dispatch_type(
                binding,
                lock,
                scope,
                check,
                definition=definition,
                runner_ref='fixture:project-runner',
                active_process_limit=2,
                job_memory_limit_bytes=128 * 1024 * 1024,
                journal=evidence,
            )
            complete = dispatch.run(
                frames,
                source,
                candidate,
                limits=limits,
                git_limits=git_limits,
                max_output_bytes=output_limit,
                stdin=payload,
                fixture_sha256=fixed_fixture,
                deadline=deadline,
                cleanup_seconds=20,
                active=lambda: None,
                cancelled=lambda: False,
            )
            result = complete.result
            assert result.result == 'PASSED' and result.exit_code == 0
            assert result.reason_code is None and result.source_integrity == 'VERIFIED'
            assert result.stdout.byte_count > 0 and result.stderr.byte_count == 0
            assert not list(source.path.iterdir())
            if testing:
                from dataclasses import replace

                from backend.app.infrastructure.check_case_pack import (
                    CaseAssertion,
                    CaseStep,
                    CheckCase,
                )
                from backend.app.infrastructure.guard_request_header import GuardProtocolError
                from backend.app.testing.cli_evidence import original_cli_outcome

                case = CheckCase(
                    'check-original-input',
                    'Check original input',
                    (),
                    (CaseStep('find', 'RUN', (definition.command_id, payload)),),
                    (CaseAssertion('exit', 'EXIT_CODE', (0,)),),
                    5,
                )
                recovered = evidence.read_completion(check, output_limit)
                for original in (complete, recovered):
                    assert original_cli_outcome(original, scope, check, case, definition) == {
                        'case_id': case.case_id,
                        'result': 'PASSED',
                        'assertion_results': [
                            {'assertion_id': 'exit', 'result': 'PASSED', 'actual_value': 0}
                        ],
                        'capture_status': 'FULL',
                    }
                if stdin or fixture:
                    expected_bytes = payload if stdin else FIXED_FIXTURE_BYTES
                    exact = replace(
                        case,
                        assertions=(CaseAssertion('stdout', 'STDOUT_BYTES', (expected_bytes,)),),
                    )
                    assert (
                        original_cli_outcome(recovered, scope, check, exact, definition)['result']
                        == 'PASSED'
                    )

                expected_empty = replace(
                    case, assertions=(CaseAssertion('stdout', 'STDOUT_BYTES', (b'',)),)
                )
                failed = original_cli_outcome(recovered, scope, check, expected_empty, definition)
                assert failed['result'] == 'FAILED' and failed['capture_status'] == 'REDACTED'
                assert (
                    failed['assertion_results'][0]['actual_value']
                    == 'sha256:' + result.stdout.sha256
                )

                assert complete.prepared['stdio_binding']['scope'] == asdict(scope)
                assert complete.released['check']['exit']['scope'] == asdict(scope)
                assert complete.released['native']['fence']['scope'] == asdict(scope)
                for wrong_scope in (
                    None,
                    replace(scope, owner_id=scope.owner_id + 1),
                    replace(scope, control_generation=scope.control_generation + 1),
                ):
                    for action, data in (
                        ('OBSERVE', {'observed_action': 'RELEASE'}),
                        ('STOP', {}),
                    ):
                        request = build_guard_request_header(
                            binding,
                            lock,
                            action=action,
                            operation_id=scope.operation_id,
                            step_no=scope.step_no,
                            nonce=scope.nonce,
                            binding_ref=complete.prepared['binding_ref'],
                            action_input=data,
                            testing_scope=wrong_scope,
                        )
                        reply = exchange_guard_project_check(
                            frames,
                            binding,
                            lock,
                            request,
                            timeout_ms=30000,
                            cancelled=lambda: False,
                        )
                        assert reply.status == 'UNKNOWN' and reply.result is None
                try:
                    build_guard_request_header(
                        binding,
                        lock,
                        action='VERIFY_MODEL_SOURCE',
                        operation_id=scope.operation_id,
                        step_no=scope.step_no,
                        nonce=scope.nonce,
                        binding_ref=complete.prepared['binding_ref'],
                        action_input={},
                        testing_scope=scope,
                    )
                except GuardProtocolError:
                    pass
                else:
                    raise AssertionError('Testing project process was admitted as a model source')
            for action in ('PREPARE', 'CREATE_SUSPENDED', 'RESUME', 'STOP', 'RELEASE'):
                assert (
                    evidence._read(action, 'intent')['input_sha256']
                    == (evidence._read(action, 'ack')['input_sha256'])
                )
        publish(
            root / 'control-git-pipe-result.json',
            {'result': 'verified', 'candidate_sha256': hashlib.sha256(raw).hexdigest()},
        )
        wait(root / 'stop')
        return

    def send(action, data=None, *, rejected=False):
        request = build_guard_request_header(
            binding,
            lock,
            action=action,
            operation_id=scope.operation_id,
            step_no=scope.step_no,
            nonce=scope.nonce,
            binding_ref=None if action == 'PREPARE' else reference,
            action_input=data or {},
        )
        reply = exchange_guard_project_check(
            frames, binding, lock, request, timeout_ms=30000, cancelled=lambda: False
        )
        expected = (
            'UNKNOWN' if rejected else ('OBSERVED' if action == 'OBSERVE' else 'ACKNOWLEDGED')
        )
        assert reply.status == expected, (action, reply.status)
        return reply.result

    with (
        PrivatePackageGuard(root / 'task-source') as source,
        BackendStandardIO(scope) as stdio,
        export_check_input(
            source, scope, candidate, limits=limits, git_limits=git_limits, active=lambda: None
        ) as capsule,
    ):
        descriptor = asdict(capsule.descriptor)
        descriptor = {key: descriptor[key] for key in ('file', 'sha256', 'byte_count', 'handle')}
        if reject_capsule:
            descriptor['sha256'] = 'a' * 64
        io = stdio.descriptor()
        stdio.begin_handoff()
        capsule.mark_offered()
        send(
            'PREPARE',
            {
                'run_kind': 'TASK',
                'execution_purpose': 'CHECK',
                'check_input': asdict(check),
                'project_command': {
                    'command_id': definition.command_id,
                    'definition_sha256': definition.definition_sha256,
                    'active_process_limit': 2,
                    'job_memory_limit_bytes': 128 * 1024 * 1024,
                },
                'runner_ref': 'fixture:project-runner',
                'network': {role: [] for role in ('model', 'forward', 'control', 'application')},
                'capsule': descriptor,
                'limits': asdict(limits),
                'stdio': {
                    key: getattr(io, key)
                    for key in ('io_nonce', 'stdin_handle', 'stdout_handle', 'stderr_handle')
                },
            },
            rejected=reject_capsule,
        )
        if reject_capsule:
            original = send('OBSERVE', {'observed_action': 'PREPARE'})
            assert original['action_phase'] == 'MAY_HAVE_BEEN_SENT'
            assert original['preparation']['launch_state'] == 'PREPARING'
            reference = original['binding_ref']
            stopped = send('STOP')
            assert stopped['native']['process_state'] == 'NOT_CREATED'
            stdio.acknowledge_closed_scope(task_launch_fence(stopped['native']['fence'], scope))
            released = send('RELEASE')
            observed = send('OBSERVE', {'observed_action': 'RELEASE'})
            assert observed['preparation']['cleanup_state'] == 'COMPLETE'
            assert observed['acknowledgement'] == released
            assert released['check']['exit'] is None
            assert released['check']['source_integrity'] == 'NOT_CHECKED'
            publish(
                root / 'control-git-pipe-result.json',
                {'result': 'rejected', 'candidate_sha256': hashlib.sha256(raw).hexdigest()},
            )
            wait(root / 'stop')
            return


def recover_exited_project_check(root, binding, lock, frames):
    from backend.app.infrastructure.project_check_journal import ProjectCheckJournal
    from backend.app.infrastructure.project_check_recovery import ProjectCheckRecovery
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
    from backend.app.infrastructure.windows_private_package import PrivatePackageGuard
    from backend.app.infrastructure.windows_task_directories import ProjectCheckInput

    previous = root.parent
    original = json.loads((previous / 'check-owner-exit.json').read_bytes())
    scope = LaunchScope(**original['scope'])
    check = ProjectCheckInput(**original['check'])
    assert binding.controller_ref != scope.controller_ref
    with (
        PrivatePackageGuard(previous / 'task-source') as parent,
        LaunchJournal(previous / 'check-evidence') as journal,
    ):
        evidence = ProjectCheckJournal(journal, scope, original['owner_epoch'], lambda: None)
        recovery = ProjectCheckRecovery(binding, lock, scope, original['owner_epoch'], evidence)
        assert evidence.read_completion(check, 4096) is None
        outcome = recovery.close_original(
            frames, parent, check, 4096, deadline=monotonic() + 45, cancelled=lambda: False
        )
        assert outcome.result.result == 'UNKNOWN'
        assert outcome.result.reason_code == 'EVIDENCE_INCOMPLETE'
        assert outcome.result.exit_code is not None
        assert outcome.result.source_integrity == 'VERIFIED'
        assert outcome.result.stdout is None and outcome.result.stderr is None
        assert evidence.read_completion(check, 4096) == outcome
        assert not list(parent.path.iterdir())
    publish(root / 'control-git-pipe-result.json', {'recovered': True})
    wait(root / 'stop')


def run_persisted_project_check(
    root, database, lock, frames, binding, fixture, *, restart=False, multi=False, handoff=False
):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import patch
    from uuid import uuid4

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.code_tasks.command_api import command_router
    from backend.app.code_tasks.repository_git_runner import _FixedGitRun
    from backend.app.code_tasks.task_candidate_git import CandidateGitDispatch
    from backend.app.code_tasks.task_candidate_worker import CandidateCaptureWorker
    from backend.app.code_tasks.task_project_check import finish_coding_project_check
    from backend.app.code_tasks.task_project_check_worker import CodingProjectCheckWorker
    from backend.app.code_tasks.task_read_api import project_saved_task, task_read_router
    from backend.app.code_tasks.task_stop_api import task_stop_router
    from backend.app.infrastructure.idempotency import Idempotency
    from backend.app.infrastructure.project_check_dispatch import ProjectCheckDispatch
    from backend.app.infrastructure.resources import ResourceCatalog
    from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
    from backend.app.infrastructure.windows_private_package import (
        PrivatePackageGuard,
        create_private_package,
    )
    from backend.app.shared.http_boundary import HttpRuntime
    from backend.tests.code_tasks.test_execution_profile_versions import resources

    driver, operation, raw, snapshot = fixture
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(
        database=database, catalog=ResourceCatalog(), commands=lambda: executor
    )
    admissions = (fixture_project_admission(),)
    if multi:
        admissions += (fixture_project_admission(missing=True),)

    content_deadlines = []
    original_run = _FixedGitRun.run

    def observe_content_run(runner, *args, **kwargs):
        if handoff and isinstance(runner._dispatch, CandidateGitDispatch):
            remaining = kwargs['deadline'] - monotonic()
            assert 0 < remaining <= 15.1, remaining
            content_deadlines.append(remaining)
        return original_run(runner, *args, **kwargs)

    @contextmanager
    def connect():
        yield frames

    with (
        PrivatePackageGuard(root / 'task-source') as parent,
        LaunchJournal(create_private_package(root / 'check-evidence')) as journal,
        resources(snapshot),
        patch.object(_FixedGitRun, 'run', observe_content_run),
    ):

        class CompleteCaptureWorker(CandidateCaptureWorker):
            def _unknown(self, operation_id, step_no):
                raise AssertionError(
                    f'Original candidate capture became unknown at {operation_id}/{step_no}'
                )

        capture = CompleteCaptureWorker(
            runtime,
            driver,
            parent,
            binding,
            journal,
            connect,
            cancelled=lambda: False,
            cleanup_timeout_ms=30000,
        )
        assert capture.advance()
        assert capture.advance()
        assert not capture.has_retained_command and not capture.advance()
        with database.transaction() as connection:
            capture_steps = [
                tuple(row)
                for row in connection.execute(
                    'SELECT step_no,status FROM code_operation_steps WHERE operation_id=? ORDER BY step_no',
                    (operation,),
                )
            ]
        assert capture_steps[:3] == [(1, 'SUCCEEDED'), (2, 'SUCCEEDED'), (3, 'SUCCEEDED')], (
            capture_steps
        )
        if handoff:
            assert content_deadlines, 'No actual content Git deadline was observed'

        class CommitReplayCheckWorker(CodingProjectCheckWorker):
            def _read_candidate(self, row):
                try:
                    return super()._read_candidate(row)
                except (OSError, RuntimeError, ValueError) as error:
                    raise AssertionError('Original project check candidate was deferred') from error

            def _execute(self, *args):
                try:
                    super()._execute(*args)
                except (OSError, RuntimeError, ValueError) as error:
                    raise AssertionError('Original project check execution was deferred') from error

            def _finish(self, claim, result):
                super()._finish(claim, result)
                with database.transaction(write=True) as connection:
                    before = connection.total_changes
                    finish_coding_project_check(
                        connection, claim, result, at='2026-11-11T00:00:00.000Z'
                    )
                    assert connection.total_changes == before

        class InterruptedCheckWorker(CodingProjectCheckWorker):
            def _finish(self, claim, result):
                raise OSError('Injected loss after the original terminal receipt')

        if restart:
            first = InterruptedCheckWorker(
                runtime, parent, binding, journal, connect, admissions, cancelled=lambda: False
            )
            assert first.advance() and first.has_retained_command
            with database.transaction() as connection:
                status = connection.execute(
                    'SELECT status FROM code_operation_steps WHERE operation_id=? AND step_no=4',
                    (operation,),
                ).fetchone()[0]
                assert status == 'RUNNING'

            @contextmanager
            def no_guard():
                raise AssertionError('A completed original check must recover locally')
                yield

            worker = CommitReplayCheckWorker(
                runtime, parent, binding, journal, no_guard, (), cancelled=lambda: False
            )
        else:
            worker = CommitReplayCheckWorker(
                runtime, parent, binding, journal, connect, admissions, cancelled=lambda: False
            )
        assert worker.advance()
        assert not worker.has_retained_command
        if multi:
            with database.transaction() as connection:
                pending = connection.execute(
                    "SELECT status,exit_code FROM code_commands WHERE operation_id=? AND purpose='CHECK' ORDER BY id",
                    (operation,),
                ).fetchall()
                assert [tuple(row) for row in pending] == [('SUCCEEDED', 0), ('PENDING', None)]
            assert worker.advance()
            assert not worker.has_retained_command
        assert not worker.advance()
        with database.transaction() as connection:
            rows = connection.execute(
                """SELECT c.status,c.exit_code,i.result,v.id,v.stop_status,v.cleanup_status
                   FROM code_commands c JOIN code_verification_items i ON i.id=c.verification_item_id
                   JOIN code_verifications v ON v.id=i.verification_id
                   WHERE c.operation_id=? AND c.purpose='CHECK' ORDER BY c.id""",
                (operation,),
            ).fetchall()
            assert len(rows) == len(admissions), list(
                connection.execute(
                    'SELECT id,status,failure_code FROM code_operations WHERE id=?', (operation,)
                )
            )
            row = rows[0]
            if multi:
                second = rows[1]
                assert (second['status'], second['exit_code'], second['result']) == (
                    'FAILED',
                    1,
                    'FAILED',
                )
                assert second['id'] == row['id']
            assert (row['status'], row['exit_code'], row['result']) == ('SUCCEEDED', 0, 'PASSED')
            assert (row['stop_status'], row['cleanup_status']) == ('VERIFIED', 'VERIFIED')
            assert (
                connection.execute(
                    "SELECT result FROM code_verification_items WHERE verification_id=? AND evidence_kind='CONTENT_INTEGRITY'",
                    (row['id'],),
                ).fetchone()[0]
                == 'PASSED'
            )
            configuration = connection.execute(
                """SELECT a.status,a.effective_evidence FROM code_verifications v
                   JOIN code_environment_records e ON e.id=v.environment_record_id
                   JOIN code_configuration_applications a ON a.id=e.effective_config_application_id
                   WHERE v.id=?""",
                (row['id'],),
            ).fetchone()
            assert configuration['status'] == 'APPLIED'
            assert json.loads(configuration['effective_evidence'])['result'] == 'VERIFIED'
            task = connection.execute('SELECT * FROM code_tasks').fetchone()
            detail = project_saved_task(connection, runtime.catalog, task)
            assert detail['current_refs']['verification_id'] == row['id']
            assert detail['active_operations'] == []
        from backend.app.code_tasks.authorization_api import authorization_router
        from backend.app.code_tasks.check_set_api import check_set_router
        from backend.app.code_tasks.execution_profile_api import execution_profile_router
        from backend.app.code_tasks.task_defects import defect_router
        from backend.app.code_tasks.task_repairs import repair_router

        app = FastAPI()
        app.include_router(authorization_router)
        app.include_router(check_set_router)
        app.include_router(execution_profile_router)
        app.include_router(task_read_router)
        app.include_router(task_stop_router)
        app.include_router(command_router)
        app.include_router(defect_router)
        app.include_router(repair_router)
        app.state.walle_runtime = HttpRuntime(database, runtime.catalog, executor)
        app.state.walle_repository_registration = SimpleNamespace(
            accepts_candidate_capture=True,
            accepts_native_responses=True,
            accepts_model_resumes=handoff,
            project_check_admissions=admissions,
            wake=lambda: None,
        )
        task_path = f'/api/v1/code-tasks/{task["id"]}'
        detail_path = task_path + f'/verifications/{row["id"]}'
        list_path = task_path + f'/candidates/{task["current_candidate_id"]}/verifications'
        with TestClient(app) as client:
            response = client.get(task_path)
            assert response.status_code == 200, response.text
            records = client.get(
                task_path + '/records', params={'session_id': task['active_session_id']}
            )
            assert records.status_code == 200, records.text
            outputs = [
                value
                for value in records.json()['data']['items']
                if value['kind'] == 'COMMAND_OUTPUT'
            ]
            with database.transaction() as connection:
                commands = connection.execute(
                    "SELECT id FROM code_commands WHERE operation_id=? AND purpose='CHECK' ORDER BY id",
                    (operation,),
                ).fetchall()
            assert outputs and all(
                value['source_kind'] == 'COMMAND'
                and value['source_id'] in {command['id'] for command in commands}
                for value in outputs
            )
            first = [value for value in outputs if value['source_id'] == commands[0]['id']]
            assert any(value['text'].startswith('标准输出') for value in first)
            assert all(chr(0) not in value['text'] for value in first)
            response = client.get(detail_path)
            assert response.status_code == 200, response.text
            projected = response.json()['data']
            assert projected['eligible'] and not projected['ineligibility_reason_codes']
            assert projected['environment_record']['effective_config_application_id'] is not None
            assert all(item['expected_case_count'] is None for item in projected['items'])
            project_item = next(
                item for item in projected['items'] if item['evidence_kind'] == 'PROCESS_EXIT'
            )
            case_path = detail_path + f'/items/{project_item["id"]}/cases'
            case_response = client.get(case_path, params={'page': 2})
            assert case_response.status_code == 200, case_response.text
            assert case_response.json()['data'] == {'items': []}
            assert case_response.json()['meta']['pagination']['page'] == 2
            assert client.get(case_path + '?page=1&page=2').status_code == 422
            assert client.get(detail_path + '/items/900/cases').status_code == 404
            from base64 import b64decode

            file_path = task_path + f'/candidates/{task["current_candidate_id"]}/file'
            chunk = client.get(
                file_path, params={'path': 'src/input.bin', 'offset': 4, 'length': 3}
            )
            assert chunk.status_code == 200, chunk.text
            actual = chunk.json()['data']
            assert b64decode(actual['content_base64']) == raw[4:7] and actual['next_offset'] == 7
            empty = client.get(file_path, params={'path': 'src/input.bin', 'offset': 100})
            assert empty.json()['data'] == {
                'candidate_id': task['current_candidate_id'],
                'path': 'src/input.bin',
                'offset': 100,
                'length': 0,
                'total_bytes': len(raw),
                'content_base64': '',
                'next_offset': None,
            }
            assert client.get(file_path, params={'path': '../input.bin'}).status_code == 422
            assert client.get(file_path, params={'path': 'src/INPUT.bin'}).status_code == 404
            assert (
                'process_identity' not in response.text and 'candidate-source' not in response.text
            )
            response = client.get(list_path, params={'purpose': 'HANDOFF'})
            assert response.status_code == 200, response.text
            assert response.json()['data']['items'] == [projected]
            response = client.get(list_path, params={'page': 2})
            assert response.status_code == 200 and response.json()['data']['items'] == []
            assert client.get(list_path, params={'purpose': 'ACCEPTANCE'}).status_code == 422
            assert client.get(list_path + '?page=1&page=2').status_code == 422
            assert (
                client.get('/api/v1/code-tasks/900/verifications/' + str(row['id'])).status_code
                == 404
            )
            if handoff:
                from backend.tests.infrastructure.v20_coding_repair_worker import (
                    exercise_checked_repair,
                )

                exercise_checked_repair(
                    runtime, client, task_path, capture, worker, driver, replace_session=True
                )
                from backend.tests.infrastructure.v20_live_configuration_worker import (
                    exercise_live_control_configuration,
                )

                exercise_live_control_configuration(
                    runtime,
                    client,
                    task_path,
                    driver,
                    check_worker=worker,
                    check_set=True,
                    output_limit=64,
                )
                exercise_live_control_configuration(
                    runtime,
                    client,
                    task_path,
                    driver,
                    check_worker=worker,
                    output_limit=1,
                    expect_output_limit=True,
                )
                exercise_live_control_configuration(
                    runtime,
                    client,
                    task_path,
                    driver,
                    check_worker=worker,
                    output_limit=64,
                )
                from backend.app.code_tasks.task_start_authorization import (
                    original_start_authorization,
                )

                with runtime.database.transaction() as connection:
                    original_models = original_start_authorization(
                        connection, int(task_path.rsplit('/', 1)[-1])
                    )['scope']['model_profile_refs']
                exercise_live_control_configuration(
                    runtime, client, task_path, driver, check_worker=worker, model_refs=[]
                )
                exercise_live_control_configuration(
                    runtime,
                    client,
                    task_path,
                    driver,
                    check_worker=worker,
                    model_refs=original_models,
                )
                exercise_role_handoffs(
                    runtime, client, task_path, driver, capture, worker, admissions
                )
            elif multi:

                def no_guard_on_withdrawal():
                    raise AssertionError('A queued command without its admission cannot run')

                state = client.get(task_path).json()['data']['state_version']
                accepted = client.post(
                    list_path,
                    json={'purpose': 'HANDOFF', 'expected_state_version': state},
                    headers={'Idempotency-Key': str(uuid4())},
                )
                assert accepted.status_code == 202, accepted.text
                original = accepted.json()['data']['operation_id']
                assert worker.advance()
                withdrawn = CodingProjectCheckWorker(
                    runtime,
                    parent,
                    binding,
                    journal,
                    no_guard_on_withdrawal,
                    (),
                    cancelled=lambda: False,
                )
                assert withdrawn.advance() and not withdrawn.advance()
                with database.transaction() as connection:
                    items = connection.execute(
                        'SELECT i.result,c.status,c.exit_code,c.started_at FROM code_commands c JOIN code_verification_items i ON i.id=c.verification_item_id WHERE c.operation_id=? ORDER BY c.id',
                        (original,),
                    ).fetchall()
                    assert tuple(items[0])[:3] == ('PASSED', 'SUCCEEDED', 0)
                    assert tuple(items[1]) == ('NOT_RUN', 'CANCELLED', None, None)
            elif not restart:

                def verify_again():
                    state = client.get(task_path).json()['data']['state_version']
                    body = {'purpose': 'HANDOFF', 'expected_state_version': state}
                    headers = {'Idempotency-Key': str(uuid4())}
                    accept = client.post(list_path, json=body, headers=headers)
                    assert accept.status_code == 202, accept.text
                    accepted = accept.json()['data']
                    assert (
                        client.post(list_path, json=body, headers=headers).json()['data']
                        == accepted
                    )
                    return accepted['operation_id']

                verify_operation = verify_again()
                state = client.get(task_path)
                assert state.status_code == 200, state.text
                assert state.json()['data']['active_operations'] == [
                    {
                        'id': verify_operation,
                        'operation_type': 'VERIFY_CANDIDATE',
                        'status': 'PENDING',
                    }
                ]
                assert worker.advance()
                response = client.get(task_path + f'/operations/{verify_operation}')
                assert response.status_code == 200, response.text
                operation_data = response.json()['data']
                assert operation_data['status'] == 'SUCCEEDED'
                assert [part['status'] for part in operation_data['steps']] == ['SUCCEEDED'] * 3
                verification_id = operation_data['steps'][-1]['result_ref']['verification_id']
                assert verification_id != row['id']
                newer = client.get(task_path + f'/verifications/{verification_id}')
                assert newer.status_code == 200, newer.text
                assert newer.json()['data']['eligible']
                assert newer.json()['data']['candidate_id'] == projected['candidate_id']

                lost = verify_again()
                with patch.object(
                    ProjectCheckDispatch, 'run', side_effect=OSError('local copy interrupted')
                ):
                    interrupted = CodingProjectCheckWorker(
                        runtime,
                        parent,
                        binding,
                        journal,
                        connect,
                        admissions,
                        cancelled=lambda: False,
                    )
                    assert interrupted.advance() and not interrupted.has_retained_command

                def no_guard_after_failed_copy():
                    raise AssertionError('A never-dispatched copy must close locally')

                recovered = CodingProjectCheckWorker(
                    runtime,
                    parent,
                    binding,
                    journal,
                    no_guard_after_failed_copy,
                    (),
                    cancelled=lambda: False,
                )
                assert recovered.advance()
                response = client.get(task_path + f'/operations/{lost}')
                assert response.status_code == 200, response.text
                failed = response.json()['data']
                assert (
                    failed['status'] == 'FAILED' and failed['failure_code'] == 'EVIDENCE_INCOMPLETE'
                )
                assert [part['status'] for part in failed['steps']] == [
                    'SUCCEEDED',
                    'FAILED',
                    'CANCELLED',
                ]
                with database.transaction() as connection:
                    assert (
                        connection.execute('SELECT count(*) FROM code_candidates').fetchone()[0]
                        == 1
                    )
                    evidence = connection.execute(
                        'SELECT status,stop_status,cleanup_status FROM code_verifications WHERE operation_id=?',
                        (lost,),
                    ).fetchone()
                    assert tuple(evidence) == ('UNKNOWN', 'VERIFIED', 'VERIFIED')
            app.state.walle_repository_registration = None
            response = client.get(detail_path)
            assert response.status_code == 200, response.text
            if not handoff:
                assert response.json()['data']['ineligibility_reason_codes'] == [
                    'RESOURCE_NOT_READY'
                ]
    publish(
        root / 'control-git-pipe-result.json',
        {'result': 'durable', 'candidate_sha256': hashlib.sha256(raw).hexdigest()},
    )
    wait(root / 'stop')


def exercise_role_handoffs(runtime, client, path, capture_driver, capture, worker, admissions):
    from types import SimpleNamespace
    from uuid import uuid4

    from backend.app.code_tasks.task_model_ingress import ModelWindow, read_original_window_state
    from backend.app.code_tasks.task_role_chain import current_role_chain
    from backend.app.code_tasks.task_role_handoff import advance_role_handoff
    from backend.app.code_tasks.task_role_reconciliation import advance_role_reconciliation
    from backend.app.code_tasks.task_runtime_stop import _stop_sessions

    calls = []
    observations = []
    creation_observations = []
    created_native = {}

    class NativeHandoffFixture:
        def session_available(self, operation):
            return True

        def observe_capture_turn(self, scope, window, ref, checkpoint):
            calls.append(('QUIESCE', window.execution_session_id))
            return capture_driver.observe_capture_turn(scope, window, ref, checkpoint)

        def revoke_session_source(self, scope, previous, ref, checkpoint):
            checkpoint()
            calls.append(('REVOKE', previous.execution_session_id))

        def create_session(self, scope, checkpoint):
            checkpoint()
            assert scope.transition_operation_id != scope.operation_id
            assert scope.metadata()['walle']['operation_id'] == scope.transition_operation_id
            assert scope.launch_generation == 1
            calls.append(('CREATE_SESSION', scope.session_id))
            created_native[scope.session_id] = f'ses_role{scope.session_id}'
            if scope.role == 'FRONTEND':
                raise OSError('Injected original native creation reply lost')
            return SimpleNamespace(native_id=created_native[scope.session_id])

        def observe_created_session(self, scope, checkpoint):
            checkpoint()
            creation_observations.append(scope.session_id)
            return created_native[scope.session_id] if len(creation_observations) > 1 else None

        def role_payload(self, scope, context, handoff, checkpoint):
            checkpoint()
            assert context.documents and handoff['scope_stages']
            return {'messageID': f'msg_role{scope.session_id}', 'parts': []}

        def gateway_reference(self, scope):
            return 'test:gateway'

        def send_successor(self, scope, previous, original, payload, checkpoint):
            checkpoint()
            new = ModelWindow(
                scope.task_id,
                scope.instance_id,
                scope.control_generation,
                scope.session_id,
                original['native_session_id'],
                scope.transition_operation_id,
                original['native_message_id'],
            )
            with runtime.database.transaction() as connection:
                assert (
                    read_original_window_state(connection, new, original['gateway_credential_ref'])
                    == 'QUEUED'
                )
                assert (
                    read_original_window_state(
                        connection, previous, original['gateway_credential_ref']
                    )
                    is None
                )
            calls.append(('SEND_HANDOFF', scope.session_id))
            if scope.role == 'FRONTEND':
                raise OSError('Injected lost original native acceptance')
            return payload['messageID']

        def observe_successor_message(self, scope, original, checkpoint):
            checkpoint()
            observations.append(scope.session_id)
            return None if len(observations) == 1 else original['native_message_id']

    fixture = NativeHandoffFixture()
    operation_ids = []
    for role in ('FRONTEND', 'INTEGRATION'):
        for _ in range(16):
            response = client.get(path)
            assert response.status_code == 200, response.text
            data = response.json()['data']
            if data['phase'] == role:
                break
            if data['status'] == 'WAITING':
                active = data['active_operations'][0]
                assert active['operation_type'] == 'HANDOFF_ROLE' and active['status'] == 'UNKNOWN'
                original_step = next(
                    step
                    for step in client.get(path + f'/operations/{active["id"]}').json()['data'][
                        'steps'
                    ]
                    if step['status'] != 'SUCCEEDED'
                )['step_type']
                assert not advance_role_handoff(
                    runtime, fixture, admissions, cancelled=lambda: False
                )
                headers = {'Idempotency-Key': str(uuid4())}
                reconcile_path = path + '/reconcile'
                fixed = {
                    'operation_id': active['id'],
                    'expected_state_version': data['state_version'],
                }
                request = client.post(reconcile_path, json=fixed, headers=headers)
                assert request.status_code == 202, request.text
                accepted = request.json()['data']
                assert (
                    client.post(reconcile_path, json=fixed, headers=headers).json()['data']
                    == accepted
                )
                original = client.get(
                    '/api/v1/code-command-receipts',
                    params={
                        'method': 'POST',
                        'path': reconcile_path,
                        'request_key': headers['Idempotency-Key'],
                    },
                )
                assert original.status_code == 200, original.text
                assert advance_role_reconciliation(runtime, fixture, cancelled=lambda: False)
                record = client.get(path + f'/operations/{accepted["operation_id"]}')
                assert record.status_code == 200, record.text
                assert record.json()['data']['steps'][-1]['result_ref'] == {
                    'operation_id': active['id'],
                    'original_status': ('RUNNING' if len(creation_observations) > 1 else 'UNKNOWN')
                    if original_step == 'CREATE_SESSION'
                    else ('UNKNOWN' if len(observations) == 1 else 'SUCCEEDED'),
                }
                continue
            assert advance_role_handoff(runtime, fixture, admissions, cancelled=lambda: False)
            active = client.get(path)
            if active.status_code != 200:
                # Preserve the actual boundary cause before its public 500 mask.
                from fastapi import Request

                from backend.app.code_tasks.task_read_api import (
                    TaskDetailRequest,
                    TaskDetailResponse,
                    read_code_task,
                )

                actual = Request(
                    {
                        'type': 'http',
                        'method': 'GET',
                        'path': path,
                        'query_string': b'',
                        'path_params': {'task_id': path.rsplit('/', 1)[-1]},
                        'app': client.app,
                    }
                )
                parsed = TaskDetailRequest.parse(actual)
                projected = read_code_task(runtime, parsed)
                TaskDetailResponse.project(projected['data'], parsed)
            assert active.status_code == 200, active.text
            for row in active.json()['data']['active_operations']:
                if row['operation_type'] == 'HANDOFF_ROLE' and row['id'] not in operation_ids:
                    operation_ids.append(row['id'])
        else:
            raise AssertionError('Original Coding handoff did not finish')
        assert data['status'] == 'RUNNING'
        history = client.get(path + f'/operations/{operation_ids[-1]}')
        assert history.status_code == 200, history.text
        assert [step['status'] for step in history.json()['data']['steps']] == ['SUCCEEDED'] * 5
        assert 'ses_role' not in history.text and 'msg_role' not in history.text
        with runtime.database.transaction() as connection:
            current = connection.execute(
                'SELECT * FROM code_tasks WHERE id=?', (data['id'],)
            ).fetchone()
            chain = current_role_chain(connection, current)
            assert chain.role == role and chain.operations == tuple(operation_ids)
            session = connection.execute(
                'SELECT * FROM code_sessions WHERE id=?', (current['active_session_id'],)
            ).fetchone()
            window = ModelWindow(
                current['id'],
                session['instance_id'],
                current['control_generation'],
                session['id'],
                session['native_session_id'],
                operation_ids[-1],
                session['native_message_id'],
            )
            assert (
                read_original_window_state(connection, window, session['gateway_credential_ref'])
                == 'OPEN'
            )
        accepted = client.post(
            path + '/candidates',
            json={'purpose': 'HANDOFF', 'expected_state_version': data['state_version']},
            headers={'Idempotency-Key': str(uuid4())},
        )
        assert accepted.status_code == 202, accepted.text
        assert capture.advance() and capture.advance()
        assert worker.advance() and not worker.has_retained_command
        captured = client.get(path)
        assert captured.status_code == 200, captured.text
        view = captured.json()['data']
        verification = client.get(
            path + f'/verifications/{view["current_refs"]["verification_id"]}'
        )
        assert verification.status_code == 200, verification.text
        observed = verification.json()['data']
        assert observed['eligible'], observed
        assert observed['role'] == role
        assert observed['scope_stages'] == list(chain.stages)
        assert observed['backend_handoff_operation_id'] == chain.backend_handoff
        assert observed['frontend_handoff_operation_id'] == chain.frontend_handoff

    assert [call[0] for call in calls] == [
        'QUIESCE',
        'REVOKE',
        'CREATE_SESSION',
        'SEND_HANDOFF',
    ] * 2
    assert len(observations) == 2 and len(set(observations)) == 1
    assert len(creation_observations) == 2 and len(set(creation_observations)) == 1
    assert not advance_role_handoff(runtime, fixture, admissions, cancelled=lambda: False)
    from backend.tests.infrastructure.v20_coding_repair_worker import exercise_checked_repair

    view = exercise_checked_repair(
        runtime, client, path, capture, worker, capture_driver, replace_session=True
    )
    view = exercise_checked_repair(
        runtime, client, path, capture, worker, capture_driver, cancel_first=True
    )
    body = {
        'expected_state_version': view['state_version'],
        'candidate_id': view['current_candidate_id'],
        'verification_id': view['current_refs']['verification_id'],
    }
    headers = {'Idempotency-Key': str(uuid4())}
    publication_path = path + '/testing-publication'
    result = client.post(publication_path, json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert (
        client.post(publication_path, json=body, headers=headers).json()['data']
        == result.json()['data']
    )
    receipt = client.get(
        '/api/v1/code-command-receipts',
        params={
            'method': 'POST',
            'path': publication_path,
            'request_key': headers['Idempotency-Key'],
        },
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()['data']['original_outcome']['data'] == result.json()['data']
    assert (
        client.post(
            publication_path, json=body, headers={'Idempotency-Key': str(uuid4())}
        ).status_code
        == 409
    )
    published = client.get(path)
    assert published.status_code == 200, published.text
    view = published.json()['data']
    assert (view['status'], view['phase']) == ('AWAITING_TESTING', 'TESTING')
    with runtime.database.transaction() as connection:
        quiet = connection.execute(
            """SELECT q.observed_at,q.active_process_count FROM code_candidates c
               JOIN code_runtime_observations q ON q.operation_id=c.capture_operation_id
               AND q.task_id=c.task_id AND q.control_generation=c.control_generation
               WHERE c.id=? AND q.kind='QUIESCE' AND q.result='VERIFIED'""",
            (view['current_candidate_id'],),
        ).fetchone()
    assert view['runtime']['activity_status'] == 'QUIESCENT'
    assert view['runtime']['observed_at'] == quiet['observed_at']
    assert view['runtime']['active_process_count'] == quiet['active_process_count']
    action = next(row for row in view['available_actions'] if row['action'] == 'LINK_TEST_REPORT')
    assert action['enabled'] and action['reason_code'] is None
    report_link = path + '/test-reports'
    missing_report = client.post(
        report_link,
        json={
            'expected_state_version': view['state_version'],
            'candidate_id': view['current_candidate_id'],
            'test_report_id': 1,
        },
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert missing_report.status_code == 404, missing_report.text
    assert client.get(path).json()['data']['current_refs']['test_report_id'] is None
    from backend.tests.infrastructure.v20_coding_failed_report_worker import exercise_failed_report_link

    exercise_failed_report_link(runtime, client, path, capture._parent.path.parent)
    candidate = client.get(path + f'/candidates/{body["candidate_id"]}').json()['data']
    assert candidate['published_for_testing_at'] is not None
    published_operation = client.get(path + f'/operations/{candidate["publication_operation_id"]}')
    assert published_operation.status_code == 200, published_operation.text
    assert [step['step_type'] for step in published_operation.json()['data']['steps']] == [
        'VALIDATE',
        'SAVE_FACT',
    ]
    from backend.tests.infrastructure.v20_live_configuration_worker import (
        exercise_live_control_configuration,
    )

    exercise_live_control_configuration(runtime, client, path, capture_driver, check_set=True)
    configured = client.get(path)
    assert configured.status_code == 200, configured.text
    view = configured.json()['data']
    assert (view['status'], view['phase']) == ('VERIFYING', 'INTEGRATION')
    assert view['current_refs']['test_report_id'] is None
    assert view['current_refs']['delivery_plan_id'] is None
    assert client.get(path + f'/candidates/{body["candidate_id"]}').json()['data'] == candidate
    recheck = client.post(
        path + f'/candidates/{body["candidate_id"]}/verifications',
        json={'purpose': 'HANDOFF', 'expected_state_version': view['state_version']},
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert recheck.status_code == 202, recheck.text
    assert worker.advance()
    after_check = client.get(path)
    assert after_check.status_code == 200, after_check.text
    view = after_check.json()['data']
    assert (view['status'], view['phase']) == ('AWAITING_TESTING', 'TESTING')
    assert view['current_refs']['verification_id'] != body['verification_id']
    assert view['current_candidate_id'] == body['candidate_id']
    same = client.get(path + f'/candidates/{body["candidate_id"]}')
    assert same.status_code == 200 and same.json()['data'] == candidate

    with runtime.database.transaction() as connection:
        assert connection.execute('SELECT count(*) FROM testing_tasks').fetchone()[0] == 1
    stopped = client.post(
        path + '/terminate',
        json={'expected_state_version': view['state_version']},
        headers={'Idempotency-Key': str(uuid4())},
    )
    assert stopped.status_code == 202, stopped.text
    with runtime.database.transaction() as connection:
        task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (view['id'],)).fetchone()
        stop = connection.execute(
            'SELECT * FROM code_operations WHERE id=?', (stopped.json()['data']['operation_id'],)
        ).fetchone()
        start = connection.execute(
            "SELECT * FROM code_operations WHERE task_id=? AND operation_type='START'",
            (task['id'],),
        ).fetchone()
        instance = connection.execute(
            'SELECT * FROM code_instances WHERE task_id=?', (task['id'],)
        ).fetchone()
        sessions, native = _stop_sessions(connection, task, stop, start, instance)
        assert len(sessions) == 5 and native['role'] == 'INTEGRATION'
        assert instance['control_generation'] == 1 and stop['control_generation'] == 6


def main():
    reference, sid, guard_pid, mode = sys.argv[1:]
    root = Path.cwd()
    database = None
    metadata_mode = mode.startswith('METADATA_')
    baseline_mode = mode.startswith('BASELINE_')
    baseline_catalog = None
    if (
        mode.startswith('REGISTER')
        or metadata_mode
        or baseline_mode
        or mode in ('OBSERVE_THREAD', 'RECOVER_REGISTRATION')
    ):
        from backend.app.infrastructure.database import Database
        from backend.app.infrastructure.schema_v20_release import load_release

        name = (
            'observation.sqlite'
            if metadata_mode or mode == 'OBSERVE_THREAD'
            else 'registration.sqlite'
        )
        baseline_restart = mode.startswith(('BASELINE_RESTART_', 'BASELINE_QUERY_RESTART_'))
        database_root = (
            root.parent / 'crashed' if mode == 'RECOVER_REGISTRATION' or baseline_restart else root
        )
        database = Database(database_root / name, schema_release=load_release())
        database.initialize()
        if baseline_restart:
            from backend.app.infrastructure.resources import ResourceCatalog

            baseline_catalog = ResourceCatalog()
        elif baseline_mode:
            baseline_catalog = seed_baseline_configuration(database)
    if mode in ('REGISTER_THREAD', 'OBSERVE_THREAD') or mode.startswith(
        ('BASELINE_HTTP_', 'BASELINE_QUERY_HTTP_')
    ):
        threaded_repository(
            root,
            reference,
            sid,
            int(guard_pid),
            database,
            refresh=mode == 'OBSERVE_THREAD',
            baseline_catalog=baseline_catalog,
            snapshot_reads=mode.startswith('BASELINE_QUERY_HTTP_'),
            start_workspace=mode.startswith('BASELINE_QUERY_HTTP_START_'),
        )
        return
    testing_fixture = None
    if mode in ('TESTING_VALIDATION_GROUP', 'TESTING_VALIDATION_RECOVERY'):
        from backend.app.infrastructure.database import Database
        from backend.app.infrastructure.schema_v20_release import load_release
        from backend.tests.infrastructure.v20_testing_validation_worker import prepare_assets
        from backend.tests.infrastructure.v20_validation_probe import validation_phase

        validation_phase(root, 'PREPARE_DATABASE')
        database = Database(root / 'validation.sqlite', schema_release=load_release())
        database.initialize()
        validation_phase(root, 'PREPARE_CATALOG')
        baseline_catalog = seed_baseline_configuration(database)
        validation_phase(root, 'PREPARE_ASSETS')
        testing_fixture = prepare_assets(root, database, baseline_catalog)
        validation_phase(root, 'CONNECT_GUARD')
    candidate_fixture = None
    if mode in (
        'CANDIDATE_DURABLE',
        'CANDIDATE_RELEASED_LOST_RESULT',
        'PROJECT_CHECK_DURABLE',
        'PROJECT_CHECK_MULTI',
        'PROJECT_CHECK_HANDOFF',
        'PROJECT_CHECK_RESTART',
    ):
        from backend.app.infrastructure.database import Database
        from backend.app.infrastructure.schema_v20_release import load_release

        database = Database(root / 'candidate.sqlite', schema_release=load_release())
        database.initialize()
        candidate_fixture = seed_candidate_capture(
            root,
            database,
            project_check=mode
            in (
                'PROJECT_CHECK_DURABLE',
                'PROJECT_CHECK_RESTART',
                'PROJECT_CHECK_MULTI',
                'PROJECT_CHECK_HANDOFF',
            ),
            multi=mode == 'PROJECT_CHECK_MULTI',
            handoff=mode == 'PROJECT_CHECK_HANDOFF',
        )
    with ObservedProcess(int(guard_pid)) as expected:
        path = Path(expected.identity.image_path)
        raw = path.read_bytes()
        with (
            ExitStack() as backend_owners,
            (
                ProcessLock.for_database(database.path)
                if database is not None
                else ProcessLock(
                    (root.parent if mode == 'PROJECT_CHECK_RECOVER_CONTROLLER' else root)
                    / 'guard-exchange-backend.lock'
                )
            ) as lock,
            ExecutablePin(
                path, expected_byte_count=len(raw), expected_sha256=hashlib.sha256(raw).hexdigest()
            ) as image,
            GuardPipeClient(
                reference,
                backend_sid=sid,
                server_sid=sid,
                expected_guard=expected.identity,
                program=image,
            ) as client,
            GuardPipeIO(client) as io,
        ):
            publish(root / 'io-peer-ready', os.getpid())
            frames = GuardPipeFrames(io)
            binding = bind_backend_controller(lock, reference)
            scope = binding.scope(17, 2, NONCE)
            registration = None
            if mode.startswith('REGISTER'):
                registration = registration_actor(root, binding, lock, backend_owners, database)

            def send(
                action,
                *,
                data=None,
                reference=None,
                scope_override=None,
                dispatcher=None,
                content_parent=None,
            ):
                actual = scope if scope_override is None else scope_override
                request = build_guard_request_header(
                    binding,
                    lock,
                    action=action,
                    operation_id=actual.operation_id,
                    step_no=actual.step_no,
                    nonce=actual.nonce,
                    binding_ref=reference,
                    action_input=data or {},
                )
                if dispatcher is not None:
                    method = dispatcher.observe if action == 'OBSERVE' else dispatcher.dispatch
                    return method(request, timeout_ms=30000, cancelled=lambda: False)
                return exchange_guard_control_git(
                    frames,
                    binding,
                    lock,
                    request,
                    timeout_ms=1200 if mode == 'NO_REPLY' else 30000,
                    cancelled=lambda: False,
                    content_parent=content_parent,
                )

            if mode in ('CANDIDATE_DURABLE', 'CANDIDATE_RELEASED_LOST_RESULT'):
                run_durable_candidate(
                    root,
                    database,
                    lock,
                    frames,
                    binding,
                    candidate_fixture,
                    lost_result=mode == 'CANDIDATE_RELEASED_LOST_RESULT',
                )
                return

            if mode == 'CANDIDATE_PACKAGE':
                run_candidate_package(root, binding, send)
                return

            if mode in (
                'PROJECT_CHECK_DURABLE',
                'PROJECT_CHECK_RESTART',
                'PROJECT_CHECK_MULTI',
                'PROJECT_CHECK_HANDOFF',
            ):
                run_persisted_project_check(
                    root,
                    database,
                    lock,
                    frames,
                    binding,
                    candidate_fixture,
                    restart=mode == 'PROJECT_CHECK_RESTART',
                    multi=mode == 'PROJECT_CHECK_MULTI',
                    handoff=mode == 'PROJECT_CHECK_HANDOFF',
                )
                return

            if mode in ('TESTING_VALIDATION_GROUP', 'TESTING_VALIDATION_RECOVERY'):
                from backend.tests.infrastructure.v20_testing_validation_worker import (
                    run_validation_group,
                )

                result = run_validation_group(
                    root,
                    database,
                    baseline_catalog,
                    testing_fixture,
                    binding,
                    lock,
                    frames,
                    recovery=mode == 'TESTING_VALIDATION_RECOVERY',
                )
                publish(root / 'control-git-pipe-result.json', result)
                wait(root / 'stop')
                return

            if mode == 'DELIVERY_NATIVE':
                from backend.tests.infrastructure.v20_native_delivery_worker import (
                    exercise_owned_delivery,
                )

                result = exercise_owned_delivery(root, binding, send)
                publish(root / 'control-git-pipe-result.json', result)
                wait(root / 'stop')
                return

            if mode == 'TESTING_BROWSER_DRIVER':
                from backend.tests.infrastructure.v20_browser_driver_native_worker import (
                    exercise_driver,
                )

                result = exercise_driver(root, binding, lock, frames)
                publish(root / 'control-git-pipe-result.json', result)
                wait(root / 'stop')
                return

            if mode == 'TESTING_HTTP_CHECK':
                from backend.tests.infrastructure.v20_testing_http_worker import run_native_http

                result = run_native_http(root, binding, lock, frames)
                publish(root / 'control-git-pipe-result.json', result)
                wait(root / 'stop')
                return

            if mode in (
                'PROJECT_CHECK',
                'TESTING_PROJECT_CHECK',
                'TESTING_SNAPSHOT_CHECK',
                'TESTING_STDIN_CHECK',
                'TESTING_FIXTURE_CHECK',
                'PROJECT_CHECK_REJECT',
                'PROJECT_CHECK_CONTROLLER_LOST',
            ):
                run_project_check(
                    root,
                    binding,
                    lock,
                    frames,
                    reject_capsule=mode == 'PROJECT_CHECK_REJECT',
                    interrupt=mode == 'PROJECT_CHECK_CONTROLLER_LOST',
                    testing=mode.startswith('TESTING_'),
                    snapshot=mode == 'TESTING_SNAPSHOT_CHECK',
                    stdin=mode == 'TESTING_STDIN_CHECK',
                    fixture=mode == 'TESTING_FIXTURE_CHECK',
                )
                return

            if mode == 'PROJECT_CHECK_RECOVER_CONTROLLER':
                recover_exited_project_check(root, binding, lock, frames)
                return

            if mode == 'TASK_RECOVER_CONTROLLER':
                run_task_controller_recovery(root, frames, binding, lock)
                return

            if mode.startswith('TASK_WORKSPACE_'):
                run_task_workspace_transfer(
                    root,
                    frames,
                    binding,
                    lock,
                    outcome=mode.removeprefix('TASK_WORKSPACE_').lower(),
                )
                return

            if mode in (
                'TASK_BASIS_SUCCESS',
                'TASK_BASIS_FINISH_UNKNOWN',
                'TASK_BASIS_STOP_WRITER',
                'TASK_BASIS_LOST_OFFER',
            ):
                run_task_basis_transfer(
                    root, frames, binding, lock, outcome=mode.removeprefix('TASK_BASIS_').lower()
                )
                return

            if mode in ('TASK_FILE_RESERVATION', 'TASK_FILE_PARTIAL', 'TASK_FILE_NO_RECEIPT'):
                run_task_file_reservation(
                    root, frames, binding, lock, held_receipt=mode == 'TASK_FILE_RESERVATION'
                )
                return

            if mode == 'TASK_SOURCE_HANDOFF':
                from backend.app.infrastructure.guard_control_git_reply import (
                    parse_guard_control_git_reply,
                )
                from backend.app.infrastructure.guard_task_sources import TaskSourcePins
                from backend.app.infrastructure.windows_config_source import LockedFileSource
                from backend.app.infrastructure.windows_local_paths import LocalPathGuard
                from backend.app.infrastructure.windows_stdio import _handle_text

                parent_path = root / 'task-source'
                nonce = '1' * 32
                with ExitStack() as original:
                    identities = [
                        original.enter_context(
                            LocalPathGuard(path, directory=is_directory)
                        ).verify()
                        for path, is_directory in (
                            (parent_path, True),
                            (parent_path / ('working-' + nonce), True),
                            (parent_path / (nonce + '.workspace-tree.json'), False),
                            (parent_path / (nonce + '.basis-seal.json'), False),
                        )
                    ]
                    parent, workspace, tree, basis = identities
                    with TaskSourcePins(
                        parent,
                        nonce,
                        workspace=workspace,
                        workspace_tree=tree,
                        basis_seal=basis,
                    ) as pins:

                        def send_prepare(data):
                            request = build_guard_request_header(
                                binding,
                                lock,
                                action='PREPARE',
                                operation_id=scope.operation_id,
                                step_no=scope.step_no,
                                nonce=scope.nonce,
                                binding_ref=None,
                                action_input=data,
                            )
                            frames.write(request.wire, timeout_ms=30000, cancelled=lambda: False)
                            reply = frames.read(timeout_ms=30000, cancelled=lambda: False)
                            assert parse_guard_control_git_reply(request, reply).status == 'UNKNOWN'

                        expected = pins.request_data(basis_plan_sha256='a' * 64)
                        assert str(parent_path) not in json.dumps(expected)
                        send_prepare(expected)
                        send_prepare({**expected, 'basis_plan_sha256': 'invalid'})
                        substituted = pins.request_data()
                        substituted['sources']['workspace_tree']['handle'] = expected['sources'][
                            'basis_seal'
                        ]['handle']
                        send_prepare(substituted)
                        with LockedFileSource(
                            basis.canonical_path, max_file_bytes=256, expected_file=basis
                        ) as body:
                            broad = pins.request_data()
                            broad['sources']['basis_seal']['handle'] = _handle_text(body._handle)
                            send_prepare(broad)
                        escaped = {**expected, 'workspace_nonce': '../unmanaged'}
                        send_prepare(escaped)
                        assert send('STOP').status == 'ACKNOWLEDGED'
                        send_prepare(expected)
                        pins.verify()
                publish(root / 'control-git-pipe-result.json', {'verified': True})
                wait(root / 'stop')
                return

            if mode == 'TASK_NETWORK_CONTROL':
                from backend.app.infrastructure.guard_control_git_reply import (
                    parse_guard_control_git_reply,
                )
                from backend.tests.infrastructure.test_v20_guard_task_network import input_network

                prepare = build_guard_request_header(
                    binding,
                    lock,
                    action='PREPARE',
                    operation_id=scope.operation_id,
                    step_no=scope.step_no,
                    nonce=scope.nonce,
                    binding_ref=None,
                    action_input=input_network(),
                )
                publish(root / 'task-network-prepare.json', prepare.wire)
                binding_file = root / 'task-network-binding.json'
                wait(binding_file)
                control = json.loads(binding_file.read_bytes())
                task_binding = control['binding_ref']
                no_deployment = task_binding is None
                bound_observation = {'observed_action': 'PREPARE'}
                unsealed = replace(
                    prepare,
                    scope=binding.scope(scope.operation_id, scope.step_no, NONCE + '-unsealed'),
                )
                disguised = replace(prepare, unvalidated_input_json='{"run_kind":"CONTROL_GIT"}')
                for blocked in (unsealed, prepare, disguised):
                    frames.write(blocked.wire, timeout_ms=30000, cancelled=lambda: False)
                    reply = frames.read(timeout_ms=30000, cancelled=lambda: False)
                    assert parse_guard_control_git_reply(blocked, reply).status == 'UNKNOWN'
                if no_deployment:
                    assert send('OBSERVE', data=bound_observation).status == 'UNKNOWN'
                elif control['create_uncertain']:
                    observed = send('OBSERVE', data=bound_observation, reference=task_binding)
                    assert observed.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                    wait(root / 'task-network-create-intent-ready')
                    assert send('STOP', reference=task_binding).status == 'UNKNOWN'
                    assert send('RELEASE', reference=task_binding).status == 'UNKNOWN'
                    stopped = send(
                        'OBSERVE', data={'observed_action': 'STOP'}, reference=task_binding
                    )
                    assert stopped.result['fence']['stop_closed']
                    assert stopped.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                    assert stopped.result['preparation']['network_state'] == 'PRESENT'
                else:
                    first = send('OBSERVE', data=bound_observation, reference=task_binding)
                    assert first.result['preparation'] == {
                        'binding_ref': task_binding,
                        'run_kind': 'TASK',
                        'network_state': 'PRESENT',
                    }
                    assert first.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                    assert send('STOP', reference='different-resource-binding').status == 'UNKNOWN'
                    stopped = send('STOP', reference=task_binding)
                    assert stopped.status == 'ACKNOWLEDGED'
                    assert stopped.result['native']['fence']['stop_closed'] is True
                    assert stopped.result['native']['scope_unlaunched'] is True
                    assert send('STOP', reference=task_binding).result == stopped.result
                    assert send('CREATE_SUSPENDED', reference=task_binding).status == 'UNKNOWN'
                    assert send('RELEASE', reference=task_binding).status == 'UNKNOWN'
                    assert send('RELEASE', reference=task_binding).status == 'UNKNOWN'
                    final = send(
                        'OBSERVE', data={'observed_action': 'RELEASE'}, reference=task_binding
                    )
                    assert final.result['preparation']['network_state'] == 'ABSENT'
                    assert final.result['action_phase'] == 'MAY_HAVE_BEEN_SENT'
                    assert final.result['acknowledgement'] is None
                publish(root / 'control-git-pipe-result.json', {'verified': True})
                wait(root / 'stop')
                return

            if mode == 'DIRECTORY_EXPORT':
                export_original_metadata_directories(root, scope)
                wait(root / 'stop')
                return
            if mode == 'CONFIG_EXPORT':
                export_original_config(root, scope)
                wait(root / 'stop')
                return
            if mode == 'VERSION':
                captured, _ = run_command(scope, send)
                result = {
                    'stdout': captured.stdout.decode('ascii').strip(),
                    'stderr': captured.stderr.hex(),
                }
            elif mode == 'CONFIG_PARSE':
                result = run_config_parse(root, scope, send)
            elif mode.startswith(('BASELINE_RESTART_', 'BASELINE_QUERY_RESTART_')):
                result = recover_baseline_after_restart(
                    root,
                    database,
                    baseline_catalog,
                    lock,
                    frames,
                    binding,
                    query=mode.startswith('BASELINE_QUERY_RESTART_'),
                )
            elif baseline_mode:
                result = run_baseline_validation(
                    root, database, baseline_catalog, lock, frames, binding, mode
                )
            elif metadata_mode:
                dispatcher, scopes, original = observation_dispatch(
                    root,
                    database,
                    lock,
                    frames,
                    binding,
                    backend_owners,
                    mode.removeprefix('METADATA_').lower(),
                )
                result = run_metadata_pair(root, scopes, send, dispatcher)
                result['queued_observation_id'] = run_observation_queue(
                    root, frames, binding, dispatcher, original
                )
            elif mode == 'RECOVER_REGISTRATION':
                result = recover_registration(root, database, lock, frames, binding)
            elif mode.startswith('REGISTER'):
                from backend.app.code_tasks.repository_acceptance import accept_repository_operation

                actor, runtime, original_request, operation_id = registration
                if mode in ('REGISTER_LOST', 'REGISTER_CRASH'):
                    try:
                        actor.run_next(
                            frames,
                            cancelled=lambda: (root / 'cancel-owned-control-request').exists(),
                        )
                    except GuardExchangeUnknown as error:
                        assert error.retained_owner is actor
                        runner = actor._active
                        assert runner is not None
                        try:
                            actor.run_next(frames, cancelled=lambda: False)
                        except RuntimeError as held:
                            assert (
                                str(held) == 'ORIGINAL_REGISTRATION_ACTOR_RECONCILIATION_REQUIRED'
                            )
                        else:
                            raise AssertionError(
                                'Unknown registration did not block later selection'
                            )
                        try:
                            actor.close()
                        except RuntimeError as retained:
                            assert retained.retained_owner is actor
                        else:
                            raise AssertionError('Unknown original resource was released')
                        with runtime.database.transaction() as connection:
                            state = connection.execute(
                                'SELECT status FROM code_operations WHERE id=?', (operation_id,)
                            ).fetchone()[0]
                            assert state == 'UNKNOWN'
                            assert (
                                connection.execute(
                                    'SELECT count(*) FROM code_repositories'
                                ).fetchone()[0]
                                == 0
                            )
                        result = {
                            'unknown': True,
                            'retained': bool(runner._owners),
                            'status': state,
                        }
                        publish(root / 'control-git-pipe-result.json', result)
                        if mode == 'REGISTER_CRASH':
                            wait(root / 'exit-original-backend')
                            os._exit(0)
                        frames.close()
                        client.close()
                        publish(root / 'old-control-connection-closed', {'closed': True})
                        wait(root / 'guard-reconnect-ready')
                        with (
                            GuardPipeClient(
                                reference,
                                backend_sid=sid,
                                server_sid=sid,
                                expected_guard=expected.identity,
                                program=image,
                            ) as reconnected,
                            GuardPipeIO(reconnected) as recovered_io,
                        ):
                            recovered_frames = GuardPipeFrames(recovered_io)
                            actor.reconcile_cleanup(
                                recovered_frames, timeout_ms=15000, cancelled=lambda: False
                            )
                            assert actor._active is None
                            assert actor.run_next(recovered_frames, cancelled=lambda: False) is None
                            actor.close()
                            with runtime.database.transaction() as connection:
                                state = connection.execute(
                                    'SELECT status FROM code_operations WHERE id=?', (operation_id,)
                                ).fetchone()[0]
                            publish(
                                root / 'control-git-cleanup-result.json',
                                {
                                    'retained': bool(runner._owners),
                                    'status': state,
                                    'released': runner._released,
                                },
                            )
                            wait(root / 'stop')
                        return
                    raise AssertionError('Missing original CREATE reply was treated as complete')
                assert actor.run_next(frames, cancelled=lambda: True) is None
                outcome = actor.run_next(frames, cancelled=lambda: False)
                assert outcome.operation_id == operation_id
                repository_id = outcome.repository_id
                assert actor.run_next(frames, cancelled=lambda: False) is None
                actor.close()
                replayed = accept_repository_operation(runtime, original_request)
                assert replayed['data']['operation_status'] == 'PENDING'
                with runtime.database.transaction() as connection:
                    operation = connection.execute(
                        'SELECT status FROM code_operations WHERE id=?', (operation_id,)
                    ).fetchone()
                    assert operation['status'] == 'SUCCEEDED'
                    assert connection.execute('SELECT count(*) FROM code_tasks').fetchone()[0] == 0
                result = {
                    'object_format': 'sha1',
                    'bare': True,
                    'stderr': '',
                    'repository_id': repository_id,
                    'operation_status': operation['status'],
                }
            else:
                try:
                    send('STOP')
                except GuardExchangeUnknown as unknown:
                    assert unknown.request.target_scope == scope
                    assert unknown.request.action == 'STOP'
                    try:
                        send('OBSERVE', data={'observed_action': 'STOP'})
                    except GuardFrameError:
                        result = {'unknown': True, 'original_scope': scope.key}
                    else:
                        raise AssertionError('Original failed stream reused')
                else:
                    raise AssertionError('Unrelated reply adopted')
            publish(root / 'control-git-pipe-result.json', result)
            wait(root / 'stop')


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        import traceback

        publish(Path.cwd() / 'control-git-pipe-failure.json', {'traceback': traceback.format_exc()})
        raise
