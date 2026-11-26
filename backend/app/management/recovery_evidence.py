"""Parse bounded, structured recovery evidence for management read paths."""

from datetime import datetime

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.shared.time import utc_milliseconds

from .registry import is_timestamp


def backup_cutoff(value, code):
    require(type(value) is str, code)
    try:
        normalized = utc_milliseconds(datetime.fromisoformat(value))
    except (ValueError, OverflowError) as error:
        raise EnvironmentFailure(code) from error
    # The capture tool originally emitted +00:00. Preserve that source in its signed proof.
    require(value in (normalized, normalized.removesuffix('Z') + '+00:00'), code)
    return normalized


def parse_local_recovery(proof, code):
    version_record(
        proof,
        (
            'status',
            'verification_id',
            'verification_policy_sha256',
            'backup_id',
            'backup_manifest_sha256',
            'runtime_manifest_sha256',
            'schema_manifest_sha256',
            'program_snapshot_sha256',
            'frontend_index_sha256',
            'rehearsal_receipt_sha256',
            'recovery_read_policy_sha256',
            'environment_id',
            'data_generation',
            'deployment_id',
            'configuration_sha256',
            'control_revision',
            'run_id',
            'verified_at',
            'verified_scopes',
            'database_sha256',
            'logical_content_sha256',
            'document_lookup',
            'outbound_hold_required',
        ),
        code,
    )
    require(
        proof['status'] == 'LOCAL_VERIFIED'
        and proof['outbound_hold_required'] is True
        and all(
            uuid_value(proof[key])
            for key in (
                'verification_id',
                'backup_id',
                'environment_id',
                'data_generation',
                'deployment_id',
                'run_id',
            )
        )
        and all(
            sha_value(proof[key])
            for key in (
                'verification_policy_sha256',
                'backup_manifest_sha256',
                'rehearsal_receipt_sha256',
                'recovery_read_policy_sha256',
                'configuration_sha256',
                'database_sha256',
                'logical_content_sha256',
                'runtime_manifest_sha256',
                'schema_manifest_sha256',
                'program_snapshot_sha256',
                'frontend_index_sha256',
            )
        )
        and type(proof['control_revision']) is int
        and 1 <= proof['control_revision'] < MAX_REVISION
        and is_timestamp(proof['verified_at'])
        and proof['verified_scopes'] == ['DOCUMENT_CONTENT', 'DOCUMENT_HISTORY'],
        code,
    )
    checked = exact(
        proof['document_lookup'], ('requirement_id', 'document_id', 'markdown_sha256'), code
    )
    require(
        sha_value(checked['markdown_sha256'])
        and all(
            type(checked[key]) is int and 1 <= checked[key] <= MAX_REVISION
            for key in ('requirement_id', 'document_id')
        ),
        code,
    )
    return proof
