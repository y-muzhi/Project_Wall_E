"""Verify ordinary backup asset coverage while the original database stays closed."""

import os
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from .data_retention import quote_identifier
from .environment_backup import (
    SNAPSHOT,
    capture_inputs,
    original_receipt,
    recovery_directory,
)
from .environment_backup_assets import (
    AUDIT_UNSUPPORTED,
    audit_directory,
    audit_names,
    audit_source_name,
    scan_audit,
    source_index,
)
from .environment_binding import EnvironmentBinding
from .environment_control import read_control, stopped_for_policy
from .environment_files import canonical, digest, require
from .environment_initialize import (
    assert_database,
    database_has_sidecars,
    read_locked_database,
    verify_locked_binding,
)
from .environment_installation import Installation, database_identity
from .environment_lock import EnvironmentLock
from .environment_restore import archived_facts, reopen_archive

UNVERIFIED = 'BACKUP_COVERAGE_UNVERIFIED'
STALE = 'BACKUP_COVERAGE_SOURCE_CHANGED'

# These rows contain ordinary document material, fixed program resource references,
# or SQLite coordination data. Other domains need their own asset handlers.
ORDINARY_INLINE_TABLES = frozenset(
    {
        'code_schema_state',
        'comments',
        'conversation_messages',
        'document_change_audits',
        'environment_binding',
        'idempotency_records',
        'manual_block_allocation_ranges',
        'manual_block_origins',
        'manual_draft_context',
        'manual_edit_sessions',
        'requirement_documents',
        'requirements',
        'revisions',
        'schema_migrations',
        'sequences',
        'sqlite_sequence',
        'suggestion_batches',
        'suggestions',
    }
)


ORDINARY_RECEIPT_CAPABILITIES = (
    'APP-REQ-CMD-C01',
    'APP-REQ-CMD-C02',
    'APP-REQ-CMD-C06',
    'APP-DOC-CMD-C01',
    'APP-DOC-CMD-C02',
    'APP-DOC-CMD-C03',
    'APP-DOC-CMD-C04',
    'APP-DOC-CMD-C05',
    'APP-DOC-CMD-C06',
)


def require_supported_tables(connection):
    tables = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"
    ).fetchall()
    for (table,) in tables:
        if table not in ORDINARY_INLINE_TABLES:
            name = quote_identifier(table)
            require(
                connection.execute(f'SELECT 1 FROM {name} LIMIT 1').fetchone() is None,
                AUDIT_UNSUPPORTED,
            )
    marks = ','.join('?' for _ in ORDINARY_RECEIPT_CAPABILITIES)
    unfamiliar = connection.execute(
        f'SELECT 1 FROM idempotency_records WHERE capability_id NOT IN ({marks}) LIMIT 1',
        ORDINARY_RECEIPT_CAPABILITIES,
    ).fetchone()
    require(unfamiliar is None, AUDIT_UNSUPPORTED)


def require_supported_directory(data_fd, installation, original):
    name = str(installation.database_relative)
    allowed = {
        name,
        name + '-journal',
        name + '-wal',
        name + '-shm',
        audit_source_name(installation),
    }
    with os.scandir(data_fd) as rows:
        for row in rows:
            require(row.name in allowed, AUDIT_UNSUPPORTED)
    assert_database(installation, data_fd, original)


def compare_count_audit(data_fd, installation, plan, index):
    with audit_directory(
        data_fd,
        audit_source_name(installation),
        installation.application_uid,
        installation.group,
        source=True,
    ) as source:
        if source is None:
            require(index['state'] == 'ABSENT', STALE)
            return
        names = audit_names(source, plan['max_audit_files'])
        require(
            index['state'] == ('FILES' if names else 'EMPTY')
            and names == [entry['name'] for entry in index['entries']],
            STALE,
        )
        remaining = plan['max_audit_bytes']
        for name, expected in zip(names, index['entries'], strict=True):
            observed, _ = scan_audit(
                source,
                name,
                installation.application_uid,
                installation.group,
                remaining,
                source=True,
            )
            require(observed == expected, STALE)
            remaining -= observed['bytes']
        require(audit_names(source, plan['max_audit_files']) == names, STALE)


def source_facts(installation, release, binding):
    with read_locked_database(installation.database) as source:
        verify_locked_binding(source, installation.database, release, binding)
        require_supported_tables(source)
        return archived_facts(source, release, binding)


@dataclass(frozen=True)
class LockedBackupCoverage:
    facts: dict
    installation: Installation
    control_fd: int
    control: dict
    lock: EnvironmentLock
    database_identity: dict


@contextmanager
def locked_coverage(native, active, args, entry, *, require_clean_database=False):
    plan, installation, release = capture_inputs(active, args, entry)
    require(plan['format_version'] == 2, UNVERIFIED)
    binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
    with ExitStack() as resources:
        lock = resources.enter_context(installation.lock(native))
        installation.check_hold()
        control_fd = resources.enter_context(installation.directory(native, 'control'))
        control = read_control(control_fd, installation)
        require(
            stopped_for_policy(control_fd, control, plan.get('maintenance'))
            and control['control_revision'] == plan['control_revision']
            and not os.path.lexists(installation.path('runtime') / 'walle.sock'),
            STALE,
        )
        data_fd = resources.enter_context(installation.directory(native, 'data'))
        original = database_identity(installation, data_fd)
        require(original is not None, STALE)
        require_supported_directory(data_fd, installation, original)
        require(
            not require_clean_database or not database_has_sidecars(installation.database), STALE
        )
        folder, sealed_fd = resources.enter_context(recovery_directory(plan, installation))
        receipt = original_receipt(sealed_fd, plan, installation, args.capture_sha256)
        require(receipt is not None, UNVERIFIED)
        _, audit = source_index(installation, sealed_fd, receipt)
        original_facts = source_facts(installation, release, binding)
        captured_facts = reopen_archive(folder / SNAPSHOT, release, binding)
        require(original_facts == captured_facts, STALE)
        compare_count_audit(data_fd, installation, plan, audit)
        lock.assert_owned()
        require_supported_directory(data_fd, installation, original)
        require(
            not require_clean_database or not database_has_sidecars(installation.database), STALE
        )
        require(
            read_control(control_fd, installation) == control
            and stopped_for_policy(control_fd, control, plan.get('maintenance'))
            and not os.path.lexists(installation.path('runtime') / 'walle.sock'),
            STALE,
        )
        installation.check_hold()
        require(
            original_receipt(sealed_fd, plan, installation, args.capture_sha256) == receipt,
            UNVERIFIED,
        )
        record = {
            'format_version': 1,
            'status': 'ORDINARY_BACKUP_COVERAGE_CHECKED',
            **{
                key: receipt[key]
                for key in (
                    'operation_id',
                    'environment_id',
                    'data_generation',
                    'deployment_id',
                    'control_revision',
                    'cutoff_at',
                    'asset_index',
                )
            },
            'capture_policy_sha256': args.capture_sha256,
            'capture_receipt_sha256': digest(canonical(receipt)),
            'database_sha256': receipt['database_artifact']['sha256'],
            'logical_content_sha256': captured_facts[1].sha256,
            'program_sha256': plan['source_program_sha256'],
            'configuration_sha256': installation.configuration_sha256,
            'runtime_manifest_sha256': installation.description['runtime_manifest_sha256'],
            'schema_manifest_sha256': installation.description['schema_manifest_sha256'],
            'schema_contract_sha256': release.schema_contract_sha256,
            'audit_state': audit['state'],
        }
        facts = {**record, 'coverage_sha256': digest(canonical(record))}
        yield LockedBackupCoverage(facts, installation, control_fd, control, lock, original)


def check_coverage(native, active, args, entry, *, require_clean_database=False):
    with locked_coverage(
        native, active, args, entry, require_clean_database=require_clean_database
    ) as source:
        return source.facts
