"""Frozen V2.1 provider grammar, separate from the authoritative local schema.

Only explicitly released DISCUSS requests opt in. Literal values/property names
are never treated as schema keywords. The private basis is read locally; only
the public output grammar and already-sent current block aliases reach the SDK.
"""

import re
from copy import deepcopy

from backend.app.shared.validation import strict_json_object

from .collaboration_resources import sha256
from .resources import ConfigInvalid
from .schema_transport import compact, derive_schema

TRANSPORT = {
    'mode': 'json_schema',
    'projection': 'ark_supported_keywords_v1',
    'strict': True,
    'operations': ['DISCUSS'],
    'bind_current_blocks': True,
}
SCHEMA_MAPS = {'properties', '$defs'}
SCHEMA_ARRAYS = {'anyOf', 'oneOf', 'allOf', 'prefixItems'}
SCHEMA_CHILDREN = {
    'items',
    'additionalProperties',
    'unevaluatedItems',
    'unevaluatedProperties',
}
LITERAL_KEYWORDS = {'type', '$ref', 'const', 'enum', 'required', 'description', 'title'}
# These constraints remain mandatory in the unchanged complete local validator.
# Conditional correlations are not claimed as provider-enforced.
LOCAL_ONLY = {
    '$schema',
    '$id',
    'minimum',
    'maximum',
    'exclusiveMinimum',
    'exclusiveMaximum',
    'multipleOf',
    'minLength',
    'maxLength',
    'pattern',
    'format',
    'minItems',
    'maxItems',
    'uniqueItems',
    'minProperties',
    'maxProperties',
    'if',
    'then',
    'else',
    'examples',
    'default',
    '$comment',
}
BLOCK_REF = re.compile(r'd[1-9][0-9]*v[1-9][0-9]*b[1-9][0-9]*')


def provider_schema(schema):
    """Project known grammar keywords; unknown schema syntax refuses dispatch."""
    if type(schema) is bool:
        return schema
    if type(schema) is not dict:
        raise ConfigInvalid('Provider schema node is invalid')
    output = {}
    for key, value in schema.items():
        if key in SCHEMA_MAPS:
            if type(value) is not dict:
                raise ConfigInvalid('Provider schema mapping is invalid')
            output[key] = {name: provider_schema(child) for name, child in value.items()}
        elif key in SCHEMA_ARRAYS:
            if type(value) is not list:
                raise ConfigInvalid('Provider schema alternatives are invalid')
            # Dropping disjoint patterns can make originally exclusive string
            # alternatives overlap. The provider grammar is a union; the full
            # local schema remains responsible for exact oneOf semantics.
            keyword = 'anyOf' if key == 'oneOf' else key
            if keyword in output or (key == 'oneOf' and 'anyOf' in schema):
                raise ConfigInvalid('Overlapping provider schema unions are unsupported')
            output[keyword] = [provider_schema(child) for child in value]
        elif key in SCHEMA_CHILDREN:
            output[key] = provider_schema(value)
        elif key in LITERAL_KEYWORDS:
            output[key] = deepcopy(value)
        elif key not in LOCAL_ONLY:
            raise ConfigInvalid('Provider schema keyword is unsupported: ' + key)
    return output


def current_blocks(wire):
    target = wire['current_request']['target']
    if target is None or target['kind'] != 'EXISTING':
        return []
    formation = wire['project_position'].get('formation')
    if formation is None:
        raise ConfigInvalid('Formation context is required for block binding')
    basis = formation['basis']
    documents = [
        document
        for document in wire['documents']
        if document['document_id'] == target['document_id']
        and document['content_version'] == target['expected_content_version']
        and document['revision_id'] == basis['document_revision_id']
        and document['content_version'] == basis['content_version']
    ]
    if len(documents) != 1:
        raise ConfigInvalid('Current target revision is missing or duplicated')
    document = documents[0]
    prefix = 'd' + str(document['document_id']) + 'v' + str(document['content_version']) + 'b'
    result = [block['ref'] for block in document['blocks']]
    if len(set(result)) != len(result) or any(
        type(value) is not str or not BLOCK_REF.fullmatch(value) or not value.startswith(prefix)
        for value in result
    ):
        raise ConfigInvalid('Current block aliases are invalid')
    return result


def bind_blocks(schema, references):
    schema = deepcopy(schema)
    definitions = schema['$defs']
    if 'FormationBlockAliasRef' not in definitions:
        raise ConfigInvalid('Released block reference type is missing')
    if references:
        definitions['FormationBlockAliasRef'] = {'type': 'string', 'enum': references}
        return schema
    changes = definitions['FormationChange']['oneOf']
    retained = []
    for change in changes:
        kind = change['properties']['type']['enum'][0]
        if kind == 'ASSOCIATE_CONTENT':
            continue
        if kind == 'ASSESS_STEP':
            change['properties']['document_refs'] = {'type': 'array', 'const': []}
        retained.append(change)
    definitions['FormationChange']['oneOf'] = retained
    # No fabricated enum member: the now unreachable block type is pruned below.
    return schema


def response_format(canonical, wire):
    """Derive from saved, digest-checked resource bytes; never read a catalog/DB."""
    try:
        resources = canonical['resources']
        by_key = {item['resource_ref']['key']: item for item in resources}
        if len(by_key) != len(resources):
            raise ConfigInvalid('Duplicate frozen model transport resource')
        frozen = by_key['collaboration.release']
        if sha256(frozen['content_text']) != frozen['resource_ref']['digest']:
            raise ConfigInvalid('Frozen model release digest differs')
        release = strict_json_object(frozen['content_text'])
        descriptor = release.get('model_transport')
        if descriptor is None:
            return None  # Historical request bodies remain exactly unchanged.
        if type(descriptor) is dict and descriptor.get('mode') == 'openai_responses_v1':
            from .openai_schema import MODE, MODE_V1

            if descriptor not in (MODE, MODE_V1):
                raise ConfigInvalid('Unknown OpenAI model transport')
            return None
        if descriptor != TRANSPORT:
            raise ConfigInvalid('Unknown released model transport')
        operation = wire['current_request']['operation']
        if operation not in TRANSPORT['operations']:
            return None
        if canonical['operation'] != operation:
            raise ConfigInvalid('Frozen model operation differs')
        frozen = by_key['collaboration.output.' + operation.lower()]
        expected = next(
            item['schema_ref']
            for item in release['output_schemas']
            if item['operation'] == operation
        )
        if (
            frozen['resource_ref'] != expected
            or sha256(frozen['content_text']) != expected['digest']
        ):
            raise ConfigInvalid('Frozen output schema identity differs')
        schema = derive_schema(frozen['content_text']).schema
        schema = bind_blocks(schema, current_blocks(wire))
        schema = derive_schema(compact(schema)).schema
        projected = provider_schema(schema)
        return {
            'type': 'json_schema',
            'json_schema': {
                'name': 'walle_discuss_' + sha256(compact(projected))[:16],
                'strict': True,
                'schema': projected,
            },
        }
    except ConfigInvalid:
        raise
    except (KeyError, ValueError, TypeError, StopIteration, RecursionError) as error:
        raise ConfigInvalid('Frozen model output transport is invalid') from error


SYSTEM_TEXT = 'system_plus_output_schema_v1'


def counting_system_text(canonical, system, output_format):
    """Exact released first count text; SDK schema is not an extra Chat message."""
    try:
        frozen = next(
            item
            for item in canonical['resources']
            if item['resource_ref']['key'] == 'collaboration.counting'
        )
        if sha256(frozen['content_text']) != frozen['resource_ref']['digest']:
            raise ConfigInvalid('Frozen counting resource digest differs')
        definition = strict_json_object(frozen['content_text'])
        strategy = definition.get('system_text')
        if strategy is None:
            return system
        if strategy == 'openai_whole_request_v1':
            return system  # Diagnostics only; native whole SDK request is counted.
        if strategy != SYSTEM_TEXT:
            raise ConfigInvalid('Unknown system counting text strategy')
        if output_format is None:
            return system
        if output_format['type'] != 'json_schema':
            raise ConfigInvalid('Schema counting requires its released SDK format')
        return system + '\n' + compact(output_format['json_schema']['schema'])
    except ConfigInvalid:
        raise
    except (KeyError, ValueError, TypeError, StopIteration) as error:
        raise ConfigInvalid('Frozen system counting text is invalid') from error
