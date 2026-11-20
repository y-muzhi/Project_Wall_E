"""Program-owned recommendation basis and precise currentness, independent from global D/F."""

from copy import deepcopy

from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_json_loads

from .artifact_links import block_digest
from .digests import digest_rows
from .history_contracts import validate
from .proposal_binding import digest, entity_semantic

RELATIONS = ('OPEN_ISSUES', 'OPEN_BRANCHES', 'ACTIVE_ARTIFACTS')


def relation_digest(context, step_ref, kind):
    sql = {
        'OPEN_ISSUES': (
            'ISSUE',
            (
                'SELECT issue_ref FROM formation_issues WHERE document_id=? AND step_ref=? '
                "AND disposition='OPEN' ORDER BY CAST(substr(issue_ref,2) AS INTEGER)"
            ),
        ),
        'OPEN_BRANCHES': (
            'BRANCH',
            (
                'SELECT branch_ref FROM formation_branches WHERE document_id=? AND return_step_ref=? '
                "AND status='OPEN' ORDER BY CAST(substr(branch_ref,2) AS INTEGER)"
            ),
        ),
        'ACTIVE_ARTIFACTS': (
            'ARTIFACT',
            (
                'SELECT a.artifact_ref FROM formation_artifacts a WHERE a.document_id=? AND a.step_ref=? '
                'AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
                "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED') "
                'ORDER BY CAST(substr(a.artifact_ref,2) AS INTEGER)'
            ),
        ),
    }
    entity_kind, query = sql[kind]
    return digest_rows(
        {
            'kind': entity_kind,
            'ref': row[0],
            'semantic_digest': digest(
                entity_semantic(context.connection, context.document_id, entity_kind, row[0])
            ),
        }
        for row in context.connection.execute(query, (context.document_id, step_ref))
    )


def step_basis(context, step_ref):
    row = context.connection.execute(
        'SELECT step_ref,definition_version,status FROM formation_steps WHERE document_id=? AND step_ref=?',
        (context.document_id, step_ref),
    ).fetchone()
    if row is None:
        raise Rejected('SOURCE_INVALID')
    return dict(row)


def capture_basis(
    context,
    owner_step_ref,
    target_step_ref,
    coverage_ids,
    source_refs,
    entities,
    *,
    carried_block_ids,
):
    """Caller supplies only aliases already resolved from this audited round's carried material."""
    if not set(coverage_ids) <= set(carried_block_ids) or any(
        ref not in context.blocks for ref in coverage_ids
    ):
        raise Rejected('SOURCE_INVALID')
    owner = step_basis(context, owner_step_ref)
    target = None if target_step_ref is None else step_basis(context, target_step_ref)
    related_steps = [owner_step_ref]
    if target_step_ref is not None and target_step_ref != owner_step_ref:
        related_steps.append(target_step_ref)
    unique_entities = sorted({(item['kind'], item['ref']) for item in entities})
    source_map = {digest(source): source for source in source_refs}
    sources = sorted(
        source_map.values(), key=lambda source: canonical_input(source).encode('utf-8')
    )
    basis = {
        'schema': 'formation_recommendation_basis_v21_1',
        'goal_version': context.head['goal_version'],
        'owner_step_ref': owner_step_ref,
        'owner_definition_version': owner['definition_version'],
        'owner_status': owner['status'],
        'evaluated_revision_id': context.current['revision_id'],
        'coverage': [
            {
                'block_id': identity,
                'block_digest': block_digest(context.blocks[identity][0].markdown),
            }
            for identity in sorted(set(coverage_ids))
        ],
        'target_step': target,
        'entity_basis': [
            {
                'kind': kind,
                'ref': ref,
                'semantic_digest': digest(
                    entity_semantic(context.connection, context.document_id, kind, ref)
                ),
            }
            for kind, ref in unique_entities
        ],
        'relation_sets': [
            {'kind': kind, 'step_ref': step, 'digest': relation_digest(context, step, kind)}
            for step in related_steps
            for kind in RELATIONS
        ],
        'source_heads': [
            {'source_ref': deepcopy(source), 'head_digest': context.source_head(source)}
            for source in sources
        ],
    }
    return validate('RecommendationBasis', basis)


def stale_reason(context, basis):
    basis = validate('RecommendationBasis', basis)
    if context.head['goal_version'] != basis['goal_version']:
        return 'GOAL_CHANGED'
    try:
        owner = step_basis(context, basis['owner_step_ref'])
    except Rejected:
        return 'OWNER_DEFINITION_CHANGED'
    if owner['definition_version'] != basis['owner_definition_version']:
        return 'OWNER_DEFINITION_CHANGED'
    if owner['status'] != basis['owner_status']:
        return 'OWNER_STATE_CHANGED'
    if basis['target_step'] is not None:
        try:
            if step_basis(context, basis['target_step']['step_ref']) != basis['target_step']:
                return 'TARGET_CHANGED'
        except Rejected:
            return 'TARGET_CHANGED'
    if not context.coverage_matches(basis['coverage']):
        return 'COVERAGE_CHANGED'
    source_changed = False
    for item in basis['source_heads']:
        try:
            if context.source_head(item['source_ref']) != item['head_digest']:
                source_changed = True
        except (Rejected, ConfigInvalid, ValueError, TypeError):
            return 'SOURCE_UNAVAILABLE'
    if source_changed:
        return 'RELATED_FACT_CHANGED'
    for item in basis['entity_basis']:
        try:
            current = digest(
                entity_semantic(context.connection, context.document_id, item['kind'], item['ref'])
            )
        except Rejected:
            return 'RELATED_FACT_CHANGED'
        if current != item['semantic_digest']:
            return 'RELATED_FACT_CHANGED'
    for item in basis['relation_sets']:
        if relation_digest(context, item['step_ref'], item['kind']) != item['digest']:
            return 'RELATED_FACT_CHANGED'
    return None


def latest_recommendation(context, step_ref):
    row = context.connection.execute(
        'SELECT * FROM formation_recommendations WHERE document_id=? AND step_ref=? ORDER BY event_id DESC,id DESC LIMIT 1',
        (context.document_id, step_ref),
    ).fetchone()
    if row is None:
        return None
    value = {
        'action': row['action'],
        'step_ref': row['target_step_ref'],
        'reason': row['reason'],
        'source_refs': strict_json_loads(row['source_refs_json']),
        'assistant_message_id': row['assistant_message_id'],
        'basis': strict_json_loads(row['basis_json']),
    }
    validate('RecommendationSnapshot', value)
    reason = stale_reason(context, value['basis'])
    return {**value, 'validity': 'CURRENT' if reason is None else 'STALE', 'stale_reason': reason}
