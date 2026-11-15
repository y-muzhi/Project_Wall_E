"""Owned Windows fixture for the complete original Testing validation chain."""

import sys
from contextlib import contextmanager
from json import loads
from time import sleep
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.code_tasks.command_registry import registered_command
from backend.app.code_tasks.repository_acceptance import accept_repository_operation
from backend.app.code_tasks.repository_git_runner import RegistrationReadLimits
from backend.app.code_tasks.repository_registration_actor import (
    BaselineOutcome,
    RepositoryRegistrationActor,
)
from backend.app.infrastructure.check_runner_bundle import RegisteredCheckRunner
from backend.app.infrastructure.idempotency import Idempotency
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_project_check_command import ProjectCheckCommand
from backend.app.service import create_app
from backend.app.shared.command_execution import operation_time
from backend.app.testing.asset_api import PublishPackRequest, ValidatePackRequest
from backend.app.testing.asset_installation import TestingAssetInstallation
from backend.app.testing.cli_plan import TestingCliRuntime
from backend.app.testing.pack_compile import basis_fingerprint, digest
from backend.app.testing.pack_publication import publish_pack
from backend.app.testing.pack_validation import advance_pending_validation_results, validate_pack
from backend.app.testing.plan_content import BASIS_FIELDS
from backend.app.testing.plans import _version
from backend.app.testing.run_settlement import settle_case
from backend.app.testing.run_worker import TestingCliWorker
from backend.app.testing.task_api import RecoverTaskRequest
from backend.app.testing.task_recovery import accept_recovery
from backend.tests.code_tasks.test_execution_profile_versions import resources
from backend.tests.code_tasks.test_repository_baseline_acceptance import BaselineInput
from backend.tests.test_testing_cli_run import _assets, _registered_cli, _sealed_pack
from backend.tests.test_testing_plan_api import MAIN, setup
from backend.tests.test_testing_policy_api import create
from backend.tests.test_testing_reference_sets import reference, register_reference
from backend.tests.test_testing_task_api import approve
from backend.tests.infrastructure.v20_validation_probe import validation_phase

TIMEOUT = 180


def command_definition():
    return ProjectCheckCommand.decode(
        {
            'command_id': 'print-result',
            'executable_ref': 'fixture:findstr',
            'argument_template': ['/L', 'owned', 'fixture.txt'],
            'working_directory': '.',
            'purpose': 'CHECK',
            'timeout_seconds': TIMEOUT,
            'network_scope_ref': None,
        }
    )


def prepare_assets(root, database, catalog):
    with PrivatePackageGuard(root / 'registered-runner') as directory:
        runner = RegisteredCheckRunner(
            directory.verify(),
            digest((directory.path / 'manifest.json').read_bytes()),
            'native-check-runner',
            '1.0.0',
        )
    installation = _assets(root, runner)
    catalog.testing_assets = installation
    admission, profile, options = _registered_cli(runner, definition=command_definition())
    app = create_app(database=database, catalog=catalog)
    with TestClient(app) as client:
        plan = setup((database, app, client))
        with resources(options):
            result = create(client, profile)
        assert result.status_code == 201, result.text
        _sealed_pack(
            database,
            client,
            {key: plan[key] for key in BASIS_FIELDS},
            publish=False,
            create_plan=False,
            quote=MAIN,
            timeout=TIMEOUT,
        )
        grant = approve(client, scope='PACK_VALIDATION', budget='0')
    return installation, admission, grant


def _register_snapshots(root, runtime, actor, frames):
    snapshots = []
    for identity, kind in enumerate(('positive', 'negative'), 1):
        fixture = root / kind
        repository = fixture / 'repository'
        commit = loads((fixture / 'setup-result.json').read_bytes())['oid']
        with runtime.database.transaction(write=True) as connection:
            connection.execute(
                'INSERT INTO code_repositories VALUES(?,?,?,?,?,?)',
                (
                    identity,
                    kind,
                    str(repository),
                    str(repository / '.git'),
                    'sha1',
                    operation_time(None),
                ),
            )
        reply = accept_repository_operation(
            runtime, BaselineInput(identity, commit, key=str(uuid4()))
        )
        assert reply['code'] == 'OPERATION_ACCEPTED', reply
        validation_phase(root, 'SNAPSHOT_' + kind.upper() + '_RUN')
        outcome = actor.run_next(frames, cancelled=lambda: False)
        validation_phase(root, 'SNAPSHOT_' + kind.upper() + '_DONE')
        assert (
            type(outcome) is BaselineOutcome
            and outcome.operation_id == reply['data']['operation_id']
        )
        snapshots.append(outcome.snapshot_id)
    return snapshots


class _ValidationWorker(TestingCliWorker):
    failure = None
    interrupted_case = None

    def _write(self, operation, *values, **options):
        if operation.__name__ == 'mark_unknown':
            self.failure = sys.exception()
        elif operation is settle_case and self.interrupted_case is None:
            original, _, _, complete = values
            assert complete.result.result == 'PASSED' and complete.result.cleanup_ref is not None
            self.interrupted_case = original
            raise LaunchOutcomeUnknown('TEST_FIXTURE_LOST_ORIGINAL_SQLITE_RESULT')
        return super()._write(operation, *values, **options)


def _scope_state(database, original):
    with database.transaction() as connection:
        task = connection.execute(
            'SELECT * FROM testing_tasks WHERE id=?', (original.scope.owner_id,)
        ).fetchone()
        cases = connection.execute(
            'SELECT id,status,ended_at FROM code_commands WHERE operation_id=? ORDER BY id',
            (original.scope.operation_id,),
        ).fetchall()
        outcomes = connection.execute(
            """SELECT c.case_id,c.result FROM code_verification_case_results c
               JOIN code_verification_items i ON i.id=c.item_id
               WHERE i.verification_id=? ORDER BY c.case_id""",
            (original.item['verification_id'],),
        ).fetchall()
        return task, cases, outcomes


def _control(runtime, original, task, resources, action):
    path = f'/api/v1/testing-tasks/{task["id"]}/{action.lower()}'
    request = RecoverTaskRequest(
        task['id'],
        task['state_version'],
        original.scope.operation_id,
        registered_command('POST', path, str(uuid4())),
    )
    result = accept_recovery(runtime, request, action, runtime_resources=resources)
    assert result['code'] == 'OPERATION_ACCEPTED', result
    assert accept_recovery(runtime, request, action, runtime_resources=resources) == result
    return result['data']['operation_id']


def _recover_first_case(runtime, worker, resources):
    assert worker.advance() and not worker.has_retained_command
    original = worker.interrupted_case
    assert original is not None
    task, cases, outcomes = _scope_state(runtime.database, original)
    assert task['status'] == 'WAITING' and not outcomes
    assert [row['status'] for row in cases] == ['UNKNOWN', 'PENDING']
    observation = _control(runtime, original, task, resources, 'RECONCILE')
    assert worker.advance()
    with runtime.database.transaction() as connection:
        op = connection.execute(
            'SELECT status FROM code_operations WHERE id=?', (observation,)
        ).fetchone()
        assert op['status'] == 'SUCCEEDED'
    sleep(2.1)
    assert worker.advance()
    task, recovered, outcomes = _scope_state(runtime.database, original)
    assert task['status'] == 'WAITING'
    assert [row['id'] for row in recovered] == [row['id'] for row in cases]
    assert [row['status'] for row in recovered] == ['SUCCEEDED', 'PENDING']
    assert [(row['case_id'], row['result']) for row in outcomes] == [(original.case_id, 'PASSED')]
    continued = _control(runtime, original, task, resources, 'RESUME')
    assert worker.advance()
    task, after, _ = _scope_state(runtime.database, original)
    assert (
        task['status'] == 'RUNNING' and task['active_operation_id'] == original.scope.operation_id
    )
    assert [tuple(row) for row in recovered] == [tuple(row) for row in after]
    with runtime.database.transaction() as connection:
        op = connection.execute(
            'SELECT status FROM code_operations WHERE id=?', (continued,)
        ).fetchone()
        assert op['status'] == 'SUCCEEDED'


def run_validation_group(root, database, catalog, prepared, binding, lock, frames, *, recovery):
    installation, admission, grant = prepared
    executor = Idempotency(database, lock)
    runtime = SimpleNamespace(database=database, catalog=catalog, commands=lambda: executor)

    @contextmanager
    def connect():
        yield frames

    with (
        LaunchJournal(create_private_package(root / 'testing-evidence')) as journal,
        PrivatePackageGuard(root / 'task-source') as parent,
    ):
        actor = RepositoryRegistrationActor(
            runtime,
            binding,
            journal,
            private_roots=(journal.root, parent.path),
            limits=RegistrationReadLimits(65536, 4096, 20000, 1024 * 1024, 1024 * 1024, 75),
        )
        try:
            validation_phase(root, 'REGISTER_SNAPSHOTS')
            positive, negative = _register_snapshots(root, runtime, actor, frames)
            validation_phase(root, 'REGISTER_REFERENCE')
            with database.transaction() as connection:
                basis = basis_fingerprint(connection, _version(connection, 1))
            registration = register_reference(
                root,
                'testing-original-reference',
                reference(
                    basis_fingerprint=basis,
                    positive_snapshot_ids=[positive],
                    repeat_count=2,
                    negative_controls=[
                        {'snapshot_id': negative, 'expected_failed_case_ids': ['private', 'public']}
                    ],
                ),
            )
            catalog.testing_assets = TestingAssetInstallation(
                installation.pack_directory, installation.registered_targets, (registration,)
            )
            original = ValidatePackRequest(
                1,
                2,
                1,
                registration.reference.reference_set_ref,
                grant,
                registered_command(
                    'POST', '/api/v1/test-pack-versions/1/validations', str(uuid4())
                ),
            )
            resources = TestingCliRuntime(binding, (admission,), snapshots=True)
            validation_phase(root, 'ACCEPT_VALIDATION')
            received = validate_pack(runtime, original, runtime_resources=resources)
            assert received['code'] == 'OPERATION_ACCEPTED', received
            assert validate_pack(runtime, original, runtime_resources=resources) == received
            worker_type = _ValidationWorker if recovery else TestingCliWorker
            worker = worker_type(
                runtime,
                parent,
                binding,
                journal,
                connect,
                (admission,),
                cancelled=lambda: False,
                query_snapshot=actor.query_snapshot,
                snapshot_reads_ready=actor.snapshot_reads_ready,
            )
            if recovery:
                _recover_first_case(runtime, worker, resources)
                original = worker.interrupted_case
                assert worker.advance() and not worker.has_retained_command
                _, commands, outcomes = _scope_state(runtime.database, original)
                assert [row['status'] for row in commands] == ['SUCCEEDED', 'SUCCEEDED']
                assert [(row['case_id'], row['result']) for row in outcomes] == [
                    ('private', 'PASSED'),
                    ('public', 'PASSED'),
                ], outcomes
                assert worker.advance()
                with database.transaction() as connection:
                    report = connection.execute(
                        'SELECT result FROM testing_reports WHERE testing_task_id=?',
                        (original.scope.owner_id,),
                    ).fetchall()
                    assert [row['result'] for row in report] == ['PASSED']
                return {'result': 'recovered', 'cases': len(commands)}
            for number in range(1, 13):
                validation_phase(root, f'WORKER_ADVANCE_{number:02d}_START')
                assert worker.advance(), number
                validation_phase(root, f'WORKER_ADVANCE_{number:02d}_DONE')
                if worker.has_retained_command:
                    failure = getattr(worker, 'failure', None)
                    action = getattr(failure, 'guard_action', None)
                    if not worker.reconcile(cancelled=lambda: False):
                        raise AssertionError(
                            f'Original command {number} retained at {action}'
                        ) from failure
                    raise AssertionError(
                        f'Original command {number} required recovery at {action}'
                    ) from failure
            validation_phase(root, 'SETTLE_VALIDATION')
            assert not worker.advance() and advance_pending_validation_results(runtime)
            with database.transaction() as connection:
                validation = connection.execute(
                    'SELECT result FROM testing_pack_validations'
                ).fetchone()
                reports = connection.execute(
                    'SELECT r.result FROM testing_reports r ORDER BY r.testing_task_id'
                ).fetchall()
                commands = connection.execute(
                    'SELECT exit_code FROM code_commands ORDER BY id'
                ).fetchall()
                assert validation['result'] == 'PASSED'
                assert [row['result'] for row in reports] == [
                    'PASSED',
                    'PASSED',
                    'FAILED',
                    'FAILED',
                ]
                assert [row['exit_code'] for row in commands] == [0] * 4 + [1] * 4
                assert connection.execute('SELECT count(*) FROM llm_uses').fetchone()[0] == 0
            validation_phase(root, 'PUBLISH_PACK')
            published = publish_pack(
                runtime,
                PublishPackRequest(
                    1,
                    2,
                    registered_command(
                        'POST', '/api/v1/test-pack-versions/1/publish', str(uuid4())
                    ),
                ),
            )
            assert published['code'] == 'UPDATED' and published['data']['status'] == 'PUBLISHED', (
                published
            )
            validation_phase(root, 'VALIDATION_DONE')
            return {
                'result': 'published',
                'validation_id': received['data']['validation_id'],
                'children': 4,
                'cases': 8,
            }
        finally:
            actor.close()
