"""Read-only effects anchored at the actual trigger message in a visible window."""

import json

from backend.app.shared.validation import object_fields, raw_text, strict_enum, strict_integer

DOCUMENT_OPERATIONS = ('GENERATE', 'REVISE', 'PROPOSE_CHANGES')
OPERATIONS = (*DOCUMENT_OPERATIONS, 'DISCUSS')
STATES = (
    'RUNNING',
    'FAILED',
    'CANCELLED',
    'SAVED',
    'PENDING_REVIEW',
    'OUTDATED',
    'APPLIED',
    'DISCARDED',
    'NO_CHANGE',
    'NOT_APPLIED',
    'PROGRESS_UPDATED',
)
FIELDS = (
    'run_id',
    'operation',
    'state',
    'document_id',
    'document_name',
    'scope_type',
    'scope_label',
    'base_content_version',
    'saved_content_version',
    'batch_id',
    'reason',
)


def guide_operation(value):
    item = object_fields(value, 'guide_operation', FIELDS, FIELDS)
    strict_integer(item['run_id'], 'run_id')
    strict_enum(item['operation'], 'operation', OPERATIONS)
    strict_enum(item['state'], 'state', STATES)
    for field in ('document_id', 'base_content_version', 'saved_content_version', 'batch_id'):
        if item[field] is not None:
            strict_integer(item[field], field)
    for field in ('document_name', 'scope_label', 'reason'):
        if item[field] is not None:
            raw_text(item[field], field, 1, 300)
    if item['scope_type'] is not None:
        strict_enum(item['scope_type'], 'scope_type', ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'))
    if item['state'] in ('SAVED', 'APPLIED') and (
        item['document_id'] is None or item['saved_content_version'] is None
    ):
        raise ValueError('A saved version requires its actual document')
    if (
        item['state'] in ('PENDING_REVIEW', 'OUTDATED', 'APPLIED', 'DISCARDED')
        and item['batch_id'] is None
    ):
        raise ValueError('A review outcome requires the actual batch')
    return dict(item)


def _scope_label(connection, run, requirement_id, document_id):
    if (
        run['scope_type'] != 'SECTION'
        or not run['scope_ref_json']
        or run['expected_content_version'] is None
    ):
        return None
    scope = json.loads(run['scope_ref_json'])
    heading = scope.get('heading_block_id') or scope.get('block_id')
    row = connection.execute(
        """SELECT json_extract(b.value,'$.section_path[#-1]') FROM revisions r
           JOIN json_each(r.block_state_snapshot_json,'$.blocks') b
           WHERE r.requirement_id=? AND r.document_id=? AND r.source_content_version=?
             AND json_extract(b.value,'$.block_id')=? AND json_extract(b.value,'$.block_type')='heading'""",
        (requirement_id, document_id, run['expected_content_version'], heading),
    ).fetchone()
    return row[0][:300] if row is not None and row[0] else None


def read_guide_operations(connection, requirement_id, document_id, visible):
    if not visible:
        return {}, frozenset()
    markers = ','.join('?' for _ in visible)
    runs = connection.execute(
        """SELECT g.id,g.operation,g.status,g.trigger_message_id,g.scope_type,g.scope_ref_json,g.error_message,
                  g.final_result_json,g.target_document_id,
                  coalesce(b.base_content_version,json_extract(g.execution_basis_json,'$.authorization.expected_content_version'))
                    AS expected_content_version,
                  b.id AS batch_id,b.status AS batch_status,b.applied_content_version
           FROM guide_runs g LEFT JOIN suggestion_batches b
             ON b.guide_run_id=g.id AND b.requirement_id=g.requirement_id
           WHERE g.requirement_id=? AND g.document_id=?
             AND g.operation IN ('GENERATE','REVISE','PROPOSE_CHANGES','DISCUSS')
             AND (g.trigger_message_id IN ("""
        + markers
        + """) OR g.id IN (
                SELECT guide_run_id FROM conversation_messages WHERE id IN ("""
        + markers
        + """)
             ))
           ORDER BY g.id""",
        (requirement_id, document_id, *visible, *visible),
    )
    receipts, hidden = {}, set()
    for run in runs:
        effects = json.loads(run['final_result_json'] or '{}')
        state = run['status']
        operation = run['operation']
        if operation == 'DISCUSS':
            if (
                effects.get('progress_result') != 'APPLIED'
                or effects.get('formation_result') == 'APPLIED'
            ):
                continue
            state = 'PROGRESS_UPDATED'
        else:
            hidden.add(run['id'])
        if run['trigger_message_id'] not in visible:
            continue
        effect = effects.get('document_effect') or {}
        target = effect.get('document_id') or run['target_document_id'] or document_id
        current = connection.execute(
            "SELECT name,content_version FROM requirement_documents WHERE id=? AND requirement_id=? AND document_type='CURRENT'",
            (target, requirement_id),
        ).fetchone()
        saved = None
        reason = None
        if state == 'COMPLETED':
            if run['batch_status'] == 'PENDING':
                state = (
                    'PENDING_REVIEW'
                    if current is not None
                    and current['content_version'] == run['expected_content_version']
                    else 'OUTDATED'
                )
            elif run['batch_status'] == 'DISCARDED':
                state = 'DISCARDED'
            elif run['batch_status'] == 'COMPLETED':
                saved = run['applied_content_version']
                state = 'APPLIED' if saved is not None else 'NO_CHANGE'
            elif effect.get('result') in ('CREATED', 'UPDATED'):
                state, saved = 'SAVED', effect['after_content_version']
            elif effects.get('application_result') == 'NO_CHANGE':
                state = 'NO_CHANGE'
            else:
                state = 'NOT_APPLIED'
                reason = effects.get('validation_error')
        elif state == 'FAILED':
            reason = run['error_message']
        receipt = guide_operation(
            {
                'run_id': run['id'],
                'operation': operation,
                'state': state,
                'document_id': target if current else None,
                'document_name': current['name'] if current else None,
                'scope_type': run['scope_type'],
                'scope_label': _scope_label(connection, run, requirement_id, target),
                'base_content_version': run['expected_content_version'],
                'saved_content_version': saved,
                'batch_id': run['batch_id'],
                'reason': reason[:300] if reason else None,
            }
        )
        receipts.setdefault(run['trigger_message_id'], []).append(receipt)
    return receipts, frozenset(hidden)
