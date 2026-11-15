"""Freeze and materialize the actual candidate or registered Git baseline for Testing."""

from backend.app.code_tasks.repository_baseline_query import (
    BaselineQueryResult,
    load_baseline_query,
)
from backend.app.code_tasks.repository_baseline_validation import (
    baseline_proof,
    original_baseline,
    read_registered_baseline,
)
from backend.app.infrastructure.check_input_transfer import SnapshotCheckSource
from backend.app.infrastructure.content_manifest import build_manifest, fixed_entries_sha256
from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.runtime_launch_journal import LaunchOutcomeUnknown


def fixed_run_target(connection, task):
    if task['target_kind'] == 'CANDIDATE':
        row = connection.execute(
            'SELECT id,manifest_sha256 FROM code_candidates WHERE id=?', (task['candidate_id'],)
        ).fetchone()
        if row is None:
            raise StorageUnavailable('Original Testing candidate disappeared')
        return {'candidate_id': row['id'], 'manifest_sha256': row['manifest_sha256']}
    row = read_registered_baseline(connection, task['snapshot_id'])
    if row is None:
        raise StorageUnavailable('Original Testing snapshot disappeared')
    _, _, steps = original_baseline(connection, row['registration_operation_id'])
    proof = baseline_proof(steps[2]['result_ref'], row['commit_oid'], row['object_format'])
    return {
        'snapshot_id': row['id'],
        'repository_id': row['repository_id'],
        'commit_oid': row['commit_oid'],
        'tree_oid': row['content_tree_oid'],
        'object_format': row['object_format'],
        'content_profile_version_id': row['content_profile_version_id'],
        'content_sha256': proof.content_sha256,
    }


def _verify_result(result, snapshot, target):
    if (
        type(result) is not BaselineQueryResult
        or result.snapshot != snapshot
        or fixed_entries_sha256(result.entries) != target.content_sha256
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_TESTING_SNAPSHOT_SOURCE_DIFFERS')


def prepare_snapshot_source(runtime, query, frames, target, *, active, cancelled):
    original, source, proof, _ = load_baseline_query(runtime, target.snapshot_id)
    if (
        original['commit_oid'] != target.commit_oid
        or original['content_tree_oid'] != target.tree_oid
        or original['object_format'] != target.object_format
        or original['content_profile_version_id'] != target.content_profile_version_id
        or proof.content_sha256 != target.content_sha256
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_TESTING_SNAPSHOT_SOURCE_DIFFERS')
    active()
    result = query(target.snapshot_id, frames, cancelled=cancelled)
    _verify_result(result, original, target)
    manifest = build_manifest(
        result.entries,
        content_profile_version_id=target.content_profile_version_id,
        format=target.object_format,
        content_tree_oid=target.tree_oid,
        limits=source.content_limits,
    )

    def read_original_files(consume, checkpoint):
        checkpoint()
        read = query(target.snapshot_id, frames, cancelled=cancelled, consume_file=consume)
        _verify_result(read, original, target)
        checkpoint()

    return SnapshotCheckSource(target, manifest, read_original_files), source.content_limits
