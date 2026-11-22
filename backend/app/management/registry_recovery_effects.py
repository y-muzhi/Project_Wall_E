"""Observe named resource bindings and original managed helper units without changing them."""

from subprocess import SubprocessError

from backend.app.infrastructure.environment_files import EnvironmentFailure, decode, require
from backend.app.infrastructure.environment_installation import uuid_value

from .attachment_observation import PATH_SCOPE
from .runtime_capacity import CLAIM_KIND
from .runtime_observation import unit_facts
from .runtime_start import preparation_group_empty

UNVERIFIED = 'MANAGEMENT_REGISTRY_RECOVERY_EFFECT_UNVERIFIED'
OBSERVATION_FAILURE = (
    EnvironmentFailure,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    SubprocessError,
)


def resource_observation(row, observed_environment):
    subject = {
        'kind': 'RESOURCE_CLAIM',
        'resource_id': row['resource_id'],
        'resource_kind': row['kind'],
        'environment_id': row['environment_id'],
        'operation_id': row['operation_id'],
    }
    if row['kind'] == CLAIM_KIND:
        return {**subject, 'state': 'PRESERVED', 'reason_code': 'CAPACITY_NOT_RELEASED'}
    actual = observed_environment.get('paths', {}).get(row['kind'])
    if actual is None:
        return {**subject, 'state': 'UNKNOWN', 'reason_code': UNVERIFIED}
    try:
        pinned = (
            None
            if row['identity_json'] is None
            else decode(row['identity_json'].encode('utf-8'), UNVERIFIED)
        )
        state = (
            'BOUND'
            if row['scope_ref'] == PATH_SCOPE
            and row['locator'] == actual['locator']
            and pinned == actual['object_identity']
            else 'CHANGED'
        )
    except OBSERVATION_FAILURE:
        state = 'UNKNOWN'
    return {**subject, 'state': state, 'reason_code': None if state == 'BOUND' else UNVERIFIED}


def original_units(row):
    require(
        all(
            uuid_value(row[field])
            for field in ('environment_id', 'operation_id', 'registry_generation')
        ),
        UNVERIFIED,
    )
    payload = row['external_identity_json']
    if type(payload) is not str:
        return ()
    identity = decode(payload.encode('utf-8'), UNVERIFIED)
    data = None
    prefixes = ()
    if row['step_kind'] == 'RUNTIME_STARTED' and row['executor_ref'] == 'SYSTEMD_ORDINARY_RUNTIME':
        data = identity.get('dispatch')
        prefixes = ('walle-prep-', 'walle-env-')
    elif row['step_kind'] in ('RELEASE_DEPLOYMENT', 'RESTORE_ENVIRONMENT'):
        data = identity.get('opening')
        prefixes = ('walle-env-',)
    if type(data) is not dict or any(
        data.get(field) != row[field]
        for field in ('environment_id', 'operation_id', 'registry_generation')
    ):
        return ()
    return tuple(
        f'{prefix}{row["environment_id"]}-{row["operation_id"]}.service' for prefix in prefixes
    )


def unit_observation(unit):
    before = unit_facts(unit)
    empty = preparation_group_empty(unit)
    require(before == unit_facts(unit) and empty == preparation_group_empty(unit), UNVERIFIED)
    load = before['LoadState']
    active = before.get('ActiveState')
    main = before.get('MainPID', '0')
    require(main.isascii() and main.isdecimal(), UNVERIFIED)
    if load == 'not-found' and empty and main == '0':
        state = 'ABSENT_OBSERVED'
    elif load == 'loaded' and empty and main == '0' and active in ('inactive', 'failed'):
        state = 'QUIET_OBSERVED'
    elif load == 'loaded' and active in ('active', 'activating', 'deactivating'):
        state = 'PRESENT_OBSERVED'
    else:
        state = 'UNKNOWN'
    return {
        'unit': unit,
        'load_state': load,
        'active_state': active,
        'invocation_id': before.get('InvocationID') or None,
        'main_pid': int(main),
        'cgroup_empty': empty,
        'state': state,
    }


def helper_observation(row):
    subject = {
        'kind': 'ORIGINAL_HELPER_STEP',
        'environment_id': row['environment_id'],
        'operation_id': row['operation_id'],
        'ordinal': row['ordinal'],
        'step_kind': row['step_kind'],
        'original_status': row['status'],
    }
    measured = []
    try:
        for unit in original_units(row):
            try:
                result = unit_observation(unit)
            except OBSERVATION_FAILURE:
                result = {'unit': unit, 'state': 'UNKNOWN'}
            measured.append(result)
    except OBSERVATION_FAILURE:
        pass
    state = (
        'OBSERVED'
        if measured and all(item['state'] != 'UNKNOWN' for item in measured)
        else 'UNKNOWN'
    )
    return {**subject, 'state': state, 'units': measured}
