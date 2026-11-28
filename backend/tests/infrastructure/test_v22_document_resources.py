"""Cover frozen template and collaboration projections used by private recovery."""

import shutil

import pytest

from backend.app.infrastructure import resources


def test_document_resources_share_frozen_templates_and_message_contract():
    recovery = resources.DocumentResources()
    ordinary = resources.ResourceCatalog(
        resources.DEFAULT_ROOT,
        versioned_root=resources.V2_ROOT,
        extended_root=resources.V3_ROOT,
        heading_root=resources.V6_ROOT,
        promoted_heading_root=resources.V7_ROOT,
    )
    for requirement, key, version in (
        ('NEW', 'new-requirement', 'v1'),
        ('NEW', 'new-requirement', 'v2'),
        ('NEW', 'new-requirement', 'v3'),
        ('NEW', 'new-requirement', 'v4'),
        ('CHANGE', 'change-requirement', 'v1'),
    ):
        assert recovery.template(requirement, key, version) == ordinary.template(
            requirement, key, version
        )

    reference = ordinary.collaboration.reference('collaboration.contract')
    assert recovery.collaboration.content(reference) == ordinary.collaboration.content(reference)
    with pytest.raises(resources.ConfigInvalid):
        recovery.collaboration.content({**reference, 'digest': '0' * 64})
    with pytest.raises(resources.TemplateInvalid):
        recovery.template('CHANGE', 'new-requirement', 'v4')


def test_document_resources_validate_template_bytes_without_model_admission(monkeypatch, tmp_path):
    def reject_unrelated_validation(*_args, **_kwargs):
        pytest.fail('Document template loading must not validate model Function schemas')

    monkeypatch.setattr(resources.Draft202012Validator, 'check_schema', reject_unrelated_validation)
    assert resources.DocumentResources().template('NEW', 'new-requirement', 'v4').locked_headings

    damaged = tmp_path / 'damaged-heading-release'
    shutil.copytree(resources.V7_ROOT, damaged)
    template = damaged / 'templates/new-requirement.v4.md'
    original = template.read_bytes()
    altered = bytes([original[0] ^ 1]) + original[1:]
    template.write_bytes(altered)
    monkeypatch.setattr(resources, 'V7_ROOT', damaged)
    with pytest.raises(resources.ConfigInvalid, match='Frozen heading-template resource'):
        resources.DocumentResources()


def test_preverified_default_collaboration_is_reused_only_for_its_profile():
    from backend.app.infrastructure.collaboration_resources import CollaborationResources, ROOT
    from backend.app.infrastructure.model_profile import ModelProfile, LONG_OUTPUT_PROFILE

    verified = CollaborationResources.load(ROOT)
    recovery = resources.DocumentResources(default_collaboration=verified)
    default_profile = ModelProfile.selected_profile({})
    assert recovery.for_collaboration_profile(default_profile).collaboration is verified

    long = recovery.for_collaboration_profile(LONG_OUTPUT_PROFILE).collaboration
    assert long.release_sha256 != verified.release_sha256
    assert long.release_sha256 == CollaborationResources.load(ROOT.parent / 'v18').release_sha256
