"""Check independent retrieval evidence and determine backup freshness."""

from datetime import datetime, timedelta

from backend.app.infrastructure.environment_files import exact, require
from backend.app.infrastructure.environment_installation import (
    sha_value,
    uuid_value,
    version_record,
)
from backend.app.infrastructure.environment_restic_contract import (
    BACKUP_POINT_FIELDS,
    OFFHOST_BINDING,
    OFFHOST_RECEIPT_FIELDS,
    OFFHOST_RETRIEVED,
    VERSION,
)

from .operation_contract import RESOURCE, installed_record
from .registry import is_timestamp

OFFHOST_AUTHORITY_FIELDS = (*OFFHOST_BINDING, 'observation_max_age_seconds')


def offhost_authority(value, code=RESOURCE):
    authority = exact(value, OFFHOST_AUTHORITY_FIELDS, code)
    require(
        all(uuid_value(authority[key]) for key in OFFHOST_BINDING[:2])
        and authority['source_host_id'] != authority['verification_host_id']
        and all(sha_value(authority[key]) for key in OFFHOST_BINDING[2:])
        and type(authority['observation_max_age_seconds']) is int
        and 1 <= authority['observation_max_age_seconds'] <= 365 * 86400,
        code,
    )
    return authority


def offhost_metadata(proof, point, environment, ceiling, authority, code=RESOURCE):
    version_record(proof, OFFHOST_RECEIPT_FIELDS, code)
    require(
        proof['status'] == OFFHOST_RETRIEVED
        and all(proof[key] == authority[key] for key in OFFHOST_BINDING)
        and uuid_value(proof['verification_id'])
        and uuid_value(proof['publication_operation_id'])
        and len({proof['verification_id'], proof['publication_operation_id'], point['backup_id']})
        == 3
        and all(
            sha_value(proof[key])
            for key in ('verification_policy_sha256', 'snapshot_id', 'restic_sha256')
        )
        and proof['source_environment_id'] == environment
        and all(proof[key] == point[key] for key in BACKUP_POINT_FIELDS)
        and type(proof['source_control_revision']) is int
        and proof['restic_version'] == VERSION
        and type(proof['snapshot_bytes']) is int
        and point['database_bytes'] <= proof['snapshot_bytes'] <= 1024**4
        and type(proof['snapshot_entries']) is int
        and 0 < proof['snapshot_entries'] <= 8192
        and is_timestamp(proof['retrieved_at'])
        and point['cutoff_at'] <= proof['retrieved_at'] <= ceiling,
        code,
    )
    return {
        'verification_id': proof['verification_id'],
        'snapshot_id': proof['snapshot_id'],
        'retrieved_at': proof['retrieved_at'],
    }


def offhost_view(directory, point, environment, ceiling, authority, local):
    pin = point['offhost_verification_sha256']
    if pin is None:
        return None
    require(sha_value(pin) and local is not None, RESOURCE)
    evidence = directory / f'{point["backup_id"]}.offhost.v1.json'
    return offhost_metadata(
        installed_record(evidence, pin, code=RESOURCE), point, environment, ceiling, authority
    )


def offhost_freshness(latest, as_of, rpo_seconds, max_age_seconds):
    if latest is None:
        return None, 'UNVERIFIED'
    stamp = {
        'backup_id': latest['backup_id'],
        'cutoff_at': latest['cutoff_at'],
        'verified_at': latest['offhost_verification']['retrieved_at'],
    }
    age = datetime.fromisoformat(as_of) - datetime.fromisoformat(stamp['verified_at'])
    if rpo_seconds is None or age > timedelta(seconds=max_age_seconds):
        return stamp, 'UNVERIFIED'
    gap = datetime.fromisoformat(as_of) - datetime.fromisoformat(stamp['cutoff_at'])
    return stamp, 'MET' if gap <= timedelta(seconds=rpo_seconds) else 'MISSED'
