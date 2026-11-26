"""Admitted Linux maintenance and read-only diagnostics."""

import json
import os
from contextlib import ExitStack

from .database import SchemaMismatch
from .environment_binding import EnvironmentBinding
from .environment_control import read_control
from .environment_files import EnvironmentFailure, digest, read_protected, require
from .environment_initialize import inspect_database, perform_initialization
from .environment_installation import CANDIDATE_PURPOSE, database_identity, load_installation
from .environment_lock import NativeEnvironmentFiles
from .schema_v22_release import load_release


def admission_inputs(args, active, program_sha, *, offline=False):
    installation = load_installation(
        args.anchor, args.anchor_sha256, active.runtime_manifest_sha256, args.project
    )
    require(
        digest(read_protected(args.project / 'program-snapshot.v1.json'))
        == program_sha
        == installation.description['program_source']['sha256'],
        'PROGRAM_SNAPSHOT_MISMATCH',
    )
    installation.check_hold(offline=offline)
    binding = installation.description.get('deployment_slot')
    if installation.description['purpose'] == CANDIDATE_PURPOSE:
        binding = installation.description['release_validation']
    if binding is not None:
        from backend.app.management.release_validation import verify_validation_frontend

        verify_validation_frontend(
            installation.path('frontend'),
            installation.project,
            binding,
        )
    try:
        release = load_release(
            installation.schema,
            installation.description['schema_manifest_sha256'],
            active.runtime_manifest_sha256,
            source_root=installation.project,
        )
    except (OSError, SchemaMismatch, ValueError) as error:
        raise EnvironmentFailure('SCHEMA_RELEASE_MISMATCH') from error
    return installation, release


def diagnose(native, installation, release):
    installation.check_identity(maintenance=False)
    with ExitStack() as resources:
        resources.enter_context(installation.lock(native))
        installation.check_hold(offline=True)
        for kind in ('runtime', 'log', 'temporary', 'frontend'):
            resources.enter_context(installation.directory(native, kind))
        control_fd = resources.enter_context(installation.directory(native, 'control'))
        control = read_control(control_fd, installation)
        require(control['admission'] == 'CLOSED', 'ENVIRONMENT_CONTROL_MISMATCH')
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
        installation, release = admission_inputs(
            args, active, program_sha, offline=args.action in ('diagnose', 'observe')
        )
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
            require(
                'recovery_replica' not in installation.description, 'RECOVERY_REPLICA_READ_ONLY'
            )
            require(
                'deployment_slot' not in installation.description,
                'INITIALIZATION_INTENT_MISMATCH',
            )
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
