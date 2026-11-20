"""V2.1 resource schemas extend new releases only; old frozen bundles stay byte-identical."""

from copy import deepcopy

from .history_contracts import array, enum, nullable, obj, ref, string, union
from .model_contracts import FIELDS, RECOMMENDATIONS
from .path_contracts import PATH_FIELDS
from .types import BRANCH_STATUSES, REFERENCE_PATTERNS, STEP_STATUSES


def scalar():
    return {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991}


def definitions(base):
    values = deepcopy(base)
    positive = scalar()
    for name in ('created_source_type', 'last_modified_source_type'):
        values['legacy_block_metadata']['properties'][name]['enum'].append('CARD_RESPONSE')
    boolean = {'type': 'boolean'}
    for name, kind in (
        ('FormationStepRef', 'STEP'),
        ('FormationResultRef', 'RESULT'),
        ('FormationBranchRef', 'BRANCH'),
        ('FormationIssueRef', 'ISSUE'),
        ('FormationArtifactRef', 'ARTIFACT'),
        ('TempStepRef', 'TEMP_STEP'),
        ('TempResultRef', 'TEMP_RESULT'),
        ('TempBranchRef', 'TEMP_BRANCH'),
        ('TempIssueRef', 'TEMP_ISSUE'),
    ):
        values[name] = {
            'type': 'string',
            'pattern': '^' + REFERENCE_PATTERNS[kind] + '$',
            'maxLength': 48,
        }
    for kind in ('Step', 'Result', 'Branch', 'Issue'):
        values['Path' + kind + 'Ref'] = union(
            ref('Formation' + kind + 'Ref'), ref('Temp' + kind + 'Ref')
        )
    values['FormationAliasRef'] = string(160)
    values['FormationBlockAliasRef'] = {
        'type': 'string',
        'pattern': r'^d[1-9][0-9]*v[1-9][0-9]*b[1-9][0-9]*$',
        'maxLength': 160,
    }
    values['FormationText'] = string()
    values['FormationTitle'] = string(120)
    values['FormationBasis'] = obj(
        formation_version=nullable(positive),
        goal_version=nullable(positive),
        document_revision_id=positive,
        content_version=positive,
    )
    values['FormationTargetSelection'] = obj(
        discussion_step_ref=nullable(ref('FormationStepRef')),
        discussion_branch_ref=nullable(ref('FormationBranchRef')),
        branch_intent=nullable(enum('ENTER', 'RESUME')),
        branch_resume_basis=nullable(
            obj(
                expected_branch_status=enum('DEFERRED', 'RESOLVED'),
                expected_branch_event_id=positive,
            )
        ),
    )
    values['FormationExpectedResult'] = obj(
        temp_ref=ref('TempResultRef'), description=string(), kind=enum('CONTENT', 'ANALYSIS')
    )
    values['FormationStepDraft'] = obj(
        temp_ref=ref('TempStepRef'),
        title=string(120),
        expected_results=array(ref('FormationExpectedResult'), 20),
        dependencies=array(ref('PathStepRef')),
        topic_refs=array(ref('FormationTopicRef')),
    )
    values['FormationStepDraft']['properties']['expected_results']['minItems'] = 1
    values['FormationTopicRef'] = {'type': 'string', 'pattern': '^t[1-9][0-9]*$', 'maxLength': 17}
    values['FormationResolution'] = obj(
        summary=string(), source_refs=array(ref('FormationAliasRef'), 100)
    )
    values['FormationResolution']['properties']['source_refs']['minItems'] = 1
    changes = []
    for kind, fields in FIELDS.items():
        props = {'type': enum(kind)}
        for field in fields:
            if field == 'goal':
                value = obj(text=string(), source_refs=array(ref('FormationAliasRef'), 100))
            elif field == 'steps':
                value = array(ref('FormationStepDraft'), 20)
                value['minItems'] = 1
            elif field == 'temp_ref':
                value = ref(
                    {
                        'ADD_STEP': 'TempStepRef',
                        'ADD_ISSUE': 'TempIssueRef',
                        'ADD_BRANCH': 'TempBranchRef',
                    }[kind]
                )
            elif field == 'title':
                value = nullable(string(120)) if kind == 'UPDATE_STEP' else string(120)
            elif field in ('expected_results', 'add_results'):
                value = array(ref('FormationExpectedResult'), 20)
            elif field == 'dependencies':
                value = array(ref('PathStepRef'))
                if kind == 'UPDATE_STEP':
                    value = nullable(value)
            elif field == 'topic_refs':
                value = array(ref('FormationTopicRef'))
                if kind in ('UPDATE_STEP', 'UPDATE_BRANCH'):
                    value = nullable(value)
            elif field in (
                'step_ref',
                'origin_step_ref',
                'return_step_ref',
                'target_step_ref',
                'before_step_ref',
            ):
                value = ref('PathStepRef')
                if field in ('target_step_ref', 'before_step_ref'):
                    value = nullable(value)
            elif field == 'branch_ref':
                value = ref('PathBranchRef')
                if kind in ('ADD_ISSUE', 'SET_BRANCH_FOCUS'):
                    value = nullable(value)
            elif field == 'issue_ref':
                value = ref('PathIssueRef')
            elif field == 'description':
                value = nullable(string()) if kind == 'UPDATE_ISSUE' else string()
            elif field == 'blocking':
                value = nullable(boolean) if kind == 'UPDATE_ISSUE' else boolean
            elif field in ('resolution', 'result'):
                value = nullable(ref('FormationResolution'))
            elif field in ('source_refs', 'document_refs'):
                value = array(
                    ref(
                        'FormationBlockAliasRef'
                        if field == 'document_refs'
                        else 'FormationAliasRef'
                    ),
                    100,
                )
                if field == 'document_refs' and kind == 'ASSOCIATE_CONTENT':
                    value['minItems'] = 1
            elif field == 'definition_version':
                value = positive
            elif field == 'verdict':
                value = enum('SUFFICIENT', 'GAPS_REMAIN', 'UNCERTAIN')
            elif field == 'action':
                value = enum(*RECOMMENDATIONS)
            elif field == 'reason' or field in ('question', 'relevance'):
                value = string()
            elif field == 'result_refs':
                value = array(ref('PathResultRef'), 20)
                value['minItems'] = 1
            elif field == 'review_of':
                value = nullable(ref('FormationArtifactRef'))
            else:
                raise AssertionError('Missing model delta Schema field: ' + field)
            props[field] = value
        if kind == 'ADD_STEP':
            props['expected_results']['minItems'] = 1
        changes.append(obj(**props))
    values['FormationChange'] = union(*changes)
    values['FormationDelta'] = obj(
        basis=ref('FormationBasis'), changes=array(ref('FormationChange'), 20)
    )
    values['FormationDelta']['properties']['changes']['minItems'] = 1
    values['Progress']['properties']['formation_delta'] = nullable(ref('FormationDelta'))
    values['Progress']['required'].append('formation_delta')
    _proposals(values, positive)
    _materials(values, positive)
    values['Canonical']['properties']['layout_version']['const'] = 'formation_context_v21_1'
    for name, schema in (
        ('formation', ref('CanonicalFormation')),
        ('formation_selection', nullable(ref('FormationTargetSelection'))),
        ('proposal_context', nullable(ref('FormationProposalContext'))),
    ):
        values['Canonical']['properties'][name] = schema
        values['Canonical']['required'].append(name)
    values['Position']['properties']['formation'] = ref('WireFormation')
    values['Position']['required'].append('formation')
    for name, schema in (
        ('formation_selection', nullable(ref('FormationTargetSelection'))),
        ('proposal_intent', nullable(enum('ADJUST_WRITE', 'ADJUST_PATH'))),
        ('proposal_ref', nullable(obj(message_id=positive, card_key=string(100)))),
    ):
        values['Request']['properties'][name] = schema
        values['Request']['required'].append(name)
    effects = nullable(enum('APPLIED', 'STRUCTURED_REJECTED', 'FAILED', 'CANCELLED'))
    values['RawMessage']['properties']['effect_state'] = effects
    values['RawMessage']['required'].append('effect_state')
    values['History']['properties']['effect_state'] = effects
    values['History']['required'].append('effect_state')
    values['OutputDiscuss'] = ref('OutputDiscussion')
    values['Release']['properties']['compiler_version']['const'] = 'formation_compiler_v21_1'
    values['Release']['properties']['formation_protocol'] = {
        'const': 'formation_v21_1',
        'type': 'string',
    }
    values['Release']['required'].append('formation_protocol')
    values['Release']['properties']['model_transport'] = {
        'const': {
            'mode': 'json_schema',
            'projection': 'ark_supported_keywords_v1',
            'strict': True,
            'operations': ['DISCUSS'],
            'bind_current_blocks': True,
        }
    }
    values['Release']['required'].append('model_transport')
    values['CountingDefinition']['properties']['layout']['const'] = 'formation_context_v21_1'
    values['CountingDefinition']['properties']['system_text'] = {
        'type': 'string',
        'const': 'system_plus_output_schema_v1',
    }
    values['CountingDefinition']['required'].append('system_text')
    values['CountingDefinition']['properties']['framing_reserve']['const'] = 2048
    values['Admission']['properties']['reserve']['const'] = 2048
    return values


def _proposals(values, positive):
    model_sources = array(ref('FormationAliasRef'), 100)
    real_sources = array(ref('SourceRef'), 100)
    path_changes = []
    for kind, fields in PATH_FIELDS.items():
        props = {'type': enum(kind)}
        for field in fields:
            if field in ('text', 'description', 'reason'):
                value = string()
            elif field == 'title':
                value = string(120)
            elif field == 'source_refs':
                value = model_sources
            elif field == 'temp_step_ref':
                value = ref('TempStepRef')
            elif field == 'temp_result_ref':
                value = ref('TempResultRef')
            elif field == 'expected_results':
                value = array(
                    obj(
                        temp_result_ref=ref('TempResultRef'),
                        description=string(),
                        kind=enum('CONTENT', 'ANALYSIS'),
                    ),
                    20,
                )
                value['minItems'] = 1
            elif field in ('dependencies', 'replacement_step_refs'):
                value = array(ref('PathStepRef'))
            elif field == 'replaces_step_refs':
                value = array(ref('FormationStepRef'))
            elif field == 'before_step_ref':
                value = nullable(ref('PathStepRef'))
            elif field in ('to_step_ref', 'return_step_ref'):
                value = ref('PathStepRef')
            elif field == 'step_ref':
                value = ref(
                    'PathStepRef' if kind in ('ADD_RESULT', 'LINK_CONTENT') else 'FormationStepRef'
                )
            elif field in ('result_ref', 'issue_ref', 'branch_ref'):
                value = ref('Formation' + field.removesuffix('_ref').title() + 'Ref')
            elif field == 'result_refs':
                value = array(ref('PathResultRef'))
                value['minItems'] = 1
            elif field == 'kind':
                value = enum('CONTENT', 'ANALYSIS')
            elif field == 'disposition':
                value = enum('DEFERRED', 'DROPPED')
            elif field == 'revision_id':
                value = positive
            elif field == 'block_ids':
                value = array(positive)
                value['minItems'] = 1
            else:
                raise AssertionError('Missing path Schema field: ' + field)
            props[field] = value
        path_changes.append(obj(**props))
    values['FormationPathChange'] = union(*path_changes)
    values['FormationResultRoute'] = obj(
        from_result_ref=ref('FormationResultRef'),
        disposition=enum('REPLACED', 'NOT_REQUIRED'),
        target_result_refs=array(ref('PathResultRef')),
        reason=string(),
    )
    write = obj(
        step_ref=ref('PathStepRef'),
        result_refs=array(ref('PathResultRef'), 20),
        write_mode=enum('FILL_EMPTY', 'PATCH_EXISTING'),
        document_revision_id=positive,
        content_version=positive,
        goal_version=positive,
        definition_version=positive,
        scope=ref('legacy_scope'),
        markdown_content=nullable(string(1000000)),
        patches=array(ref('legacy_patch')),
        change_summary=string(),
        source_refs=model_sources,
    )
    write['properties']['result_refs']['minItems'] = 1
    path = obj(
        basis=obj(
            formation_version=positive,
            goal_version=positive,
            document_revision_id=positive,
            content_version=positive,
        ),
        changes=array(ref('FormationPathChange'), 20),
        result_routes=array(ref('FormationResultRoute')),
        change_summary=string(),
        source_refs=model_sources,
    )
    path['properties']['changes']['minItems'] = 1
    card = deepcopy(values['legacy_card'])
    card['properties']['card_type'] = enum('SINGLE_SELECT')
    card['properties']['required'] = {'const': True, 'type': 'boolean'}
    card['properties']['options']['minItems'] = card['properties']['options']['maxItems'] = 1
    option_ref = card['properties']['options']['items']['$ref'].split('/')[-1]
    card['properties']['options']['items'] = deepcopy(values[option_ref])
    card['properties']['options']['items']['properties']['option_key'] = enum('apply')
    card['properties']['selection_rule'] = obj(
        min={'const': 1, 'type': 'integer'}, max={'const': 1, 'type': 'integer'}
    )
    card['properties']['custom_answer'] = obj(
        enabled={'const': False, 'type': 'boolean'}, max_length={'const': 0, 'type': 'integer'}
    )
    values['FormationApplyCard'] = card
    for purpose, payload in (('STAGED_WRITE', write), ('FORMATION_PATH_CHANGE', path)):
        name = 'FormationWritePayload' if purpose == 'STAGED_WRITE' else 'FormationPathPayload'
        values[name] = payload
        canonical = deepcopy(payload)
        canonical['properties']['source_refs'] = real_sources
        if purpose == 'STAGED_WRITE':
            canonical['properties']['step_ref'] = ref('FormationStepRef')
            canonical['properties']['result_refs'] = array(ref('FormationResultRef'), 20)
            canonical['properties']['result_refs']['minItems'] = 1
        else:
            canonical_changes = deepcopy(path_changes)
            for change in canonical_changes:
                if 'source_refs' in change['properties']:
                    change['properties']['source_refs'] = real_sources
            values['CanonicalFormationPathChange'] = union(*canonical_changes)
            canonical['properties']['changes']['items'] = ref('CanonicalFormationPathChange')
        values['Canonical' + name] = canonical
        group = obj(
            schema_version={'const': 1, 'type': 'integer'},
            intro=string(10000, 0),
            purpose=enum(purpose),
            cards=array(ref('FormationApplyCard'), 1),
            action_payload=ref(name),
        )
        group['properties']['cards']['minItems'] = 1
        values['ModelCardGroup']['oneOf'].append(group)
        stored = deepcopy(group)
        stored['properties']['action_payload'] = ref('Canonical' + name)
        stored['properties']['program_binding'] = ref('ProgramBinding')
        stored['required'].append('program_binding')
        values['StoredCardGroup']['oneOf'].append(stored)
    values['FormationProposalContext'] = obj(
        proposal_ref=obj(message_id=positive, card_key=string(100)),
        purpose=enum('STAGED_WRITE', 'FORMATION_PATH_CHANGE'),
        action_payload=union(
            ref('CanonicalFormationWritePayload'), ref('CanonicalFormationPathPayload')
        ),
    )


def _materials(values, positive):
    count = {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
    goal = obj(version=positive, text=string(), source_refs=array(ref('SourceRef'), 100))
    step = obj(
        step_ref=ref('FormationStepRef'),
        definition_version=positive,
        title=string(120),
        status=enum(*STEP_STATUSES),
        expected_results=array(
            obj(
                result_ref=ref('FormationResultRef'),
                description=string(),
                kind=enum('CONTENT', 'ANALYSIS'),
            ),
            20,
        ),
        dependencies=array(ref('FormationStepRef')),
        replaces_step_refs=array(ref('FormationStepRef')),
        topic_refs=array(ref('FormationTopicRef')),
    )
    branch = obj(
        branch_ref=ref('FormationBranchRef'),
        origin_step_ref=ref('FormationStepRef'),
        return_step_ref=ref('FormationStepRef'),
        question=string(),
        relevance=string(),
        status=enum(*BRANCH_STATUSES),
        result_summary=nullable(string()),
        result_source_refs=array(ref('SourceRef'), 100),
        state_event_ref=positive,
        topic_refs=array(ref('FormationTopicRef')),
    )
    issue = obj(
        issue_ref=ref('FormationIssueRef'),
        step_ref=ref('FormationStepRef'),
        branch_ref=nullable(ref('FormationBranchRef')),
        description=string(),
        blocking={'type': 'boolean'},
        disposition=enum(*BRANCH_STATUSES),
        source_refs=array(ref('SourceRef'), 100),
        resolution_source_refs=array(ref('SourceRef'), 100),
    )
    artifact = obj(
        artifact_ref=ref('FormationArtifactRef'),
        step_ref=ref('FormationStepRef'),
        result_refs=array(ref('FormationResultRef'), 20),
        summary=string(240),
        freshness=enum('CURRENT', 'NEEDS_REVIEW', 'REMOVED'),
        review_reason=nullable(enum('CHANGED', 'UNVERIFIABLE')),
        origin_revision_id=positive,
        checked_against_revision_id=positive,
        current_block_ids=array(positive, 100),
        source_refs=array(ref('SourceRef'), 100),
    )
    assessment = obj(
        verdict=enum('SUFFICIENT', 'GAPS_REMAIN', 'UNCERTAIN'),
        reason=string(),
        goal_version=positive,
        evaluated_step_version=positive,
        evaluated_revision_id=positive,
        coverage_block_ids=array(positive, 100),
        source_refs=array(ref('SourceRef'), 100),
        assistant_message_id=positive,
    )
    recommendation = obj(
        action=enum(*RECOMMENDATIONS),
        step_ref=nullable(ref('FormationStepRef')),
        reason=string(),
        source_refs=array(ref('SourceRef'), 100),
        assistant_message_id=positive,
        validity=enum('CURRENT', 'STALE'),
    )
    branch['properties']['previous_result'] = nullable(
        obj(
            summary=string(),
            source_refs=array(ref('SourceRef'), 100),
            event_id=positive,
        )
    )
    branch['required'].append('previous_result')
    branch['properties']['origin_source_refs'] = array(ref('SourceRef'), 100)
    branch['required'].append('origin_source_refs')
    artifact['properties']['current_block_count'] = count
    artifact['required'].append('current_block_count')
    assessment['properties']['validity'] = enum('CURRENT', 'STALE')
    assessment['properties']['stale_reason'] = nullable(
        enum('GOAL_CHANGED', 'DEFINITION_CHANGED', 'COVERAGE_CHANGED')
    )
    assessment['required'].extend(('validity', 'stale_reason'))
    recommendation['properties']['stale_reason'] = nullable(
        enum(
            'GOAL_CHANGED',
            'OWNER_DEFINITION_CHANGED',
            'OWNER_STATE_CHANGED',
            'TARGET_CHANGED',
            'COVERAGE_CHANGED',
            'SOURCE_UNAVAILABLE',
            'RELATED_FACT_CHANGED',
        )
    )
    recommendation['required'].append('stale_reason')
    values['CanonicalFormation'] = obj(
        basis=ref('FormationBasis'),
        goal=nullable(goal),
        selected_step=nullable(step),
        selected_branch=nullable(branch),
        related_issues=array(issue, 100),
        artifacts=array(artifact, 100),
        assessment=nullable(assessment),
        recommendation=nullable(recommendation),
        coverage=obj(
            limit={'const': 100, 'type': 'integer'},
            included=array(
                obj(kind=enum('STEP', 'BRANCH', 'ISSUE', 'ARTIFACT'), ref=string(48)), 100
            ),
            omitted=array(
                obj(
                    kind=enum('STEP', 'BRANCH', 'ISSUE', 'ARTIFACT'),
                    count=count,
                    reason=enum('ENTITY_LIMIT', 'NOT_RELATED'),
                ),
                4,
            ),
        ),
    )
    included = values['CanonicalFormation']['properties']['coverage']['properties']['included']
    included['items'] = union(
        included['items'],
        obj(kind=enum('STEP'), ref=ref('FormationStepRef'), definition=deepcopy(step)),
        obj(kind=enum('BRANCH'), ref=ref('FormationBranchRef'), definition=deepcopy(branch)),
    )
    wire = deepcopy(values['CanonicalFormation'])

    # The model sees material aliases, never SQL/source objects or program bindings.
    def aliases(shape):
        if isinstance(shape, dict):
            for key, child in shape.items():
                if key in (
                    'source_refs',
                    'origin_source_refs',
                    'result_source_refs',
                    'resolution_source_refs',
                ) and isinstance(child, dict):
                    child.clear()
                    child.update(array(ref('FormationAliasRef'), 100))
                else:
                    aliases(child)
        elif isinstance(shape, list):
            for child in shape:
                aliases(child)

    aliases(wire)
    values['WireFormation'] = wire
