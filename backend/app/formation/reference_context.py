"""Freeze reference-only formation facts for an independent non-DISCUSS operation.

Input: the accepted legacy operation and its current owned document.
Output: detached formation/source facts in the existing execution basis.
Invariant: no selection, entity allocation, formation_request or state mutation.
"""

from backend.app.guide.accepted_context import capture_source
from backend.app.requirements.source_refs import verify_source_refs
from backend.app.shared.json_canonical import canonical_input

from .model_material import capture_material, freeze_message_effects, material_sources


def capture_reference_context(connection, root, catalog, basis):
    selection = {
        'discussion_step_ref': None,
        'discussion_branch_ref': None,
        'branch_intent': None,
        'branch_resume_basis': None,
    }
    material = capture_material(connection, root, selection, catalog)
    references = material_sources(material)
    verify_source_refs(connection, root['id'], references, resources=catalog.collaboration)
    snapshots = {canonical_input(item['source_ref']): item for item in basis['source_snapshots']}
    for source in references:
        name = canonical_input(source)
        if name not in snapshots:
            snapshots[name] = capture_source(connection, root['id'], source, catalog.collaboration)
    basis.update(
        formation=material,
        formation_selection=None,
        proposal_context=None,
        source_snapshots=list(snapshots.values()),
    )
    basis['message_effects'] = freeze_message_effects(connection, basis)
