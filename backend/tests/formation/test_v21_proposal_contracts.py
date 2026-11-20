"""The persisted proposal is exact, typed, and cannot carry replacement authority."""

from copy import deepcopy
import pytest

from backend.app.formation.proposal_contracts import proposal_group
from backend.app.infrastructure.resources import ProtocolInvalid, ResourceCatalog
from backend.app.shared.validation import InvalidInput
from backend.tests.guide.test_v15_cards import card


@pytest.fixture(scope='module')
def resources():
    return ResourceCatalog().collaboration


def group(purpose='STAGED_WRITE'):
    payload = (
        {
            'step_ref': 's1',
            'result_refs': ['s1.o1'],
            'write_mode': 'FILL_EMPTY',
            'document_revision_id': 1,
            'content_version': 1,
            'goal_version': 1,
            'definition_version': 1,
            'scope': {'scope_type': 'DOCUMENT', 'scope_ref': None},
            'markdown_content': '  # 原文\r\n\r\n正文  ',
            'patches': [],
            'change_summary': '保存成果',
            'source_refs': [],
        }
        if purpose == 'STAGED_WRITE'
        else {
            'basis': {
                'formation_version': 1,
                'goal_version': 1,
                'document_revision_id': 1,
                'content_version': 1,
            },
            'changes': [
                {
                    'type': 'ADD_STEP',
                    'temp_step_ref': 'new_step_1',
                    'title': '下一步',
                    'expected_results': [
                        {
                            'temp_result_ref': 'new_result_1',
                            'description': '成果',
                            'kind': 'CONTENT',
                        }
                    ],
                    'dependencies': ['s1'],
                    'replaces_step_refs': [],
                    'before_step_ref': None,
                }
            ],
            'result_routes': [],
            'change_summary': '补充路线',
            'source_refs': [],
        }
    )
    return {
        'schema_version': 1,
        'intro': '',
        'purpose': purpose,
        'cards': [card(('apply',))],
        'action_payload': payload,
    }


def test_single_apply_preserves_exact_markdown_and_detaches_original(resources):
    original = group()
    parsed = proposal_group(original, resources)
    assert parsed == original
    assert (
        parsed['action_payload']['markdown_content'].encode()
        == b'  # \xe5\x8e\x9f\xe6\x96\x87\r\n\r\n\xe6\xad\xa3\xe6\x96\x87  '
    )
    parsed['cards'][0]['options'][0]['label'] = '更改副本'
    assert original['cards'][0]['options'][0]['label'] == 'apply'


@pytest.mark.parametrize(
    'mutation',
    [
        lambda g: g.update(program_binding={}),
        lambda g: g['action_payload'].update(binding={}),
        lambda g: g['action_payload'].update(result_refs=['s2.o1']),
        lambda g: g['action_payload'].update(step_ref='new_step_1'),
        lambda g: g['action_payload'].update(content_version=True),
        lambda g: g['action_payload'].update(markdown_content=None),
        lambda g: g['action_payload'].update(patches=[{}]),
        lambda g: g['action_payload'].update(
            scope={'scope_type': 'SECTION', 'scope_ref': {'heading_block_id': 1}}
        ),
        lambda g: g['cards'][0].update(card_type='CONFIRM'),
        lambda g: g['cards'][0].update(required=False),
        lambda g: g['cards'][0].update(custom_answer={'enabled': True, 'max_length': 20}),
        lambda g: g['cards'][0]['options'][0].update(option_key='defer'),
        lambda g: g['cards'].append(deepcopy(g['cards'][0])),
        lambda g: g['cards'][0].update(
            recommendation={'option_keys': ['defer'], 'reason': '另行处理'}
        ),
    ],
)
def test_client_authority_invalid_payload_and_ambiguous_choices_are_rejected(mutation, resources):
    value = group()
    mutation(value)
    with pytest.raises((InvalidInput, ProtocolInvalid)):
        proposal_group(value, resources)


def test_path_future_symbols_stay_unallocated_and_stored_binding_is_only_legacy_projection(
    resources,
):
    value = group('FORMATION_PATH_CHANGE')
    expected = deepcopy(value)
    value['program_binding'] = {
        'discussion_version': 2,
        'target_content_version': 1,
        'source_heads': [],
    }
    parsed = proposal_group(value, resources, stored=True)
    assert parsed['action_payload'] == expected['action_payload']
    assert parsed['action_payload']['changes'][0]['temp_step_ref'] == 'new_step_1'
    with pytest.raises(InvalidInput):
        proposal_group(value, resources)


def test_patch_mode_never_accepts_an_alternative_full_document(resources):
    value = group()
    value['action_payload']['write_mode'] = 'PATCH_EXISTING'
    value['action_payload']['markdown_content'] = None
    with pytest.raises(InvalidInput):
        proposal_group(value, resources)
