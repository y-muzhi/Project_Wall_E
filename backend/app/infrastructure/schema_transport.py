"""D-011 deterministic transport derivation, never an output validator.

Only unreachable root $defs are removed. The supported reference graph has
one root base URI, direct local definition references, and no recursion or
dynamic resolution. Unknown resolution mechanisms fail closed. Production
Builder/Audit still require the independently verified counting release.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from urllib.parse import urlsplit

from .resources import FrozenFunction, ConfigInvalid
from backend.app.shared.validation import strict_json_object

STRATEGY = 'root_reachable_local_defs_v1'
DIALECT = 'https://json-schema.org/draft/2020-12/schema'


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class TransportSchema:
    schema_json: str
    original_sha256: str
    derived_sha256: str
    retained_definitions: tuple[str, ...]
    removed_definitions: tuple[str, ...]

    @property
    def schema(self):
        return strict_json_object(self.schema_json)

    @property
    def evidence(self):
        return {
            'strategy': STRATEGY,
            'original_schema_sha256': self.original_sha256,
            'derived_schema_sha256': self.derived_sha256,
            'retained_definitions': list(self.retained_definitions),
            'removed_definitions': list(self.removed_definitions),
        }


def derive_schema(original_json: str) -> TransportSchema:
    """Preserve every root keyword and retained definition byte-for-value.

    Scanning all dictionary values is intentionally conservative: annotations
    containing reference-looking keys can retain more definitions, or refuse
    unsupported mechanisms, but cannot make a required definition disappear.
    The original signed JSON remains the sole complete validation resource.
    """
    try:
        root = strict_json_object(original_json)
        if root.get('$schema') != DIALECT or type(root.get('$defs')) is not dict:
            raise ValueError('Unsupported schema dialect/definitions')
        base = root.get('$id')
        if base is not None and (
            type(base) is not str or not urlsplit(base).scheme or urlsplit(base).fragment
        ):
            raise ValueError('Unsupported root base URI')
        definitions = root['$defs']

        def references(node, *, top=False, mapping=False):
            found = set()
            if type(node) is dict:
                if mapping:
                    # Property names (including "id", "$id" or "$ref") are
                    # instance keys, never schema resolution keywords.
                    for child in node.values():
                        found.update(references(child))
                    return found
                for key, value in node.items():
                    if key in (
                        '$dynamicRef',
                        '$dynamicAnchor',
                        '$recursiveRef',
                        '$recursiveAnchor',
                        '$anchor',
                        '$vocabulary',
                        'id',
                    ):
                        raise ValueError('Unsupported schema resolution')
                    if key == '$id' and not top:
                        raise ValueError('Embedded base URI is unsupported')
                    if key == '$schema' and not top:
                        raise ValueError('Embedded dialect is unsupported')
                    if key == '$defs':
                        if not top:
                            raise ValueError('Nested definitions are unsupported')
                        continue
                    if key in ('properties', 'patternProperties', 'dependentSchemas'):
                        if type(value) is not dict:
                            raise ValueError('Schema mapping required')
                        found.update(references(value, mapping=True))
                    elif key == '$ref':
                        if type(value) is not str or not re.fullmatch(
                            r'#\/\$defs\/[A-Za-z_][A-Za-z_0-9]*', value
                        ):
                            raise ValueError('Only direct local named definitions are supported')
                        name = value[8:]
                        if name not in definitions:
                            raise ValueError('Missing local definition')
                        found.add(name)
                    else:
                        found.update(references(value))
            elif type(node) is list:
                for value in node:
                    found.update(references(value))
            return found

        start = references(root, top=True)
        graph = {}
        for name, definition in definitions.items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name) or type(definition) not in (
                dict,
                bool,
            ):
                raise ValueError('Unsupported local definition')
            graph[name] = references(definition)
        visited, active = set(), set()

        def visit(name):
            if name in active:
                raise ValueError('Recursive references are unsupported')
            if name in visited:
                return
            active.add(name)
            for child in graph[name]:
                visit(child)
            active.remove(name)
            visited.add(name)

        # Even unused recursive/identifier mechanisms are refused, not quietly
        # deleted and interpreted under a weaker resolution contract.
        for name in graph:
            visit(name)
        reachable, pending = set(), list(start)
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.extend(graph[name])
        retained = tuple(name for name in definitions if name in reachable)
        removed = tuple(name for name in definitions if name not in reachable)
        derived = {
            key: ({name: definitions[name] for name in retained} if key == '$defs' else value)
            for key, value in root.items()
        }
        encoded = compact(derived)
        return TransportSchema(
            encoded,
            hashlib.sha256(original_json.encode('utf-8')).hexdigest(),
            hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
            retained,
            removed,
        )
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ConfigInvalid('Output schema transport resolution is unsupported') from error


def function_schema(function: FrozenFunction) -> TransportSchema:
    if type(function) is not FrozenFunction:
        raise ConfigInvalid('Frozen Function required')
    return derive_schema(function.output_schema_json)


def named_schema(bundle: dict, entry: str) -> TransportSchema:
    """V1.5 named entry: local closure with lexically ordered definitions.

    Reuses the existing conservative resolution checks; a different bundle
    entry never substitutes for the caller's selected operation contract.
    """
    if type(entry) is not str or entry not in bundle.get('$defs', {}):
        raise ConfigInvalid('Unknown collaboration schema entry')
    root = {'$schema': DIALECT, '$ref': '#/$defs/' + entry, '$defs': bundle['$defs']}
    derived = derive_schema(compact(root))
    schema = derived.schema
    retained = tuple(sorted(derived.retained_definitions))
    schema['$defs'] = {key: schema['$defs'][key] for key in retained}
    encoded = compact(schema)
    return TransportSchema(
        encoded,
        derived.original_sha256,
        hashlib.sha256(encoded.encode('utf-8')).hexdigest(),
        retained,
        derived.removed_definitions,
    )


def declared_json(schema: dict, value) -> str:
    """Validate and serialize instances in named type declaration order.

    Never normalizes strings, fills nullable fields, sorts arrays or removes
    data. Schema objects themselves keep their original keyword order.
    """
    from .resources import _validate, STRICT_VALIDATOR

    _validate(compact(schema), value)
    definitions = schema.get('$defs', {})

    def matches(rule, item):
        return STRICT_VALIDATOR({'$schema': DIALECT, '$defs': definitions, **rule}).is_valid(item)

    def expand(rule, item):
        if type(rule) is not dict:
            return []
        result = []
        if '$ref' in rule:
            result.extend(expand(definitions[rule['$ref'][8:]], item))
        result.append(rule)
        for keyword in ('oneOf', 'anyOf', 'allOf'):
            for branch in rule.get(keyword, []):
                if matches(branch, item):
                    result.extend(expand(branch, item))
        return result

    def order(rule, item):
        rules = expand(rule, item)
        if type(item) is dict:
            properties = {}
            for candidate in rules:
                for key, child in candidate.get('properties', {}).items():
                    properties.setdefault(key, child)
            output = {
                key: order(child, item[key]) for key, child in properties.items() if key in item
            }
            for key in item:
                if key not in output:
                    output[key] = item[key]
            return output
        if type(item) is list:
            items_rule = next(
                (candidate['items'] for candidate in rules if 'items' in candidate), {}
            )
            return [order(items_rule, child) for child in item]
        return item

    return compact(order(schema, value))
