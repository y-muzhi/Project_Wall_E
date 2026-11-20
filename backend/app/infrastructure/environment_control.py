"""Persistent P1 admission facts shared by initialization and startup."""

from .environment_files import canonical, decode, exact, persisted_write, read_entry, require

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
        'outbound_hold': False,
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
