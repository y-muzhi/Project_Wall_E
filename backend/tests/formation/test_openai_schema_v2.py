"""Exact empty-array grammar and byte-for-byte restoration of the old projection."""

import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from formation_evaluation_fixture import prepare_sample
from formation_evaluation_spec import samples

from backend.app.infrastructure.collaboration_resources import ROOT, CollaborationResources
from backend.app.infrastructure.model_profile import OPENAI_PROFILE, ModelProfile
from backend.app.infrastructure.openai_protocol import count_request
from backend.app.infrastructure.openai_schema import project
from backend.app.infrastructure.resources import ConfigInvalid, ResourceCatalog
from backend.app.shared.json_canonical import canonical_input


def composite_enums(schema):
    found = []

    def visit(node):
        if type(node) is not dict:
            return
        if 'enum' in node and any(type(value) in (list, dict) for value in node['enum']):
            found.append(node)
        for keyword in ('properties', '$defs'):
            for child in node.get(keyword, {}).values():
                visit(child)
        for keyword in ('anyOf', 'allOf', 'oneOf'):
            for child in node.get(keyword, []):
                visit(child)
        if type(node.get('items')) is dict:
            visit(node['items'])

    visit(schema)
    return found


def test_empty_array_has_exact_membership_and_explicit_items_in_new_projection():
    source = {'type': 'array', 'const': []}
    old = project(source)
    new = project(source, empty_arrays=True)
    assert old == {'type': 'array', 'enum': [[]]}
    assert new == {'type': 'array', 'items': {'type': 'string'}, 'minItems': 0, 'maxItems': 0}
    for rule in (source, new):
        validator = Draft202012Validator(rule)
        assert validator.is_valid([])
        assert all(not validator.is_valid(value) for value in (None, {}, '', ['d42v1b1'], [None]))
    for source in (
        {'type': 'array', 'const': ['x']},
        {'type': 'object', 'const': {}},
        {'enum': [[]]},
    ):
        with pytest.raises(ConfigInvalid):
            project(source, empty_arrays=True)


def test_actual_frozen_blank_context_uses_v2_and_legacy_count_request_restores_exactly(tmp_path):
    profile = ModelProfile('offline-grammar-fixture', OPENAI_PROFILE)
    catalog = ResourceCatalog().for_formation_profile(OPENAI_PROFILE)
    assert catalog.collaboration.release['version'] == 'openai-v2'
    legacy = catalog.for_collaboration_release(
        CollaborationResources.load(ROOT.parent / 'openai-v1').reference('collaboration.release')
    )
    sample = samples()[0]
    hashes = {}
    for name, active in (('v1', legacy), ('v2', catalog)):
        slot = tmp_path / name
        slot.mkdir()
        context, _ = prepare_sample(slot, active, sample)
        body = profile.request(context)
        schema = body['text']['format']['schema']
        Draft202012Validator.check_schema(schema)
        assert bool(composite_enums(schema)) == (name == 'v1')
        hashes[name] = sha256(canonical_input(count_request(body)).encode()).hexdigest()
        current = active.collaboration.reference('collaboration.release')
        assert (
            catalog.for_collaboration_release(current).collaboration.reference(
                'collaboration.release'
            )
            == current
        )
    # Canonical digest of the actual compat-03 prepared native request. Only a
    # digest is embedded; original audit/resource bytes remain unchanged.
    assert hashes['v1'] == '3fa0174632c0a32a1d9e71cc6f096eb84b70f081f6a68a2db65cd9db8bad0c70'
    assert hashes['v1'] != hashes['v2']
