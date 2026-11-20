"""Strict immutable history DTOs, kept separate from mutable aggregate projections."""

import json
from functools import lru_cache

from backend.app.infrastructure.resources import _validate
from backend.app.requirements.discussion import discussion_resources

from .events import EVENT_ACTIONS, MEMBER_COLLECTIONS
from .types import BRANCH_STATUSES, RESULT_KINDS, STEP_STATUSES


def ref(name):
    return {'$ref': '#/$defs/' + name}


def nullable(value):
    return {'anyOf': [value, {'type': 'null'}]}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


def string(maximum=1000, minimum=1):
    return {'type': 'string', 'minLength': minimum, 'maxLength': maximum}


def array(value, maximum=None):
    result = {'type': 'array', 'items': value}
    if maximum is not None:
        result['maxItems'] = maximum
    return result


def obj(**fields):
    return {
        'type': 'object',
        'properties': fields,
        'required': list(fields),
        'additionalProperties': False,
    }


def union(*values):
    return {'oneOf': list(values)}


@lru_cache(maxsize=1)
def definitions():
    result = discussion_resources().bundle['$defs']
    result = {**result}
    positive = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
    count = {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
    digest = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    boolean = {'type': 'boolean'}
    for name, pattern in (
        ('StepRef', r'^s[1-9][0-9]*$'),
        ('ResultRef', r'^s[1-9][0-9]*\.o[1-9][0-9]*$'),
        ('IssueRef', r'^i[1-9][0-9]*$'),
        ('BranchRef', r'^b[1-9][0-9]*$'),
        ('ArtifactRef', r'^a[1-9][0-9]*$'),
    ):
        result[name] = {'type': 'string', 'pattern': pattern, 'maxLength': 36}
    result['VersionBasis'] = obj(
        discussion_version=positive,
        formation_version=nullable(positive),
        goal_version=nullable(positive),
        document_revision_id=positive,
        content_version=positive,
    )
    result['ProposalRef'] = obj(message_id=positive, card_key=string(100))
    result['ClosureHead'] = obj(
        event_id=positive,
        step_ref=ref('StepRef'),
        definition_version=positive,
        goal_version=positive,
        revision_id=positive,
        command_message_id=positive,
        next_step_ref=nullable(ref('StepRef')),
        result_count=count,
        issue_count=count,
        branch_count=count,
        items_digest=digest,
    )
    event = {
        'event_id': positive,
        'action': enum(*sorted(EVENT_ACTIONS)),
        'actor': enum('USER', 'AI', 'PROGRAM'),
        'reason': string(),
        'created_at': {'type': 'string', 'format': 'date-time'},
    }
    result['EventSummary'] = obj(**event)
    result['EventView'] = obj(
        **event,
        schema={'const': 'formation_event_v1'},
        document_id=positive,
        batch_ref=positive,
        ordinal=positive,
        batch_size=positive,
        version_before=ref('VersionBasis'),
        version_after=ref('VersionBasis'),
        change_count=count,
        closure=nullable(ref('ClosureHead')),
    )
    result['StepSnapshot'] = obj(
        step_ref=ref('StepRef'),
        definition_version=positive,
        title=string(120),
        status=enum(*STEP_STATUSES),
        position=positive,
        next_result_no=positive,
        closure_event_ref=nullable(positive),
    )
    result['GoalSnapshot'] = obj(version=positive, text=string())
    result['ResultSnapshot'] = obj(
        result_ref=ref('ResultRef'), description=string(), kind=enum(*RESULT_KINDS)
    )
    result['IssueSnapshot'] = obj(
        issue_ref=ref('IssueRef'),
        step_ref=ref('StepRef'),
        branch_ref=nullable(ref('BranchRef')),
        description=string(),
        blocking=boolean,
        disposition=enum(*BRANCH_STATUSES),
        disposition_reason=nullable(string()),
        disposition_event_ref=nullable(positive),
    )
    result['BranchSnapshot'] = obj(
        branch_ref=ref('BranchRef'),
        origin_step_ref=ref('StepRef'),
        origin_event_ref=positive,
        return_step_ref=ref('StepRef'),
        question=string(),
        relevance=string(),
        status=enum(*BRANCH_STATUSES),
        state_event_ref=positive,
        result_summary=nullable(string()),
        disposition_event_ref=nullable(positive),
    )
    result['ArtifactSnapshot'] = obj(
        artifact_ref=ref('ArtifactRef'),
        step_ref=ref('StepRef'),
        source_event_ref=positive,
        origin_revision_id=positive,
        origin_content_digest=digest,
        summary=string(240),
        checked_against_revision_id=positive,
        freshness=enum('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
        review_reason=nullable(enum('CHANGED', 'UNVERIFIABLE')),
    )
    result['OrderSnapshot'] = obj(step_ref=ref('StepRef'), position=positive)
    result['ResultRouteSnapshot'] = obj(
        from_result_ref=ref('ResultRef'),
        disposition=enum('REPLACED', 'NOT_REQUIRED'),
        target_result_refs=array(ref('ResultRef')),
        reason=string(),
    )
    result['AssessmentSnapshot'] = obj(
        verdict=enum('SUFFICIENT', 'GAPS_REMAIN', 'UNCERTAIN'),
        reason=string(),
        goal_version=positive,
        evaluated_step_version=positive,
        evaluated_revision_id=positive,
        coverage_block_ids=array(positive, 100),
        source_refs=array(ref('SourceRef'), 100),
        assistant_message_id=positive,
    )
    result['RecommendationBasis'] = obj(
        schema={'const': 'formation_recommendation_basis_v21_1'},
        goal_version=positive,
        owner_step_ref=ref('StepRef'),
        owner_definition_version=positive,
        owner_status=enum(*STEP_STATUSES),
        evaluated_revision_id=positive,
        coverage=array(obj(block_id=positive, block_digest=digest), 100),
        target_step=nullable(
            obj(step_ref=ref('StepRef'), definition_version=positive, status=enum(*STEP_STATUSES))
        ),
        entity_basis=array(
            union(
                *[
                    obj(kind=enum(kind), ref=ref(kind.title() + 'Ref'), semantic_digest=digest)
                    for kind in ('BRANCH', 'ISSUE', 'ARTIFACT')
                ]
            ),
            100,
        ),
        relation_sets=array(
            obj(
                kind=enum('OPEN_ISSUES', 'OPEN_BRANCHES', 'ACTIVE_ARTIFACTS'),
                step_ref=ref('StepRef'),
                digest=digest,
            ),
            6,
        ),
        source_heads=array(obj(source_ref=ref('SourceRef'), head_digest=digest), 100),
    )
    result['RecommendationSnapshot'] = obj(
        action=enum(
            'DISCUSS',
            'WRITE',
            'RESOLVE_BRANCH',
            'REVIEW_CONTENT',
            'COMPLETE_STEP',
            'SWITCH_STEP',
            'NEED_MATERIAL',
        ),
        step_ref=nullable(ref('StepRef')),
        reason=string(),
        source_refs=array(ref('SourceRef'), 100),
        assistant_message_id=positive,
        basis=ref('RecommendationBasis'),
    )
    result['ProposalSnapshot'] = obj(
        proposal=ref('ProposalRef'),
        disposition=enum('PENDING', 'DEFERRED', 'APPLIED', 'SUPERSEDED'),
        needs_revision=boolean,
        binding_digest=digest,
    )
    result['WithdrawalCheckProof'] = obj(
        proposal=ref('ProposalRef'),
        publication_binding_digest=digest,
        expected_semantic_digest=digest,
        observed_semantic_digest=digest,
        checked_versions=ref('VersionBasis'),
        check_kind=enum('WITHDRAW_ADJUSTMENT'),
        result=enum('MATCHED'),
        command_message_id=positive,
    )
    result['ArtifactReview'] = obj(
        reviewed_artifact_ref=ref('ArtifactRef'),
        replacement_artifact_ref=nullable(ref('ArtifactRef')),
        result=enum('MATCHED', 'REASSOCIATED', 'UNVERIFIED', 'REMOVED'),
        checked_against_revision_id=positive,
        assistant_message_id=positive,
        source_refs=array(ref('SourceRef'), 100),
    )
    changes = []
    for kind, schema in (
        ('STEP', 'StepSnapshot'),
        ('GOAL', 'GoalSnapshot'),
        ('RESULT', 'ResultSnapshot'),
        ('ISSUE', 'IssueSnapshot'),
        ('BRANCH', 'BranchSnapshot'),
        ('ARTIFACT', 'ArtifactSnapshot'),
        ('ORDER', 'OrderSnapshot'),
        ('RESULT_ROUTE', 'ResultRouteSnapshot'),
        ('ASSESSMENT', 'AssessmentSnapshot'),
        ('RECOMMENDATION', 'RecommendationSnapshot'),
        ('PROPOSAL', 'ProposalSnapshot'),
        ('PROPOSAL_CHECK', 'WithdrawalCheckProof'),
        ('ARTIFACT_REVIEW', 'ArtifactReview'),
    ):
        shape = obj(
            ordinal=positive,
            entity_kind=enum(kind),
            entity_ref=string(160),
            before={'type': 'null'}
            if kind in ('PROPOSAL_CHECK', 'ARTIFACT_REVIEW')
            else nullable(ref(schema)),
            after=ref(schema)
            if kind in ('PROPOSAL_CHECK', 'ARTIFACT_REVIEW')
            else nullable(ref(schema)),
            member_changes=obj(count=count, digest=digest),
        )
        shape['not'] = {'properties': {'before': {'type': 'null'}, 'after': {'type': 'null'}}}
        changes.append(shape)
    result['EntityChangeView'] = union(*changes)
    members = []
    for collection in MEMBER_COLLECTIONS:
        if collection.endswith('_SOURCE'):
            value = obj(kind=enum('SOURCE'), source_ref=ref('SourceRef'))
        elif collection.endswith('_RANGE'):
            value = obj(
                kind=enum('RANGE'), revision_id=positive, block_id=positive, block_digest=digest
            )
        else:
            target = (
                'StepRef'
                if collection in ('DEPENDENCY', 'REPLACES')
                else 'ResultRef'
                if collection == 'ARTIFACT_RESULT'
                else None
            )
            value = obj(kind=enum('REF'), ref=ref(target) if target else string(200))
        shape = obj(
            ordinal=positive,
            collection=enum(collection),
            member_key=string(240),
            before=nullable(value),
            after=nullable(value),
        )
        shape['not'] = {'properties': {'before': {'type': 'null'}, 'after': {'type': 'null'}}}
        members.append(shape)
    result['MemberDelta'] = union(*members)
    result['ResultClosureItem'] = obj(
        kind=enum('RESULT'),
        ordinal=positive,
        result_ref=ref('ResultRef'),
        description=string(),
        result_kind=enum(*RESULT_KINDS),
        status=enum('LANDED', 'ANALYZED', 'OUTSTANDING'),
        artifact_count=count,
        range_count=count,
        source_count=count,
        evidence_count=count,
        evidence_digest=digest,
    )
    for kind in ('ISSUE', 'BRANCH'):
        result[kind.title() + 'ClosureItem'] = obj(
            kind=enum(kind),
            ordinal=positive,
            ref=ref(kind.title() + 'Ref'),
            description=string(),
            state_at_close=enum(*BRANCH_STATUSES),
            disposition=enum('KEEP_OPEN', 'TRANSFER', 'DEFERRED', 'DROPPED', 'RESOLVED'),
            to_step_ref=nullable(ref('StepRef')),
            reason=nullable(string()),
            source_count=count,
            evidence_count=count,
            evidence_digest=digest,
        )
    result['ClosureEvidenceItem'] = union(
        obj(
            kind=enum('ARTIFACT'),
            ordinal=positive,
            artifact_ref=ref('ArtifactRef'),
            source_event_ref=positive,
            origin_revision_id=positive,
            checked_against_revision_id=positive,
            freshness=enum('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
            review_reason=nullable(enum('CHANGED', 'UNVERIFIABLE')),
            range_count=count,
            range_digest=digest,
        ),
        obj(
            kind=enum('RANGE'),
            ordinal=positive,
            artifact_ref=ref('ArtifactRef'),
            role=enum('ORIGIN', 'CURRENT'),
            revision_id=positive,
            block_id=positive,
            block_digest=digest,
        ),
        obj(kind=enum('SOURCE'), ordinal=positive, source_ref=ref('SourceRef')),
    )
    result['EventPage'] = obj(
        document_id=positive,
        upper_event_id=nullable(positive),
        total=count,
        items=array(ref('EventView'), 100),
    )
    result['ChangePage'] = obj(
        document_id=positive,
        event_id=positive,
        total=count,
        items=array(ref('EntityChangeView'), 100),
    )
    result['MemberChangePage'] = obj(
        document_id=positive,
        event_id=positive,
        change_ordinal=positive,
        total=count,
        digest=digest,
        items=array(ref('MemberDelta'), 100),
    )
    result['ClosureItemPage'] = union(
        *[
            obj(
                document_id=positive,
                event_id=positive,
                closure=ref('ClosureHead'),
                kind=enum(kind),
                total=count,
                items=array(ref(kind.title() + 'ClosureItem'), 100),
            )
            for kind in ('RESULT', 'ISSUE', 'BRANCH')
        ]
    )
    result['ClosureEvidencePage'] = union(
        *[
            obj(
                document_id=positive,
                event_id=positive,
                owner_kind=enum(kind),
                item_ref=ref(kind.title() + 'Ref'),
                total=count,
                digest=digest,
                items=array(ref('ClosureEvidenceItem'), 100),
            )
            for kind in ('RESULT', 'ISSUE', 'BRANCH')
        ]
    )
    return result


@lru_cache(maxsize=32)
def schema_json(entry):
    return json.dumps({'$ref': '#/$defs/' + entry, '$defs': definitions()}, ensure_ascii=False)


def validate(entry, value):
    return _validate(schema_json(entry), value)
