"""Host policy and transactional ordinary-runtime capacity reservations."""

from dataclasses import dataclass
import os
from pathlib import Path
from uuid import uuid4

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    absolute,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import uuid_value

from .attachment_observation import now
from .host_capacity import NOT_READY, available_memory_bytes
from .operation_contract import PURPOSES, RESOURCE, UNAVAILABLE, installed_record

POLICY_PATH = Path('/run/wall-e/management/ordinary-capacity.v1.json')
MINIMUM = dict(memory_bytes=128 * 1024**2, cpu_percent=25, tasks=16, run_slots=1)
MAXIMUM = dict(memory_bytes=2 * 1024**3, cpu_percent=200, tasks=512, run_slots=1)
DIMENSIONS = tuple(MINIMUM)
CLAIM_KIND = 'ORDINARY_RUNTIME_CAPACITY'
CLAIM_SCOPE = 'ORDINARY_RUNTIME'


@dataclass(frozen=True)
class CapacityPolicy:
    sha256: str
    home: Path
    temporary: Path
    limits: dict
    profiles: dict

    def profile(self, row):
        profile = self.profiles[row['purpose']]
        require(profile['profile_ref'] == row['profile_ref'], RESOURCE)
        return profile['limits']

    def binding(self, row):
        return {
            'policy_sha256': self.sha256,
            'profile_ref': row['profile_ref'],
            'configuration_sha256': row['configuration_sha256'],
        }


def load_capacity(catalog):
    expected = catalog.capacity_policy_sha256
    require(expected is not None, UNAVAILABLE)
    try:
        record = installed_record(POLICY_PATH, expected, code=NOT_READY)
    except (OSError, ValueError, EnvironmentFailure) as error:
        raise EnvironmentFailure(NOT_READY) from error
    exact(
        record,
        (
            'format_version',
            *catalog.scope,
            'registry_anchor_sha256',
            'catalog_directory',
            'manager_home',
            'manager_temporary',
            'limits',
            'profiles',
        ),
        NOT_READY,
    )
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and all(record[key] == value for key, value in catalog.scope.items())
        and record['registry_anchor_sha256'] == catalog.registry_anchor_sha256
        and record['catalog_directory'] == str(catalog.directory),
        NOT_READY,
    )
    home = absolute(record['manager_home'], NOT_READY)
    temporary = absolute(record['manager_temporary'], NOT_READY)
    require(not home.is_relative_to(temporary) and not temporary.is_relative_to(home), NOT_READY)
    limits = exact(record['limits'], DIMENSIONS, NOT_READY)
    require(
        all(
            type(limits[key]) is int and MINIMUM[key] <= limits[key] <= MAX_REVISION
            for key in DIMENSIONS
        )
        and limits['cpu_percent'] <= (os.cpu_count() or 0) * 100
        and limits['memory_bytes'] <= os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE'),
        NOT_READY,
    )
    profiles = exact(record['profiles'], PURPOSES, NOT_READY)
    for profile in profiles.values():
        exact(profile, ('profile_ref', 'limits'), NOT_READY)
        requested = exact(profile['limits'], DIMENSIONS, NOT_READY)
        require(
            uuid_value(profile['profile_ref'])
            and all(
                type(requested[key]) is int
                and MINIMUM[key] <= requested[key] <= min(MAXIMUM[key], limits[key])
                for key in DIMENSIONS
            ),
            NOT_READY,
        )
    return CapacityPolicy(expected, home, temporary, limits, profiles)


def held_capacity(connection):
    return connection.execute(
        'SELECT claim.*, op.status AS operation_status, op.action AS operation_action '
        'FROM resource_claims AS claim JOIN management_operations AS op USING(operation_id) '
        'WHERE claim.kind=? AND claim.scope_ref=? AND claim.released_at IS NULL',
        (CLAIM_KIND, CLAIM_SCOPE),
    ).fetchall()


def capacity_totals(claims):
    counts = dict.fromkeys(DIMENSIONS, 0)
    pending_memory = 0
    for claim in claims:
        kind = claim['locator']
        require(
            kind in counts
            and type(claim['quota']) is int
            and claim['quota'] > 0
            and claim['operation_action'] in ('START', 'RELEASE', 'RESTORE'),
            RESOURCE,
        )
        counts[kind] += claim['quota']
        if kind == 'memory_bytes' and claim['operation_status'] != 'SUCCEEDED':
            pending_memory += claim['quota']
    return counts, pending_memory


def check_capacity(connection, policy, row):
    requested = policy.profile(row)
    held = held_capacity(connection)
    require(not any(claim['environment_id'] == row['environment_id'] for claim in held), RESOURCE)
    counts, pending_memory = capacity_totals(held)
    try:
        available = available_memory_bytes()
    except OSError as error:
        raise EnvironmentFailure(NOT_READY) from error
    missing = [key for key in DIMENSIONS if counts[key] + requested[key] > policy.limits[key]]
    if available < pending_memory + requested['memory_bytes'] and 'memory_bytes' not in missing:
        missing = ['memory_bytes', *missing]
    return {'observed_at': now(), 'missing': missing} if missing else None


def reserve_capacity(connection, operation, policy, row, encoded):
    binding = encoded(policy.binding(row))
    connection.executemany(
        'INSERT INTO resource_claims (resource_id, environment_id, operation_id, kind, '
        'scope_ref, locator, identity_json, quota) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (
            (
                str(uuid4()),
                row['environment_id'],
                operation,
                CLAIM_KIND,
                CLAIM_SCOPE,
                key,
                binding,
                amount,
            )
            for key, amount in policy.profile(row).items()
        ),
    )


def reservations_for(connection, operation):
    return [claim for claim in held_capacity(connection) if claim['operation_id'] == operation]


def verify_reserved_binding(connection, operation, environment_id, expected, binding):
    claims = reservations_for(connection, operation)
    require(
        len(claims) == len(DIMENSIONS)
        and {item['locator']: item['quota'] for item in claims} == expected
        and all(
            item['environment_id'] == environment_id and item['identity_json'] == binding
            for item in claims
        ),
        RESOURCE,
    )


def verify_reservation(connection, operation, policy, row, encoded):
    verify_reserved_binding(
        connection,
        operation,
        row['environment_id'],
        policy.profile(row),
        encoded(policy.binding(row)),
    )


def release_capacity(connection, start_id, stop_id, environment_id, outcome, encoded, decoded):
    claims = reservations_for(connection, start_id)
    if not claims:
        return
    source = connection.execute(
        'SELECT op.environment_id, op.action, op.status, step.result_json '
        'FROM management_operations AS op JOIN management_steps AS step USING(operation_id) '
        'WHERE op.operation_id=? AND step.ordinal=1 AND '
        "((op.action='START' AND step.step_kind='RUNTIME_STARTED') OR "
        "(op.action='RELEASE' AND step.step_kind='RELEASE_DEPLOYMENT') OR "
        "(op.action='RESTORE' AND step.step_kind='RESTORE_ENVIRONMENT'))",
        (start_id,),
    ).fetchone()
    require(
        source is not None
        and source['environment_id'] == environment_id
        and source['action'] in ('START', 'RELEASE', 'RESTORE')
        and source['status'] == 'SUCCEEDED'
        and source['result_json'] is not None
        and decoded(source['result_json'])['run_id'] == outcome['run_id']
        and len(claims) == len(DIMENSIONS),
        RESOURCE,
    )
    release_rows(
        connection,
        start_id,
        environment_id,
        claims,
        {'stop_operation_id': stop_id, **outcome},
        encoded,
    )


def release_rows(connection, operation_id, environment_id, claims, evidence, encoded):
    require(
        len(claims) == len(DIMENSIONS)
        and {claim['locator'] for claim in claims} == set(DIMENSIONS)
        and all(claim['environment_id'] == environment_id for claim in claims),
        RESOURCE,
    )
    changed = connection.execute(
        'UPDATE resource_claims SET released_at=?, release_json=? WHERE operation_id=? '
        'AND environment_id=? AND kind=? AND scope_ref=? AND released_at IS NULL',
        (now(), encoded(evidence), operation_id, environment_id, CLAIM_KIND, CLAIM_SCOPE),
    )
    require(changed.rowcount == len(DIMENSIONS), RESOURCE)


def cancel_reservation(connection, operation, control_key, encoded):
    claims = reservations_for(connection, operation['operation_id'])
    if not claims:
        return
    require(operation['status'] == 'ACCEPTED', RESOURCE)
    release_rows(
        connection,
        operation['operation_id'],
        operation['environment_id'],
        claims,
        {'control_key': control_key, 'reason_code': 'START_NOT_DISPATCHED'},
        encoded,
    )
