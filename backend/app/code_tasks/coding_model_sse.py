"""Bounded SSE bytes and original completion/usage evidence for Coding."""

import re
from dataclasses import dataclass, field, replace

from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .coding_model_ledger import FRAME_BYTES, RESPONSE_BYTES
from .usage import UsageState, confirm_final_usage, observe_usage

_TOOL = re.compile(r'[A-Za-z0-9_-]{1,64}')
_FINISH = ('stop', 'tool_calls', 'length', 'content_filter')


class CodingSseError(ValueError):
    pass


def _invalid():
    raise CodingSseError('CODING_MODEL_SSE_UNVERIFIED')


@dataclass(frozen=True)
class CodingSseFrame:
    wire: bytes = field(repr=False)
    kind: str
    audit: dict = field(repr=False)


def _frame(raw):
    try:
        lines = raw.decode('utf-8', errors='strict').split('\n')
        data, comments = [], []
        for item in lines:
            line = item.removesuffix('\r')
            if not line:
                continue
            if line.startswith(':'):
                comments.append(line[1:].removeprefix(' '))
            elif line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            else:
                _invalid()
        if not data:
            return CodingSseFrame(raw, 'KEEPALIVE', {'kind': 'KEEPALIVE', 'comments': comments})
        payload = '\n'.join(data)
        if payload == '[DONE]':
            return CodingSseFrame(raw, 'DONE', {'kind': 'DONE', 'comments': comments})
        value = strict_json_object(payload)
        return CodingSseFrame(raw, 'DATA', {'kind': 'DATA', 'payload': value, 'comments': comments})
    except (ValueError, UnicodeError, RecursionError):
        _invalid()


class CodingSseReader:
    def __init__(self):
        self._line = bytearray()
        self._frame = bytearray()
        self._size = 0

    @property
    def has_pending(self):
        return bool(self._line or self._frame)

    def feed(self, chunk):
        if type(chunk) is not bytes or self._size + len(chunk) > RESPONSE_BYTES:
            _invalid()
        self._size += len(chunk)
        position = 0
        while position < len(chunk):
            newline = chunk.find(b'\n', position)
            end = len(chunk) if newline < 0 else newline + 1
            if len(self._frame) + len(self._line) + end - position > FRAME_BYTES:
                _invalid()
            self._line.extend(chunk[position:end])
            position = end
            if newline < 0:
                break
            blank = self._line in (b'\n', b'\r\n')
            self._frame.extend(self._line)
            self._line.clear()
            if blank:
                raw = bytes(self._frame)
                self._frame.clear()
                yield _frame(raw)


def _usage(value):
    if value is None:
        return {}
    if type(value) is not dict:
        _invalid()
    result = {}
    for source, destination in (
        ('prompt_tokens', 'input_tokens'),
        ('completion_tokens', 'output_tokens'),
    ):
        if source in value:
            result[destination] = value[source]
    for group, keys in (
        ('prompt_tokens_details', {'cached_tokens'}),
        ('completion_tokens_details', {'reasoning_tokens'}),
    ):
        details = value.get(group)
        if details is None:
            continue
        if type(details) is not dict:
            _invalid()
        for name, count in details.items():
            if name in keys:
                result[name] = count
            elif count is not None and (type(count) is not int or count != 0):
                _invalid()
    if set(value) - {
        'prompt_tokens',
        'completion_tokens',
        'total_tokens',
        'prompt_tokens_details',
        'completion_tokens_details',
    }:
        _invalid()
    total = value.get('total_tokens')
    if total is not None:
        if type(total) is not int or not 0 <= total <= MAX_SAFE_INTEGER:
            _invalid()
        left, right = result.get('input_tokens'), result.get('output_tokens')
        if type(left) is int and type(right) is int and total != left + right:
            _invalid()
    return result


class CodingSseResponse:
    def __init__(self, response_ref, contract, *, model_name):
        self.usage = UsageState(response_ref)
        self._contract = contract
        self._model = model_name
        self._completion = None
        self._tool_ids = {}
        self._tool_names = set()
        self._final_candidate = None
        self.finish_reason = None
        self.done = False

    def _tools(self, calls):
        if type(calls) is not list or not calls:
            _invalid()
        chunk_indices = set()
        for item in calls:
            if type(item) is not dict or set(item) - {'index', 'id', 'type', 'function'}:
                _invalid()
            index = item.get('index')
            function = item.get('function')
            if (
                type(index) is not int
                or not 0 <= index <= MAX_SAFE_INTEGER
                or index in chunk_indices
                or ('type' in item and item['type'] != 'function')
                or type(function) is not dict
                or set(function) - {'name', 'arguments'}
                or ('arguments' in function and type(function['arguments']) is not str)
            ):
                _invalid()
            chunk_indices.add(index)
            identity = item.get('id')
            original = self._tool_ids.get(index)
            if identity is not None:
                if (
                    type(identity) is not str
                    or not 1 <= len(identity) <= 256
                    or not identity.isprintable()
                    or (original is not None and identity != original)
                    or (original is None and identity in self._tool_ids.values())
                ):
                    _invalid()
                self._tool_ids[index] = identity
            elif original is None:
                _invalid()
            if 'name' in function:
                name = function['name']
                if type(name) is not str or not _TOOL.fullmatch(name) or index in self._tool_names:
                    _invalid()
                self._tool_names.add(index)

    def _content(self, choice):
        if type(choice) is not dict or type(choice.get('index')) is not int or choice['index'] != 0:
            _invalid()
        delta = choice.get('delta')
        if (
            type(delta) is not dict
            or set(delta) - {'role', 'content', 'tool_calls', 'reasoning_content'}
            or ('role' in delta and delta['role'] != 'assistant')
            or any(
                delta[key] is not None and type(delta[key]) is not str
                for key in ('content', 'reasoning_content')
                if key in delta
            )
        ):
            _invalid()
        if 'tool_calls' in delta:
            self._tools(delta['tool_calls'])
        reason = choice.get('finish_reason')
        if reason is not None:
            if reason not in _FINISH or (
                reason == 'tool_calls'
                and (not self._tool_ids or self._tool_ids.keys() != self._tool_names)
            ):
                _invalid()
            self.finish_reason = reason
        return reason

    def _observe_usage(self, values, *, finished_here, trailer):
        previous = self._final_candidate
        if (
            self._contract.final_source == 'FINAL_FINISH_FRAME'
            and previous is not None
            and any(
                value is not None and previous.get(key) != value for key, value in values.items()
            )
        ):
            self.usage = replace(
                self.usage, status='DISPUTED', dispute_reason='FINISH_USAGE_CHANGED'
            )
            return
        self.usage = observe_usage(
            self.usage, values, response_ref=self.usage.response_ref, contract=self._contract
        )
        if any(values.get(key) is None for key in self._contract.required_dimensions):
            return
        if (finished_here and self._contract.final_source == 'FINAL_FINISH_FRAME') or (
            trailer and self._contract.final_source == 'USAGE_TRAILER'
        ):
            self._final_candidate = values.copy()

    def observe(self, frame):
        if self.done:
            _invalid()
        if frame.kind == 'KEEPALIVE':
            return
        if frame.kind == 'DONE':
            if self._completion is None or self.finish_reason is None:
                _invalid()
            self.done = True
            return
        payload = frame.audit['payload']
        completion, choices = payload.get('id'), payload.get('choices')
        if (
            'error' in payload
            or type(completion) is not str
            or not 1 <= len(completion) <= 1024
            or not completion.isprintable()
            or payload.get('model', self._model) != self._model
            or payload.get('object', 'chat.completion.chunk') != 'chat.completion.chunk'
            or type(choices) is not list
            or len(choices) > 1
            or (self._completion is not None and self._completion != completion)
        ):
            _invalid()
        self._completion = completion
        values = _usage(payload.get('usage'))
        finished_here = False
        trailer = not choices and self.finish_reason is not None
        if choices:
            if self.finish_reason is not None:
                _invalid()
            finished_here = self._content(choices[0]) is not None
        elif not values:
            _invalid()
        self._observe_usage(values, finished_here=finished_here, trailer=trailer)

    def finalize(self):
        if not self.done:
            _invalid()
        if self._final_candidate is not None:
            self.usage = confirm_final_usage(
                self.usage,
                self._final_candidate,
                response_ref=self.usage.response_ref,
                contract=self._contract,
                source=self._contract.final_source,
                complete=True,
                audit_complete=True,
            )
        return self.usage
