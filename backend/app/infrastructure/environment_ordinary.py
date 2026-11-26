"""Ordinary Linux database ownership and fail-closed recovery preconditions."""

from contextlib import closing

from .database import Database, StorageUnavailable
from .environment_binding import EnvironmentBinding, verify_binding
from .environment_files import EnvironmentFailure, identity, require
from .environment_initialize import (
    assert_database,
    database_has_sidecars,
    inspect_database,
    read_locked_database,
    verify_locked_binding,
)
from .environment_installation import database_identity

EXTERNAL_EFFECTS = (
    "SELECT 1 FROM llm_uses WHERE ended_at IS NULL OR transport_status IN ('SENDING','SENT','UNKNOWN')",
    "SELECT 1 FROM code_instances WHERE status <> 'STOPPED'",
    "SELECT 1 FROM code_sessions WHERE status <> 'RETIRED'",
    "SELECT 1 FROM code_commands WHERE status IN ('RUNNING','UNKNOWN')",
    "SELECT 1 FROM code_operations WHERE status IN ('RUNNING','UNKNOWN')",
    "SELECT 1 FROM code_operation_steps WHERE status IN ('RUNNING','UNKNOWN')",
    "SELECT 1 FROM code_workspaces WHERE status IN ('PREPARING','UNKNOWN')",
)


class OrdinaryDatabase(Database):
    """Use the existing transaction/authorizer/commit contract on a fixed target."""

    def __init__(self, installation, release, data_fd, process_lock):
        super().__init__(installation.database, schema_release=release)
        self.installation = installation
        self.environment_lock = process_lock
        self.data_fd = data_fd
        self.binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
        self.idempotency_generation = (
            installation.data_generation
            if getattr(installation, 'restore_generation_sha256', None) is not None
            else None
        )
        self.identity = database_identity(installation, data_fd)
        require(self.identity is not None, 'ENVIRONMENT_BINDING_MISMATCH')

    def initialize(self):
        raise StorageUnavailable('Ordinary service cannot initialize a database')

    def _initialize_locked(self):
        raise StorageUnavailable('Ordinary service cannot initialize a database')

    def _check_file(self):
        self.environment_lock.assert_owned()
        observed = self.installation.path('data').stat(follow_symlinks=False)
        require(
            identity(observed) == self.installation.roots['data'],
            'ENVIRONMENT_ROOT_IDENTITY_MISMATCH',
        )
        assert_database(self.installation, self.data_fd, self.identity)

    def _connect(self, *, create=False):
        if create:
            raise StorageUnavailable('Ordinary service cannot initialize a database')
        try:
            self._check_file()
            connection = super()._connect()
            try:
                self._check_file()
            except BaseException:
                connection.close()
                raise
        except (EnvironmentFailure, OSError) as error:
            raise StorageUnavailable('Environment database ownership changed') from error
        return connection

    def _check_schema(self, connection):
        verify_binding(connection, self.schema_release, self.binding)
        return 1

    def preflight(self):
        self.installation.check_hold()
        self._check_file()
        timestamp = inspect_database(
            self.installation, self.data_fd, self.identity, self.schema_release, self.binding
        )
        require(timestamp is not None, 'ENVIRONMENT_BINDING_MISMATCH')

    def check_recovery(self):
        self.installation.check_hold()
        self._check_file()
        with read_locked_database(self.path) as connection:
            verify_locked_binding(connection, self.path, self.schema_release, self.binding)
            check_external_effects(connection)
        self._check_file()

    def checkpoint_for_stop(self):
        self._check_file()
        if database_has_sidecars(self.path):
            with closing(self._connect()) as connection:
                connection.execute('BEGIN')
                self._check_schema(connection)
                connection.rollback()
                result = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
                require(tuple(result) == (0, 0, 0), 'ENVIRONMENT_STOP_UNVERIFIED')
        self._check_file()
        require(not database_has_sidecars(self.path), 'ENVIRONMENT_STOP_UNVERIFIED')


def check_external_effects(connection):
    for query in EXTERNAL_EFFECTS:
        if connection.execute(query).fetchone() is not None:
            raise EnvironmentFailure('EXTERNAL_RECOVERY_REQUIRED')
