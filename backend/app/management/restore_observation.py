"""Read the actual stopped source needed to register a managed restore plan."""

import os
from types import SimpleNamespace
from uuid import uuid4

from backend.app.infrastructure.environment_command import admission_inputs
from backend.app.infrastructure.environment_files import canonical, digest, require
from backend.app.infrastructure.environment_installation import WORKSPACE_PURPOSES, uuid_value
from backend.app.infrastructure.environment_lock import NativeEnvironmentFiles

from .attachment_observation import (
    FRESH_MS,
    candidate_environment,
    machine_clock,
    now,
    publish_observation,
)
from .operation_contract import DENIED, INVALID, RESOURCE
from .release_observation import stopped_source

SOURCE = 'restore-source-'


def capture_restore_source(catalog, args, entry):
    require(os.geteuid() == 0, DENIED)
    reference = args.candidate_ref
    require(uuid_value(reference), INVALID)
    pin = catalog.installed_candidate_pin(reference)
    candidate = catalog.candidate(reference, pin)
    source = candidate_environment(candidate, args.sha256)
    program = entry['verify_program'](source.project)
    measured, _ = admission_inputs(
        SimpleNamespace(
            anchor=source.anchor, anchor_sha256=source.anchor_sha256, project=source.project
        ),
        SimpleNamespace(runtime_manifest_sha256=args.sha256),
        program,
    )
    require(
        measured == source
        and source.description['purpose'] in WORKSPACE_PURPOSES
        and 'recovery_replica' not in source.description,
        RESOURCE,
    )
    boot, started = machine_clock()
    observed = stopped_source(NativeEnvironmentFiles(args.root), source)
    ended_boot, ended = machine_clock()
    require(ended_boot == boot and 0 <= ended - started <= FRESH_MS, RESOURCE)
    database = observed.pop('database_identity')
    proof = {
        'format_version': 1,
        'status': 'RESTORE_SOURCE_STOPPED_VERIFIED',
        **catalog.scope,
        'environment_id': source.environment_id,
        'source_attachment': {'candidate_ref': reference, 'sha256': pin},
        'proof_id': str(uuid4()),
        'boot_id': boot,
        'observed_at': now(),
        'observed_monotonic_ms': ended,
        'source': {
            **observed,
            'database_identity_sha256': digest(canonical(database)),
        },
    }
    publish_observation(catalog, SOURCE + reference, proof)
    return {
        key: proof[key]
        for key in (
            'status',
            'environment_id',
            'source_attachment',
            'proof_id',
            'observed_at',
            'source',
        )
    }
