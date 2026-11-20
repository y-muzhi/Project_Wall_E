"""Strict current read models and bounded pages; not the model's private canonical state."""

import json
from copy import deepcopy
from functools import lru_cache

from backend.app.infrastructure.resources import _validate

from .history_contracts import (
    array,
    enum,
    nullable,
    obj,
    ref,
    string,
    union,
)
from .history_contracts import (
    definitions as history_definitions,
)
from .native_contracts import NATIVE_FIELDS
from .types import BRANCH_STATUSES, STEP_STATUSES


def currentness(base, reasons):
    fields = deepcopy(base['properties'])
    shape = obj(**fields, validity=enum('CURRENT', 'STALE'), stale_reason=nullable(enum(*reasons)))
    shape['allOf'] = [
        {
            'if': {'properties': {'validity': {'const': 'CURRENT'}}},
            'then': {'properties': {'stale_reason': {'type': 'null'}}},
            'else': {'properties': {'stale_reason': enum(*reasons)}},
        }
    ]
    return shape


@lru_cache(maxsize=1)
def definitions():
    values = deepcopy(history_definitions())
    positive = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
    count = {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
    boolean = {'type': 'boolean'}
    digest = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    reasons = (
        'WORK_STATE_CONFLICT',
        'WORK_STATE_INCONSISTENT',
        'INVALID_TRANSITION',
        'FORMATION_NOT_INITIALIZED',
        'ARTIFACT_SUPERSEDED',
        'PATH_CHANGED',
        'GOAL_CHANGED',
        'STEP_DEFINITION_CHANGED',
        'TARGET_CHANGED',
        'BRANCH_STATE_CHANGED',
        'BRANCH_RETURN_MISMATCH',
        'PROPOSAL_ADJUSTING',
        'PROPOSAL_BASIS_CHANGED',
        'SOURCE_UNAVAILABLE',
        'CONTENT_CHANGED',
        'GOAL_CHANGED',
        'DEFINITION_CHANGED',
        'PURPOSE_CHANGED',
        'BASIS_CHANGED',
        'ADJUSTING',
        'ALREADY_ANSWERED',
        'DEFERRED',
        'SUPERSEDED',
    )
    values['Availability'] = obj(
        action=enum(*NATIVE_FIELDS, 'apply', 'adjust', 'preview'),
        available=boolean,
        reason=nullable(enum(*dict.fromkeys(reasons))),
    )
    values['Availability']['allOf'] = [
        {
            'if': {'properties': {'available': {'const': True}}},
            'then': {'properties': {'reason': {'type': 'null'}}},
            'else': {'properties': {'reason': enum(*dict.fromkeys(reasons))}},
        }
    ]
    values['SourceStatus'] = union(
        obj(source_ref=ref('SourceRef'), availability=enum('AVAILABLE'), reason={'type': 'null'}),
        obj(
            source_ref=ref('SourceRef'), availability=enum('MISSING'), reason=enum('SOURCE_MISSING')
        ),
        obj(
            source_ref=ref('SourceRef'),
            availability=enum('UNSUPPORTED'),
            reason=enum('RESOURCE_UNSUPPORTED'),
        ),
    )
    values['StateCounts'] = obj(
        steps=obj(**{state: count for state in STEP_STATUSES}),
        branches=obj(**{state: count for state in BRANCH_STATUSES}),
        issues=obj(**{state: count for state in BRANCH_STATUSES}),
        proposals=obj(
            **{state: count for state in ('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED')}
        ),
        pending_review_artifacts=count,
    )
    values['GoalView'] = obj(version=positive, text=string(), source_refs=array(ref('SourceRef')))
    values['Summary'] = obj(
        document_id=positive,
        view_schema={'const': 'formation_read_v21_1'},
        exists=boolean,
        formation_version=nullable(positive),
        goal=nullable(ref('GoalView')),
        current_step_ref=nullable(ref('StepRef')),
        active_branch_ref=nullable(ref('BranchRef')),
        counts=ref('StateCounts'),
        availability=array(ref('Availability'), 20),
    )
    zero_counts = deepcopy(values['StateCounts'])
    for name, shape in zero_counts['properties'].items():
        if name == 'pending_review_artifacts':
            shape['const'] = 0
        else:
            for state in shape['properties'].values():
                state['const'] = 0
    values['Summary']['allOf'] = [
        {
            'if': {'properties': {'exists': {'const': False}}},
            'then': {
                'properties': {
                    **{
                        name: {'type': 'null'}
                        for name in (
                            'formation_version',
                            'goal',
                            'current_step_ref',
                            'active_branch_ref',
                        )
                    },
                    'counts': zero_counts,
                    'availability': {'maxItems': 0},
                }
            },
            'else': {'properties': {'formation_version': positive, 'goal': ref('GoalView')}},
        }
    ]
    values['AssessmentView'] = currentness(
        values['AssessmentSnapshot'], ('GOAL_CHANGED', 'DEFINITION_CHANGED', 'COVERAGE_CHANGED')
    )
    values['RecommendationView'] = currentness(
        values['RecommendationSnapshot'],
        (
            'GOAL_CHANGED',
            'OWNER_DEFINITION_CHANGED',
            'OWNER_STATE_CHANGED',
            'TARGET_CHANGED',
            'COVERAGE_CHANGED',
            'SOURCE_UNAVAILABLE',
            'RELATED_FACT_CHANGED',
        ),
    )
    expected = array(ref('ResultSnapshot'), 20)
    expected['minItems'] = 1
    step_fields = {
        'step_ref': ref('StepRef'),
        'definition_version': positive,
        'title': string(120),
        'status': enum(*STEP_STATUSES),
        'position': positive,
        'expected_results': expected,
        'relation_counts': obj(
            **{
                name: count
                for name in (
                    'dependencies',
                    'replaces',
                    'topics',
                    'issues',
                    'branches',
                    'artifacts',
                )
            }
        ),
        'last_event': nullable(ref('EventSummary')),
        'assessment': nullable(ref('AssessmentView')),
        'recommendation': nullable(ref('RecommendationView')),
        'availability': array(ref('Availability'), 20),
    }
    values['StepView'] = obj(**step_fields)
    values['StepDetail'] = obj(
        **step_fields, closure=nullable(ref('ClosureHead')), sources=array(ref('SourceStatus'))
    )
    branch = deepcopy(values['BranchSnapshot']['properties'])
    branch.pop('result_summary')
    values['BranchView'] = obj(
        **branch,
        topic_count=count,
        result_summary=nullable(string()),
        result_source_refs=array(ref('SourceRef')),
        availability=array(ref('Availability'), 20),
    )
    issue = deepcopy(values['IssueSnapshot']['properties'])
    values['IssueView'] = obj(
        **issue,
        source_refs=array(ref('SourceRef')),
        resolution_source_refs=array(ref('SourceRef')),
        availability=array(ref('Availability'), 20),
    )
    artifact = deepcopy(values['ArtifactSnapshot']['properties'])
    values['ArtifactView'] = obj(
        predecessor_ref=nullable(ref('ArtifactRef')),
        predecessor_review_event_id=nullable(positive),
        successor_ref=nullable(ref('ArtifactRef')),
        successor_review_event_id=nullable(positive),
        is_active=boolean,
        **artifact,
        result_refs=array(ref('ResultRef'), 20),
        origin_block_count=count,
        current_block_count=count,
        sources=array(ref('SourceStatus')),
    )
    relation_items = [
        obj(relation_kind=enum(kind), from_step_ref=ref('StepRef'), to_step_ref=ref('StepRef'))
        for kind in ('DEPENDENCY', 'REPLACES')
    ]
    relation_items += [
        obj(relation_kind=enum('TOPIC'), step_ref=ref('StepRef'), topic_ref=string(200))
    ]
    for kind, name in (('ISSUE', 'issue'), ('BRANCH', 'branch'), ('ARTIFACT', 'artifact')):
        relation_items.append(
            obj(
                relation_kind=enum(kind),
                step_ref=ref('StepRef'),
                **{name: ref(kind.title() + 'View')},
            )
        )
    values['RelationItem'] = union(*relation_items)
    values['EntityPage'] = union(
        *[
            obj(
                document_id=positive,
                formation_version=positive,
                kind=enum(kind),
                items=array(ref(entry), 100),
                total=count,
            )
            for kind, entry in (
                ('steps', 'StepView'),
                ('branches', 'BranchView'),
                ('issues', 'IssueView'),
                ('artifacts', 'ArtifactView'),
                ('relations', 'RelationItem'),
            )
        ]
    )
    from backend.app.infrastructure.resources import ResourceCatalog

    from .resource_schema import definitions as model_definitions

    shared = model_definitions(ResourceCatalog().collaboration.bundle['$defs'])
    for name, definition in shared.items():
        values.setdefault(name, definition)
    values['ProposalView'] = union(
        *[
            obj(
                message_id=positive,
                card_key=string(100),
                purpose=enum(purpose),
                payload=ref(payload),
                disposition=enum('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'),
                needs_revision=boolean,
                can_apply=boolean,
                reasons=array(enum(*dict.fromkeys(reasons)), len(reasons)),
                availability=array(ref('Availability'), 20),
                expiry_reason=nullable(
                    enum(
                        'CONTENT_CHANGED',
                        'GOAL_CHANGED',
                        'DEFINITION_CHANGED',
                        'SOURCE_UNAVAILABLE',
                        'PURPOSE_CHANGED',
                        'BASIS_CHANGED',
                        'ADJUSTING',
                        'ALREADY_ANSWERED',
                    )
                ),
                source_run_id=positive,
            )
            for purpose, payload in (
                ('STAGED_WRITE', 'CanonicalFormationWritePayload'),
                ('FORMATION_PATH_CHANGE', 'CanonicalFormationPathPayload'),
            )
        ]
    )
    values['EntityPage']['oneOf'].append(
        obj(
            document_id=positive,
            formation_version=positive,
            kind=enum('proposals'),
            items=array(ref('ProposalView'), 100),
            total=count,
        )
    )
    values['RangePage'] = obj(
        document_id=positive,
        formation_version=positive,
        artifact_ref=ref('ArtifactRef'),
        role=enum('ORIGIN', 'CURRENT'),
        total=count,
        items=array(
            obj(ordinal=positive, revision_id=positive, block_id=positive, block_digest=digest), 100
        ),
    )
    values['LineageItem'] = obj(
        artifact_ref=ref('ArtifactRef'),
        predecessor_ref=nullable(ref('ArtifactRef')),
        predecessor_review_event_id=nullable(positive),
        successor_ref=nullable(ref('ArtifactRef')),
        successor_review_event_id=nullable(positive),
        is_active=boolean,
        freshness=enum('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
        review_reason=nullable(enum('CHANGED', 'UNVERIFIABLE')),
    )
    values['LineagePage'] = obj(
        document_id=positive,
        formation_version=positive,
        anchor_ref=ref('ArtifactRef'),
        total=count,
        items=array(ref('LineageItem'), 100),
    )
    return values


@lru_cache(maxsize=32)
def schema_json(entry):
    return json.dumps({'$ref': '#/$defs/' + entry, '$defs': definitions()}, ensure_ascii=False)


def validate(entry, value):
    return _validate(schema_json(entry), value)
