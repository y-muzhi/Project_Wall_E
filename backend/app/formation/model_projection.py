"""One deterministic model projection from accepted facts; never queries or widens material."""

from copy import deepcopy

from backend.app.infrastructure.schema_transport import compact


def project_material(value, resolve):
    result = deepcopy(value)

    def visit(item):
        if isinstance(item, dict):
            for name, child in item.items():
                if name in (
                    'source_refs',
                    'origin_source_refs',
                    'result_source_refs',
                    'resolution_source_refs',
                ):
                    item[name] = list(dict.fromkeys(resolve(source) for source in child))
                else:
                    visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(result)
    return result


def append_proposal_material(canonical, goal, alias, material, resolve):
    proposal = canonical['proposal_context']
    if proposal is None:
        return
    reference = proposal['proposal_ref']
    sources = [{'kind': 'MESSAGE', 'message_id': reference['message_id']}]
    name = 'm' + str(reference['message_id']) + ':' + reference['card_key']
    alias(name, sources)
    # Exact Markdown/patch strings are retained; only source addresses become
    # this Wire's aliases, while the immutable canonical payload remains private.
    projected = project_material(proposal, resolve)
    goal.append(
        {
            'ref': name,
            'origin': 'AI_PROPOSAL',
            'text': compact(projected),
            'source_refs': [resolve(source) for source in sources],
            'nature': 'PROPOSAL',
            'applies_to': 'GLOBAL',
        }
    )
    material(
        name,
        'MESSAGE',
        sources,
        ['REFERENCE'],
        'ORIGINAL_FORMATION_PROPOSAL',
        message_ids=[reference['message_id']],
    )
