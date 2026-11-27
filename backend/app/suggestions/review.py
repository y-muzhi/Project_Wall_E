"""Version-bound review of the existing batch and durable decision receipts."""

import json

from backend.app.infrastructure.batch_repository import has_independent_review
from backend.app.infrastructure.idempotency import generation_namespace
from backend.app.infrastructure.revision_repository import RevisionRepository
from backend.app.shared.command_execution import Rejected
from backend.app.shared.validation import object_fields, raw_text, strict_integer

GROUP_DECISION = 'APP-BATCH-CMD-C05'
GENERATION_TARGET = generation_namespace('????????-????-4???-[89ab]???-????????????')


def validate_groups(value, count):
    """Wire and persisted groups address stable, one-based patch order."""
    if type(value) is not list or not 1 <= len(value) <= count:
        raise ValueError('A group is required for every proposed patch')
    groups, orders = [], []
    for row in value:
        fields = ('title', 'reason', 'suggestion_orders')
        item = object_fields(row, 'review_group', fields, fields)
        members = item['suggestion_orders']
        if type(members) is not list or not 1 <= len(members) <= count:
            raise ValueError('A group must contain actual patch orders')
        members = [strict_integer(order, 'suggestion_orders', maximum=count) for order in members]
        if members != sorted(members):
            raise ValueError('Group member order must match patch order')
        orders.extend(members)
        groups.append(
            {
                'title': raw_text(item['title'], 'title', 1, 120),
                'reason': raw_text(item['reason'], 'reason', 1, 600),
                'suggestion_orders': members,
            }
        )
    if sorted(orders) != list(range(1, count + 1)):
        raise ValueError('Review groups must partition the actual proposed patches')
    return groups


def stored_groups(parent):
    return json.loads(parent['final_result_json'] or '{}').get('review_groups')


def review_groups(parent, suggestions):
    stored = stored_groups(parent)
    if stored is None:
        return [
            {
                'group_id': item['order_no'],
                'title': item['title'],
                'reason': item['explanation'],
                'suggestion_ids': [item['id']],
                'status': item['status'],
            }
            for item in suggestions
        ]
    items = {item['order_no']: item for item in suggestions}
    projected = []
    for identity, group in enumerate(validate_groups(stored, len(items)), 1):
        members = [items[order] for order in group['suggestion_orders']]
        statuses = {item['status'] for item in members}
        if len(statuses) != 1 or 'EDITED' in statuses:
            raise ValueError('An atomic group has inconsistent stored decisions')
        projected.append(
            {
                'group_id': identity,
                'title': group['title'],
                'reason': group['reason'],
                'suggestion_ids': [item['id'] for item in members],
                'status': members[0]['status'],
            }
        )
    return projected


def decision_version(connection, batch_id):
    # A retained batch keeps its review version when its receipts move to a new generation.
    group_target = f'Batch:{batch_id}'
    return (
        1
        + connection.execute(
            """SELECT count(*) FROM idempotency_records i
           WHERE i.status='SUCCEEDED' AND (
               (i.capability_id IN ('APP-BATCH-CMD-C04', ?) AND (
                   i.target_identity=? OR i.target_identity GLOB ? || ?
               ))
               OR (i.capability_id='APP-BATCH-CMD-C01' AND EXISTS (
                   SELECT 1 FROM suggestions WHERE batch_id=? AND (
                       i.target_identity='Suggestion:' || id
                       OR i.target_identity GLOB ? || 'Suggestion:' || id
                   )
               ))
           )""",
            (
                GROUP_DECISION,
                group_target,
                GENERATION_TARGET,
                group_target,
                batch_id,
                GENERATION_TARGET,
            ),
        ).fetchone()[0]
    )


def check_decision_version(connection, batch_id, expected):
    current = decision_version(connection, batch_id)
    if expected != current:
        raise Rejected(
            'DECISION_VERSION_CONFLICT',
            details={
                'expected_version': expected,
                'actual_version': current,
                'resource_kind': 'SuggestionBatch',
                'resource_id': batch_id,
            },
        )
    return current


def review_projection(connection, batch, parent):
    revisions = RevisionRepository(connection)

    def version_ref(version):
        if version is None:
            return None
        row = revisions.current(batch['target_document_id'], version)
        if row is None:
            return None
        if row['requirement_id'] != batch['requirement_id']:
            raise ValueError('Review version must belong to the actual target')
        return row['id']

    return {
        'base_revision_id': version_ref(batch['base_content_version']),
        'applied_revision_id': version_ref(batch['applied_content_version']),
        'groups': review_groups(parent, batch['suggestions']),
        'decision_version': decision_version(connection, batch['id']),
        'independent': has_independent_review(parent),
        'grouped': stored_groups(parent) is not None,
    }
