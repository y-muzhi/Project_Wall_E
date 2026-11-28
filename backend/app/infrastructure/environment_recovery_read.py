"""Admit a fixed recovery replica under a closed, outbound-held installation."""

import os
import stat
from hashlib import sha256

from backend.app.management.attachment_observation import now
from backend.app.management.release_artifacts import indexed_files, snapshot_file

from .database import Database, StorageUnavailable
from .environment_binding import EnvironmentBinding, verify_snapshot_binding
from .environment_control import read_control, stopped_for_policy
from .environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    decode,
    digest,
    exact,
    identity,
    no_acl,
    read_protected,
    require,
)
from .environment_installation import (
    ACCESS_NAME,
    CONFIG_NAME,
    RECOVERY_EVIDENCE,
    RECOVERY_FRONTEND_INDEX,
    identity_record,
    sha_value,
    uuid_value,
)
from .environment_restore import DOCUMENT_AI, RECEIPT, reopen_archive, restoration_status
from .schema_v22_release import DocumentAiSchemaRelease

POLICY = 'recovery-read-policy.v1.json'
INVALID = 'RECOVERY_READ_INTENT_MISMATCH'
UNVERIFIED = 'RECOVERY_READ_UNVERIFIED'
SCOPES = ('DOCUMENT_CONTENT', 'DOCUMENT_HISTORY')
TUPLE_FIELDS = ('environment_id', 'data_generation', 'deployment_id', 'configuration_sha256')


def protected_receipt(ref):
    exact(ref, ('path', 'sha256'), INVALID)
    path = absolute(ref['path'], INVALID)
    require(path.name == RECEIPT and sha_value(ref['sha256']), INVALID)
    raw = read_protected(path)
    require(digest(raw) == ref['sha256'], UNVERIFIED)
    return raw


def read_policy(path, expected):
    require(path.is_absolute() and path.name == POLICY and sha_value(expected), INVALID)
    raw = read_protected(path)
    require(digest(raw) == expected, INVALID)
    result = exact(
        decode(raw, INVALID),
        (
            'format_version',
            'operation_id',
            'run_id',
            *TUPLE_FIELDS,
            'installation_sha256',
            'control_revision',
            'control_sha256',
            'database',
            'verified_scopes',
            'rehearsal_receipt',
        ),
        INVALID,
    )
    require(
        type(result['format_version']) is int
        and result['format_version'] == 1
        and all(
            uuid_value(result[key])
            for key in (
                'operation_id',
                'run_id',
                'environment_id',
                'data_generation',
                'deployment_id',
            )
        )
        and all(
            sha_value(result[key])
            for key in ('configuration_sha256', 'installation_sha256', 'control_sha256')
        )
        and type(result['control_revision']) is int
        and result['control_revision'] > 0
        and result['verified_scopes'] == list(SCOPES),
        INVALID,
    )
    database = exact(result['database'], ('identity', 'bytes', 'sha256'), INVALID)
    identity_record(database['identity'], INVALID)
    require(
        type(database['bytes']) is int
        and 0 < database['bytes'] <= 1024**4
        and sha_value(database['sha256']),
        INVALID,
    )
    return result


def file_signature(facts):
    return (identity(facts), facts.st_size, facts.st_ctime_ns, facts.st_mtime_ns)


class RecoveryDatabase(Database):
    def __init__(self, scope, release):
        self.scope = scope
        self.binding = EnvironmentBinding(
            scope.installation.environment_id, scope.installation.data_generation
        )
        super().__init__(scope.installation.database, schema_release=release, read_only=True)

    def _connection_uri(self, *, create):
        return super()._connection_uri(create=create) + '&immutable=1'

    def _connect(self, *, create=False):
        try:
            self.scope.check_current()
            connection = super()._connect(create=create)
            try:
                self.scope.check_current()
            except BaseException:
                connection.close()
                raise
        except (EnvironmentFailure, OSError, ValueError, TypeError, KeyError) as error:
            raise StorageUnavailable('Recovery data authorization changed') from error
        return connection

    def _check_schema(self, connection):
        verify_snapshot_binding(connection, self.schema_release, self.binding)
        return 1


class ClosedReadScope:
    """Read a locked, sidecar-free snapshot under a pinned closed selection."""

    offline_host_check = False

    def __init__(self, installation, native, release, resources, path, expected, plan):
        self.installation = installation
        self.policy_path = path
        self.policy_sha256 = expected
        self.plan = plan
        self.lock = resources.enter_context(installation.lock(native))
        self.control_fd = resources.enter_context(installation.directory(native, 'control'))
        self.data_fd = resources.enter_context(installation.directory(native, 'data'))
        for kind in ('runtime', 'log', 'temporary', 'frontend'):
            resources.enter_context(installation.directory(native, kind))
        self.release = release
        self.run_id = self.plan['run_id']
        self.database = RecoveryDatabase(self, release)
        self.control = self.check_control()
        self.database_signature = None
        self.observed_at = None
        self.active = False

    def check_installation(self):
        installation = self.installation
        self.lock.assert_owned()
        installation.check_hold(offline=self.offline_host_check)
        for path, expected in (
            (installation.anchor, installation.anchor_sha256),
            (installation.anchor.parent / CONFIG_NAME, installation.configuration_sha256),
            (
                installation.anchor.parent / ACCESS_NAME,
                installation.description['access_policy_ref']['sha256'],
            ),
            (self.policy_path, self.policy_sha256),
        ):
            require(digest(read_protected(path)) == expected, UNVERIFIED)
        require(self.check_control() == self.control, UNVERIFIED)

    def snapshot_signature(self, *, verify_header=False, verify_payload=None):
        installation = self.installation
        observed = installation.path('data').stat(follow_symlinks=False)
        require(identity(observed) == installation.roots['data'], UNVERIFIED)
        name = str(installation.database_relative)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        descriptor = os.open(name, flags, dir_fd=self.data_fd)
        with os.fdopen(descriptor, 'rb') as stream:
            facts = os.fstat(stream.fileno())
            self.check_database_file(facts)
            no_acl(stream.fileno())
            signature = file_signature(facts)
            if verify_header or verify_payload is not None:
                header = stream.read(20)
                require(
                    header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x02\x02',
                    UNVERIFIED,
                )
                if verify_payload is not None:
                    verify_payload(stream, header, facts)
            require(file_signature(os.fstat(stream.fileno())) == signature, UNVERIFIED)
        at_path = os.stat(name, dir_fd=self.data_fd, follow_symlinks=False)
        require(file_signature(at_path) == signature, UNVERIFIED)
        for suffix in ('-wal', '-shm', '-journal'):
            try:
                os.stat(name + suffix, dir_fd=self.data_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise EnvironmentFailure(UNVERIFIED)
        return signature

    def check_current(self):
        self.check_installation()
        require(self.active and self.snapshot_signature() == self.database_signature, UNVERIFIED)

    def drain(self):
        self.active = False


class RecoveryScope(ClosedReadScope):
    def __init__(self, installation, native, release, resources, operation, path, expected):
        installation.check_identity(maintenance=False)
        plan = read_policy(path, expected)
        require(
            operation == plan['operation_id']
            and plan['installation_sha256'] == installation.anchor_sha256
            and all(plan[key] == getattr(installation, key) for key in TUPLE_FIELDS),
            INVALID,
        )
        self.replica = installation.description.get('recovery_replica')
        if self.replica is not None:
            evidence = installation.anchor.parent / RECOVERY_EVIDENCE
            require(
                path == evidence / POLICY
                and plan['operation_id'] == self.replica['operation_id']
                and plan['run_id'] == self.replica['run_id']
                and plan['rehearsal_receipt']
                == {
                    'path': str(evidence / RECEIPT),
                    'sha256': self.replica['rehearsal_receipt_sha256'],
                },
                INVALID,
            )
        super().__init__(installation, native, release, resources, path, expected, plan)

    def check_control(self):
        control = read_control(self.control_fd, self.installation)
        reference = {
            'operation_id': self.plan['operation_id'],
            'plan_sha256': control['plan_sha256'],
        }
        require(
            stopped_for_policy(self.control_fd, control, reference)
            and control['outbound_hold'] is True
            and control['control_revision'] == self.plan['control_revision']
            and digest(canonical(control)) == self.plan['control_sha256']
            and all(control[key] == self.plan[key] for key in TUPLE_FIELDS)
            and control['data_root_ref'] == str(self.installation.path('data')),
            UNVERIFIED,
        )
        return control

    def check_installation(self):
        super().check_installation()
        protected_receipt(self.plan['rehearsal_receipt'])

    def check_database_file(self, facts):
        pinned = self.plan['database']
        require(
            stat.S_ISREG(facts.st_mode)
            and (facts.st_uid, facts.st_gid, facts.st_nlink, stat.S_IMODE(facts.st_mode))
            == (0, self.installation.group, 1, 0o440)
            and identity(facts) == pinned['identity']
            and facts.st_size == pinned['bytes'],
            UNVERIFIED,
        )

    def verify_database_bytes(self, stream, header, facts):
        pinned = self.plan['database']
        measured = sha256(header)
        size = len(header)
        while block := stream.read(128 * 1024):
            size += len(block)
            require(size <= facts.st_size, UNVERIFIED)
            measured.update(block)
        require(size == pinned['bytes'] and measured.hexdigest() == pinned['sha256'], UNVERIFIED)

    def start(self):
        self.check_installation()
        if self.replica is not None:
            evidence = self.installation.anchor.parent / RECOVERY_EVIDENCE
            fingerprint, raw = snapshot_file(
                evidence / RECOVERY_FRONTEND_INDEX, 0o444, capture=True
            )
            require(fingerprint == self.replica['frontend_index_sha256'], UNVERIFIED)
            indexed_files(decode(raw, UNVERIFIED), self.installation.path('frontend'), 'frontend')
        self.database_signature = self.snapshot_signature(verify_payload=self.verify_database_bytes)
        receipt = decode(protected_receipt(self.plan['rehearsal_receipt']), UNVERIFIED)
        artifact = receipt['database_artifact']
        document_ai = DOCUMENT_AI in receipt
        if document_ai:
            require(
                self.replica is not None
                and self.installation.description['purpose'] == 'DEVELOPMENT'
                and isinstance(self.release, DocumentAiSchemaRelease)
                and receipt[DOCUMENT_AI]
                == {
                    'directory': str(self.installation.schema),
                    'contract_sha256': self.release.schema_contract_sha256,
                    'manifest_sha256': self.release.manifest_sha256,
                    'program': str(self.installation.project),
                    'program_sha256': self.installation.description['program_source']['sha256'],
                },
                UNVERIFIED,
            )
        require(
            type(receipt['format_version']) is int
            and receipt['format_version'] == 2
            and receipt['status'] == restoration_status(2, document_ai=document_ai)
            and receipt['source_environment_id'] == self.installation.environment_id
            and receipt['target_data_generation'] == self.installation.data_generation
            and receipt['source_data_generation'] != self.installation.data_generation
            and receipt['outbound_hold_required'] is True
            and sha_value(receipt['backup_manifest_sha256'])
            and (
                self.replica is None
                or self.replica['backup_manifest_sha256'] == receipt['backup_manifest_sha256']
            )
            and sha_value(receipt['rehearsal_policy_sha256'])
            and sha_value(receipt['restored_asset_index']['sha256'])
            and all(artifact[key] == self.plan['database'][key] for key in ('sha256', 'bytes')),
            UNVERIFIED,
        )
        initialized, contents = reopen_archive(
            self.installation.database, self.release, self.database.binding
        )
        require(
            initialized == receipt['initialized_at']
            and contents.sha256 == receipt['content_sha256']
            and self.snapshot_signature() == self.database_signature,
            UNVERIFIED,
        )
        self.check_installation()
        self.observed_at = now()
        self.active = True
