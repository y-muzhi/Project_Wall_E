"""Retire an original held fixed deployment before any selection was attempted."""

import os

from backend.app.infrastructure.environment_files import (
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_maintenance import CANCELLED
from backend.app.infrastructure.environment_maintenance import POLICY as MAINTENANCE_POLICY

from .attachment_observation import invoke_observer
from .operation_contract import INVALID, RESOURCE, UNAVAILABLE, installed_record
from .release_execution import (
    EXECUTIONS,
    HOLD_RECEIPT,
    RETIREMENT,
    RETIREMENT_INTENT,
    SOURCE_KEYS,
    admitted_release,
    environment_command,
    known_maintenance,
    optional_fact,
    release_execution,
    write_fact,
)
from .release_selection import SELECTED, SWITCH_POLICY

RETIRED = 'MANAGED_RELEASE_RETIRED_BEFORE_SELECTION'


def retirement_intent(grant, hold):
    require(
        hold['operation_id'] == grant['operation_id']
        and hold['plan_sha256'] == grant['plan_sha256']
        and hold['grant_sha256'] == digest(canonical(grant)),
        RESOURCE,
    )
    return {
        'format_version': 1,
        'status': 'MANAGED_RELEASE_RETIREMENT_REQUESTED',
        'operation_id': grant['operation_id'],
        **{key: hold[key] for key in SOURCE_KEYS},
        'plan_sha256': grant['plan_sha256'],
        'grant_sha256': hold['grant_sha256'],
        'maintenance_policy_sha256': hold['maintenance_policy_sha256'],
        'maintenance_receipt_sha256': digest(canonical(hold)),
    }


def retirement_receipt(facts, grant, hold):
    exact(
        facts, ('status', 'operation_id', *SOURCE_KEYS, 'plan_sha256', 'control_revision'), RESOURCE
    )
    intent = retirement_intent(grant, hold)
    require(
        facts['status'] == CANCELLED
        and all(facts[key] == intent[key] for key in ('operation_id', *SOURCE_KEYS))
        and facts['plan_sha256'] == intent['maintenance_policy_sha256']
        and type(facts['control_revision']) is int
        and facts['control_revision'] == hold['control_revision'] + 1,
        RESOURCE,
    )
    return {
        **intent,
        'status': RETIRED,
        'control_revision': facts['control_revision'],
        'retirement_intent_sha256': digest(canonical(intent)),
    }


def verified_retirement(record, grant, hold, intent):
    require(intent == retirement_intent(grant, hold), RESOURCE)
    facts = {
        'status': CANCELLED,
        **{key: record[key] for key in ('operation_id', *SOURCE_KEYS, 'control_revision')},
        'plan_sha256': record['maintenance_policy_sha256'],
    }
    require(record == retirement_receipt(facts, grant, hold), RESOURCE)
    return record


def retire_managed_release(catalog, registry, args, entry, launcher):
    operation = args.release_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), INVALID)
    with release_execution(catalog, operation) as (root, fd):
        require(optional_fact(fd, HOLD_RECEIPT) is not None, RESOURCE)
        require(
            optional_fact(fd, SWITCH_POLICY) is None and optional_fact(fd, SELECTED) is None,
            UNAVAILABLE,
        )
        admitted = admitted_release(catalog, registry, args, entry, launcher, read_retired=True)
        hold = known_maintenance(fd, admitted)
        intent = retirement_intent(admitted.grant, hold)
        known = optional_fact(fd, RETIREMENT)
        if known is not None:
            confirmed = verified_retirement(
                known, admitted.grant, hold, optional_fact(fd, RETIREMENT_INTENT)
            )
            os.fsync(fd)
            return confirmed
        write_fact(fd, RETIREMENT_INTENT, intent)
        installation = admitted.pair.source
        stopped = invoke_observer(
            installation.maintenance_uid,
            installation.group,
            environment_command(
                'environment-maintenance',
                args,
                launcher,
                installation,
                '--maintenance-policy',
                root / MAINTENANCE_POLICY,
                '--maintenance-policy-sha256',
                hold['maintenance_policy_sha256'],
                '--maintenance-action',
                'cancel',
            ),
            catalog.directory / 'observations',
        )
        result = retirement_receipt(stopped, admitted.grant, hold)
        write_fact(fd, RETIREMENT, result)
        return result


def original_retirement(catalog, grant):
    root = catalog.directory / EXECUTIONS / grant['operation_id']
    try:
        record = installed_record(root / RETIREMENT)
    except FileNotFoundError:
        return None
    for name in (SWITCH_POLICY, SELECTED):
        try:
            installed_record(root / name)
        except FileNotFoundError:
            continue
        raise EnvironmentFailure(RESOURCE)
    return verified_retirement(
        record,
        grant,
        installed_record(root / HOLD_RECEIPT),
        installed_record(root / RETIREMENT_INTENT),
    )
