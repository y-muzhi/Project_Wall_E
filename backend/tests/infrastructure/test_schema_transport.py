"""D-011 graph-closure guarantee and all immutable v1/v2 Function resources."""
from copy import deepcopy
import hashlib
import json
import unittest

from jsonschema import Draft202012Validator

from backend.app.infrastructure.resources import ResourceCatalog, FUNCTIONS, ConfigInvalid
from backend.app.infrastructure.schema_transport import derive_schema, function_schema, compact, DIALECT


def schema():
    return {'$schema': DIALECT, '$id': 'urn:walle:transport-test:v1',
            'type': 'object', 'properties': {'answer': {'$ref': '#/$defs/choice'}},
            'required': ['answer'], 'additionalProperties': False,
            '$defs': {'choice': {'oneOf': [{'$ref': '#/$defs/positive'}, {'type': 'string', 'const': 'unknown'}]},
                      'positive': {'type': 'integer', 'minimum': 1, 'maximum': 3},
                      'unused': {'type': 'object', 'required': ['never'], 'additionalProperties': False}}}


class SchemaTransportTests(unittest.TestCase):
    def test_all_twelve_signed_functions_retain_root_and_complete_reachable_definitions(self):
        catalog = ResourceCatalog()
        for version in ('v1', 'v2'):
            for action, source in FUNCTIONS:
                current = catalog.freeze(action, source)
                frozen = catalog.restore(current.function_type, version,
                    prompt_version=version, context_template=current.context_template.split('@')[0]+'@'+version)
                with self.subTest(function=frozen.function_type, version=version):
                    raw = frozen.output_schema_json; original = json.loads(raw)
                    derived = function_schema(frozen)
                    self.assertEqual(frozen.output_schema_json, raw)
                    self.assertEqual({key: value for key, value in original.items() if key != '$defs'},
                                     {key: value for key, value in derived.schema.items() if key != '$defs'})
                    self.assertTrue(derived.removed_definitions)
                    self.assertEqual(derived.schema['$defs'], {key: original['$defs'][key] for key in derived.retained_definitions})
                    self.assertEqual(derived.original_sha256, hashlib.sha256(raw.encode()).hexdigest())
                    self.assertEqual(derived.derived_sha256, hashlib.sha256(derived.schema_json.encode()).hexdigest())
                    self.assertEqual(function_schema(frozen), derived)
                    self.assertLess(len(derived.schema_json.encode()), len(compact(original).encode()))
                    Draft202012Validator.check_schema(derived.schema)

    def test_no_constraint_is_relaxed_and_original_object_is_not_mutated(self):
        original = schema(); before = deepcopy(original)
        actual = derive_schema(compact(original))
        self.assertEqual(original, before)
        self.assertEqual(actual.retained_definitions, ('choice', 'positive'))
        self.assertEqual(actual.removed_definitions, ('unused',))
        full, sent = Draft202012Validator(original), Draft202012Validator(actual.schema)
        valid = [{'answer': 1}, {'answer': 3}, {'answer': 'unknown'}]
        invalid = [{}, {'answer': 0}, {'answer': 4}, {'answer': True}, {'answer': 1, 'extra': 2}, {'answer': 'UNKNOWN'}, {'answer': None}]
        for instance, expected in [(instance, True) for instance in valid] + [(instance, False) for instance in invalid]:
            self.assertEqual(full.is_valid(instance), sent.is_valid(instance))
            self.assertEqual(sent.is_valid(instance), expected)

    def test_ref_siblings_and_unused_boolean_defs_are_preserved(self):
        original = schema(); original['properties']['answer']['not'] = {'const': 2}
        original['$defs']['positive']['anyOf'] = [True, False]
        actual = derive_schema(compact(original)).schema
        self.assertEqual(actual['properties'], original['properties'])
        self.assertFalse(Draft202012Validator(actual).is_valid({'answer': 2}))

    def test_external_indirect_missing_and_escaped_refs_refuse(self):
        for ref in ('https://elsewhere/schema', '#/properties/answer', '#/$defs/absent', '#/$defs/a~1b', '#anchor', '#'):
            with self.subTest(ref=ref):
                value = schema(); value['properties']['answer']['$ref'] = ref
                with self.assertRaises(ConfigInvalid): derive_schema(compact(value))

    def test_recursive_even_unreachable_dynamic_and_embedded_identifiers_refuse(self):
        for key, value in (('$dynamicRef', '#/$defs/choice'), ('$anchor', 'anchor'),
                           ('$id', 'urn:other'), ('$recursiveRef', '#'), ('$schema', DIALECT),
                           ('$defs', {'nested': True}), ('$vocabulary', {})):
            with self.subTest(key=key):
                original = schema(); original['$defs']['unused'][key] = value
                with self.assertRaises(ConfigInvalid): derive_schema(compact(original))
        original = schema(); original['$defs']['unused'] = {'$ref': '#/$defs/unused'}
        with self.assertRaises(ConfigInvalid): derive_schema(compact(original))
        original = schema(); original['$defs']['positive'] = {'$ref': '#/$defs/choice'}
        with self.assertRaises(ConfigInvalid): derive_schema(compact(original))

    def test_other_dialects_relative_base_and_invalid_json_refuse(self):
        for change in ({'$schema': 'https://json-schema.org/draft-07/schema'}, {'$id': '/relative'}, {'$id': 'urn:test#fragment'}, {'$defs': []}):
            original = {**schema(), **change}
            with self.assertRaises(ConfigInvalid): derive_schema(compact(original))
        for raw in ('{}', '[]', '{"$schema":null,"$schema":null}', '{not json}'):
            with self.assertRaises(ConfigInvalid): derive_schema(raw)

    def test_annotation_reference_scanning_can_only_retain_extra_definitions(self):
        original = schema(); original['examples'] = [{'$ref': '#/$defs/unused'}]
        actual = derive_schema(compact(original))
        self.assertEqual(actual.removed_definitions, ())
        self.assertEqual(actual.schema, original)

    def test_instance_property_names_do_not_become_resolution_keywords(self):
        original = schema(); original['properties'].update({name: {'type': 'string'} for name in ('id', '$id', '$ref')})
        actual = derive_schema(compact(original))
        self.assertEqual(actual.schema['properties'], original['properties'])
        self.assertEqual(actual.retained_definitions, ('choice', 'positive'))
