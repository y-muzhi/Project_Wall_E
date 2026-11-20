"""Strict route preview DTOs; local labels never become persistent identities or authority."""

import json
from copy import deepcopy
from functools import lru_cache

from backend.app.infrastructure.resources import _validate

from .history_contracts import array, enum, nullable, obj, ref, string, union
from .path_contracts import PATH_FIELDS
from .read_contracts import definitions as read_definitions
from .types import BRANCH_STATUSES, STEP_STATUSES


@lru_cache(maxsize=1)
def schema_json():
    definitions = deepcopy(read_definitions())
    positive = {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}
    count = {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
    digest = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
    for name, kind in (('PathStepRef', 'step'), ('PathResultRef', 'result')):
        definitions[name] = union(
            ref('StepRef' if kind == 'step' else 'ResultRef'),
            {'type': 'string', 'pattern': '^new_' + kind + '_[1-9][0-9]*$', 'maxLength': 36},
        )
    definitions['TempRef'] = {
        'type': 'string',
        'pattern': '^new_(step|result|issue|branch)_[1-9][0-9]*$',
        'maxLength': 36,
    }
    expected = array(
        obj(
            result_ref=ref('PathResultRef'), description=string(), kind=enum('CONTENT', 'ANALYSIS')
        ),
        20,
    )
    expected['minItems'] = 1
    definitions['PreviewEntity'] = union(
        obj(
            kind=enum('STEP'),
            step_ref=ref('PathStepRef'),
            title=string(120),
            status=enum(*STEP_STATUSES),
            position=positive,
            expected_results=expected,
        ),
        obj(kind=enum('GOAL'), text=string()),
        obj(
            kind=enum('RESULT'),
            result_ref=ref('PathResultRef'),
            description=string(),
            result_kind=enum('CONTENT', 'ANALYSIS'),
        ),
        obj(
            kind=enum('ISSUE'),
            issue_ref=ref('IssueRef'),
            step_ref=ref('PathStepRef'),
            disposition=enum(*BRANCH_STATUSES),
        ),
        obj(
            kind=enum('BRANCH'),
            branch_ref=ref('BranchRef'),
            origin_step_ref=ref('StepRef'),
            return_step_ref=ref('PathStepRef'),
            status=enum(*BRANCH_STATUSES),
        ),
        obj(
            kind=enum('ARTIFACT'),
            artifact_ref=ref('ArtifactRef'),
            step_ref=ref('StepRef'),
            result_refs=array(ref('ResultRef'), 20),
            freshness=enum('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
        ),
        obj(
            kind=enum('DEPENDENCIES'),
            step_ref=ref('PathStepRef'),
            dependencies=array(ref('PathStepRef')),
        ),
        obj(
            kind=enum('ARTIFACT_LINK'),
            step_ref=ref('PathStepRef'),
            result_refs=array(ref('PathResultRef'), 20),
            revision_id=positive,
            block_ids={**array(positive, 100), 'minItems': 1},
        ),
    )
    affected = obj(
        ordinal=positive,
        change_type=enum(*PATH_FIELDS),
        entity_ref=string(160),
        before=nullable(ref('PreviewEntity')),
        after=nullable(ref('PreviewEntity')),
    )
    affected['not'] = {'properties': {'before': {'type': 'null'}, 'after': {'type': 'null'}}}
    warning = obj(
        ordinal=positive,
        code=enum(
            'OUTSTANDING_CONTENT',
            'UNRESOLVED_ISSUE',
            'OPEN_BRANCH',
            'PROPOSAL_AFFECTED',
            'ASSESSMENT_STALE',
            'FOCUS_CLEARED',
        ),
        step_ref=nullable(ref('PathStepRef')),
        related_ref=nullable(string(160)),
        message=string(),
    )

    def slice_of(shape):
        result = obj(
            items=array(shape, 100),
            total=count,
            has_more={'type': 'boolean'},
            next_cursor=nullable(string(4096)),
        )
        result['allOf'] = [
            {
                'if': {'properties': {'has_more': {'const': True}}},
                'then': {'properties': {'next_cursor': string(4096)}},
                'else': {'properties': {'next_cursor': {'type': 'null'}}},
            }
        ]
        return result

    route = obj(
        from_result_ref=ref('ResultRef'),
        disposition=enum('REPLACED', 'NOT_REQUIRED'),
        target_result_refs=array(ref('PathResultRef')),
        reason=string(),
    )
    definitions['PathPreview'] = obj(
        document_id=positive,
        discussion_version=positive,
        formation_version=positive,
        content_version=positive,
        changes_digest=digest,
        affected_items=slice_of(affected),
        result_routes=array(route),
        warnings=slice_of(warning),
        reference_map=array(obj(temp_ref=ref('TempRef'), preview_label=string(120)), 420),
    )
    return json.dumps({'$ref': '#/$defs/PathPreview', '$defs': definitions}, ensure_ascii=False)


def validate(value):
    return _validate(schema_json(), value)
