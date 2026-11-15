"""Verify the original pinned baseline and publish its sole snapshot."""

from dataclasses import asdict

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.schema_transport import compact
from backend.app.shared.command_execution import operation_time

from .repository_baseline_validation import (
    baseline_pinned_ref,
    baseline_proof,
    original_baseline,
    verify_baseline_ref,
)
from .repository_git_dispatch import VALIDATION_FAILURES, BaselineGitDispatch


class BaselineVerifyGitDispatch(BaselineGitDispatch):
    _external_key = 'git_baseline_verify'
    _step_no = 3

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        operation, _, steps = original_baseline(connection, operation_id)
        active = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
        if (
            operation['status'] not in active
            or any(step['status'] != 'SUCCEEDED' for step in steps[:2])
            or steps[2]['status'] != operation['status']
            or steps[3]['status'] != 'PENDING'
        ):
            raise StorageUnavailable('Original baseline VERIFY_PINNED_OBJECTS is not active')
        return steps[2]

    def fail_validation(self, operation_id, code):
        with (
            self._validation_cleanup(
                self.original(operation_id),
                code,
                allowed=VALIDATION_FAILURES | {'CONTENT_NOT_READY', 'RESOURCE_CONFLICT'},
            ),
            self._runtime.database.transaction(write=True) as connection,
        ):
            if self._active_step(connection, operation_id)['result_ref'] is not None:
                raise StorageUnavailable('Original baseline verification already has a result')
            at = operation_time(None)
            connection.execute(
                "UPDATE code_operation_steps SET status='FAILED',ended_at=?,last_observed_at=? "
                'WHERE operation_id=? AND step_no=3',
                (at, at, operation_id),
            )
            connection.execute(
                "UPDATE code_operations SET status='FAILED',ended_at=?,failure_code=? WHERE id=?",
                (at, code, operation_id),
            )

    def publish_baseline(
        self, operation_id, source, metadata, parsed, proof, batch_output, *, observed_pin=None
    ):
        self._verify_completed_batch(operation_id, source, metadata, parsed, proof, batch_output)
        with self._runtime.database.transaction() as connection:
            _, fixed, steps = original_baseline(connection, operation_id)
        first = baseline_proof(steps[0]['result_ref'], source.commit_oid, source.format)
        if observed_pin is None:
            file, location = baseline_pinned_ref(steps[1]['result_ref'])
        else:
            (file, location), record_observation = observed_pin
        if first.tree_oid != proof.tree_oid or first.content_sha256 != proof.content_sha256:
            raise StorageUnavailable('Original baseline verified content differs')
        if (fixed['repository_id'], fixed['commit_oid'], fixed['execution_profile_version_id']) != (
            source.repository_id,
            source.commit_oid,
            source.profile_version_id,
        ):
            raise StorageUnavailable('Original verified baseline input differs')
        verify_baseline_ref(metadata, source, fixed['retention_ref'], file, location)
        observed_result = None if observed_pin is None else record_observation(file)
        verified_at = operation_time(None)
        snapshot_id = fixed['snapshot_id']
        with self._runtime.database.transaction(write=True) as connection:
            active = self._active_step(connection, operation_id)
            if active['result_ref'] is not None:
                raise StorageUnavailable('Original verified baseline already has a result')
            if observed_result is not None:
                connection.execute(
                    "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? "
                    'WHERE operation_id=? AND step_no=2',
                    (compact(observed_result), verified_at, verified_at, operation_id),
                )
            created_at = max(verified_at, operation_time(None))
            connection.execute(
                'INSERT INTO code_snapshots (id,repository_id,registration_operation_id,'
                'content_profile_version_id,commit_oid,content_tree_oid,retention_ref,'
                'content_policy_version,registered_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (
                    snapshot_id,
                    source.repository_id,
                    operation_id,
                    source.profile_version_id,
                    source.commit_oid,
                    proof.tree_oid,
                    fixed['retention_ref'],
                    'GIT20-BASELINE-1',
                    verified_at,
                    created_at,
                ),
            )
            connection.execute(
                "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,ended_at=?,last_observed_at=? "
                'WHERE operation_id=? AND step_no=3',
                (compact(asdict(proof)), verified_at, verified_at, operation_id),
            )
            connection.execute(
                "UPDATE code_operation_steps SET status='SUCCEEDED',result_ref=?,started_at=?,"
                'ended_at=?,last_observed_at=? WHERE operation_id=? AND step_no=4',
                (
                    compact({'snapshot_id': snapshot_id}),
                    created_at,
                    created_at,
                    created_at,
                    operation_id,
                ),
            )
            connection.execute(
                "UPDATE code_operations SET status='SUCCEEDED',ended_at=?,failure_code=NULL WHERE id=?",
                (created_at, operation_id),
            )
        return snapshot_id


class BaselineRecoveredVerifyGitDispatch(BaselineVerifyGitDispatch):
    """Allow one original read scope while the earlier write remains uncertain."""

    @staticmethod
    def _active_step(connection, operation_id, *, allow_unknown=False):
        operation, _, steps = original_baseline(connection, operation_id)
        active = ('RUNNING', 'UNKNOWN') if allow_unknown else ('RUNNING',)
        if (
            operation['status'] != 'UNKNOWN'
            or steps[0]['status'] != 'SUCCEEDED'
            or steps[1]['status'] != 'UNKNOWN'
            or steps[1]['result_ref'] is not None
            or steps[2]['status'] not in active
            or steps[3]['status'] != 'PENDING'
        ):
            raise StorageUnavailable('Original baseline observation is not active')
        return steps[2]
