"""Plan-bound rehearsal/apply/recovery, with immutable external receipts.

Database commit and receipt publication are deliberately separate facts.
No function retries DDL after an unknown result or starts an application service.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import re
import sqlite3
from uuid import uuid4

from backend.app.shared.time import utc_milliseconds
from backend.app.documents.snapshot import _time
from .audit_repository import AuditRepository
from .database import Database, CommitOutcomeUnknown
from .document_repository import DocumentRepository
from .requirement_repository import RequirementRepository
from .schema_inspection import verify_integrity
from .schema_v20_assets import capture_audit, MaintenancePreparationError
from .schema_v20_legacy import original_columns
from .schema_v20_plan import (
    load_plan,
    verify_preapply,
    verify_backup,
    copy_database_new,
    _bound,
    _intent,
    _file_fact,
    BACKUP_NAME,
)
from .schema_v20_plan_codec import BackupFact, _object, _identity, _hex, _integer
from .schema_v20_records import read_record, write_record
from .schema_v20_references import verify_registered_references
from .schema_v20_release import canonical_bytes
from .schema_v20_upgrade import (
    MaintenanceSession,
    UpgradeIntent,
    rebuild_locked,
    recover_locked,
    _new_business_tables_empty,
)
from .windows_local_paths import local_absolute_path

REHEARSAL_SEAL = 'rehearsal.v1.json'


def _at():
    return utc_milliseconds(datetime.now(timezone.utc))


def _append_receipt(session, plan, plan_sha256, phase, status, observation=None):
    _bound(session, plan)
    directory = session.package_path / 'receipts'
    try:
        directory.mkdir()
    except FileExistsError:
        pass
    session.package_guard.verify_member('receipts', directory=True)
    return write_record(
        session,
        'receipts/' + str(uuid4()) + '.json',
        {
            'schema_version': 1,
            'upgrade_id': plan.upgrade_id,
            'plan_sha256': plan_sha256,
            'release_manifest_sha256': plan.release_manifest_sha256,
            'program_sha256': plan.program_sha256,
            'phase': phase,
            'status': status,
            'recorded_at': _at(),
            'observation': None if observation is None else asdict(observation),
        },
    )


def _document_read_digest(database, *, verify_owner_isolation=False):
    """Exercise existing repository reads; only their digest may leave this function."""
    digest = hashlib.sha256(b'DB20-DOCUMENT-READS-1')
    with database.transaction() as connection:
        verify_integrity(connection)
        requirements = RequirementRepository(connection)
        documents = DocumentRepository(connection)
        for row in connection.execute('SELECT id FROM requirements ORDER BY id'):
            identity = row[0]
            value = {
                'requirement': requirements.get(identity),
                'documents': documents.list_current_summaries(identity),
            }
            digest.update(canonical_bytes(value))
        audit = AuditRepository(connection)
        calls = list(connection.execute('SELECT id FROM llm_uses ORDER BY id'))
        for call in calls:
            identity = call[0]
            record = audit.get(identity)
            if record is None:
                raise MaintenancePreparationError('DOCUMENT_CALL_READ_FAILED')
            # New owner columns are not part of an original document read.
            value = {name: record[name] for name in original_columns('llm_uses')}
            digest.update(canonical_bytes(value))
            if verify_owner_isolation and (
                audit.get(identity, owner_kind='CODING', owner_id=1) is not None
                or audit.get(identity, owner_kind='TESTING', owner_id=1) is not None
                or record['execution_session_id'] is not None
                or record['testing_task_id'] is not None
            ):
                raise MaintenancePreparationError('DOCUMENT_OWNER_ISOLATION_FAILED')
    return digest.hexdigest(), len(calls)


def _owner_constraint_probes(database):
    # Only the isolated rehearsal database is supplied, after its actual upgrade.
    probes = 0
    with database.transaction(write=True) as connection:
        row = connection.execute('SELECT id FROM llm_uses ORDER BY id LIMIT 1').fetchone()
        if row is not None:
            for assignment in ('guide_run_id=NULL', 'testing_task_id=1'):
                try:
                    connection.execute(
                        'UPDATE llm_uses SET ' + assignment + ' WHERE id=?', (row[0],)
                    )
                except sqlite3.IntegrityError as error:
                    if not (
                        error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK
                        or (
                            error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_TRIGGER
                            and str(error)
                            in (
                                'IMMUTABLE_FIELD',
                                'IMMUTABLE_CALL_OWNER',
                                'CALL_OPERATION_OWNER_MISMATCH',
                            )
                        )
                    ):
                        raise MaintenancePreparationError(
                            'OWNER_PROBE_NOT_A_CONSTRAINT_REJECTION'
                        ) from error
                    probes += 1
                else:
                    raise MaintenancePreparationError('OWNER_CONSTRAINT_PROBE_FAILED')
    return probes


def verify_rehearsal(session, plan, plan_sha256):
    _bound(session, plan)
    value, sha256 = read_record(session, REHEARSAL_SEAL)
    keys = (
        'schema_version',
        'upgrade_id',
        'plan_sha256',
        'release_manifest_sha256',
        'program_sha256',
        'status',
        'completed_at',
        'rehearsal',
        'document_reads_sha256',
        'document_call_count',
        'owner_constraint_probe_count',
    )
    _object(value, keys)
    if (
        type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or value['upgrade_id'] != plan.upgrade_id
        or value['plan_sha256'] != plan_sha256
        or value['release_manifest_sha256'] != plan.release_manifest_sha256
        or value['program_sha256'] != plan.program_sha256
        or value['status'] != 'PASSED'
    ):
        raise MaintenancePreparationError('REHEARSAL_SEAL_BINDING_DIFFERS')
    _time(value['completed_at'])
    _hex(value['document_reads_sha256'])
    _integer(value['document_call_count'])
    probes = _integer(value['owner_constraint_probe_count'])
    if probes != (2 if value['document_call_count'] else 0):
        raise MaintenancePreparationError('REHEARSAL_PROBES_INCOMPLETE')
    file = _object(value['rehearsal'], ('identity', 'byte_count', 'sha256'))
    native = _identity(file['identity'], directory=False)
    path = local_absolute_path(native.canonical_path)
    if (
        path.parent != session.package_path
        or re.fullmatch(
            r'rehearsal-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.sqlite',
            path.name,
        )
        is None
    ):
        raise MaintenancePreparationError('REHEARSAL_PATH_DIFFERS')
    expected = BackupFact(native, _integer(file['byte_count'], 1), _hex(file['sha256']))
    if _file_fact(session, path.name) != expected:
        raise MaintenancePreparationError('REHEARSAL_DATABASE_CHANGED')
    rehearsal_intent = UpgradeIntent(
        plan.upgrade_id, plan.release_manifest_sha256, native, plan.retained
    )
    with MaintenanceSession(
        path, session.package_path, session.release, maintenance_window_confirmed=True
    ) as copy:
        result = recover_locked(copy, rehearsal_intent)
        if result.status != 'ALREADY_COMMITTED' or result.retained_data_matches is not True:
            raise MaintenancePreparationError('REHEARSAL_DATABASE_UNVERIFIED')
    with Database(path, schema_release=session.release, read_only=True).transaction() as connection:
        _new_business_tables_empty(connection, session.release, plan.retained)
    backup_reads = _document_read_digest(
        Database(session.package_path / BACKUP_NAME, read_only=True)
    )
    copy_reads = _document_read_digest(
        Database(path, schema_release=session.release, read_only=True), verify_owner_isolation=True
    )
    if backup_reads != copy_reads or copy_reads != (
        value['document_reads_sha256'],
        value['document_call_count'],
    ):
        raise MaintenancePreparationError('REHEARSAL_DOCUMENT_READS_DIFFER')
    if _file_fact(session, path.name) != expected:
        raise MaintenancePreparationError('REHEARSAL_DATABASE_CHANGED')
    _bound(session, plan)
    return value, sha256


def rehearse_plan(session, *, upgrade_id, plan_sha256):
    plan, plan_sha256 = load_plan(session, upgrade_id=upgrade_id, plan_sha256=plan_sha256)
    verify_preapply(session, plan)
    try:
        (session.package_path / REHEARSAL_SEAL).lstat()
    except FileNotFoundError:
        pass
    else:
        return verify_rehearsal(session, plan, plan_sha256)
    name = 'rehearsal-' + str(uuid4()) + '.sqlite'
    try:
        copy_database_new(
            session,
            Database(session.package_path / BACKUP_NAME, read_only=True),
            name,
            plan.retained,
        )
        path = session.package_path / name
        with MaintenanceSession(
            path, session.package_path, session.release, maintenance_window_confirmed=True
        ) as copy:
            original = UpgradeIntent(
                plan.upgrade_id,
                plan.release_manifest_sha256,
                copy.source_guard.identity,
                plan.retained,
            )
            result = rebuild_locked(copy, original)
            if result.status != 'UPGRADED' or result.retained_data_matches is not True:
                raise MaintenancePreparationError('REHEARSAL_DID_NOT_UPGRADE')
        copied = Database(path, schema_release=session.release)
        probes = _owner_constraint_probes(copied)
        reads = _document_read_digest(
            Database(path, schema_release=session.release, read_only=True),
            verify_owner_isolation=True,
        )
        backup_reads = _document_read_digest(
            Database(session.package_path / BACKUP_NAME, read_only=True)
        )
        if reads != backup_reads:
            raise MaintenancePreparationError('REHEARSAL_DOCUMENT_READS_DIFFER')
        verify_preapply(session, plan)
        value = {
            'schema_version': 1,
            'upgrade_id': plan.upgrade_id,
            'plan_sha256': plan_sha256,
            'release_manifest_sha256': plan.release_manifest_sha256,
            'program_sha256': plan.program_sha256,
            'status': 'PASSED',
            'completed_at': _at(),
            'rehearsal': asdict(_file_fact(session, name)),
            'document_reads_sha256': reads[0],
            'document_call_count': reads[1],
            'owner_constraint_probe_count': probes,
        }
        write_record(session, REHEARSAL_SEAL, value)
        verified = verify_rehearsal(session, plan, plan_sha256)
    except Exception:
        # An incomplete copy is retained, never upgraded into a successful seal.
        _append_receipt(session, plan, plan_sha256, 'REHEARSAL', 'INCOMPLETE')
        raise
    _append_receipt(session, plan, plan_sha256, 'REHEARSAL', 'PASSED')
    return verified


def _historical_evidence(session, plan, plan_sha256):
    _bound(session, plan)
    verify_backup(session, plan)
    verify_rehearsal(session, plan, plan_sha256)


def apply_plan(session, *, upgrade_id, plan_sha256):
    plan, plan_sha256 = load_plan(session, upgrade_id=upgrade_id, plan_sha256=plan_sha256)
    _historical_evidence(session, plan, plan_sha256)
    result = recover_locked(session, _intent(plan))
    if result.status == 'UNKNOWN':
        raise MaintenancePreparationError('ORIGINAL_DATABASE_UNVERIFIED')
    if result.status == 'NOT_APPLIED':
        verify_preapply(session, plan)
        result = rebuild_locked(session, _intent(plan))
        try:
            if capture_audit(session) != plan.audit:
                raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
            verify_registered_references(session, plan.references)
        except Exception as error:
            raise CommitOutcomeUnknown(
                'Committed database requires explicit original-intent recovery'
            ) from error
    try:
        _append_receipt(session, plan, plan_sha256, 'APPLY', result.status, result)
    except Exception as error:
        raise CommitOutcomeUnknown(
            'Database and external receipt require explicit reconciliation'
        ) from error
    return result


def recover_plan(session, *, upgrade_id, plan_sha256):
    plan, plan_sha256 = load_plan(session, upgrade_id=upgrade_id, plan_sha256=plan_sha256)
    _historical_evidence(session, plan, plan_sha256)
    result = recover_locked(session, _intent(plan))
    _append_receipt(session, plan, plan_sha256, 'RECOVER', result.status, result)
    return result
