"""OpenAI-only strict output grammar from frozen local resources.

This projection never replaces full local validation and never adds material.
"""

import re
from copy import deepcopy

from backend.app.shared.validation import strict_json_object

from .collaboration_format import bind_blocks, current_blocks
from .collaboration_resources import sha256
from .resources import ConfigInvalid
from .schema_transport import compact, derive_schema

MODE_V1 = {
    'mode': 'openai_responses_v1',
    'projection': 'openai_strict_subset_v1',
    'strict': True,
    'operations': ['DISCUSS', 'GENERATE', 'REVISE', 'PROPOSE_CHANGES', 'COMPARE', 'REVIEW'],
    'bind_current_blocks': True,
}
MODE = {**MODE_V1, 'projection': 'openai_strict_subset_v2'}
LOCAL_ONLY = {
    '$schema',
    '$id',
    'description',
    'title',
    'examples',
    'default',
    '$comment',
    'pattern',
    'format',
    'minLength',
    'maxLength',
    'uniqueItems',
    'minimum',
    'maximum',
    'multipleOf',
    'exclusiveMinimum',
    'exclusiveMaximum',
    'minProperties',
    'maxProperties',
}
SIMPLE = {'type', 'enum', 'required', '$ref', 'minItems', 'maxItems'}
MAPS = {'$defs', 'properties'}
ARRAYS = {'oneOf', 'anyOf'}
CHILDREN = {'items', 'additionalProperties'}


def _enum_refinement(node):
    if type(node) is not dict:
        return False
    if set(node) == {'enum'}:
        return type(node['enum']) is list and bool(node['enum'])
    return (
        set(node) == {'properties'}
        and type(node['properties']) is dict
        and bool(node['properties'])
        and all(_enum_refinement(child) for child in node['properties'].values())
    )


def project(node, *, empty_arrays=False):
    if type(node) is bool:
        return node
    if type(node) is not dict:
        raise ConfigInvalid('OpenAI schema node is invalid')
    result = {}
    for key, value in node.items():
        if key in MAPS:
            result[key] = {
                name: project(child, empty_arrays=empty_arrays) for name, child in value.items()
            }
        elif key in ARRAYS:
            destination = 'anyOf'
            if destination in result:
                raise ConfigInvalid('Conflicting OpenAI schema unions')
            result[destination] = [project(child, empty_arrays=empty_arrays) for child in value]
        elif key in CHILDREN:
            result[key] = project(value, empty_arrays=empty_arrays)
        elif key == 'const':
            if empty_arrays and type(value) in (list, dict):
                if type(value) is not list or value or node.get('type') != 'array':
                    raise ConfigInvalid('Unsupported OpenAI composite constant')
                result['items'] = {'type': 'string'}
                result['minItems'] = 0
                result['maxItems'] = 0
            else:
                result['enum'] = [deepcopy(value)]
        elif key in SIMPLE:
            if key == 'enum' and empty_arrays and any(type(item) in (dict, list) for item in value):
                raise ConfigInvalid('Unsupported OpenAI composite enum')
            if key == '$ref' and not re.fullmatch(r'#/\$defs/[A-Za-z_][A-Za-z_0-9]*', value):
                raise ConfigInvalid('OpenAI requires direct local schema references')
            result[key] = deepcopy(value)
        elif key == 'allOf':
            # Current contracts use this exclusively for conditional field
            # correlations. Full local validation retains those correlations.
            if type(value) is not list or any(
                type(child) is not dict
                or 'if' not in child
                or not set(child) <= {'if', 'then', 'else'}
                for child in value
            ):
                if (
                    set(node) == {'allOf'}
                    and type(value) is list
                    and len(value) == 2
                    and type(value[0]) is dict
                    and set(value[0]) == {'$ref'}
                    and _enum_refinement(value[1])
                ):
                    result.update(project(value[0], empty_arrays=empty_arrays))
                else:
                    raise ConfigInvalid('Unsupported OpenAI schema intersection')
        elif key in ('if', 'then', 'else'):
            continue  # Local-only conditional correlation, not provider grammar.
        elif key not in LOCAL_ONLY:
            raise ConfigInvalid('Unsupported OpenAI schema keyword: ' + key)
    if result.get('type') == 'object':
        if result.get('additionalProperties') is not False:
            raise ConfigInvalid('OpenAI requires closed object output')
        if set(result.get('required', [])) != set(result.get('properties', {})):
            raise ConfigInvalid('OpenAI requires all output fields')
    return result


def validate_limits(schema):
    definitions = schema.get('$defs', {})
    properties = 0
    enums = 0
    strings = 0

    def inspect(node):
        nonlocal properties, enums, strings
        if type(node) is dict:
            for key, value in node.items():
                if key in MAPS:
                    strings += sum(len(name) for name in value)
                    if key == 'properties':
                        properties += len(value)
                    for child in value.values():
                        inspect(child)
                elif key == 'enum':
                    enums += len(value)
                    strings += sum(len(item) for item in value if type(item) is str)
                elif type(value) in (dict, list):
                    inspect(value)
        elif type(node) is list:
            for child in node:
                inspect(child)

    def depth(node, level=0, active=()):
        if type(node) is not dict:
            return level
        if '$ref' in node:
            name = node['$ref'][8:]
            if name in active or name not in definitions:
                raise ConfigInvalid('Recursive or missing OpenAI output definition')
            return depth(definitions[name], level, (*active, name))
        next_level = level + (node.get('type') in ('object', 'array'))
        greatest = next_level
        for keyword in ('properties',):
            for child in node.get(keyword, {}).values():
                greatest = max(greatest, depth(child, next_level, active))
        if 'items' in node:
            greatest = max(greatest, depth(node['items'], next_level, active))
        for child in node.get('anyOf', []):
            greatest = max(greatest, depth(child, next_level, active))
        return greatest

    inspect(schema)
    nesting = depth(schema)
    if properties > 5000 or enums > 1000 or strings > 120000 or nesting > 10:
        raise ConfigInvalid('OpenAI output schema exceeds supported capacity')
    return {
        'properties': properties,
        'enum_values': enums,
        'string_characters': strings,
        'nesting': nesting,
    }


def schema_for(original, *, block_refs=None, projection=MODE['projection']):
    schema = derive_schema(original).schema
    if block_refs is not None:
        schema = bind_blocks(schema, block_refs)
        schema = derive_schema(compact(schema)).schema
    if projection not in (MODE['projection'], MODE_V1['projection']):
        raise ConfigInvalid('Unknown OpenAI projection version')
    projected = project(schema, empty_arrays=projection == MODE['projection'])
    definitions = projected['$defs']
    root = {key: value for key, value in projected.items() if key != '$defs'}
    seen = set()
    while '$ref' in root:
        name = root['$ref'][8:]
        if name in seen or name not in definitions:
            raise ConfigInvalid('Invalid OpenAI schema root')
        seen.add(name)
        root = deepcopy(definitions[name])
    if set(root) == {'anyOf'}:
        branches = []
        for branch in root['anyOf']:
            while '$ref' in branch:
                branch = definitions[branch['$ref'][8:]]
            if branch.get('type') != 'object':
                raise ConfigInvalid('OpenAI root alternatives must be objects')
            branches.append(branch)
        fields = list(branches[0]['properties'])
        if any(
            list(branch.get('properties', {})) != fields
            or set(branch.get('required', [])) != set(fields)
            or branch.get('additionalProperties') is not False
            for branch in branches
        ):
            raise ConfigInvalid('OpenAI root fields differ')
        props = {}
        for name in fields:
            alternatives = []
            for branch in branches:
                value = branch['properties'][name]
                if value not in alternatives:
                    alternatives.append(value)
            props[name] = alternatives[0] if len(alternatives) == 1 else {'anyOf': alternatives}
        root = {
            'type': 'object',
            'properties': props,
            'required': fields,
            'additionalProperties': False,
        }
    if root.get('type') != 'object' or 'anyOf' in root:
        raise ConfigInvalid('OpenAI output requires an object root')
    result = {**root, '$defs': definitions}
    validate_limits(result)
    return result


def output_format(context):
    try:
        resources = context.canonical['resources']
        by_key = {item['resource_ref']['key']: item for item in resources}
        if len(by_key) != len(resources):
            raise ConfigInvalid('Duplicate OpenAI frozen resource')
        frozen = by_key['collaboration.release']
        if sha256(frozen['content_text']) != frozen['resource_ref']['digest']:
            raise ConfigInvalid('OpenAI frozen release digest differs')
        release = strict_json_object(frozen['content_text'])
        descriptor = release.get('model_transport')
        if descriptor not in (MODE, MODE_V1):
            raise ConfigInvalid('Frozen release does not authorize OpenAI transport')
        operation = context.input['current_request']['operation']
        if context.canonical['operation'] != operation or operation not in MODE['operations']:
            raise ConfigInvalid('OpenAI operation differs')
        expected = next(
            item['schema_ref']
            for item in release['output_schemas']
            if item['operation'] == operation
        )
        frozen = by_key['collaboration.output.' + operation.lower()]
        if (
            frozen['resource_ref'] != expected
            or sha256(frozen['content_text']) != expected['digest']
        ):
            raise ConfigInvalid('OpenAI frozen output identity differs')
        schema = schema_for(
            frozen['content_text'],
            block_refs=current_blocks(context.input) if operation == 'DISCUSS' else None,
            projection=descriptor['projection'],
        )
        return {
            'type': 'json_schema',
            'name': 'walle_' + operation.lower() + '_' + sha256(compact(schema))[:12],
            'strict': True,
            'schema': schema,
        }
    except ConfigInvalid:
        raise
    except (KeyError, ValueError, TypeError, StopIteration, RecursionError) as error:
        raise ConfigInvalid('OpenAI frozen output format is invalid') from error
