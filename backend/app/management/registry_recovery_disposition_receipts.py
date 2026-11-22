"""Read the protected, typed dispositions published after registry commit."""

import os
from contextlib import ExitStack

from backend.app.infrastructure.environment_files import (
    MAX_REVISION,
    canonical,
    decode,
    digest,
    exact,
    require,
)
from backend.app.infrastructure.environment_installation import sha_value, uuid_value

from .registry import is_timestamp
from .registry_recovery_backup import STEP as BACKUP_STEP
from .registry_recovery_backup import matches_step_status
from .registry_recovery_disposition import CURRENT_FIELDS, RECEIPTS, RECORDED, receipt_bytes
from .registry_recovery_outcome import (
    BACKUP_COMPLETED,
    COLUMNS,
    UNDISPATCHED,
    UNVERIFIED,
    matching_original,
)
from .registry_recovery_undispatched import ORIGINAL_FIELDS
from .registry_snapshot import snapshot_directory

EVIDENCE_FIELDS = (
    *ORIGINAL_FIELDS,
    'environment_id',
    'original_status',
    'step_kind',
    'disposition',
)
RECEIPT_SCOPE = (*CURRENT_FIELDS, 'recovery_operation_id', 'selection_receipt_sha256')


def permitted_evidence(value, disposition):
    if disposition == UNDISPATCHED:
        evidence = exact(value, (*EVIDENCE_FIELDS, 'waiting_evidence_sha256'), UNVERIFIED)
        require(
            evidence['original_status'] == 'WAITING_CAPACITY'
            and evidence['step_kind'] == 'RUNTIME_STARTED'
            and sha_value(evidence['waiting_evidence_sha256']),
            UNVERIFIED,
        )
        return evidence
    require(disposition == BACKUP_COMPLETED, UNVERIFIED)
    pins = ('capture_grant_sha256', 'completion_result_sha256')
    evidence = exact(value, (*EVIDENCE_FIELDS, 'backup_id', 'step_status', *pins), UNVERIFIED)
    require(
        matching_original(disposition, 'BACKUP', evidence['original_status'])
        and evidence['step_kind'] == BACKUP_STEP
        and matches_step_status(evidence['original_status'], evidence['step_status'])
        and uuid_value(evidence['backup_id'])
        and all(sha_value(evidence[key]) for key in pins),
        UNVERIFIED,
    )
    return evidence


def read_permitted_receipt(raw, identifier, current, subject, source_pin):
    receipt = exact(
        decode(raw, UNVERIFIED),
        ('format_version', 'status', *RECEIPT_SCOPE, 'outcome', 'evidence'),
        UNVERIFIED,
    )
    outcome = exact(receipt['outcome'], COLUMNS, UNVERIFIED)
    evidence = permitted_evidence(receipt['evidence'], outcome['disposition'])
    require(
        type(receipt['format_version']) is int
        and receipt['format_version'] == 1
        and receipt['status'] == RECORDED
        and receipt['manager_id'] == current.manager_id
        and receipt['host_id'] == current.host_id
        and receipt['registry_generation']
        == outcome['recorded_registry_generation']
        == current.registry_generation
        and receipt['registry_anchor_sha256'] == current.sha256
        and receipt['recovery_operation_id'] == subject['operation_id']
        and receipt['selection_receipt_sha256'] == subject['selection_receipt_sha256']
        and outcome['source_registry_generation'] == subject['source_registry_generation']
        and outcome['source_snapshot_sha256'] == source_pin
        and outcome['operation_id'] == identifier
        and type(outcome['source_revision']) is int
        and 1 <= outcome['source_revision'] <= MAX_REVISION
        and is_timestamp(outcome['recorded_at'])
        and all(
            sha_value(outcome[key])
            for key in ('policy_sha256', 'evidence_sha256', 'source_intent_sha256')
        )
        and outcome['evidence_sha256'] == digest(canonical(evidence))
        and all(evidence[key] == outcome[key] for key in ORIGINAL_FIELDS)
        and uuid_value(evidence['environment_id'])
        and evidence['disposition'] == outcome['disposition'],
        UNVERIFIED,
    )
    return {**receipt, 'receipt_sha256': digest(raw)}


def permitted_dispositions(native, current, subject, source_pin):
    if source_pin is None:
        return {}
    with current.private_directory(native, 'proof') as proof, ExitStack() as opened:
        try:
            directory = opened.enter_context(snapshot_directory(native, current, proof, RECEIPTS))
        except FileNotFoundError:
            return {}
        records = {}
        for name in sorted(os.listdir(directory)):
            identifier = name.removesuffix('.json')
            require(name == identifier + '.json' and uuid_value(identifier), UNVERIFIED)
            raw = receipt_bytes(directory, identifier, current)
            require(raw is not None, UNVERIFIED)
            records[identifier] = read_permitted_receipt(
                raw, identifier, current, subject, source_pin
            )
        return records


def confirms_original_operation(receipt, operation):
    outcome = receipt['outcome']
    evidence = receipt['evidence']
    require(
        outcome['operation_id'] == operation['operation_id']
        and outcome['source_registry_generation'] == operation['registry_generation']
        and outcome['source_revision'] == operation['revision']
        and outcome['source_intent_sha256'] == operation['intent_sha256']
        and matching_original(outcome['disposition'], operation['action'], operation['status'])
        and evidence['original_status'] == operation['status']
        and evidence['environment_id'] == operation['environment_id'],
        UNVERIFIED,
    )


def disposition_manifest(dispositions):
    pins = [
        (identifier, receipt['receipt_sha256'])
        for identifier, receipt in sorted(dispositions.items())
    ]
    return {'count': len(pins), 'sha256': digest(canonical(pins))}
