"""Explicit DB20 plan sealing on the original path and SQLite snapshot.

Only the native maintenance caller opens a session. This module has no default
database path, service management, arbitrary SQL, provider IO or asset deletion.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sqlite3
from uuid import uuid4

from backend.app.shared.time import utc_milliseconds
from .database import Database, SchemaMismatch
from .data_retention import capture_retained_data, verify_retained_data
from .schema_inspection import verify_integrity
from .schema_v20_assets import (
    capture_audit,
    copy_audit,
    verify_audit_backup,
    require_disk_space,
    _hash_file,
    MaintenancePreparationError,
)
from .schema_v20_plan_codec import BackupFact, MaintenancePlan, decode_plan
from .schema_v20_records import read_record, write_record
from .schema_v20_references import capture_registered_references, verify_registered_references
from .schema_v20_release import ROOT, SOURCE_NAMES, canonical_bytes
from .schema_v20_upgrade import UpgradeIntent
from .windows_local_paths import LocalPathGuard

PLAN_NAME = 'plan.v1.json'
BACKUP_NAME = 'source-backup.sqlite'


def program_digest():
    names = set(SOURCE_NAMES)
    names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / 'backend/app').rglob('*.py'))
    names.add('tools/python-v20.py')
    if (ROOT / 'tools/db-v20.py').exists():
        names.add('tools/db-v20.py')
    sources = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(names)
    }
    return hashlib.sha256(canonical_bytes(sources)).hexdigest()


def _intent(plan):
    return UpgradeIntent(
        plan.upgrade_id, plan.release_manifest_sha256, plan.source_identity, plan.retained
    )


def _file_fact(session, name):
    native = session.package_guard.verify_member(name, directory=False)
    path = session.package_path / name
    with LocalPathGuard(path, directory=False) as guard:
        size, sha256 = _hash_file(path, guard)
        if native != guard.verify():
            raise MaintenancePreparationError('MAINTENANCE_ASSET_CHANGED')
    return BackupFact(native, size, sha256)


def copy_database_new(session, database, name, retained):
    """Backup API from a distinct read connection; never from a write transaction."""
    session.verify()
    if (
        type(name) is not str
        or (
            name != BACKUP_NAME
            and re.fullmatch(
                r'rehearsal-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.sqlite',
                name,
            )
            is None
        )
        or database.read_only is not True
    ):
        raise MaintenancePreparationError('REGISTERED_BACKUP_SOURCE_AND_NAME_REQUIRED')
    if database.path not in (session.database.path, session.package_path / BACKUP_NAME):
        raise MaintenancePreparationError('REGISTERED_BACKUP_SOURCE_AND_NAME_REQUIRED')
    target = session.package_path / name
    # Exclusive creation and privacy verification precede any business byte write.
    with target.open('xb'):
        pass
    native = session.package_guard.verify_member(name, directory=False)
    source = database._connect()
    destination = None
    try:
        source.execute('BEGIN')
        database._check_schema(source)
        verify_integrity(source)
        verify_retained_data(source, retained)
        with LocalPathGuard(target, directory=False) as guard:
            if guard.identity != native:
                raise MaintenancePreparationError('MAINTENANCE_ASSET_CHANGED')
            destination = sqlite3.connect(target, isolation_level=None)
            destination.execute('PRAGMA synchronous=FULL')
            source.backup(destination)
            destination.close()
            destination = None
            guard.verify()
    finally:
        if destination is not None:
            destination.close()
        source.close()
    with target.open('r+b') as stream:
        os.fsync(stream.fileno())
    # All backup connections are closed before an actual independent reopen.
    backup = Database(target, read_only=True)
    with backup.transaction() as reopened:
        verify_integrity(reopened)
        verify_retained_data(reopened, retained)
    session.verify()
    return _file_fact(session, name)


def verify_backup(session, plan):
    if _file_fact(session, BACKUP_NAME) != plan.backup:
        raise MaintenancePreparationError('SOURCE_BACKUP_CHANGED')
    with Database(session.package_path / BACKUP_NAME, read_only=True).transaction() as reopened:
        verify_integrity(reopened)
        verify_retained_data(reopened, plan.retained)
    if _file_fact(session, BACKUP_NAME) != plan.backup:
        raise MaintenancePreparationError('SOURCE_BACKUP_CHANGED')
    verify_audit_backup(session, plan.audit)


def _bound(session, plan):
    session.verify()
    if (
        session.source_guard.identity != plan.source_identity
        or session.package_guard.verify() != plan.package_identity
        or session.package_guard.operator_sid != plan.operator_sid
        or session.release.release_id != plan.release_id
        or session.release.manifest_sha256 != plan.release_manifest_sha256
        or session.release.schema_contract_sha256 != plan.schema_contract_sha256
        or program_digest() != plan.program_sha256
    ):
        raise MaintenancePreparationError('MAINTENANCE_PLAN_BINDING_DIFFERS')


def load_plan(session, *, upgrade_id, plan_sha256):
    # Both original identities are mandatory, not inferred from package contents.
    from .idempotency import request_key
    import re

    if (
        request_key(upgrade_id) != upgrade_id
        or type(plan_sha256) is not str
        or re.fullmatch('[0-9a-f]{64}', plan_sha256) is None
    ):
        raise MaintenancePreparationError('ORIGINAL_PLAN_IDENTITY_REQUIRED')
    value, actual = read_record(session, PLAN_NAME, expected_sha256=plan_sha256)
    plan = decode_plan(value)
    if plan.upgrade_id != upgrade_id:
        raise MaintenancePreparationError('MAINTENANCE_UPGRADE_ID_DIFFERS')
    _bound(session, plan)
    return plan, actual


def prepare_plan(session, *, configuration_paths):
    """Seal a new original-source plan LAST, after all immutable backup checks.

    configuration_paths must be explicitly supplied, including an explicit empty
    sequence when the maintenance operator declares no external config files.
    """
    session.verify()
    # Do not build another asset set in a sealed or partially used package.
    for name in (
        PLAN_NAME,
        BACKUP_NAME,
        'count-audit-copy',
        'rehearsal.sqlite',
        'rehearsal.v1.json',
    ):
        try:
            (session.package_path / name).lstat()
        except FileNotFoundError:
            continue
        raise MaintenancePreparationError('NEW_MAINTENANCE_PACKAGE_REQUIRED')
    if type(configuration_paths) not in (tuple, list):
        raise MaintenancePreparationError('EXPLICIT_CONFIGURATION_REFERENCES_REQUIRED')
    program = program_digest()
    connection = session.database._connect()
    try:
        # A second read connection performs Backup API while this original writer
        # snapshot excludes all other SQLite writers. No data changes are made.
        connection.execute('BEGIN IMMEDIATE')
        session.database._check_schema(connection)
        verify_integrity(connection)
        retained = capture_retained_data(connection)
        audit = capture_audit(session)
        space = require_disk_space(session, connection, audit)
        references = capture_registered_references(
            session, audit, configuration_paths=configuration_paths
        )
        backup = copy_database_new(
            session, Database(session.database.path, read_only=True), BACKUP_NAME, retained
        )
        copy_audit(session, audit)
        if capture_retained_data(connection) != retained or capture_audit(session) != audit:
            raise SchemaMismatch('SOURCE_CHANGED: original plan assets differ')
        verify_registered_references(session, references)
        session.verify()
        if program_digest() != program:
            raise MaintenancePreparationError('MAINTENANCE_PROGRAM_CHANGED')
        plan = MaintenancePlan(
            1,
            str(uuid4()),
            utc_milliseconds(datetime.now(timezone.utc)),
            session.source_guard.identity,
            session.package_guard.verify(),
            session.package_guard.operator_sid,
            session.release.release_id,
            session.release.manifest_sha256,
            session.release.schema_contract_sha256,
            program,
            retained,
            audit,
            backup,
            references,
            space,
        )
        # Exercise the complete strict decoding before making an approved plan visible.
        plan = decode_plan(json.loads(canonical_bytes(asdict(plan))))
        verify_backup(session, plan)
        _bound(session, plan)
        sha256 = write_record(session, PLAN_NAME, asdict(plan))
        return plan, sha256
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def verify_preapply(session, plan):
    """Read-only prerequisites, repeated by the eventual original-source apply."""
    _bound(session, plan)
    verify_backup(session, plan)
    if capture_audit(session) != plan.audit:
        raise MaintenancePreparationError('AUDIT_SOURCE_CHANGED')
    verify_registered_references(session, plan.references)
    with session.database.transaction() as connection:
        verify_integrity(connection)
        if capture_retained_data(connection) != plan.retained:
            raise SchemaMismatch('SOURCE_CHANGED: the original approved plan is stale')
        require_disk_space(session, connection, plan.audit)
    _bound(session, plan)
