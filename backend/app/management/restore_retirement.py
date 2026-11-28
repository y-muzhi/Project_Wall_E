"""Retire an unselected managed restore without reopening the original deployment."""

import os

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    EnvironmentFailure,
    canonical,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import uuid_value
from backend.app.infrastructure.environment_maintenance import (
    CANCELLED,
    POLICY as MAINTENANCE_POLICY,
)

from .attachment_observation import invoke_observer
from .operation_contract import INVALID, RESOURCE, UNAVAILABLE, VERSION, installed_record
from .operation_store import stored
from .release_execution import (
    SOURCE_KEYS,
    environment_command,
    execution_directory,
    optional_fact,
    write_fact,
)
from .restore_execution import (
    EXECUTIONS,
    HOLD_RECEIPT,
    RETIREMENT,
    admitted_restore,
    known_restore_maintenance,
)
from .restore_selection import SELECTED

RETIRED = 'MANAGED_RESTORE_RETIRED_BEFORE_SELECTION'


def retirement_receipt(facts, grant, hold):
    exact(
        facts, ('status', 'operation_id', *SOURCE_KEYS, 'plan_sha256', 'control_revision'), RESOURCE
    )
    preview = grant['confirmation']
    require(
        facts['status'] == CANCELLED
        and facts['operation_id'] == hold['operation_id'] == preview['operation_id']
        and all(facts[key] == hold[key] for key in SOURCE_KEYS)
        and hold['plan_sha256'] == grant['plan_sha256']
        and hold['grant_sha256'] == digest(canonical(grant))
        and facts['plan_sha256']
        == hold['restore_authorization_sha256']
        == preview['restore_authorization_sha256']
        and facts['control_revision'] == hold['control_revision'] + 1,
        RESOURCE,
    )
    return {
        'format_version': 1,
        'status': RETIRED,
        'operation_id': facts['operation_id'],
        **{key: facts[key] for key in SOURCE_KEYS},
        'control_revision': facts['control_revision'],
        'plan_sha256': grant['plan_sha256'],
        'restore_authorization_sha256': facts['plan_sha256'],
        'grant_sha256': digest(canonical(grant)),
        'maintenance_receipt_sha256': digest(canonical(hold)),
    }


def verify_retirement(receipt, grant, hold):
    facts = {
        'status': CANCELLED,
        **{key: receipt[key] for key in ('operation_id', *SOURCE_KEYS, 'control_revision')},
        'plan_sha256': receipt['restore_authorization_sha256'],
    }
    require(receipt == retirement_receipt(facts, grant, hold), RESOURCE)
    return receipt


def retire_managed_restore(catalog, registry, args, launcher):
    operation = args.release_operation_id
    require(os.geteuid() == 0 and uuid_value(operation), INVALID)
    with execution_directory(catalog, EXECUTIONS, operation) as (root, fd):
        require(optional_fact(fd, HOLD_RECEIPT) is not None, RESOURCE)
        require(optional_fact(fd, SELECTED) is None, UNAVAILABLE)
        admitted = admitted_restore(catalog, registry, args, launcher)
        hold = known_restore_maintenance(fd, admitted)
        known = optional_fact(fd, RETIREMENT)
        if known is not None:
            verified = verify_retirement(known, admitted.grant, hold)
            os.fsync(fd)
            return verified
        source = admitted.source
        outside = invoke_observer(
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
                hold['maintenance_policy_sha256'],
                '--maintenance-action',
                'cancel',
            ),
            catalog.directory / 'observations',
        )
        result = retirement_receipt(outside, admitted.grant, hold)
        write_fact(fd, RETIREMENT, result)
        return result


def original_retirement(catalog, grant):
    root = catalog.directory / EXECUTIONS / grant['confirmation']['operation_id']
    try:
        receipt = installed_record(root / RETIREMENT)
    except FileNotFoundError:
        return None
    try:
        installed_record(root / SELECTED)
    except FileNotFoundError:
        return verify_retirement(receipt, grant, installed_record(root / HOLD_RECEIPT))
    raise EnvironmentFailure(RESOURCE)


def record_retirement(connection, operation, state, retirement):
    require(operation['status'] == 'RUNNING' and operation['revision'] < MAX_REVISION, VERSION)
    recorded = connection.execute(
        "UPDATE management_steps SET status='SKIPPED',external_identity_json=? "
        "WHERE operation_id=? AND ordinal=1 AND status='DISPATCHING' AND result_json IS NULL",
        (
            stored({**state, 'retirement_sha256': digest(canonical(retirement))}),
            operation['operation_id'],
        ),
    )
    finished = connection.execute(
        "UPDATE management_operations SET status='CANCELLED',cancel_requested=1,revision=revision+1 "
        "WHERE operation_id=? AND status='RUNNING' AND revision=?",
        (operation['operation_id'], operation['revision']),
    )
    require(recorded.rowcount == finished.rowcount == 1, VERSION)
