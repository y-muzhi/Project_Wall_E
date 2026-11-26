"""Bind a release's original registry operation to an actual stopped maintenance window."""

import fcntl
import os
from contextlib import contextmanager
from dataclasses import dataclass

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    check_ext4,
    decode,
    digest,
    exact,
    persisted_write,
    protected_directory,
    read_entry,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value
from backend.app.infrastructure.environment_maintenance import ACTIVE
from backend.app.infrastructure.environment_maintenance import POLICY as MAINTENANCE_POLICY

from .attachment_observation import invoke_observer
from .operation_contract import (
    DENIED,
    INVALID,
    RECONFIGURE,
    RELEASE_ACTIONS,
    RESOURCE,
    ROLLBACK_CODE,
    UNAVAILABLE,
    VERSION,
)
from .operation_store import decoded, mutation, stored
from .release_configuration import CHANGED, ReleaseConfiguration, read_configuration
from .release_observation import ReleasePair, admitted_pair, deployment_subject
from .release_operations import STEP, confirmed_preview, raw_plan, row_for_release

EXECUTIONS = 'release-executions'
HOLD_RECEIPT = 'maintenance-closed.v1.json'
RETIREMENT_INTENT = 'release-retirement-intent.v1.json'
RETIREMENT = 'release-retired.v1.json'
HOLD_EXECUTOR = 'NATIVE_RELEASE_MAINTENANCE'
SOURCE_KEYS = ('environment_id', 'data_generation', 'deployment_id')


@dataclass(frozen=True)
class AdmittedRelease:
    grant: dict
    configuration: ReleaseConfiguration
    pair: ReleasePair


def operation_record(connection, catalog, operation_id, *, action=RELEASE_ACTIONS, kind=STEP):
    require(uuid_value(operation_id), INVALID)
    row = connection.execute(
        'SELECT * FROM management_operations WHERE operation_id=? AND registry_generation=?',
        (operation_id, catalog.scope['registry_generation']),
    ).fetchone()
    allowed = (action,) if isinstance(action, str) else action
    require(row is not None and row['action'] in allowed, RESOURCE)
    step = connection.execute(
        'SELECT * FROM management_steps WHERE operation_id=? AND ordinal=1 AND step_kind=?',
        (operation_id, kind),
    ).fetchone()
    require(step is not None, RESOURCE)
    return row, step


def grant_subject(preview, operation, catalog):
    fields = (
        'plan_id',
        'environment_id',
        'configuration_ref',
        'configuration_record_sha256',
        'release_manifest_sha256',
        'release_candidate_sha256',
        'schema_contract_sha256',
        'compatibility_sha256',
        'recovery_policy_sha256',
        'recovery_requirement',
        'source_attachment',
        'target_attachment',
        'source_database_identity_sha256',
        'source',
        'target',
    )
    grant = {
        'format_version': 1,
        **catalog.scope,
        'operation_id': operation['operation_id'],
        'plan_sha256': decoded(operation['intent_json'])['plan_sha256'],
        **{key: preview[key] for key in fields},
    }
    if operation['action'] == ROLLBACK_CODE:
        return {
            **grant,
            'release_ref': preview['retained_release_ref'],
            'rollback_source_sha256': preview['rollback_source_sha256'],
            'repair_of_operation_id': preview['repair_of_operation_id'],
        }
    if operation['action'] == RECONFIGURE:
        return {
            **grant,
            'release_ref': preview['fixed_release_ref'],
            'target_access_sha256': preview['target_access_sha256'],
        }
    return {**grant, 'release_ref': preview['release_ref']}


def retained_binding(configuration, grant):
    target = configuration.target_access_sha256
    if target is None:
        if 'target_access_sha256' in grant:
            return False
    elif grant.get('target_access_sha256') != target:
        return False
    if configuration.rollback_source is None:
        return 'rollback_source_sha256' not in grant
    return grant.get('rollback_source_sha256') == digest(canonical(configuration.rollback_source))


def claim_release_maintenance(connection, lock, catalog, request):
    require(type(request) is dict, INVALID)
    fields = ('operation_id', 'read_retired') if 'read_retired' in request else ('operation_id',)
    exact(request, fields, INVALID)
    require('read_retired' not in request or request['read_retired'] is True, INVALID)
    read_retired = 'read_retired' in request
    with mutation(connection, lock):
        operation, step = operation_record(connection, catalog, request['operation_id'])
        principal = catalog.access(operation['principal'])
        require(principal.role == 'MANAGER', DENIED)
        intent = decoded(operation['intent_json'])
        plan = raw_plan(connection, intent['plan_id'])
        preview = confirmed_preview(plan, principal.id, intent)
        require(plan['execution_operation_id'] == operation['operation_id'], CHANGED)
        grant = grant_subject(preview, operation, catalog)
        if step['external_identity_json'] is not None:
            external = decoded(step['external_identity_json'])
            continuing = (
                operation['status'] in ('RUNNING', 'UNKNOWN', 'SUCCEEDED')
                and not operation['cancel_requested']
            )
            retired = (
                read_retired
                and operation['status'] == 'CANCELLED'
                and operation['cancel_requested']
                and step['status'] == 'SKIPPED'
                and sha_value(external.get('retirement_sha256'))
            )
            require(
                (continuing or retired)
                and (not read_retired or operation['status'] in ('RUNNING', 'CANCELLED'))
                and external.get('maintenance') == grant,
                RESOURCE,
            )
            return grant
        require(not read_retired, RESOURCE)
        row_for_release(connection, principal, intent)
        require(
            operation['status'] == 'ACCEPTED'
            and step['status'] == 'PLANNED'
            and operation['revision'] < MAX_REVISION
            and not operation['cancel_requested'],
            UNAVAILABLE,
        )
        config = read_configuration(catalog, intent['configuration_ref'])
        require(
            config.sha256 == grant['configuration_record_sha256']
            and config.action == operation['action']
            and retained_binding(config, grant)
            and config.source_reference == grant['source_attachment']
            and config.target_reference == grant['target_attachment']
            and config.manifest_reference['sha256'] == grant['release_manifest_sha256']
            and config.candidate_sha256 == grant['release_candidate_sha256'],
            CHANGED,
        )
        advanced = connection.execute(
            "UPDATE management_operations SET status='RUNNING', revision=revision+1 "
            "WHERE operation_id=? AND status='ACCEPTED' AND revision=?",
            (operation['operation_id'], operation['revision']),
        )
        registered = connection.execute(
            "UPDATE management_steps SET status='DISPATCHING', executor_ref=?, external_identity_json=? "
            "WHERE operation_id=? AND ordinal=1 AND status='PLANNED'",
            (HOLD_EXECUTOR, stored({'maintenance': grant}), operation['operation_id']),
        )
        require(advanced.rowcount == registered.rowcount == 1, VERSION)
        return grant


@contextmanager
def execution_directory(catalog, area, operation, *, create=False):
    require(uuid_value(operation), INVALID)
    base = catalog.directory / area
    if create:
        with protected_directory(catalog.directory) as fd:
            if not os.path.lexists(base):
                try:
                    base.mkdir(mode=0o755)
                    base.chmod(0o755)
                except FileExistsError:
                    pass
                os.fsync(fd)
    with protected_directory(base) as parent:
        check_ext4(parent)
        root = base / operation
        if create and not os.path.lexists(root):
            try:
                root.mkdir(mode=0o755)
                root.chmod(0o755)
            except FileExistsError:
                pass
            os.fsync(parent)
        with protected_directory(root) as fd:
            check_ext4(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield root, fd


def release_execution(catalog, operation, *, create=False):
    return execution_directory(catalog, EXECUTIONS, operation, create=create)


def optional_fact(fd, name):
    try:
        raw = read_entry(fd, name, owner=0, reject_writers=0o222)
    except FileNotFoundError:
        return None
    return decode(raw, RESOURCE)


def write_fact(fd, name, value):
    raw = canonical(value)
    existing = optional_fact(fd, name)
    if existing is None:
        persisted_write(fd, name, raw, mode=0o444)
        existing = optional_fact(fd, name)
    require(canonical(existing) == raw, RESOURCE)
    os.fsync(fd)
    return digest(raw)


def manager_command(action, args, launcher):
    return [
        launcher,
        action,
        '--root',
        args.root,
        '--sha256',
        args.sha256,
        '--project',
        args.project,
        '--program-sha256',
        args.program_sha256,
        '--runtime-entry',
        args.runtime_entry,
        '--anchor',
        args.anchor,
        '--anchor-sha256',
        args.anchor_sha256,
        '--catalog',
        args.catalog,
        '--catalog-sha256',
        args.catalog_sha256,
    ]


def maintenance_policy(grant, environment):
    return {
        'format_version': 1,
        'operation_id': grant['operation_id'],
        **{key: getattr(environment, key) for key in SOURCE_KEYS},
        'installation_sha256': environment.anchor_sha256,
        'program': str(environment.project),
        'program_sha256': environment.description['program_source']['sha256'],
        'expected_control_revision': grant['source']['control_revision'],
        'expected_control_sha256': grant['source']['control_sha256'],
        'expected_database_identity_sha256': grant['source_database_identity_sha256'],
    }


def maintenance_result(facts, grant, policy, policy_sha):
    exact(
        facts, ('status', 'operation_id', *SOURCE_KEYS, 'plan_sha256', 'control_revision'), RESOURCE
    )
    require(
        facts['status'] == ACTIVE
        and facts['operation_id'] == grant['operation_id']
        and all(facts[key] == policy[key] for key in SOURCE_KEYS)
        and facts['plan_sha256'] == policy_sha
        and facts['control_revision'] == policy['expected_control_revision'] + 1,
        RESOURCE,
    )
    return {
        'format_version': 1,
        'status': 'MANAGED_RELEASE_MAINTENANCE_CLOSED',
        'operation_id': grant['operation_id'],
        'plan_sha256': grant['plan_sha256'],
        'grant_sha256': digest(canonical(grant)),
        'maintenance_policy_sha256': policy_sha,
        **{key: facts[key] for key in SOURCE_KEYS},
        'control_revision': facts['control_revision'],
    }


def admitted_release(catalog, registry, args, entry, launcher, *, read_retired=False):
    operation = args.release_operation_id
    grant = invoke_observer(
        registry.uid,
        registry.gid,
        manager_command('_claim-release-maintenance', args, launcher),
        catalog.directory / 'observations',
        input_bytes=canonical(
            {'operation_id': operation, **({'read_retired': True} if read_retired else {})}
        ),
    )
    require(
        grant['operation_id'] == operation
        and all(grant[key] == value for key, value in catalog.scope.items())
        and sha_value(grant['source_database_identity_sha256']),
        RESOURCE,
    )
    registered = read_configuration(catalog, grant['configuration_ref'])
    require(
        registered.sha256 == grant['configuration_record_sha256']
        and retained_binding(registered, grant)
        and registered.source_reference == grant['source_attachment']
        and registered.target_reference == grant['target_attachment']
        and registered.manifest_reference['sha256'] == grant['release_manifest_sha256'],
        CHANGED,
    )
    pair = admitted_pair(registered, args.sha256, entry)
    require(
        all(grant['source'][key] == value for key, value in deployment_subject(pair.source).items())
        and grant['target'] == deployment_subject(pair.target),
        CHANGED,
    )
    return AdmittedRelease(grant, registered, pair)


def known_maintenance(fd, admitted):
    known = optional_fact(fd, HOLD_RECEIPT)
    if known is None:
        return None
    expected = maintenance_policy(admitted.grant, admitted.pair.source)
    pin = digest(canonical(expected))
    policy = optional_fact(fd, MAINTENANCE_POLICY)
    require(canonical(policy) == canonical(expected), RESOURCE)
    facts = {
        'status': ACTIVE,
        'operation_id': admitted.grant['operation_id'],
        **{key: known[key] for key in SOURCE_KEYS},
        'control_revision': known['control_revision'],
        'plan_sha256': known['maintenance_policy_sha256'],
    }
    require(
        canonical(known) == canonical(maintenance_result(facts, admitted.grant, expected, pin)),
        RESOURCE,
    )
    return known


def environment_command(action, args, launcher, installation, *arguments):
    return [
        launcher,
        action,
        '--root',
        args.root,
        '--sha256',
        args.sha256,
        '--runtime-entry',
        args.runtime_entry,
        '--project',
        installation.project,
        '--program-sha256',
        installation.description['program_source']['sha256'],
        '--anchor',
        installation.anchor,
        '--anchor-sha256',
        installation.anchor_sha256,
        *arguments,
    ]


def enter_release_maintenance(catalog, registry, args, entry, launcher):
    require(os.geteuid() == 0 and uuid_value(args.release_operation_id), INVALID)
    with release_execution(catalog, args.release_operation_id, create=True) as (root, fd):
        require(optional_fact(fd, RETIREMENT_INTENT) is None, UNAVAILABLE)
        admitted = admitted_release(catalog, registry, args, entry, launcher)
        known = known_maintenance(fd, admitted)
        if known is not None:
            os.fsync(fd)
            return known
        source = admitted.pair.source
        expected = maintenance_policy(admitted.grant, source)
        pin = write_fact(fd, MAINTENANCE_POLICY, expected)
        facts = invoke_observer(
            source.maintenance_uid,
            source.group,
            environment_command(
                'environment-maintenance',
                args,
                launcher,
                source,
                '--maintenance-policy',
                root / MAINTENANCE_POLICY,
                '--maintenance-policy-sha256',
                pin,
                '--maintenance-action',
                'enter',
            ),
            catalog.directory / 'observations',
        )
        readback = maintenance_result(facts, admitted.grant, expected, pin)
        write_fact(fd, HOLD_RECEIPT, readback)
        return readback
