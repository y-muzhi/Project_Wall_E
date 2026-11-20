"""Explicit source-read-only copy to a new target; never an in-place migration."""

import os
import sqlite3
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from backend.app.shared.command_execution import operation_time

from .data_retention import verify_retained_data
from .database import CommitOutcomeUnknown, Database, SchemaMismatch, _statements
from .formation_database import FormationDatabase, check_v21
from .formation_schema_release import load_release
from .formation_upgrade_source import reviewed_source, source_facts, verify_source_resources
from .process_lock import ProcessLock
from .schema_inspection import quote_identifier, verify_integrity
from .schema_v20_assets import capture_audit, copy_audit, require_disk_space
from .schema_v20_records import _publish_new
from .schema_v20_references import capture_registered_references, verify_registered_references
from .schema_v20_upgrade import MaintenanceSession
from .windows_local_paths import LocalPathGuard, local_absolute_path
from .windows_private_package import create_private_package


class FormationUpgradeSession(MaintenanceSession):
    """Reuse the original native paths, private package, OS lock and asset guards."""

    def __enter__(self):
        super().__enter__()
        self.database = Database(self.source_path, schema_release=self.release, read_only=True)
        return self


@dataclass(frozen=True)
class UpgradeResult:
    status: str
    upgrade_id: str
    source_data_sha256: str
    target_manifest_sha256: str
    report_path: str


def _inputs(source, target, source_manifest, target_manifest, maintenance_window_confirmed):
    if maintenance_window_confirmed is not True:
        raise ValueError('Explicit offline maintenance window required')
    release = load_release()
    if target_manifest != release.manifest_sha256:
        raise SchemaMismatch('Target manifest is not the current compiled Schema210 pin')
    core = reviewed_source(source_manifest, release)
    source, target = local_absolute_path(source), local_absolute_path(target)
    if source == target or source.parent == target.parent or source.is_relative_to(target.parent):
        raise ValueError('A separate new target package outside the source directory is required')
    if target.name.lower() in (
        'upgrade-result.md',
        'upgrade-intent.md',
        'upgrade-failure.md',
        'count-audit-copy',
    ):
        raise ValueError('Target filename conflicts with maintenance evidence')
    return source, target, release, core


def _uuid(value):
    text = str(value)
    if str(UUID(text)) != text or UUID(text).version != 4:
        raise ValueError('A canonical upgrade UUID is required')
    return text


def _write_report(session, name, lines):
    raw = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Maintenance Markdown report is too large')
    target = session.package_path / name
    temporary = None
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix='.formation-report-', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            session.package_guard.verify_member(temporary.name, directory=False)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        session.verify()
        _publish_new(temporary, target)
        session.package_guard.verify_member(name, directory=False)
        with LocalPathGuard(target, directory=False):
            if target.read_bytes() != raw:
                raise SchemaMismatch('Published maintenance report differs')
        return str(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _intent_lines(source, target, release, core, identity, facts):
    return [
        '# WALL-E V2.1只读复制升级',
        '',
        '状态：PREPARED；未执行服务切换。',
        '',
        f'- 升级标识：{identity}',
        f'- 源路径：{source}',
        f'- 目标路径：{target}',
        f'- 源manifest：{core.manifest_sha256}',
        f'- 目标manifest：{release.manifest_sha256}',
        f'- 源完整行及历史摘要：{facts.sha256}',
        '',
        '| 原表 | 行数 | 类型／字节摘要 |',
        '| --- | --- | --- |',
        *(
            f'| {table.projection.table} | {table.row_count} | {table.sha256} |'
            for table in facts.retained.tables
        ),
    ]


def _copy_database(session, connection, target):
    # Reserve a new file and verify its inherited private ACL before copying bytes.
    with target.open('xb') as stream:
        stream.flush()
        os.fsync(stream.fileno())
    session.package_guard.verify_member(target.name, directory=False)
    with LocalPathGuard(target, directory=False) as guard:
        copy = Database(target, schema_release=session.release)._connect()
        try:
            connection.backup(copy)
        finally:
            copy.close()
        guard.verify()
    session.verify()


def _apply_extension(database, release, facts, identity):
    connection = database._connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        from .schema_v20_state import check_v20

        check_v20(connection, release.core)
        verify_retained_data(connection, facts.retained)
        for statement in _statements(release.upgrade):
            connection.execute(statement)
        at = operation_time(None)
        connection.execute(
            'INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(210,?,?)',
            (release.upgrade_checksum, at),
        )
        connection.execute(
            'INSERT INTO formation_schema_state(singleton_id,schema_version,'
            'schema_contract_sha256,core_contract_sha256,origin,upgrade_id,source_data_sha256,committed_at) '
            "VALUES(1,210,?,?,'UPGRADED_V200',?,?,?)",
            (
                release.schema_contract_sha256,
                release.core.schema_contract_sha256,
                identity,
                facts.sha256,
                at,
            ),
        )
        check_v21(connection, release)
        verify_integrity(connection)
        verify_retained_data(connection, facts.retained)
        try:
            connection.commit()
        except sqlite3.Error as error:
            raise CommitOutcomeUnknown('Inspect the retained target; do not retry DDL') from error
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def _audit_fingerprint(audit):
    return audit.state, tuple((file.name, file.byte_count, file.sha256) for file in audit.files)


def _verify_target(database, release, facts, identity):
    with database.transaction() as connection:
        verify_integrity(connection)
        verify_retained_data(connection, facts.retained)
        history = tuple(
            tuple(row)
            for row in connection.execute(
                'SELECT version,checksum,applied_at FROM schema_migrations WHERE version<>210 ORDER BY version'
            )
        )
        marker = connection.execute('SELECT * FROM formation_schema_state').fetchone()
        if (
            history != facts.history
            or marker['origin'] != 'UPGRADED_V200'
            or marker['upgrade_id'] != identity
            or marker['source_data_sha256'] != facts.sha256
        ):
            raise SchemaMismatch('Target does not retain this original source and upgrade intent')
        old = {table.name for table in release.core.expected_schema.tables}
        new = (
            {table.name for table in release.expected_schema.tables}
            - old
            - {'formation_schema_state'}
        )
        for table in new:
            if connection.execute(f'SELECT 1 FROM {quote_identifier(table)} LIMIT 1').fetchone():
                raise SchemaMismatch('New formation business data is not empty')


class TargetAuditView:
    def __init__(self, session, database, guard, lock):
        self.session, self.database, self.guard, self.process_lock = session, database, guard, lock

    def verify(self):
        self.session.verify()
        self.guard.verify()
        self.process_lock.assert_owned()


def copy_upgrade(
    source,
    target,
    *,
    source_manifest,
    target_manifest,
    maintenance_window_confirmed,
    upgrade_id=None,
):
    source, target, release, core = _inputs(
        source,
        target,
        source_manifest,
        target_manifest,
        maintenance_window_confirmed,
    )
    identity = _uuid(str(uuid4()) if upgrade_id is None else upgrade_id)
    if target.exists() or target.parent.exists():
        raise SchemaMismatch('A brand-new target file and private parent package are required')
    # Reject a missing/redirected source before preparing even an empty package.
    with LocalPathGuard(source, directory=False):
        create_private_package(target.parent)
    with FormationUpgradeSession(
        source, target.parent, core, maintenance_window_confirmed=True
    ) as session:
        facts = None
        try:
            with session.database.transaction() as connection:
                facts = source_facts(connection, core)
                verify_source_resources(connection)
                audit = capture_audit(session)
                references = capture_registered_references(session, audit, configuration_paths=())
                require_disk_space(session, connection, audit)
                _write_report(
                    session,
                    'upgrade-intent.md',
                    _intent_lines(source, target, release, core, identity, facts),
                )
                copy_audit(session, audit)
                _copy_database(session, connection, target)
            # A fresh snapshot detects writers that bypassed the application's OS lock.
            with session.database.transaction() as connection:
                if source_facts(connection, core) != facts:
                    raise SchemaMismatch('Source changed while the target was copied')
            verify_registered_references(session, references)
            if audit.state != 'ABSENT':
                os.rename(
                    session.package_path / 'count-audit-copy',
                    target.with_name(target.name + '.count-audit'),
                )
                session.package_guard.verify_member(target.name + '.count-audit', directory=True)
            database = FormationDatabase(target, formation_release=release)
            with ExitStack() as stack:
                guard = stack.enter_context(LocalPathGuard(target, directory=False))
                lock = stack.enter_context(ProcessLock.for_database(target))
                view = TargetAuditView(session, database, guard, lock)
                if _audit_fingerprint(capture_audit(view)) != _audit_fingerprint(audit):
                    raise SchemaMismatch('Target audit bytes differ')
                _apply_extension(database, release, facts, identity)
                _verify_target(database, release, facts, identity)
                if capture_audit(session) != audit:
                    raise SchemaMismatch('Source audit changed')
                with session.database.transaction() as connection:
                    if source_facts(connection, core) != facts:
                        raise SchemaMismatch('Source changed after target validation')
                verify_registered_references(session, references)
                view.verify()
                report = _write_report(
                    session,
                    'upgrade-result.md',
                    [
                        '# WALL-E V2.1目标核验',
                        '',
                        '状态：VERIFIED_TARGET；仅离线目标核验通过，未切换服务，未新增模型准入。',
                        '',
                        f'- 升级标识：{identity}',
                        f'- 源完整行及历史摘要：{facts.sha256}',
                        f'- 源manifest：{source_manifest}',
                        f'- 目标manifest：{target_manifest}',
                        f'- 目标完整DDL摘要：{release.schema_contract_sha256}',
                        f'- 保留原表：{len(facts.retained.tables)}',
                        f'- 保留计数审计文件：{len(audit.files)}',
                        '- 原ID、类型及字节、全部JSON、历史、幂等回执和高水位逐表核验一致。',
                        '- 新formation业务表为空；源库全程只读；使用新库后的回退须另行保全新数据。',
                    ],
                )
                return UpgradeResult(
                    'VERIFIED_TARGET', identity, facts.sha256, target_manifest, report
                )
        except Exception as error:
            try:
                _write_report(
                    session,
                    'upgrade-failure.md',
                    [
                        '# WALL-E V2.1复制升级未完成',
                        '',
                        '状态：FAILED；源保持只读，目标及维护证据保留，未切换服务。不要重复执行DDL。',
                        '',
                        f'- 升级标识：{identity}',
                        f'- 源摘要：{facts.sha256 if facts is not None else "未建立"}',
                        f'- 诊断类别：{type(error).__name__}',
                        '- 使用inspect及原升级标识只读核实目标；不得覆盖或删除后重试。',
                    ],
                )
            except RuntimeError as report_error:
                error.add_note(
                    'Failure report could not be published: ' + type(report_error).__name__
                )
            except OSError as report_error:
                error.add_note(
                    'Failure report could not be published: ' + type(report_error).__name__
                )
            raise


def inspect_target(
    source,
    target,
    *,
    source_manifest,
    target_manifest,
    maintenance_window_confirmed,
    upgrade_id,
):
    """Observe an existing original target; never resume DDL or repair either copy."""
    source, target, release, core = _inputs(
        source,
        target,
        source_manifest,
        target_manifest,
        maintenance_window_confirmed,
    )
    identity = _uuid(upgrade_id)
    with FormationUpgradeSession(
        source, target.parent, core, maintenance_window_confirmed=True
    ) as session:
        with session.database.transaction() as connection:
            facts = source_facts(connection, core)
            verify_source_resources(connection)
        audit = capture_audit(session)
        references = capture_registered_references(session, audit, configuration_paths=())
        with (
            LocalPathGuard(target, directory=False) as guard,
            ProcessLock.for_database(target) as lock,
        ):
            database = FormationDatabase(target, formation_release=release, read_only=True)
            # A source-only copy has no marker. Report it without applying anything.
            connection = database._connect()
            try:
                connection.execute('BEGIN')
                present = connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name='formation_schema_state'"
                ).fetchone()
                if present is None:
                    observed = source_facts(connection, core)
                    if observed != facts:
                        raise SchemaMismatch(
                            'Incomplete target does not match the current original source'
                        )
                    status = 'COPIED_SOURCE_NOT_UPGRADED'
                else:
                    check_v21(connection, release)
                    status = 'VERIFIED_TARGET'
            finally:
                connection.rollback()
                connection.close()
            if status == 'VERIFIED_TARGET':
                _verify_target(database, release, facts, identity)
                view = TargetAuditView(session, database, guard, lock)
                if _audit_fingerprint(capture_audit(view)) != _audit_fingerprint(audit):
                    raise SchemaMismatch('Recovered target audit bytes differ')
            with session.database.transaction() as connection:
                if source_facts(connection, core) != facts:
                    raise SchemaMismatch('Source changed during inspection')
            verify_registered_references(session, references)
            report = _write_report(
                session,
                'upgrade-inspection-' + str(uuid4()) + '.md',
                [
                    '# WALL-E V2.1只读目标核实',
                    '',
                    f'状态：{status}；未重放DDL、未修改业务数据、未切换服务。',
                    '',
                    f'- 原升级标识：{identity}',
                    f'- 源摘要：{facts.sha256}',
                    f'- 目标manifest：{target_manifest}',
                ],
            )
            return UpgradeResult(status, identity, facts.sha256, target_manifest, report)
