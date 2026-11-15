"""OC20-MODEL-1 text/tool request verification and exact supplier projection."""

import re
from dataclasses import dataclass, field

from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

REQUEST_BYTES = 4 * 1024 * 1024
ALIASES = {'walle-code': 'CODE', 'walle-compaction': 'COMPACTION'}
_OPTIONAL = frozenset(('top_p', 'frequency_penalty', 'presence_penalty', 'stop', 'seed'))
_FIXED = {'stream': True, 'temperature': 0, 'service_tier': 'default', 'n': 1}
_TOP = frozenset(
    (
        'model',
        'messages',
        'tools',
        'tool_choice',
        'parallel_tool_calls',
        'max_tokens',
        'stream_options',
        'thinking',
        *_FIXED,
        *_OPTIONAL,
    )
)
_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')


class CodingModelProtocolError(ValueError):
    pass


def _reject():
    raise CodingModelProtocolError('CODING_MODEL_REQUEST_INVALID')


def _positive(value):
    return type(value) is int and 1 <= value <= MAX_SAFE_INTEGER


def _name(value):
    return type(value) is str and _NAME.fullmatch(value) is not None


@dataclass(frozen=True)
class CodingRequestContract:
    alias: str
    model_name: str
    input_cap: int
    context_cap: int
    output_cap: int
    authorization_output_cap: int
    chunk_usage: bool = False
    optional_fields: frozenset[str] = frozenset()

    def __post_init__(self):
        if (
            type(self.alias) is not str
            or self.alias not in ALIASES
            or type(self.model_name) is not str
            or not self.model_name
            or self.model_name.strip() != self.model_name
            or any(
                not _positive(value)
                for value in (
                    self.input_cap,
                    self.context_cap,
                    self.output_cap,
                    self.authorization_output_cap,
                )
            )
            or self.context_cap <= self.input_cap
            or type(self.chunk_usage) is not bool
            or type(self.optional_fields) is not frozenset
            or not self.optional_fields <= _OPTIONAL
        ):
            raise CodingModelProtocolError('CODING_MODEL_REQUEST_CONTRACT_INVALID')

    @property
    def permitted_output(self):
        return min(
            self.output_cap, self.authorization_output_cap, self.context_cap - self.input_cap
        )


@dataclass(frozen=True)
class CodingModelRequest:
    native: dict = field(repr=False)
    supplier: dict = field(repr=False)
    supplier_body: bytes = field(repr=False)
    output_cap: int


def parse_request(raw):
    if type(raw) is not bytes or not 1 <= len(raw) <= REQUEST_BYTES:
        _reject()
    try:
        value = strict_json_object(raw)
    except (ValueError, RecursionError):
        _reject()
    alias = value.get('model')
    if (
        type(alias) is not str
        or alias not in ALIASES
        or 'messages' not in value
        or value.keys() - _TOP
    ):
        _reject()
    return value


def _text_content(value):
    if type(value) is str:
        return True
    return (
        type(value) is list
        and bool(value)
        and all(
            type(part) is dict
            and set(part) == {'type', 'text'}
            and part['type'] == 'text'
            and type(part['text']) is str
            for part in value
        )
    )


def _call_id(value):
    return type(value) is str and 1 <= len(value) <= 256 and value.isprintable()


def _tool_call(value):
    if (
        type(value) is not dict
        or set(value) != {'id', 'type', 'function'}
        or value['type'] != 'function'
    ):
        _reject()
    call, function = value['id'], value['function']
    if (
        not _call_id(call)
        or type(function) is not dict
        or set(function) != {'name', 'arguments'}
        or not _name(function['name'])
        or type(function['arguments']) is not str
    ):
        _reject()
    return call


def _messages(values):
    if type(values) is not list or not values:
        _reject()
    awaiting, used = set(), set()
    for message in values:
        if type(message) is not dict:
            _reject()
        role = message.get('role')
        common = {'role', 'content', 'name'}
        content = message.get('content')
        if 'name' in message and not _name(message['name']):
            _reject()
        if role == 'tool':
            call = message.get('tool_call_id')
            if (
                message.keys() - (common | {'tool_call_id'})
                or not _call_id(call)
                or call not in awaiting
                or not _text_content(content)
            ):
                _reject()
            awaiting.remove(call)
            continue
        if awaiting:
            _reject()
        if role in ('system', 'user'):
            if message.keys() - common or not _text_content(content):
                _reject()
        elif role == 'assistant':
            if message.keys() - (common | {'tool_calls'}):
                _reject()
            calls = message.get('tool_calls', [])
            if type(calls) is not list or not (
                _text_content(content) or (content is None and calls)
            ):
                _reject()
            for value in calls:
                call = _tool_call(value)
                if call in used:
                    _reject()
                used.add(call)
                awaiting.add(call)
        else:
            _reject()
    if awaiting:
        _reject()


def _local_schema(value):
    pending = [value]
    while pending:
        current = pending.pop()
        if type(current) is dict:
            for key, child in current.items():
                if key in ('$ref', '$dynamicRef', '$recursiveRef') and (
                    type(child) is not str or not child.startswith('#')
                ):
                    _reject()
                if key in ('$id', '$schema') and type(child) is not str:
                    _reject()
                pending.append(child)
        elif type(current) is list:
            pending.extend(current)


def _tools(value):
    if type(value) is not list:
        _reject()
    names = set()
    for item in value:
        if (
            type(item) is not dict
            or set(item) != {'type', 'function'}
            or item['type'] != 'function'
        ):
            _reject()
        function = item['function']
        if (
            type(function) is not dict
            or function.keys() - {'name', 'description', 'parameters', 'strict'}
            or not _name(function.get('name'))
            or function['name'] in names
            or ('description' in function and type(function['description']) is not str)
            or ('parameters' in function and type(function['parameters']) is not dict)
            or ('strict' in function and type(function['strict']) is not bool)
        ):
            _reject()
        if 'parameters' in function:
            _local_schema(function['parameters'])
        names.add(function['name'])
    return names


def _tool_choice(value, names):
    if type(value) is str:
        if value not in ('none', 'auto', 'required') or (value == 'required' and not names):
            _reject()
        return
    if (
        type(value) is not dict
        or set(value) != {'type', 'function'}
        or value['type'] != 'function'
        or type(value['function']) is not dict
        or set(value['function']) != {'name'}
        or not _name(value['function']['name'])
        or value['function']['name'] not in names
    ):
        _reject()


def _verify_optional(request, contract):
    if request.keys() & (_OPTIONAL - contract.optional_fields):
        _reject()
    for key, minimum, maximum in (
        ('top_p', 0, 1),
        ('frequency_penalty', -2, 2),
        ('presence_penalty', -2, 2),
    ):
        if key in request and (
            type(request[key]) not in (int, float) or not minimum <= request[key] <= maximum
        ):
            _reject()
    if 'seed' in request and (
        type(request['seed']) is not int or abs(request['seed']) > MAX_SAFE_INTEGER
    ):
        _reject()
    if 'stop' in request:
        stop = request['stop']
        if not (type(stop) is str and stop) and not (
            type(stop) is list
            and 1 <= len(stop) <= 4
            and all(type(item) is str and item for item in stop)
        ):
            _reject()


def prepare_request(request, contract):
    if (
        type(contract) is not CodingRequestContract
        or type(request) is not dict
        or request.get('model') != contract.alias
        or 'messages' not in request
        or request.keys() - _TOP
    ):
        _reject()
    _messages(request['messages'])
    names = _tools(request.get('tools', []))
    if 'tool_choice' in request:
        _tool_choice(request['tool_choice'], names)
    if 'parallel_tool_calls' in request and type(request['parallel_tool_calls']) is not bool:
        _reject()
    _verify_optional(request, contract)
    for key, fixed in _FIXED.items():
        if key in request and (
            request[key] != fixed
            or (
                type(request[key]) is not type(fixed)
                and not (key == 'temperature' and type(request[key]) is float)
            )
        ):
            _reject()
    options = request.get('stream_options', {})
    fields = {'include_usage', 'chunk_include_usage'} if contract.chunk_usage else {'include_usage'}
    if (
        type(options) is not dict
        or options.keys() - fields
        or options.get('include_usage', True) is not True
        or ('chunk_include_usage' in options and type(options['chunk_include_usage']) is not bool)
        or ('thinking' in request and request['thinking'] != {'type': 'disabled'})
    ):
        _reject()
    output = request.get('max_tokens', contract.permitted_output)
    if not _positive(output) or output > contract.permitted_output:
        _reject()
    supplier = {
        **request,
        **_FIXED,
        'model': contract.model_name,
        'max_tokens': output,
        'stream_options': {**options, 'include_usage': True},
        'thinking': {'type': 'disabled'},
    }
    body = _bytes(supplier)
    if len(body) > REQUEST_BYTES:
        _reject()
    return CodingModelRequest(request, supplier, body, output)
