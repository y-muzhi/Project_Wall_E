"""New immutable model resources do not weaken old releases or confer live admission."""

from copy import deepcopy

import pytest

from backend.app.infrastructure.collaboration_resources import ROOT, CollaborationResources
from backend.app.infrastructure.resources import ConfigInvalid, ProtocolInvalid, ResourceCatalog
from backend.tests.formation.test_v21_model_contracts import examples
from backend.tests.formation.test_v21_proposal_contracts import group


@pytest.fixture(scope='module')
def resources():
    return CollaborationResources.load(ROOT.parent / 'v37')


@pytest.mark.parametrize('value', examples())
def test_published_schema_has_all_twelve_strict_model_alternatives(resources, value):
    assert resources.validate('FormationChange', value) == value
    changed = {**value, 'private_basis': {}}
    with pytest.raises(ProtocolInvalid):
        resources.validate('FormationChange', changed)


@pytest.mark.parametrize('purpose', ('STAGED_WRITE', 'FORMATION_PATH_CHANGE'))
def test_published_model_cards_use_aliases_but_stored_cards_have_real_sources(resources, purpose):
    model = group(purpose)
    model['action_payload']['source_refs'] = ['m1']
    assert resources.validate('ModelCardGroup', model) == model
    model['action_payload']['source_refs'] = [{'kind': 'MESSAGE', 'message_id': 1}]
    with pytest.raises(ProtocolInvalid):
        resources.validate('ModelCardGroup', model)
    stored = {
        **model,
        'program_binding': {
            'discussion_version': 1,
            'target_content_version': 1,
            'source_heads': [],
        },
    }
    assert resources.validate('StoredCardGroup', stored) == stored
    stored['program_binding']['protected_semantic_digest'] = '0' * 64
    with pytest.raises(ProtocolInvalid):
        resources.validate('StoredCardGroup', stored)


def test_only_new_releases_recognize_new_fields_and_explicit_profile_selection(resources):
    old = CollaborationResources.load(ROOT.parent / 'v17')
    assert not old.formation_driven and resources.formation_driven
    for purpose in ('STAGED_WRITE', 'FORMATION_PATH_CHANGE'):
        with pytest.raises(ProtocolInvalid):
            old.validate('ModelCardGroup', group(purpose))
    value = {
        'topic_changes': [],
        'evidence_changes': [],
        'focus_topic_ref': None,
        'next_step': None,
        'processed_user_message_ids': [],
        'formation_delta': None,
    }
    assert resources.validate('Progress', value) == value
    with pytest.raises(ProtocolInvalid):
        old.validate('Progress', value)
    with pytest.raises(ProtocolInvalid):
        resources.validate(
            'Progress', {key: value for key, value in value.items() if key != 'formation_delta'}
        )
    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, LONG_OUTPUT_PROFILE

    catalog = ResourceCatalog()
    selected = catalog.for_formation_profile(DEFAULT_PROFILE, discussion_routes=False)
    assert not catalog.collaboration.formation_driven
    assert selected.collaboration.release_sha256 == resources.release_sha256
    long = catalog.for_formation_profile(LONG_OUTPUT_PROFILE, discussion_routes=False).collaboration
    assert (
        long.formation_driven
        and long.counting['output_limit'] != resources.counting['output_limit']
    )
    assert (
        catalog.for_collaboration_release(
            selected.collaboration.reference('collaboration.release')
        ).collaboration.release_sha256
        == resources.release_sha256
    )


def test_output_has_original_nine_roots_and_same_eight_text_count_strategy(resources):
    definition = resources.bundle['$defs']['OutputDiscussion']
    assert list(definition['properties']) == [
        'schema_version',
        'response_type',
        'message',
        'basis_ref',
        'progress_delta',
        'cards',
        'document_result',
        'suggestions',
        'analysis',
    ]
    assert definition['additionalProperties'] is False
    assert resources.layout == 'formation_context_v21_1'
    assert resources.release['formation_protocol'] == 'formation_v21_1'
    assert (
        resources.counting['max_chat_calls'] == 1 and resources.counting['transport_retries'] == 0
    )
    assert resources.release['admission']['state'] == 'OFFLINE_READY'
    from backend.app.infrastructure.model_profile import DEFAULT_PROFILE, ModelProfile

    with pytest.raises(ConfigInvalid):
        resources.require_live(ModelProfile('offline-placeholder', DEFAULT_PROFILE).snapshot)


def test_wire_schema_separates_aliases_from_private_identity_basis(resources):
    defs = resources.bundle['$defs']
    canonical = defs['CanonicalFormation']['properties']['goal']['anyOf'][0]['properties'][
        'source_refs'
    ]
    wire = defs['WireFormation']['properties']['goal']['anyOf'][0]['properties']['source_refs']
    assert canonical['items']['$ref'] == '#/$defs/SourceRef'
    assert wire['items']['$ref'] == '#/$defs/FormationAliasRef'
    for name in ('CanonicalFormation', 'WireFormation'):
        assert 'publication_binding' not in defs[name]['properties']
    step = deepcopy(examples()[9])
    step['source_refs'] = [{'kind': 'MESSAGE', 'message_id': 1}]
    with pytest.raises(ProtocolInvalid):
        resources.validate('FormationChange', step)


def test_previous_formation_resources_remain_frozen_and_historically_selectable(resources):
    catalog = ResourceCatalog()
    for batch in ('v27', 'v28', 'v29', 'v30', 'v31', 'v32', 'v33', 'v34', 'v35', 'v36'):
        previous = CollaborationResources.load(ROOT.parent / batch)
        assert previous.release_sha256 != resources.release_sha256
        assert previous.release['prompt']['version'] == (
            'v8' if batch in ('v27', 'v28') else 'v9' if batch in ('v29', 'v30') else 'v10'
        )
        selected = catalog.for_collaboration_release(previous.reference('collaboration.release'))
        assert selected.collaboration.release_sha256 == previous.release_sha256
    assert resources.release['prompt']['version'] == 'v10'
