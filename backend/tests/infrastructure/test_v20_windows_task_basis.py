"""Real two-process handoff of an original basis file and its readback receipt."""

import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.code_tasks.task_basis import BasisOriginal, TaskBasisUnavailable
from backend.app.infrastructure import windows_task_basis_group as group_module
from backend.app.code_tasks.task_basis_package import (
    basis_digest,
    basis_source,
    publish_basis_package,
    runtime_basis_plan,
    verify_runtime_basis_copy,
    write_runtime_basis,
)
from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.guard_controller_binding import (
    GuardControllerBinding,
    bind_backend_controller,
)
from backend.app.infrastructure.guard_request_header import _parse
from backend.app.infrastructure.process_lock import ProcessLock
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchScope
from backend.app.infrastructure.windows_controller_token import ControllerPrimaryToken
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import FileIdentity, LocalDirectoryPin
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_process import NativeProcessIdentity, ObservedProcess
from backend.app.infrastructure.windows_task_basis import (
    BasisCopyReceipt,
    BasisCopySpec,
    BasisWriteOffer,
    TaskBasisTransferError,
)
from backend.app.infrastructure.windows_task_basis_group import (
    BasisCopyPlan,
    TaskBasisGroup,
    basis_group_evidence,
)
from backend.app.infrastructure.windows_task_directories import TaskLpacDirectories, TaskRuntimeRoot
from backend.tests.infrastructure.test_v20_guard_action_journal import packet
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.infrastructure.v20_stdio_worker import publish, wait
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]
OPERATION = 17
NONCE = 'original-guard-action-nonce-0001'


def _receipt(value):
    return BasisCopyReceipt(
        LaunchScope(**value['scope']),
        value['binding_ref'],
        BasisCopySpec(**value['spec']),
        FileIdentity(**value['file']),
    )


def _read(path):
    wait(path)
    return json.loads(path.read_bytes())


def run_basis_worker(installation, outcome):
    root = Path.cwd()
    source_path = create_private_package(root / 'original-source')
    with ProcessLock(root / 'basis.lock') as lock, PrivatePackageGuard(source_path) as source:
        binding = bind_backend_controller(lock, installation)
        scope = binding.scope(OPERATION, 4, NONCE)
        originals = (BasisOriginal(3, 9, '设计\r\n'.encode()), BasisOriginal(4, 11, b''))
        basis = {
            'operation_id': OPERATION,
            'task_id': 1,
            'workspace_id': 2,
            'generation': 3,
            'nonce': uuid4().hex,
            'document_count': len(originals),
            'source_sha256': basis_digest(basis_source(originals)),
        }
        seal = publish_basis_package(source, basis, originals, lock.assert_owned)
        plan = runtime_basis_plan(source, basis, seal, lock.assert_owned)
        specs = plan.members if outcome in ('success', 'stop', 'seal_unknown') else plan.members[:1]
        receipts = []
        publish(
            root / 'basis-ready.json',
            {'pid': os.getpid(), 'epoch': binding.owner_epoch, 'plan': asdict(plan)},
        )
        for spec in specs:
            number = spec.number
            value = _read(root / f'offer-{number}.json')
            offer = BasisWriteOffer(
                NativeProcessIdentity(**value['owner']),
                _receipt(value['expected']),
                value['writer'],
            )
            expected = offer.expected
            try:
                write_runtime_basis(
                    source, basis, seal, offer, scope, uuid4().hex, lock.assert_owned
                )
            except TaskBasisTransferError as error:
                assert str(error) == 'ORIGINAL_BASIS_WRITER_SCOPE_DIFFERS'
            else:
                raise AssertionError('Wrong binding touched the original writer')

            def check_active():
                lock.assert_owned()
                if outcome in ('cancel', 'close_pending'):
                    raise TaskBasisUnavailable('Fixture stopped before write')

            if outcome in ('cancel', 'close_pending'):
                try:
                    write_runtime_basis(
                        source, basis, seal, offer, scope, expected.binding_ref, check_active
                    )
                except TaskBasisUnavailable as error:
                    assert str(error) == 'Fixture stopped before write'
                else:
                    raise AssertionError('Cancelled source was written')
                publish(root / f'written-{number}.json', {'closed': True})
                break
            write_runtime_basis(
                source, basis, seal, offer, scope, expected.binding_ref, check_active
            )
            publish(root / f'written-{number}.json', {'closed': True})
            wait(root / f'pinned-{number}')
            try:
                receipt = verify_runtime_basis_copy(
                    offer, scope, expected.binding_ref, lock.assert_owned
                )
            except TaskBasisUnavailable as error:
                assert (
                    outcome == 'tamper' and str(error) == 'Original basis runtime copy bytes differ'
                )
                publish(root / f'copy-{number}.json', {'verified': False})
            else:
                assert outcome in ('success', 'stop', 'seal_unknown')
                receipts.append(receipt)
                publish(root / f'copy-{number}.json', asdict(receipt))
        if outcome == 'success':
            group = basis_group_evidence(plan, scope, receipts[0].binding_ref, tuple(receipts))
            assert _read(root / 'basis-complete.json') == asdict(group)
            (root / 'basis-complete-verified').touch()
        wait(root / 'stop-worker')


@pytest.mark.parametrize(
    'outcome', ['success', 'cancel', 'tamper', 'stop', 'close_pending', 'seal_unknown']
)
def test_basis_original_write_handle_and_readback_across_real_processes(
    tmp_path, outcome, monkeypatch
):
    installation = uuid4().hex + uuid4().hex
    script = (
        'import sys,traceback\n'
        f'sys.path.insert(0,{str(ROOT)!r})\n'
        'from pathlib import Path\n'
        'from backend.tests.infrastructure.test_v20_windows_task_basis import run_basis_worker\n'
        'try:\n'
        f'    run_basis_worker({installation!r},{outcome!r})\n'
        'except BaseException:\n'
        '    Path("worker-failure.txt").write_text(traceback.format_exc(),encoding="utf-8")\n'
        '    raise\n'
    )
    with OwnedJob(active_process_limit=4, job_memory_limit_bytes=512 * 1024 * 1024) as job:
        child = TestSuspendedRoot(job, tmp_path, script)
        try:
            child.resume()
            original = _read(tmp_path / 'basis-ready.json')
            data = original['plan']
            plan = BasisCopyPlan(
                **{**data, 'members': tuple(BasisCopySpec(**row) for row in data['members'])}
            )
            with ObservedProcess(original['pid']) as process:
                assert job.contains_process(process)
                binding = GuardControllerBinding(installation, original['epoch'], process.identity)
                with (
                    ControllerPrimaryToken(process, expected=binding.controller) as token,
                    LaunchJournal(create_private_package(tmp_path / 'guard-journal')) as journal,
                    LocalDirectoryPin(tmp_path) as base,
                    TaskRuntimeRoot.create(base, binding.controller.user_sid) as runtime,
                ):
                    actions = GuardActionJournal(journal)
                    prepare = packet(
                        binding,
                        number=OPERATION,
                        action_input={'run_kind': 'TASK', 'basis_plan_sha256': plan.sha256},
                    )
                    prepare = _parse({**prepare.wire, 'step_no': 4}, binding)
                    directories = TaskLpacDirectories(
                        runtime, actions, actions.begin(prepare), prepare, binding, token
                    )
                    try:
                        directories.allocate(cancelled=lambda: False)
                        with pytest.raises(TaskBasisTransferError, match='GROUP_SCOPE_DIFFERS'):
                            TaskBasisGroup(
                                directories, replace(plan, generation=99), cancelled=lambda: False
                            )
                        group = TaskBasisGroup(directories, plan, cancelled=lambda: False)
                        with pytest.raises(
                            TaskBasisTransferError, match='GROUP_ALREADY_REGISTERED'
                        ):
                            TaskBasisGroup(directories, plan, cancelled=lambda: False)
                        with pytest.raises(TaskBasisTransferError, match='MEMBER_NOT_PLANNED'):
                            group.offer(len(plan.members) + 1)
                        with pytest.raises(TaskBasisTransferError, match='GROUP_INCOMPLETE'):
                            group.finish()
                        specs = (
                            plan.members
                            if outcome in ('success', 'stop', 'seal_unknown')
                            else plan.members[:1]
                        )
                        for spec in specs:
                            offer = group.offer(spec.number)
                            with pytest.raises(TaskBasisTransferError, match='ALREADY_OFFERED'):
                                group.offer(spec.number)
                            with pytest.raises(
                                TaskBasisTransferError, match='WRITER_STILL_UNVERIFIED'
                            ) as pending:
                                group.pin_written(spec.number)
                            assert pending.value.native_error == 32
                            if outcome == 'close_pending':
                                with pytest.raises(
                                    TaskBasisTransferError, match='WRITER_STILL_UNVERIFIED'
                                ) as blocked:
                                    directories.close()
                                assert blocked.value.retained_owner is directories
                                assert directories.verify()
                            publish(tmp_path / f'offer-{spec.number}.json', asdict(offer))
                            assert _read(tmp_path / f'written-{spec.number}.json') == {
                                'closed': True
                            }
                            if outcome == 'cancel':
                                with pytest.raises(TaskBasisTransferError, match='LENGTH_DIFFERS'):
                                    group.pin_written(spec.number)
                                break
                            if outcome == 'close_pending':
                                with pytest.raises(TaskBasisTransferError, match='GROUP_CLOSED'):
                                    group.finish()
                                break
                            if outcome == 'tamper':
                                Path(offer.expected.file.canonical_path).write_bytes(
                                    b'?' * spec.byte_count
                                )
                            group.pin_written(spec.number)
                            (tmp_path / f'pinned-{spec.number}').touch()
                            reply = _read(tmp_path / f'copy-{spec.number}.json')
                            if outcome in ('success', 'stop', 'seal_unknown'):
                                observed = _receipt(reply)
                                with pytest.raises(TaskBasisTransferError, match='RECEIPT_DIFFERS'):
                                    group.confirm(replace(observed, binding_ref=uuid4().hex))
                                with pytest.raises(TaskBasisTransferError, match='RECEIPT_DIFFERS'):
                                    group.confirm(
                                        replace(
                                            observed, file=replace(observed.file, file_id='0' * 32)
                                        )
                                    )
                                assert group.confirm(observed) == offer.expected
                                if spec.number == 1:
                                    with pytest.raises(
                                        TaskBasisTransferError, match='GROUP_INCOMPLETE'
                                    ):
                                        group.finish()
                            else:
                                assert reply == {'verified': False}
                        if outcome == 'success':
                            with pytest.raises(TaskBasisTransferError, match='SEAL_UNVERIFIED'):
                                group.verify()
                            extra = directories.root / 'basis' / 'extra.md'
                            extra.write_bytes(b'fixture')
                            with pytest.raises(TaskBasisTransferError, match='GROUP_TREE_DIFFERS'):
                                group.finish()
                            extra.unlink()
                            publish_original = group_module.PrivateRecordAppend.publish

                            def lose_commit_reply(record):
                                publish_original(record)
                                raise OSError('fixture lost acknowledgement')

                            with monkeypatch.context() as injected:
                                injected.setattr(
                                    group_module.PrivateRecordAppend, 'publish', lose_commit_reply
                                )
                                with pytest.raises(OSError, match='lost acknowledgement'):
                                    group.finish()
                            evidence = group.verify()
                            assert evidence == group.finish()
                            assert len(list(journal.root.glob('*.task-basis-complete.json'))) == 1
                            assert (
                                actions.find(directories.scope, 'PREPARE').phase
                                == 'MAY_HAVE_BEEN_SENT'
                            )
                            publish(tmp_path / 'basis-complete.json', asdict(evidence))
                            wait(tmp_path / 'basis-complete-verified')
                        elif outcome == 'seal_unknown':

                            def unknown_without_readable_record(_):
                                raise OSError('fixture outcome unknown')

                            with monkeypatch.context() as injected:
                                injected.setattr(
                                    group_module.PrivateRecordAppend,
                                    'publish',
                                    unknown_without_readable_record,
                                )
                                with pytest.raises(OSError, match='outcome unknown'):
                                    group.finish()
                            with pytest.raises(
                                TaskBasisTransferError, match='SEAL_OUTCOME_UNVERIFIED'
                            ):
                                group.finish()
                        elif outcome == 'stop':
                            journal.close_nonce(directories.scope)
                            with pytest.raises(
                                PackageSecurityError, match='ALLOCATION_INTERRUPTED'
                            ):
                                group.finish()
                        elif outcome in ('cancel', 'tamper'):
                            with pytest.raises(TaskBasisTransferError, match='GROUP_INCOMPLETE'):
                                group.finish()
                        if outcome != 'success':
                            assert not list(journal.root.glob('*.task-basis-complete.json'))
                    finally:
                        directories.close()
                (tmp_path / 'stop-worker').touch()
                assert process._kernel.WaitForSingleObject(process._handle, 8000) == 0
                assert process.observe().exit_code == 0
        except BaseException:
            failure = tmp_path / 'worker-failure.txt'
            if failure.exists():
                pytest.fail(failure.read_text(encoding='utf-8'))
            raise
        finally:
            job.terminate_owned(1)
            assert child.kernel.WaitForSingleObject(child.info.process, 8000) == 0
            child.close()
