"""Admitted Linux maintenance and read-only diagnostics."""

from contextlib import ExitStack
import json
import os

from .database import SchemaMismatch
from .environment_binding import EnvironmentBinding
from .environment_control import CONTROL_NAME, confirm_initial_control
from .environment_files import (
    EnvironmentFailure,
    decode,
    digest,
    read_entry,
    read_protected,
    require,
)
from .environment_initialize import inspect_database, perform_initialization
from .environment_installation import database_identity, load_installation, uuid_value
from .environment_lock import NativeEnvironmentFiles
from .schema_v22_release import load_release


def admission_inputs(args, active, program_sha):
    installation = load_installation(
        args.anchor, args.anchor_sha256, active.runtime_manifest_sha256, args.project
    )
    require(
        digest(read_protected(args.project / 'program-snapshot.v1.json'))
        == program_sha
        == installation.description['program_source']['sha256'],
        'PROGRAM_SNAPSHOT_MISMATCH',
    )
    installation.check_hold()
    try:
        release = load_release(
            installation.schema,
            installation.description['schema_manifest_sha256'],
            active.runtime_manifest_sha256,
        )
    except (OSError, SchemaMismatch, ValueError) as error:
        raise EnvironmentFailure('SCHEMA_RELEASE_MISMATCH') from error
    return installation, release


def read_initial_operation(control_fd, installation):
    raw = read_entry(
        control_fd, CONTROL_NAME, owner=installation.maintenance_uid, group=installation.group
    )
    control = decode(raw, 'ENVIRONMENT_CONTROL_MISMATCH')
    operation = control.get('operation_id')
    require(
        uuid_value(operation)
        and confirm_initial_control(control_fd, installation, operation, create=False),
        'ENVIRONMENT_CONTROL_MISMATCH',
    )
    return operation


def diagnose(native, installation, release):
    installation.check_identity(maintenance=False)
    with ExitStack() as resources:
        resources.enter_context(installation.lock(native))
        installation.check_hold()
        for kind in ('runtime', 'log', 'temporary', 'frontend'):
            resources.enter_context(installation.directory(native, kind))
        control_fd = resources.enter_context(installation.directory(native, 'control'))
        read_initial_operation(control_fd, installation)
        data_fd = resources.enter_context(installation.directory(native, 'data'))
        file_identity = database_identity(installation, data_fd)
        require(file_identity is not None, 'ENVIRONMENT_BINDING_MISMATCH')
        binding = EnvironmentBinding(installation.environment_id, installation.data_generation)
        timestamp = inspect_database(installation, data_fd, file_identity, release, binding)
        require(timestamp is not None, 'ENVIRONMENT_BINDING_MISMATCH')
        return {
            'status': 'DATABASE_READY',
            'admission': 'CLOSED',
            'environment_id': installation.environment_id,
            'data_generation': installation.data_generation,
            'initialized_at': timestamp,
        }


def run_command(args, active, program_sha):
    os.umask(0o007)
    try:
        installation, release = admission_inputs(args, active, program_sha)
        native = NativeEnvironmentFiles(args.root)
        if args.action in ('diagnose', 'observe'):
            require(
                args.operation_id is None and args.intent_sha256 is None,
                'INITIALIZATION_INTENT_MISMATCH',
            )
            if args.action == 'diagnose':
                result = diagnose(native, installation, release)
            else:
                installation.check_identity(maintenance=True)
                pid = installation.lock(native).observer_pid()
                result = {'status': 'LOCK_OBSERVED', 'pid': pid}
        else:
            result = perform_initialization(
                native, installation, release, args.action, args.operation_id, args.intent_sha256
            )
    except EnvironmentFailure as error:
        status = 'PENDING_RECONCILIATION' if error.uncertain else 'BLOCKED'
        result = {'status': status, 'reason_code': error.code}
    except SchemaMismatch:
        result = {'status': 'BLOCKED', 'reason_code': 'ENVIRONMENT_BINDING_MISMATCH'}
    except (OSError, ValueError, KeyError, TypeError):
        result = {'status': 'BLOCKED', 'reason_code': 'ENVIRONMENT_INSTALLATION_UNVERIFIED'}
    print(json.dumps(result, sort_keys=True))
    if result['status'] == 'PENDING_RECONCILIATION':
        return 3
    return 2 if result['status'] == 'BLOCKED' else 0
