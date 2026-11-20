"""Empirical reserve candidate keeps hard budgets and old release history."""

import pytest

from backend.app.infrastructure.collaboration_resources import ROOT, CollaborationResources
from backend.app.infrastructure.practical_usage import validate_collaboration_measurements
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog


def validate(release, gap, *, output=1353, text=24842):
    incoming = text + gap
    raw = {
        'model': release['model'],
        'object': 'chat.completion',
        'usage': {
            'prompt_tokens': incoming,
            'completion_tokens': output,
            'total_tokens': incoming + output,
        },
    }
    validate_collaboration_measurements(
        raw,
        model=release['model'],
        release=release,
        counts=[text - 1002, 1002, 1, 1, 1, 1, 1, 1],
        input_tokens=incoming,
        output_tokens=output,
    )


def test_old_actual_gap_stays_rejected_by_old_resource_and_new_is_only_candidate():
    old = CollaborationResources.load(ROOT.parent / 'v33')
    new = ResourceCatalog().for_formation_profile('deepseek-v2').collaboration
    assert old.counting['framing_reserve'] == 1024
    assert new.counting['framing_reserve'] == 2048
    assert new.release['admission']['state'] == 'OFFLINE_READY'
    assert new.release_sha256 != old.release_sha256
    for name in ('input_limit', 'output_limit', 'total_limit'):
        assert new.counting[name] == old.counting[name]
    with pytest.raises(ConfigInvalid):
        validate(old.counting, 1641)
    validate(new.counting, 1641)
    for gap in (-1, 2049):
        with pytest.raises(ConfigInvalid):
            validate(new.counting, gap)
    with pytest.raises(ConfigInvalid):
        validate(new.counting, 0, text=131073)
    with pytest.raises(ConfigInvalid):
        validate(new.counting, 0, output=8193)
    from backend.app.infrastructure.model_profile import ModelProfile

    with pytest.raises(ConfigInvalid):
        new.require_live(ModelProfile('offline-only-reserve', 'deepseek-v2').snapshot)


def test_counter_candidate_reserves_more_inside_the_same_hard_limit():
    old = CollaborationResources.load(ROOT.parent / 'v33').counting
    new = ResourceCatalog().for_formation_profile('deepseek-v2').collaboration.counting
    text = 130000
    assert text + old['framing_reserve'] <= old['input_limit']
    assert text + new['framing_reserve'] > new['input_limit']


def test_counting_release_and_admission_bind_the_same_reserve():
    from backend.app.infrastructure.model_profile import ModelProfile

    for identity in ('deepseek-v2', 'deepseek-long-v3'):
        resource = ResourceCatalog().for_formation_profile(identity).collaboration
        baseline = resource.validate('Admission', resource.release['admission'])
        assert baseline['reserve'] == resource.counting['framing_reserve'] == 2048
        evidence = {
            **baseline,
            'state': 'LIVE_VERIFIED',
            'evidence_ref': 'llm-use:1',
            'count_request_sha256': 'a' * 64,
            'chat_request_sha256': 'b' * 64,
            'actual_input_tokens': 26483,
            'counted_system_tokens': 23840,
            'counted_user_tokens': 1002,
            'framing_gap': 1641,
        }
        resource.validate('Admission', evidence)
        with pytest.raises(ConfigInvalid):
            resource.require_live(ModelProfile('offline-only-reserve', identity).snapshot)
