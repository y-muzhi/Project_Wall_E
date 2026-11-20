"""Ordinary issue/branch/evaluation/association changes on a planned graph, never a SQL write."""

from copy import deepcopy
from dataclasses import replace

from backend.app.guide.progress_application import ProgressInvalid
from backend.app.infrastructure.identifiers import increment

from .json_arrays import json_array


def apply_entities(connection, root, context, evidence, changes, route, mapping, catalog):
    head, steps, results = route.head, route.steps, route.results
    branches, issues = deepcopy(route.branches), deepcopy(route.issues)
    mapping = dict(mapping)
    document_id = root['assistant_document_id']
    branch_topics = {ref: set() for ref in branches}
    for row in connection.execute(
        'SELECT branch_ref,topic_ref FROM formation_branch_topics WHERE document_id=?',
        (document_id,),
    ):
        branch_topics[row['branch_ref']].add(row['topic_ref'])
    declarations = [change for change in changes if change['type'] in ('ADD_BRANCH', 'ADD_ISSUE')]
    if len({change['temp_ref'] for change in declarations}) != len(declarations):
        raise ProgressInvalid('Branch and issue declarations must each be unique')
    for change in declarations:
        kind = 'branch' if change['type'] == 'ADD_BRANCH' else 'issue'
        name = 'next_' + kind + '_no'
        ref = kind[0] + str(head[name])
        head[name] = increment(head[name])
        if ref in (branches if kind == 'branch' else issues):
            raise ProgressInvalid('An allocator cannot reuse an existing identity')
        mapping[change['temp_ref']] = ref

    def mapped(ref):
        return mapping.get(ref, ref)

    def step(ref, *, full=True):
        evidence.require_visible('STEP', ref, newly_declared=mapping, full=full)
        real = mapped(ref)
        if real not in steps:
            raise ProgressInvalid('Step is not in the complete planned graph')
        return real

    topics = {row['topic_ref'] for row in context.canonical['discussion']['topics']}
    for change in declarations:
        ref = mapped(change['temp_ref'])
        if change['type'] == 'ADD_BRANCH':
            origin, target = (
                step(change['origin_step_ref'], full=False),
                step(change['return_step_ref'], full=False),
            )
            if not set(change['topic_refs']) <= topics:
                raise ProgressInvalid('Branch topics were not actual frozen topics')
            branches[ref] = {
                'document_id': document_id,
                'branch_ref': ref,
                'origin_step_ref': origin,
                'return_step_ref': target,
                'question': change['question'],
                'relevance': change['relevance'],
                'status': 'OPEN',
                'origin_event_id': None,
                'state_event_id': None,
                'result_summary': None,
                'result_sources_json': '[]',
                'disposition_event_id': None,
            }
            branch_topics[ref] = set(change['topic_refs'])
        else:
            target = step(change['step_ref'], full=False)
            branch_ref = mapped(change['branch_ref'])
            evidence.require_visible(
                'BRANCH', change['branch_ref'], newly_declared=mapping
            ) if change['branch_ref'] is not None else None
            issues[ref] = {
                'document_id': document_id,
                'issue_ref': ref,
                'step_ref': target,
                'branch_ref': branch_ref,
                'description': change['description'],
                'source_refs_json': json_array(change['source_refs']),
                'blocking': int(change['blocking']),
                'disposition': 'OPEN',
                'disposition_reason': None,
                'resolution_sources_json': '[]',
                'disposition_event_id': None,
            }
    assessments, recommendations, associations = {}, {}, []
    for change in changes:
        kind = change['type']
        if kind == 'UPDATE_ISSUE':
            ref = change['issue_ref']
            evidence.require_visible('ISSUE', ref, newly_declared=mapping)
            value = issues.get(mapped(ref))
            if value is None:
                raise ProgressInvalid('Issue does not belong to this planned document')
            if change['description'] is not None:
                value['description'] = change['description']
            if change['blocking'] is not None:
                value['blocking'] = int(change['blocking'])
            if change['resolution'] is not None:
                if value['disposition'] != 'OPEN':
                    raise ProgressInvalid(
                        'A model cannot override user disposition or silently resume an issue'
                    )
                value.update(
                    disposition='RESOLVED',
                    disposition_reason=change['resolution']['summary'],
                    resolution_sources_json=json_array(change['resolution']['source_refs']),
                    disposition_event_id=None,
                )
        elif kind == 'UPDATE_BRANCH':
            ref = change['branch_ref']
            evidence.require_visible('BRANCH', ref, newly_declared=mapping)
            value = branches.get(mapped(ref))
            if value is None:
                raise ProgressInvalid('Branch does not belong to this planned document')
            if change['topic_refs'] is not None:
                if not set(change['topic_refs']) <= topics:
                    raise ProgressInvalid('Branch topics were not actual frozen topics')
                branch_topics[mapped(ref)] = set(change['topic_refs'])
            if change['result'] is not None:
                if value['status'] != 'OPEN':
                    raise ProgressInvalid('Only an OPEN branch can receive its current result')
                value.update(
                    status='RESOLVED',
                    result_summary=change['result']['summary'],
                    result_sources_json=json_array(change['result']['source_refs']),
                    state_event_id=None,
                )
                if head['active_branch_ref'] == mapped(ref):
                    head['active_branch_ref'] = None
        elif kind == 'SET_BRANCH_FOCUS':
            ref = change['branch_ref']
            if ref is None:
                head['active_branch_ref'] = None
            else:
                evidence.require_visible('BRANCH', ref, newly_declared=mapping)
                real = mapped(ref)
                value = branches.get(real)
                frozen_step = context.canonical['formation_selection']['discussion_step_ref']
                if (
                    value is None
                    or value['status'] != 'OPEN'
                    or frozen_step is None
                    or value['return_step_ref'] != frozen_step
                    or head['current_step_ref'] != frozen_step
                ):
                    raise ProgressInvalid(
                        'Model branch focus cannot migrate the accepted step target'
                    )
                head['active_branch_ref'] = real
        elif kind == 'ASSESS_STEP':
            ref = step(change['step_ref'])
            if change['definition_version'] != steps[ref]['definition_version']:
                raise ProgressInvalid('Assessment names another definition version')
            assessments[ref] = {
                **change,
                'step_ref': ref,
                'coverage_block_ids': evidence.block_ids(change['document_refs']),
            }
        elif kind == 'RECOMMEND':
            ref = step(change['step_ref'])
            target = (
                None
                if change['target_step_ref'] is None
                else step(change['target_step_ref'], full=False)
            )
            recommendations[ref] = {**change, 'step_ref': ref, 'target_step_ref': target}
        elif kind == 'ASSOCIATE_CONTENT':
            ref = step(change['step_ref'])
            if steps[ref]['status'] == 'CANCELLED':
                raise ProgressInvalid('A cancelled step cannot gain a new content association')
            covered = [mapped(value) for value in change['result_refs']]
            if any(value not in results or results[value]['step_ref'] != ref for value in covered):
                raise ProgressInvalid('Association result ownership differs from its actual step')
            block_ids = evidence.block_ids(change['document_refs'])
            old = None
            if change['review_of'] is not None:
                evidence.require_visible('ARTIFACT', change['review_of'])
                old = connection.execute(
                    'SELECT a.* FROM formation_artifacts a WHERE a.document_id=? AND a.artifact_ref=? AND NOT EXISTS('
                    'SELECT 1 FROM formation_artifact_reviews r WHERE r.document_id=a.document_id '
                    "AND r.reviewed_artifact_ref=a.artifact_ref AND r.result='REASSOCIATED')",
                    (document_id, change['review_of']),
                ).fetchone()
                if old is None or old['step_ref'] != ref:
                    raise ProgressInvalid(
                        'Review must bind an actual read active association and owner'
                    )
                old_results = {
                    row[0]
                    for row in connection.execute(
                        'SELECT result_ref FROM formation_artifact_results WHERE document_id=? AND artifact_ref=?',
                        (document_id, change['review_of']),
                    )
                }
                if old_results != set(covered):
                    raise ProgressInvalid(
                        'A review cannot redirect an old association to different requirements'
                    )
                if any(
                    item['reviewed'] is not None
                    and item['reviewed']['artifact_ref'] == old['artifact_ref']
                    for item in associations
                ):
                    raise ProgressInvalid(
                        'One structured unit cannot review the same artifact twice'
                    )
                old = dict(old)
            associations.append(
                {
                    'link': {
                        'step_ref': ref,
                        'result_refs': covered,
                        'revision_id': context.canonical['formation']['basis'][
                            'document_revision_id'
                        ],
                        'block_ids': block_ids,
                    },
                    'source_refs': change['source_refs'],
                    'reviewed': old,
                }
            )
    return (
        replace(route, branches=branches, issues=issues),
        mapping,
        branch_topics,
        list(assessments.values()),
        list(recommendations.values()),
        associations,
    )
