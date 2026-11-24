"""Document-scoped evidence associations preserved with their committing discussion run."""

from backend.app.guide.progress_application import ProgressInvalid
from .model_evidence import ModelEvidence


def linked_evidence(connection, requirement, document, step):
    return {
        row[0]
        for row in connection.execute(
            "SELECT json_extract(l.value,'$.evidence_ref') FROM guide_runs r,json_each(r.final_result_json,'$.step_evidence_links') l WHERE r.requirement_id=? AND r.document_id=? AND r.status='COMPLETED' AND json_extract(l.value,'$.step_ref')=?",
            (requirement, document, step),
        )
    }


def bind_links(
    connection, root, context, catalog, requested, discussion, mapping, formation_effect
):
    if not requested:
        return []
    document = root['assistant_document_id']
    allowed = {row['ref'] for row in context.input['goal_and_decisions']}
    allowed.update(
        row['evidence_ref']
        for row in context.input['project_position']['formation']['route_context']['decisions']
    )
    allowed.update(mapping.values())
    decisions = {row['evidence_ref']: row for row in discussion['evidence']}
    steps = {
        row['temp_ref']: row['resolved_ref']
        for row in (formation_effect or {}).get('reference_map', [])
    }
    evidence = ModelEvidence(connection, root, context, catalog)
    links = []
    existing = {}
    for requested_link in requested:
        target = requested_link['step_ref']
        evidence.require_visible('STEP', target, newly_declared=steps)
        step = steps.get(target, target)
        ref = mapping.get(requested_link['evidence_ref'], requested_link['evidence_ref'])
        row = decisions.get(ref)
        if (
            ref not in allowed
            or not row
            or row['state'] != 'ACTIVE'
            or row['origin'] not in ('USER_STATEMENT', 'USER_DECISION')
            or row['nature'] == 'PROPOSAL'
            or not row['source_refs']
        ):
            raise ProgressInvalid('A step association needs a carried, active user decision')
        if step not in existing:
            if not connection.execute(
                "SELECT 1 FROM formation_steps WHERE document_id=? AND step_ref=? AND status<>'CANCELLED'",
                (document, step),
            ).fetchone():
                raise ProgressInvalid('A step association needs an effective document step')
            existing[step] = linked_evidence(connection, root['id'], document, step)
        if ref not in existing[step]:
            existing[step].add(ref)
            links.append({'step_ref': step, 'evidence_ref': ref})
    return links
