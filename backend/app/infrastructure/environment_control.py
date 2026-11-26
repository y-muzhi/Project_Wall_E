"""Persistent P1 admission facts shared by initialization and startup."""

import os

from .environment_files import (
    MAX_REVISION,
    canonical,
    decode,
    digest,
    exact,
    persisted_write,
    read_entry,
    require,
)
from .environment_installation import (
    RESTORE_MODE,
    identity_record,
    read_restore_generation,
    sha_value,
    uuid_value,
    version_record,
)

CONTROL_NAME = 'control.v1.json'


def initial_control(installation, operation_id):
    description = installation.description
    return {
        'format_version': 1,
        'environment_id': installation.environment_id,
        'control_revision': 1,
        'maintenance_id': None,
        'operation_source': 'LOCAL_TOOL',
        'operation_id': operation_id,
        'plan_sha256': None,
        'deployment_id': installation.deployment_id,
        'program_ref': description['program_source'],
        'runtime_manifest_sha256': description['runtime_manifest_sha256'],
        'schema_manifest_sha256': description['schema_manifest_sha256'],
        'configuration_sha256': installation.configuration_sha256,
        'data_generation': installation.data_generation,
        'data_root_ref': str(installation.path('data')),
        'admission': 'CLOSED',
        'closed_reason': 'NORMAL_STOP',
        'drain_manifest_ref': None,
        'drain_manifest_sha256': None,
        'last_opened_deployment_id': None,
        'open_receipt_ref': None,
        'outbound_hold': getattr(installation, 'restore_generation_sha256', None) is not None,
        'cause_operation_id': None,
        'model_access': {
            'revision': 0,
            'active_permit_ref': None,
            'last_operation_id': None,
            'last_effect_ref': None,
        },
    }


def confirm_initial_control(directory, installation, operation_id, *, create):
    # A3 is restricted to the initial LOCAL_TOOL operation. Later startup/stop
    # uses the same deployed tuple with the next control revisions.
    desired = initial_control(installation, operation_id)
    try:
        raw = read_entry(
            directory, CONTROL_NAME, owner=installation.maintenance_uid, group=installation.group
        )
    except FileNotFoundError:
        if create:
            persisted_write(directory, CONTROL_NAME, canonical(desired), mode=0o640)
        return False
    actual = exact(
        decode(raw, 'ENVIRONMENT_CONTROL_MISMATCH'), desired, 'ENVIRONMENT_CONTROL_MISMATCH'
    )
    require(raw == canonical(desired) and actual == desired, 'ENVIRONMENT_CONTROL_MISMATCH')
    return True


CONTROL_ERROR = 'ENVIRONMENT_CONTROL_MISMATCH'


def normal_stop(record):
    return (record['admission'], record['closed_reason']) == ('CLOSED', 'NORMAL_STOP')


def check_maintenance_reference(reference, code):
    exact(reference, ('operation_id', 'plan_sha256'), code)
    require(uuid_value(reference['operation_id']) and sha_value(reference['plan_sha256']), code)


def maintenance_cancel_name(operation):
    return f'maintenance-cancel-{operation}.v1.json'


def stopped_for_policy(fd, record, reference):
    if reference is None:
        return normal_stop(record)
    bound = (
        (record['admission'], record['closed_reason']) == ('CLOSED', 'MAINTENANCE')
        and record['maintenance_id'] == record['operation_id'] == reference['operation_id']
        and record['plan_sha256'] == reference['plan_sha256']
    )
    if not bound:
        return False
    try:
        os.stat(maintenance_cancel_name(record['operation_id']), dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    return False


def maintenance_name(operation):
    return f'maintenance-{operation}.v1.json'


def maintained_control(before, operation, plan_sha):
    return {
        **before,
        'control_revision': before['control_revision'] + 1,
        'maintenance_id': operation,
        'operation_id': operation,
        'plan_sha256': plan_sha,
        'closed_reason': 'MAINTENANCE',
        'outbound_hold': True,
        'cause_operation_id': before['operation_id'],
    }


def validate_normal_control(record, installation):
    require(uuid_value(record.get('operation_id')), CONTROL_ERROR)
    original = initial_control(installation, record['operation_id'])
    exact(record, original, CONTROL_ERROR)
    observed = {
        'control_revision',
        'admission',
        'closed_reason',
        'last_opened_deployment_id',
        'open_receipt_ref',
    }
    require(
        all(
            canonical(record[field]) == canonical(value)
            for field, value in original.items()
            if field not in observed
        )
        and type(record['control_revision']) is int
        and 1 <= record['control_revision'] < MAX_REVISION
        and (record['admission'], record['closed_reason'])
        in (('CLOSED', 'NORMAL_STOP'), ('OPEN', 'NONE'), ('DRAINING', 'NORMAL_STOP')),
        CONTROL_ERROR,
    )


def read_maintenance_intent(fd, installation, operation):
    require(uuid_value(operation), CONTROL_ERROR)
    raw = read_entry(
        fd,
        maintenance_name(operation),
        owner=installation.maintenance_uid,
        group=installation.group,
        reject_writers=0o227,
    )
    record = exact(
        decode(raw, CONTROL_ERROR),
        ('format_version', 'operation_id', 'plan_sha256', 'before_sha256', 'before'),
        CONTROL_ERROR,
    )
    before = record['before']
    require(
        type(record['format_version']) is int
        and record['format_version'] == 1
        and record['operation_id'] == operation
        and uuid_value(operation)
        and sha_value(record['plan_sha256'])
        and type(before) is dict
        and digest(canonical(before)) == record['before_sha256'],
        CONTROL_ERROR,
    )
    validate_normal_control(before, installation)
    require(
        normal_stop(before)
        and before['operation_id'] != operation
        and before['control_revision'] < MAX_REVISION - 2,
        CONTROL_ERROR,
    )
    return record


def release_transition_name(operation):
    return f'release-transition-{operation}.v1.json'


def selected_release_control(before, installation):
    return {
        **before,
        'control_revision': before['control_revision'] + 1,
        'deployment_id': installation.deployment_id,
        'program_ref': installation.description['program_source'],
        'runtime_manifest_sha256': installation.description['runtime_manifest_sha256'],
        'schema_manifest_sha256': installation.description['schema_manifest_sha256'],
        'configuration_sha256': installation.configuration_sha256,
        'data_generation': installation.data_generation,
        'data_root_ref': str(installation.path('data')),
        'closed_reason': 'RECOVERY_REQUIRED',
    }


def read_release_transition(fd, installation, operation):
    binding = installation.description.get('deployment_slot')
    require(binding is not None and uuid_value(operation), CONTROL_ERROR)
    raw = read_entry(
        fd,
        release_transition_name(operation),
        owner=installation.maintenance_uid,
        group=installation.group,
        reject_writers=0o227,
    )
    transition = decode(raw, CONTROL_ERROR)
    restore = binding['authorization_mode'] == RESTORE_MODE
    version_record(
        transition,
        (
            'operation_id',
            'switch_policy_sha256',
            'preflight_policy_sha256',
            'release_preflight_sha256',
            'source_installation_sha256',
            'target_installation_sha256',
            'backup_manifest_sha256',
            'logical_content_sha256',
            'database_identity',
            *(
                (
                    'restore_generation_sha256',
                    'source_database_identity',
                    'preserved_result_index_sha256',
                    'selected_backup_manifest_sha256',
                    'selected_result_index_sha256',
                    'selected_source_data_generation',
                )
                if restore
                else ()
            ),
            'before_sha256',
            'before',
            'after_sha256',
            'after',
        ),
        CONTROL_ERROR,
    )
    require(
        raw == canonical(transition)
        and transition['operation_id'] == operation
        and transition['target_installation_sha256'] == installation.anchor_sha256
        and all(
            sha_value(value) for field, value in transition.items() if field.endswith('_sha256')
        ),
        CONTROL_ERROR,
    )
    identity_record(transition['database_identity'], CONTROL_ERROR)
    before = exact(transition['before'], initial_control(installation, operation), CONTROL_ERROR)
    require(
        before['environment_id'] == installation.environment_id
        and before['deployment_id'] == binding['source_deployment_id']
        and before['configuration_sha256'] == binding['source_configuration_sha256']
        and before['operation_id'] == before['maintenance_id'] == operation
        and sha_value(before['plan_sha256'])
        and (before['admission'], before['closed_reason'], before['outbound_hold'])
        == ('CLOSED', 'MAINTENANCE', True)
        and type(before['control_revision']) is int
        and 1 <= before['control_revision'] < MAX_REVISION - 3
        and digest(canonical(before)) == transition['before_sha256'],
        CONTROL_ERROR,
    )
    if restore:
        validate_restore_transition(installation, transition)
    else:
        require(
            before['data_generation'] == installation.data_generation
            and before['data_root_ref'] == str(installation.path('data')),
            CONTROL_ERROR,
        )
    expected = selected_release_control(before, installation)
    require(
        canonical(transition['after']) == canonical(expected)
        and transition['after_sha256'] == digest(canonical(expected)),
        CONTROL_ERROR,
    )
    return transition


def validate_restore_transition(installation, transition):
    binding = installation.restore_generation_sha256
    require(
        sha_value(binding) and transition['restore_generation_sha256'] == binding, CONTROL_ERROR
    )
    receipt, _ = read_restore_generation(
        installation.environment_root,
        installation.environment_id,
        installation.data_generation,
        expected=binding,
    )
    before = transition['before']
    identity_record(transition['source_database_identity'], CONTROL_ERROR)
    require(
        uuid_value(before['data_generation'])
        and uuid_value(transition['selected_source_data_generation'])
        and installation.data_generation != transition['selected_source_data_generation']
        and before['data_generation'] != installation.data_generation
        and type(before['data_root_ref']) is str
        and before['data_root_ref'] != str(installation.path('data'))
        and receipt['operation_id'] == transition['operation_id']
        and receipt['source_control_sha256'] == transition['before_sha256']
        and receipt['source_database_identity'] == transition['source_database_identity']
        and receipt['database_identity'] == transition['database_identity'],
        CONTROL_ERROR,
    )


def control_bytes(fd, installation):
    metadata = os.stat(CONTROL_NAME, dir_fd=fd, follow_symlinks=False)
    require(
        metadata.st_uid in (installation.maintenance_uid, installation.application_uid),
        CONTROL_ERROR,
    )
    raw = read_entry(fd, CONTROL_NAME, owner=metadata.st_uid, group=installation.group)
    return metadata.st_uid, raw


def read_control(fd, installation):
    writer, raw = control_bytes(fd, installation)
    record = decode(raw, CONTROL_ERROR)
    last_deployment = installation.deployment_id
    last_generation = installation.data_generation
    if record.get('closed_reason') == 'MAINTENANCE':
        operation = record.get('operation_id')
        require(uuid_value(operation) and writer == installation.maintenance_uid, CONTROL_ERROR)
        intent = read_maintenance_intent(fd, installation, operation)
        expected = maintained_control(intent['before'], operation, intent['plan_sha256'])
        require(raw == canonical(expected), CONTROL_ERROR)
    elif record.get('closed_reason') == 'RECOVERY_REQUIRED':
        require(writer == installation.maintenance_uid, CONTROL_ERROR)
        transition = read_release_transition(fd, installation, record.get('operation_id'))
        require(raw == canonical(transition['after']), CONTROL_ERROR)
        last_deployment = transition['before']['deployment_id']
        last_generation = transition['before']['data_generation']
    else:
        validate_normal_control(record, installation)
    previous = record['last_opened_deployment_id']
    receipt = record['open_receipt_ref']
    if previous is None:
        require(receipt is None and record['admission'] == 'CLOSED', CONTROL_ERROR)
    else:
        require(
            previous == last_deployment
            and type(receipt) is str
            and receipt.startswith('open-')
            and receipt.endswith('.v1.json')
            and uuid_value(receipt[5:-8]),
            CONTROL_ERROR,
        )
        opened = decode(
            read_entry(fd, receipt, owner=installation.application_uid, group=installation.group),
            CONTROL_ERROR,
        )
        require(
            opened.get('environment_id') == installation.environment_id
            and opened.get('data_generation') == last_generation
            and opened.get('deployment_id') == last_deployment
            and opened.get('run_id') == receipt[5:-8],
            CONTROL_ERROR,
        )
    return record
