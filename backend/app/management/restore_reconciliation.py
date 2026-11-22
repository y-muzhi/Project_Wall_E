"""Reconcile a durably opened restored generation into its original registry operation."""

from backend.app.infrastructure.environment_files import require

from .management_query import business_entry
from .operation_contract import DENIED, RESOURCE, UNAVAILABLE, installed_record
from .operation_store import decoded
from .release_configuration import CHANGED
from .release_open_admission import TARGET
from .release_reconciliation import adopt_opened_deployment, verify_opened_evidence
from .release_runtime import OPENED
from .restore_execution import EXECUTIONS, original_restore_grant, restore_operation
from .restore_runtime import read_restore_selection, restore_registry_row
from .restore_retirement import original_retirement, record_retirement


def opened_restore(catalog, grant, request):
    root = catalog.directory / EXECUTIONS / request['operation_id']
    try:
        receipt = installed_record(root / OPENED)
    except FileNotFoundError:
        return None
    selected, _ = read_restore_selection(catalog, grant, request['selection_receipt_sha256'])
    require(all(selected[key] == request[key] for key in TARGET), CHANGED)
    verify_opened_evidence(catalog, root, request, selected, selected['target_attachment'], receipt)
    return selected, receipt


def reconcile_restore(connection, catalog, principal, operation):
    require(principal.role == 'MANAGER', DENIED)
    if operation['status'] in ('SUCCEEDED', 'CANCELLED'):
        return
    require(
        operation['status'] in ('ACCEPTED', 'RUNNING') and not operation['cancel_requested'],
        UNAVAILABLE,
    )
    _, intent, grant = original_restore_grant(connection, catalog, operation)
    row = restore_registry_row(connection, principal, intent, grant)
    if operation['status'] == 'ACCEPTED':
        return
    _, step = restore_operation(connection, catalog, operation['operation_id'])
    require(
        step['status'] == 'DISPATCHING' and step['external_identity_json'] is not None, RESOURCE
    )
    state = decoded(step['external_identity_json'])
    require(state['maintenance'] == grant, RESOURCE)
    request = state.get('opening')
    if request is None:
        retirement = original_retirement(catalog, grant)
        if retirement is not None:
            record_retirement(connection, operation, state, retirement)
        return
    opened = opened_restore(catalog, grant, request)
    if opened is None:
        return
    selected, receipt = opened
    preview = grant['confirmation']
    origin = business_entry(catalog, row, decoded(row['work_package_json']))
    adopt_opened_deployment(
        connection,
        operation,
        row,
        {
            'source': preview['source'],
            'target': preview['target'],
            'source_attachment': preview['source_attachment'],
            'target_attachment': selected['target_attachment'],
            'release_ref': preview['target_release_ref'],
            'release_manifest_sha256': preview['release_manifest_sha256'],
        },
        request,
        receipt,
        recovery={
            'source_data_generation': preview['source']['data_generation'],
            'backup_id': preview['backup']['backup_id'],
            'backup_cutoff_at': preview['backup']['cutoff_at'],
            'restore_authorization_sha256': preview['restore_authorization_sha256'],
        },
        business_entry=origin,
    )
