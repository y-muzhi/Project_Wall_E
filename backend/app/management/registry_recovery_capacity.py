"""Bind and retire an exact original reservation in a management recovery transaction."""

from backend.app.infrastructure.environment_files import canonical, digest, exact, require
from backend.app.infrastructure.environment_installation import sha_value

from .operation_store import decoded, stored
from .registry import is_timestamp
from .registry_recovery_outcome import UNVERIFIED
from .runtime_capacity import (
    CLAIM_KIND,
    CLAIM_SCOPE,
    DIMENSIONS,
    MAXIMUM,
    MINIMUM,
    release_rows,
    reservations_for,
)

CAPACITY_FIELDS = (
    'resource_id',
    'environment_id',
    'operation_id',
    'kind',
    'scope_ref',
    'locator',
    'identity_json',
    'quota',
)


def measured_capacity(claims, environment_id):
    require(
        not claims
        or (
            len(claims) == len(DIMENSIONS)
            and {claim['locator'] for claim in claims} == set(DIMENSIONS)
            and all(
                claim['environment_id'] == environment_id
                and type(claim['quota']) is int
                and MINIMUM[claim['locator']] <= claim['quota'] <= MAXIMUM[claim['locator']]
                and type(claim['identity_json']) is str
                for claim in claims
            )
        ),
        UNVERIFIED,
    )
    if claims:
        frozen = {claim['identity_json'] for claim in claims}
        require(len(frozen) == 1, UNVERIFIED)
        binding = exact(
            decoded(frozen.pop()),
            ('policy_sha256', 'profile_ref', 'configuration_sha256'),
            UNVERIFIED,
        )
        require(
            sha_value(binding['policy_sha256'])
            and sha_value(binding['configuration_sha256'])
            and type(binding['profile_ref']) is str
            and bool(binding['profile_ref']),
            UNVERIFIED,
        )
    measured = [
        {key: claim[key] for key in CAPACITY_FIELDS}
        for claim in sorted(claims, key=lambda item: item['resource_id'])
    ]
    return {'count': len(measured), 'sha256': digest(canonical(measured))}


def settle_capacity(connection, operation_id, environment_id, expected, released, *, recorded):
    held = reservations_for(connection, operation_id)
    if not recorded or expected['count'] == 0:
        require(measured_capacity(held, environment_id) == expected, UNVERIFIED)
        if held:
            release_rows(connection, operation_id, environment_id, held, released, stored)
        return
    require(not held, UNVERIFIED)
    claims = connection.execute(
        'SELECT * FROM resource_claims WHERE operation_id=? AND kind=? AND scope_ref=?',
        (operation_id, CLAIM_KIND, CLAIM_SCOPE),
    ).fetchall()
    require(
        measured_capacity(claims, environment_id) == expected
        and all(
            is_timestamp(claim['released_at']) and claim['release_json'] == stored(released)
            for claim in claims
        ),
        UNVERIFIED,
    )
