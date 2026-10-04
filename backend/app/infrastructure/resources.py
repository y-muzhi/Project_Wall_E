"""Frozen, approved template and six Function resources (INF-TEMPLATE/FUNCTION).

Schema validation is a structural gate, never proof of business authorization,
target freshness, facts, or model quality. Those gates belong to later units.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, FormatChecker, validators

from backend.app.shared.validation import InvalidInput, strict_json_object
from .idempotency import canonical_input

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / 'resources' / 'v1'
MANIFEST_SHA256 = '79b9435a8c410009ba93936354a6f15f90d911d6ae0f81194022322b25899bbc'
STRICT_VALIDATOR = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda checker, value: type(value) is int))
FUNCTIONS = {
    ('INITIALIZE', 'USER_INSTRUCTION'): ('INITIALIZE_REQUIREMENT', 'INITIALIZE'),
    ('ASK', 'USER_INSTRUCTION'): ('ANSWER_REQUIREMENT', 'ASK'),
    ('REVIEW', 'USER_INSTRUCTION'): ('REVIEW_REQUIREMENT', 'REVIEW'),
    ('MODIFY', 'USER_INSTRUCTION'): ('MODIFY_REQUIREMENT', 'MODIFY'),
    ('MODIFY', 'REVIEW_RESULT'): ('MODIFY_FROM_REVIEW', 'MODIFY_FROM_REVIEW'),
    ('MODIFY', 'COMMENT'): ('MODIFY_FROM_COMMENT', 'MODIFY_FROM_COMMENT'),
}


class ConfigInvalid(RuntimeError):
    code = 'CONFIG_INVALID'


class TemplateInvalid(RuntimeError):
    code = 'TEMPLATE_INVALID'


@dataclass(frozen=True)
class ProtocolIssue:
    path: str
    rule: str


class ProtocolInvalid(ValueError):
    def __init__(self, issues: tuple[ProtocolIssue, ...]):
        self.issues = issues
        super().__init__('输入或模型输出未满足冻结协议')


def _path(parts) -> str:
    result = '$'
    for part in parts:
        if type(part) is int:
            result += f'[{part}]'
        elif type(part) is str and re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]{0,80}', part):
            result += '.' + part
        else:
            result += '.?'
    return result


def _validate(schema_json: str, value: dict) -> dict:
    try:
        canonical_input(value)  # finite JSON, exact integer range, valid Unicode
    except (ValueError, UnicodeError, RecursionError):
        raise ProtocolInvalid((ProtocolIssue('$', 'json'),)) from None
    validator = STRICT_VALIDATOR(json.loads(schema_json), format_checker=FormatChecker())
    issues = []
    for error in validator.iter_errors(value):
        issues.append(ProtocolIssue(_path(error.absolute_path), error.validator))
        if len(issues) == 20:
            break
    if issues:
        raise ProtocolInvalid(tuple(issues))
    # A detached result prevents caller mutation of any cached schema/resource.
    return json.loads(canonical_input(value))


@dataclass(frozen=True)
class FrozenFunction:
    function_type: str
    version: str
    action_type: str
    source_type: str
    input_schema: str
    output_schema: str
    context_template: str
    prompt_reference: str
    prompt: str
    context_json: str
    input_schema_json: str
    output_schema_json: str
    manifest_sha256: str

    @property
    def context_policy(self) -> dict:
        return json.loads(self.context_json)

    def validate_input(self, value: dict) -> dict:
        return _validate(self.input_schema_json, value)

    def validate_read_manifest(self, value: dict) -> dict:
        definitions = json.loads(self.input_schema_json)['$defs']
        schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$ref': '#/$defs/read_manifest', '$defs': definitions}
        return _validate(json.dumps(schema), value)

    def validate_patch(self, value: dict) -> dict:
        definitions = json.loads(self.output_schema_json)['$defs']
        schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$ref': '#/$defs/patch', '$defs': definitions}
        return _validate(json.dumps(schema), value)

    def validate_allowed_targets(self, value: dict) -> dict:
        root = json.loads(self.input_schema_json)
        schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object', 'properties': {'schema_version': {'type': 'integer', 'const': 1}, 'targets': root['properties']['allowed_targets']}, 'required': ['schema_version', 'targets'], 'additionalProperties': False, '$defs': root['$defs']}
        return _validate(json.dumps(schema), value)

    def parse_output(self, content: str | bytes) -> dict:
        try:
            if type(content) is str:
                if len(content.encode('utf-8')) > 1024 * 1024:
                    raise ProtocolInvalid((ProtocolIssue('$', 'output_capacity'),))
            elif type(content) is bytes and len(content) > 1024 * 1024:
                raise ProtocolInvalid((ProtocolIssue('$', 'output_capacity'),))
            value = strict_json_object(content)
        except (InvalidInput, UnicodeError):
            raise ProtocolInvalid((ProtocolIssue('$', 'single_json_object'),)) from None
        return _validate(self.output_schema_json, value)


@dataclass(frozen=True)
class LockedHeading:
    level: int
    text: str


@dataclass(frozen=True)
class FixedTemplate:
    key: str
    version: str
    label: str
    requirement_types: tuple[str, ...]
    markdown: str
    locked_headings: tuple[LockedHeading, ...]
    manifest_sha256: str


def _inspect_schema(node, root):
    if type(node) is dict:
        if node.get('type') == 'object' and node.get('additionalProperties') is not False:
            raise ConfigInvalid('Every protocol object must reject unknown fields')
        if '$ref' in node:
            reference = node['$ref']
            if not reference.startswith('#/$defs/') or reference[8:] not in root.get('$defs', {}):
                raise ConfigInvalid('Protocol references must be local and resolvable')
        for child in node.values():
            _inspect_schema(child, root)
    elif type(node) is list:
        for child in node:
            _inspect_schema(child, root)


class ResourceCatalog:
    def __init__(self, root: Path | str = DEFAULT_ROOT):
        self.root = Path(root).resolve()
        try:
            raw_manifest = (self.root / 'manifest.json').read_bytes()
            if hashlib.sha256(raw_manifest).hexdigest() != MANIFEST_SHA256:
                raise ConfigInvalid('Frozen resource manifest differs from the approved release')
            manifest = strict_json_object(raw_manifest)
            if manifest['schema_version'] != 1 or manifest['status'] != 'APPROVED':
                raise ConfigInvalid('Resources have not been approved')
            texts = {}
            for entry in manifest['files']:
                relative = Path(entry['path'])
                path = (self.root / relative).resolve()
                if relative.is_absolute() or not path.is_relative_to(self.root):
                    raise ConfigInvalid('Resource path must stay within the frozen catalog')
                content = path.read_bytes()
                if len(content) != entry['bytes'] or hashlib.sha256(content).hexdigest() != entry['sha256']:
                    raise ConfigInvalid('Frozen resource content has changed')
                texts[entry['path']] = content.decode('utf-8', errors='strict')
            schemas = {}
            for name, text in texts.items():
                if name.startswith('schemas/'):
                    schema = strict_json_object(text)
                    if schema.get('$schema') != 'https://json-schema.org/draft/2020-12/schema':
                        raise ConfigInvalid('Draft 2020-12 protocol required')
                    Draft202012Validator.check_schema(schema)
                    _inspect_schema(schema, schema)
                    schemas[Path(name).name.replace('.v1.json', '@v1')] = text
            if len(schemas) != 10:
                raise ConfigInvalid('Six inputs and four shared outputs required')
            self._functions = {}
            entries = strict_json_object(texts['functions.v1.json'])['functions']
            if len(entries) != 6:
                raise ConfigInvalid('All six Functions required')
            for entry in entries:
                action_source = entry['action_type'], entry['source_type']
                expected_function, expected_context = FUNCTIONS[action_source]
                function, version = entry['function_type'], entry['version']
                if function != expected_function or version != 'v1' or entry['context_template'] != expected_context + '_CONTEXT@v1':
                    raise ConfigInvalid('Function mapping differs from the fixed protocol')
                context = texts['contexts/' + entry['context_template'].replace('@', '.') + '.json']
                context_value = strict_json_object(context)
                for field in ('function_type', 'action_type', 'source_type', 'input_schema', 'output_schema', 'prompt'):
                    if context_value[field] != entry[field]:
                        raise ConfigInvalid('Function and ContextTemplate do not agree')
                self._functions[(function, version)] = FrozenFunction(function, version, *action_source, entry['input_schema'], entry['output_schema'], entry['context_template'], entry['prompt'], texts['prompts/' + entry['prompt'].replace('@', '.') + '.md'], context, schemas[entry['input_schema']], schemas[entry['output_schema']], MANIFEST_SHA256)
            self._templates = {}
            self._catalog_json = texts['templates/catalog.v1.json']
            for template in strict_json_object(self._catalog_json)['templates']:
                key, version = template['template_key'], template['template_version']
                metadata = strict_json_object(texts[f'templates/{key}.{version}.json'])
                if metadata != template:
                    raise ConfigInvalid('Template catalog and metadata do not agree')
                self._templates[(key, version)] = FixedTemplate(key, version, template['label'], tuple(template['requirement_types']), texts[template['markdown_path']], tuple(LockedHeading(**heading) for heading in template['locked_headings']), MANIFEST_SHA256)
        except ConfigInvalid:
            raise
        except Exception as error:
            raise ConfigInvalid('Frozen resource catalog cannot be loaded') from error

    def template(self, requirement_type: str, key: str, version: str) -> FixedTemplate:
        template = self._templates.get((key, version))
        if template is None or requirement_type not in template.requirement_types:
            raise TemplateInvalid('模板不存在或不适用于需求类型')
        return template

    def freeze(self, action_type: str, source_type: str) -> FrozenFunction:
        try:
            function, _ = FUNCTIONS[(action_type, source_type)]
            return self.restore(function, 'v1')
        except (KeyError, TypeError):
            raise ConfigInvalid('No Function matches this action and source') from None

    def restore(self, function_type: str, version: str, *, prompt_version: str | None = None, context_template: str | None = None) -> FrozenFunction:
        try:
            function = self._functions[(function_type, version)]
        except (KeyError, TypeError):
            raise ConfigInvalid('Frozen Function version is missing; no fallback allowed') from None
        if prompt_version is not None and prompt_version != function.version or context_template is not None and context_template != function.context_template:
            raise ConfigInvalid('Frozen Prompt or ContextTemplate does not match')
        return function

    @property
    def frontend_catalog(self) -> dict:
        """Build-time catalog, no extra public configuration endpoint."""
        return {**json.loads(self._catalog_json), 'manifest_sha256': MANIFEST_SHA256}
