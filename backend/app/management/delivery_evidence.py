"""Read fixed Git, resource and independent check evidence for delivery."""

import os
from uuid import uuid4

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    absolute,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .attachment_observation import (
    machine_clock,
    now,
    observation_path,
    publish_observation,
    require_fresh,
    verified_workspace,
)
from .operation_contract import (
    DENIED,
    RESOURCE,
    commit,
    delivery_intent,
    installed_record,
    operation_request,
)
from .registry import is_timestamp
from .release_artifacts import snapshot_file


def request_commits(intent):
    return {
        intent['environment_id']: intent['commit'],
        **dict(
            zip(
                intent.get('source_environment_ids', ()),
                intent.get('source_commits', ()),
                strict=True,
            )
        ),
    }


def capture_delivery(catalog, request, args):
    require(os.geteuid() == 0, RESOURCE)
    principal, key, raw = operation_request(request, catalog)
    require(principal.role in ('DEVELOPER', 'MANAGER'), DENIED)
    intent = delivery_intent(raw)
    reference, expected = args.workspace_ref, args.workspace_sha256
    require(uuid_value(reference) and sha_value(expected), RESOURCE)
    workspace = catalog.directory / 'workspaces' / (reference + '.json')
    area = catalog.directory / 'observations'
    policy, git = verified_workspace((workspace, expected), args, area)
    requested = request_commits(intent)
    configured = {row['environment_id']: row for row in policy['worktrees']}
    observed = {}
    for row in git['worktrees']:
        environment = row['environment_id']
        if environment not in requested:
            continue
        require(row['commit'] == requested[environment], RESOURCE)
        pinned = configured[environment]
        observed[environment] = {
            'purpose': row['purpose'],
            'branch': row['branch'],
            'commit': row['commit'],
            'tree': row['tree'],
            'head': row['head'],
            'worktree_locator': absolute(pinned['path'], RESOURCE).as_posix().removeprefix('/'),
            'worktree_identity': pinned['identity'],
        }
    require(set(observed) == set(requested), RESOURCE)
    boot, at = machine_clock()
    proof = {
        'format_version': 1,
        **catalog.scope,
        'proof_id': str(uuid4()),
        'request_key': key,
        'principal': principal.id,
        'intent_sha256': digest(canonical(intent)),
        'boot_id': boot,
        'observed_monotonic_ms': at,
        'observed_at': now(),
        'repository_ref': git['repository_ref'],
        'workspace_ref': reference,
        'workspace_evidence_sha256': git['evidence_sha256'],
        'commits': observed,
    }
    publish_observation(catalog, 'delivery-' + key, proof)
    return {name: proof[name] for name in ('proof_id', 'request_key', 'observed_at')}


def artifact(value):
    exact(value, ('path', 'sha256', 'bytes'), RESOURCE)
    expected, size = value['sha256'], value['bytes']
    require(sha_value(expected) and type(size) is int and size >= 0, RESOURCE)
    actual, _ = snapshot_file(absolute(value['path'], RESOURCE), 0o444, size)
    require(actual == expected, RESOURCE)
    return {'sha256': actual, 'bytes': size}


def admitted_reference(catalog, reference, proof, subject, *, check):
    registry = catalog.checks if check else catalog.resources
    folder = 'checks' if check else 'resources'
    try:
        require(reference in registry, RESOURCE)
        record = installed_record(
            catalog.directory / folder / (reference + '.json'), registry[reference]
        )
        fields = ('format_version', *catalog.scope, 'reference', 'repository_ref', 'artifact')
        if check:
            fields += ('commit', 'tree', 'checked_at', 'result')
        exact(record, fields, RESOURCE)
        require(
            type(record['format_version']) is int
            and record['format_version'] == 1
            and all(record[key] == value for key, value in catalog.scope.items())
            and record['reference'] == reference
            and record['repository_ref'] == proof['repository_ref'],
            RESOURCE,
        )
        if check:
            require(
                record['commit'] == subject['commit']
                and record['tree'] == subject['tree']
                and is_timestamp(record['checked_at'])
                and record['result'] in ('PASSED', 'FAILED', 'INCONCLUSIVE'),
                RESOURCE,
            )
        result = {'ref': reference, **artifact(record['artifact'])}
        if check:
            result.update(result=record['result'], checked_at=record['checked_at'])
        return result
    except (EnvironmentFailure, OSError, TypeError, ValueError) as error:
        raise EnvironmentFailure(RESOURCE) from error


def prepare_delivery(catalog, principal, key, intent):
    try:
        proof = installed_record(observation_path(catalog, 'delivery-' + key))
        exact(
            proof,
            (
                'format_version',
                *catalog.scope,
                'proof_id',
                'request_key',
                'principal',
                'intent_sha256',
                'boot_id',
                'observed_monotonic_ms',
                'observed_at',
                'repository_ref',
                'workspace_ref',
                'workspace_evidence_sha256',
                'commits',
            ),
            RESOURCE,
        )
        require(
            type(proof['format_version']) is int
            and proof['format_version'] == 1
            and all(proof[key] == value for key, value in catalog.scope.items())
            and proof['request_key'] == key
            and proof['principal'] == principal.id
            and proof['intent_sha256'] == digest(canonical(intent))
            and uuid_value(proof['repository_ref'])
            and sha_value(proof['workspace_evidence_sha256'])
            and is_timestamp(proof['observed_at']),
            RESOURCE,
        )
        require_fresh(proof)
        requested = request_commits(intent)
        exact(proof['commits'], requested, RESOURCE)
        for environment, oid in requested.items():
            observed = exact(
                proof['commits'][environment],
                (
                    'purpose',
                    'branch',
                    'commit',
                    'tree',
                    'head',
                    'worktree_locator',
                    'worktree_identity',
                ),
                RESOURCE,
            )
            require(
                observed['commit'] == oid and len(commit(observed['tree'])) == len(oid), RESOURCE
            )
        subject = proof['commits'][intent['environment_id']]
        resources = [
            admitted_reference(catalog, ref, proof, subject, check=False)
            for ref in intent['resource_refs']
        ]
        checks = [
            admitted_reference(catalog, ref, proof, subject, check=True)
            for ref in intent['check_refs']
        ]
        return proof, resources, checks
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EnvironmentFailure(RESOURCE) from error
