"""Verify the review layout on an offline copy of an admitted Schema210 database."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import os

from .data_retention import capture_retained_data, original_projections, verify_retained_data
from .database import SchemaMismatch
from .formation_database import FormationDatabase, check_v21
from .formation_schema_release import load_release
from .review_schema import LEGACY_BUDGET_CHECK, REQUIREMENT_INDEX, load_review_release
from .schema_inspection import quote_identifier, verify_integrity


def _replace_task_table(connection):
    definitions = connection.execute(
        "SELECT type,name,sql FROM sqlite_schema WHERE tbl_name='code_tasks' AND sql IS NOT NULL ORDER BY type,name"
    ).fetchall()
    old = next(row['sql'] for row in definitions if row['type'] == 'table')
    header = 'CREATE TABLE "code_tasks"'
    if not old.startswith(header) or old.count(LEGACY_BUDGET_CHECK) != 1:
        raise SchemaMismatch('Code task table differs from the admitted layout')
    new_header = 'CREATE TABLE "review_code_tasks_copy"'
    connection.execute(old.replace(header, new_header, 1).replace(LEGACY_BUDGET_CHECK, ''))
    columns = ','.join(
        quote_identifier(row['name']) for row in connection.execute('PRAGMA table_info(code_tasks)')
    )
    connection.execute(
        f'INSERT INTO review_code_tasks_copy ({columns}) SELECT {columns} FROM code_tasks'
    )
    connection.execute('DROP TABLE code_tasks')
    connection.execute('ALTER TABLE review_code_tasks_copy RENAME TO code_tasks')
    for row in definitions:
        if row['type'] != 'table':
            connection.execute(row['sql'])


def _convert_copy(database, source_release, target_release, retained):
    with closing(database._connect()) as connection:
        connection.execute('PRAGMA foreign_keys=OFF')
        connection.execute('PRAGMA legacy_alter_table=ON')
        connection.execute('BEGIN IMMEDIATE')
        check_v21(connection, source_release)
        connection.execute('DROP INDEX ' + quote_identifier(REQUIREMENT_INDEX))
        _replace_task_table(connection)
        guard = 'formation_schema_state_update_guard'
        definition = connection.execute(
            'SELECT sql FROM sqlite_schema WHERE name=?', (guard,)
        ).fetchone()
        if definition is None:
            raise SchemaMismatch('Formation state guard is missing')
        connection.execute('DROP TRIGGER ' + quote_identifier(guard))
        connection.execute(
            'UPDATE formation_schema_state SET schema_contract_sha256=? WHERE singleton_id=1',
            (target_release.schema_contract_sha256,),
        )
        connection.execute(definition['sql'])
        origin = connection.execute('SELECT origin FROM formation_schema_state').fetchone()[0]
        if origin == 'FRESH_V21':
            connection.execute(
                'UPDATE schema_migrations SET checksum=? WHERE version=210',
                (target_release.fresh_checksum,),
            )
        check_v21(connection, target_release)
        verify_retained_data(connection, retained)
        verify_integrity(connection)
        connection.commit()


def copy_review_database(source_path: Path, target_path: Path) -> str:
    """Copy checked SQLite business rows into a new path. Caller owns the offline window."""
    source_path = Path(source_path).resolve(strict=True)
    target_path = Path(target_path).absolute()
    if target_path.exists() or target_path.is_symlink() or source_path == target_path:
        raise FileExistsError('A new review database path is required')
    if any(
        target_path.with_name(target_path.name + suffix).exists()
        for suffix in ('-wal', '-shm', '-journal')
    ):
        raise FileExistsError('The new database must have no prior SQLite sidecars')
    if not target_path.parent.is_dir():
        raise FileNotFoundError('The owner must prepare a separate target directory')
    source_release, target_release = load_release(), load_review_release()
    source = FormationDatabase(source_path, formation_release=source_release, read_only=True)
    with TemporaryDirectory(prefix='.review-db-copy-', dir=target_path.parent) as directory:
        staged = Path(directory) / 'review.sqlite'
        database = FormationDatabase(staged, formation_release=target_release)
        with source.transaction() as connection:
            verify_integrity(connection)
            projections = tuple(
                projection
                for projection in original_projections(connection)
                if projection.table not in ('schema_migrations', 'formation_schema_state')
            )
            retained = capture_retained_data(connection, projections)
            with closing(database._connect(create=True)) as destination:
                connection.backup(destination)
        _convert_copy(database, source_release, target_release, retained)
        with database.transaction() as connection:
            verify_retained_data(connection, retained)
        with staged.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.link(staged, target_path)
    return retained.sha256
