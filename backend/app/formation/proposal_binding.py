"""Program-owned proposal protection; global counters and self flags are never authority."""

import hashlib
from copy import deepcopy

from backend.app.shared.command_execution import Rejected
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import strict_integer, strict_json_loads

from .digests import digest_rows
from .repository import FormationRepository
from .source_semantics import source_digest
from .types import proposal as proposal_reference

SCHEMA = 'formation_card_binding_v21_1'
PROTECTED_FIELDS = (
    'payload_digest',
    'goal_version',
    'document_revision_id',
    'content_version',
    'step_definitions',
    'source_heads',
    'related_entries',
)


def digest(value):
    return hashlib.sha256(canonical_input(value).encode('utf-8')).hexdigest()


def scope_for(purpose, payload):
    steps, entities, titles = set(), set(), set()

    def step(ref):
        if type(ref) is str and ref.startswith('s') and '.o' not in ref:
            steps.add(ref)

    if purpose == 'STAGED_WRITE':
        step(payload['step_ref'])
        for ref in payload['result_refs']:
            entities.add(('RESULT', ref))
    elif purpose == 'FORMATION_PATH_CHANGE':
        for change in payload['changes']:
            for name in ('step_ref', 'to_step_ref', 'return_step_ref', 'before_step_ref'):
                step(change.get(name))
            for name in ('dependencies', 'replaces_step_refs', 'replacement_step_refs'):
                for ref in change.get(name, []):
                    step(ref)
            if change['type'] == 'RENAME_STEP':
                titles.add(change['step_ref'])
            for kind, name in (
                ('RESULT', 'result_ref'),
                ('ISSUE', 'issue_ref'),
                ('BRANCH', 'branch_ref'),
            ):
                if name in change:
                    entities.add((kind, change[name]))
            for ref in change.get('result_refs', []):
                if not ref.startswith('new_'):
                    entities.add(('RESULT', ref))
        for route in payload['result_routes']:
            entities.add(('RESULT', route['from_result_ref']))
            for ref in route['target_result_refs']:
                if not ref.startswith('new_'):
                    entities.add(('RESULT', ref))
    else:
        raise ValueError('Unknown proposal purpose')
    for kind, ref in entities:
        if kind == 'RESULT':
            step(ref.split('.o')[0])
    return {
        'step_refs': sorted(steps, key=lambda ref: int(ref[1:])),
        'entities': [{'kind': kind, 'ref': ref} for kind, ref in sorted(entities)],
        'title_refs': sorted(titles),
    }


def entity_semantic(connection, document_id, kind, ref):
    registry = {
        'RESULT': (
            'formation_results',
            'result_ref',
            ('result_ref', 'step_ref', 'description', 'kind'),
        ),
        'ISSUE': (
            'formation_issues',
            'issue_ref',
            (
                'issue_ref',
                'step_ref',
                'branch_ref',
                'description',
                'blocking',
                'disposition',
                'disposition_reason',
                'source_refs_json',
                'resolution_sources_json',
            ),
        ),
        'BRANCH': (
            'formation_branches',
            'branch_ref',
            (
                'branch_ref',
                'return_step_ref',
                'question',
                'relevance',
                'status',
                'state_event_id',
                'result_summary',
                'result_sources_json',
            ),
        ),
        'ARTIFACT': (
            'formation_artifacts',
            'artifact_ref',
            (
                'artifact_ref',
                'step_ref',
                'origin_revision_id',
                'origin_digest',
                'checked_against_revision_id',
                'freshness',
                'review_reason',
            ),
        ),
    }
    table, identity, columns = registry[kind]
    row = connection.execute(
        f'SELECT * FROM {table} WHERE document_id=? AND {identity}=?', (document_id, ref)
    ).fetchone()
    if row is None:
        raise Rejected('SOURCE_INVALID')
    value = {
        name: strict_json_loads(row[name]) if name.endswith('_json') else row[name]
        for name in columns
    }
    if kind == 'ARTIFACT':
        value['results'] = [
            item[0]
            for item in connection.execute(
                'SELECT result_ref FROM formation_artifact_results WHERE document_id=? AND artifact_ref=? ORDER BY result_ref',
                (document_id, ref),
            )
        ]
        value['ranges'] = [
            dict(item)
            for item in connection.execute(
                'SELECT role,ordinal,revision_id,block_id,block_digest FROM formation_artifact_ranges '
                'WHERE document_id=? AND artifact_ref=? ORDER BY role,ordinal',
                (document_id, ref),
            )
        ]
        value['successor'] = [
            dict(item)
            for item in connection.execute(
                'SELECT replacement_artifact_ref FROM formation_artifact_reviews WHERE document_id=? '
                "AND reviewed_artifact_ref=? AND result='REASSOCIATED'",
                (document_id, ref),
            )
        ]
    return value


def protected_projection(connection, root, purpose, payload, resources):
    document_id = root['assistant_document_id']
    head = FormationRepository(connection).head(document_id, required=True)
    document = connection.execute(
        'SELECT d.content_version,r.id FROM requirement_documents d JOIN revisions r '
        'ON r.document_id=d.id AND r.source_content_version=d.content_version WHERE d.id=?',
        (document_id,),
    ).fetchone()
    if document is None:
        raise ValueError('Proposal document lost its actual revision')
    scope = scope_for(purpose, payload)
    parents = set(scope['step_refs'])
    related = {(item['kind'], item['ref']) for item in scope['entities']}
    for kind, ref in tuple(related):
        value = entity_semantic(connection, document_id, kind, ref)
        owner = value.get('step_ref', value.get('return_step_ref'))
        if owner is not None:
            parents.add(owner)
        if kind == 'ISSUE' and value['branch_ref'] is not None:
            related.add(('BRANCH', value['branch_ref']))
    scope['step_refs'] = sorted(parents, key=lambda ref: int(ref[1:]))
    scope['entities'] = [{'kind': kind, 'ref': ref} for kind, ref in sorted(related)]
    definitions, entries = [], []
    for ref in scope['step_refs']:
        row = connection.execute(
            'SELECT * FROM formation_steps WHERE document_id=? AND step_ref=?', (document_id, ref)
        ).fetchone()
        if row is None:
            raise Rejected('SOURCE_INVALID')
        definitions.append({'step_ref': ref, 'definition_version': row['definition_version']})
        semantic = {'definition_version': row['definition_version']}
        if ref in scope['title_refs']:
            semantic['title'] = row['title']
        entries.append(
            {'entity_kind': 'STEP', 'entity_ref': ref, 'semantic_digest': digest(semantic)}
        )
        # Include empty sets, incoming edges and all owned members. A new relation cannot escape the binding.
        sets = {
            'EDGES': (
                (
                    'SELECT from_step_ref,to_step_ref,kind FROM formation_step_edges WHERE document_id=? '
                    'AND (from_step_ref=? OR to_step_ref=?) ORDER BY from_step_ref,to_step_ref,kind'
                ),
                (document_id, ref, ref),
            ),
            'RESULTS': (
                'SELECT result_ref,description,kind FROM formation_results WHERE document_id=? AND step_ref=? ORDER BY result_ref',
                (document_id, ref),
            ),
            'ISSUES': (
                'SELECT issue_ref FROM formation_issues WHERE document_id=? AND step_ref=? ORDER BY issue_ref',
                (document_id, ref),
            ),
            'BRANCHES': (
                'SELECT branch_ref FROM formation_branches WHERE document_id=? AND return_step_ref=? ORDER BY branch_ref',
                (document_id, ref),
            ),
        }
        for name, (sql, parameters) in sets.items():

            def values(sql=sql, parameters=parameters, name=name):
                for item in connection.execute(sql, parameters):
                    row = dict(item)
                    if name == 'ISSUES':
                        yield entity_semantic(connection, document_id, 'ISSUE', row['issue_ref'])
                    elif name == 'BRANCHES':
                        yield entity_semantic(connection, document_id, 'BRANCH', row['branch_ref'])
                    else:
                        yield row

            entries.append(
                {
                    'entity_kind': 'RELATION_SET',
                    'entity_ref': ref + ':' + name,
                    'semantic_digest': digest_rows(values()),
                }
            )

        def artifacts(ref=ref):
            for item in connection.execute(
                'SELECT a.artifact_ref FROM formation_artifacts a WHERE a.document_id=? AND a.step_ref=? '
                'AND NOT EXISTS(SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
                "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED') ORDER BY a.artifact_ref",
                (document_id, ref),
            ):
                yield entity_semantic(connection, document_id, 'ARTIFACT', item[0])

        entries.append(
            {
                'entity_kind': 'RELATION_SET',
                'entity_ref': ref + ':ARTIFACTS',
                'semantic_digest': digest_rows(artifacts()),
            }
        )
    for entity in scope['entities']:
        entries.append(
            {
                'entity_kind': entity['kind'],
                'entity_ref': entity['ref'],
                'semantic_digest': digest(
                    entity_semantic(connection, document_id, entity['kind'], entity['ref'])
                ),
            }
        )
    source_refs = payload['source_refs']
    source_heads = []
    for source in sorted(source_refs, key=canonical_input):
        source_heads.append(
            {
                'source_ref': deepcopy(source),
                'version_token': str(source['revision_id'])
                if source['kind'] == 'REVISION'
                else None,
                'head_digest': source_digest(
                    connection, root['id'], source, resources.collaboration
                ),
            }
        )
    return {
        'payload_digest': digest(payload),
        'goal_version': head['goal_version'],
        'document_revision_id': document['id'],
        'content_version': document['content_version'],
        'step_definitions': definitions,
        'source_heads': source_heads,
        'related_entries': sorted(
            entries, key=lambda item: (item['entity_kind'], item['entity_ref'])
        ),
    }


def publish_binding(connection, root, purpose, payload, reference, frozen_f, resources):
    proposal_reference(reference, 'proposal')
    if frozen_f is not None:
        strict_integer(frozen_f, 'origin_frozen_formation_version')
    projection = protected_projection(connection, root, purpose, payload, resources)
    basis = payload if purpose == 'STAGED_WRITE' else payload['basis']
    for name in ('goal_version', 'document_revision_id', 'content_version'):
        if basis[name] != projection[name]:
            raise Rejected('SOURCE_INVALID')

    if purpose == 'STAGED_WRITE':
        owner = next(
            item
            for item in projection['step_definitions']
            if item['step_ref'] == payload['step_ref']
        )
        if payload['definition_version'] != owner['definition_version']:
            raise Rejected('SOURCE_INVALID')
    validate_use(connection, root, purpose, payload, reference)

    return {
        'schema': SCHEMA,
        'proposal': deepcopy(reference),
        'purpose': purpose,
        'origin_frozen_formation_version': frozen_f,
        **projection,
        'protected_semantic_digest': digest(projection),
    }


def check_binding(connection, root, proposal, purpose, resources):
    original = proposal.binding
    required = {
        'schema',
        'proposal',
        'purpose',
        'origin_frozen_formation_version',
        'protected_semantic_digest',
        *PROTECTED_FIELDS,
    }
    if (
        set(original) != required
        or original['schema'] != SCHEMA
        or original['proposal'] != proposal.reference
        or original['purpose'] != purpose
        or original['payload_digest'] != digest(proposal.payload)
    ):
        raise ValueError('Original publication binding is missing or damaged')
    projection = {key: original[key] for key in PROTECTED_FIELDS}
    if digest(projection) != original['protected_semantic_digest']:
        raise ValueError('Original protected projection digest differs')
    current = protected_projection(connection, root, purpose, proposal.payload, resources)
    if digest(current) != original['protected_semantic_digest']:
        raise Rejected(
            'STATE_CONFLICT',
            details={
                'reason': 'PROPOSAL_BASIS_CHANGED',
                'step_ref': None,
                'proposal': proposal.reference,
            },
        )
    validate_use(connection, root, purpose, proposal.payload, proposal.reference)
    return original['protected_semantic_digest']


def validate_use(connection, root, purpose, payload, reference):
    # Lifecycle is an independent permission and never a way to alter a use fingerprint.
    if purpose == 'STAGED_WRITE':
        status = connection.execute(
            'SELECT status FROM formation_steps WHERE document_id=? AND step_ref=?',
            (root['assistant_document_id'], payload['step_ref']),
        ).fetchone()
        if status is None or status[0] == 'CANCELLED':
            raise Rejected(
                'STATE_CONFLICT',
                details={
                    'reason': 'INVALID_TRANSITION',
                    'step_ref': payload['step_ref'],
                    'proposal': reference,
                },
            )
    elif any(
        change['type'] == 'CANCEL_STEP'
        and connection.execute(
            'SELECT status FROM formation_steps WHERE document_id=? AND step_ref=?',
            (root['assistant_document_id'], change['step_ref']),
        ).fetchone()[0]
        not in ('PLANNED', 'IN_PROGRESS', 'PAUSED')
        for change in payload['changes']
    ):
        raise Rejected(
            'STATE_CONFLICT',
            details={
                'reason': 'INVALID_TRANSITION',
                'step_ref': None,
                'proposal': reference,
            },
        )
    if purpose == 'FORMATION_PATH_CHANGE':
        from .path_plan import prepare_route

        head, steps, branches, issues, edges = FormationRepository(connection).graph(
            root['assistant_document_id']
        )
        results = {
            row['result_ref']: dict(row)
            for row in connection.execute(
                'SELECT * FROM formation_results WHERE document_id=?',
                (root['assistant_document_id'],),
            )
        }
        prepare_route(
            head,
            steps,
            results,
            branches,
            issues,
            set(edges['DEPENDENCY']),
            set(edges['REPLACES']),
            payload['changes'],
            payload['result_routes'],
        )
