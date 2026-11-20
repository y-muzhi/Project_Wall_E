"""Program review classification over real live ranges; no AI verdict becomes a storage proof."""

from .artifact_links import current_artifact_matches
from .read_context import ReadContext


def classify_associations(plan):
    context = (
        ReadContext(plan.evidence.connection, plan.evidence.root, plan.evidence.catalog)
        if not plan.initializing
        else None
    )
    result = []
    for item in plan.associations:
        old = item['reviewed']
        classification = None
        if old is not None:
            ranges = tuple(
                (row['block_id'], row['block_digest'])
                for row in plan.evidence.connection.execute(
                    "SELECT block_id,block_digest FROM formation_artifact_ranges WHERE document_id=? AND artifact_ref=? AND role='CURRENT' ORDER BY ordinal",
                    (plan.route.head['document_id'], old['artifact_ref']),
                )
            )
            verified = item['verified']
            actual = current_artifact_matches(
                plan.evidence.connection, plan.route.head['document_id'], old, context.blocks
            )
            if actual:
                classification = 'MATCHED' if ranges == verified.ranges else 'UNVERIFIED'
            else:
                classification = 'REASSOCIATED'
        result.append({**item, 'review_result': classification})
    return tuple(result)
