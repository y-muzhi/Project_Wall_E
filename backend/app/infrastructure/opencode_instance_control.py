"""Fixed local OpenCode routes for one original process and directory."""

import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlencode

from backend.app.shared.validation import strict_json_loads

from .opencode_control import OpenCodeControlCredential
from .opencode_task_launch import TaskExecutionError
from .runtime_launch_journal import _bytes
from .windows_local_paths import FileIdentity, LocalPathGuard, local_absolute_path
from .windows_process import NativeProcessIdentity, ObservedProcess

_MAX_NATIVE_JSON = 4 * 1024 * 1024


def native_request_bytes(body):
    try:
        raw = _bytes(body)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise TaskExecutionError('ORIGINAL_OPENCODE_REQUEST_INVALID') from None
    if len(raw) > _MAX_NATIVE_JSON:
        raise TaskExecutionError('ORIGINAL_OPENCODE_REQUEST_TOO_LARGE')
    return raw


def native_json_equal(first, second):
    return native_request_bytes(first) == native_request_bytes(second)


def native_permission_rules(value, *, allow_empty=False):
    if type(value) is not list or (not value and not allow_empty):
        raise TaskExecutionError('ORIGINAL_OPENCODE_PERMISSION_RULES_REQUIRED')
    for rule in value:
        if (
            type(rule) is not dict
            or set(rule) != {'permission', 'pattern', 'action'}
            or any(type(rule[key]) is not str or not rule[key] for key in rule)
            or rule['action'] not in ('allow', 'ask', 'deny')
            or any('\x00' in rule[key] for key in rule)
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_PERMISSION_RULES_REQUIRED')
    native_request_bytes({'permission': value})
    # Own the bytes; callers cannot change the pending request through aliases.
    return strict_json_loads(native_request_bytes(value))


def native_session_input(payload):
    if type(payload) is not dict or set(payload) != {
        'title',
        'agent',
        'model',
        'metadata',
        'permission',
    }:
        raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_INPUT_REQUIRED')
    model = payload['model']
    if (
        type(model) is not dict
        or set(model) not in ({'id', 'providerID'}, {'id', 'providerID', 'variant'})
        or any(type(value) is not str or not value for value in model.values())
        or type(payload['title']) is not str
        or not payload['title'].strip()
        or type(payload['agent']) is not str
        or not payload['agent']
        or type(payload['metadata']) is not dict
        or type(payload['permission']) is not list
    ):
        raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_INPUT_REQUIRED')
    native_permission_rules(payload['permission'], allow_empty=True)
    return strict_json_loads(native_request_bytes(payload))


def native_message_input(payload):
    if type(payload) is not dict or set(payload) != {'messageID', 'model', 'agent', 'parts'}:
        raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_INPUT_REQUIRED')
    _identifier(payload['messageID'], 'msg')
    model, parts = payload['model'], payload['parts']
    if (
        type(model) is not dict
        or set(model) != {'providerID', 'modelID'}
        or any(type(value) is not str or not value for value in model.values())
        or type(payload['agent']) is not str
        or not payload['agent']
        or type(parts) is not list
        or not parts
        or any(
            type(part) is not dict
            or set(part) != {'id', 'type', 'text'}
            or part['type'] != 'text'
            or type(part['text']) is not str
            or not part['text']
            for part in parts
        )
    ):
        raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_INPUT_REQUIRED')
    ids = [_identifier(part['id'], 'prt') for part in parts]
    if len(ids) != len(set(ids)):
        raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_INPUT_REQUIRED')
    return strict_json_loads(native_request_bytes(payload))


def _identifier(value, prefix):
    if type(value) is not str or re.fullmatch(prefix + r'_[0-9A-Za-z]{1,96}', value) is None:
        raise TaskExecutionError('ORIGINAL_OPENCODE_IDENTIFIER_INVALID')
    return value


_SETTLED_PART_TYPES = frozenset(
    {
        'text',
        'reasoning',
        'file',
        'tool',
        'step-start',
        'step-finish',
        'snapshot',
        'patch',
        'agent',
        'retry',
        'compaction',
    }
)


def _settled_parts(parts, native, message, seen):
    for part in parts:
        if (
            type(part) is not dict
            or part.get('sessionID') != native
            or part.get('messageID') != message
            or type(part.get('type')) is not str
            or part['type'] not in _SETTLED_PART_TYPES
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_PART_UNVERIFIED')
        identity = _identifier(part.get('id'), 'prt')
        if identity in seen:
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_PART_UNVERIFIED')
        seen.add(identity)
        if part['type'] != 'tool':
            continue
        state = part.get('state')
        timing = state.get('time') if type(state) is dict else None
        if (
            type(part.get('callID')) is not str
            or not part['callID']
            or type(part.get('tool')) is not str
            or not part['tool']
            or type(state) is not dict
            or state.get('status') not in ('completed', 'error')
            or type(timing) is not dict
            or type(timing.get('start')) is not int
            or type(timing.get('end')) is not int
            or not 0 <= timing['start'] <= timing['end']
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_TOOL_NOT_SETTLED')


@dataclass(frozen=True)
class NativeTurnRecord:
    event_id: str
    kind: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class NativeTurnCompletion:
    session_id: str
    trigger_message_id: str
    assistant_message_id: str
    outcome: str
    records: tuple[NativeTurnRecord, ...] = field(default=(), repr=False, compare=False)

    def scope_proof(self):
        return {
            'session_id': self.session_id,
            'trigger_message_id': self.trigger_message_id,
            'assistant_message_id': self.assistant_message_id,
            'outcome': self.outcome,
        }


def _turn_records(assistants, parts_by_message, outcome):
    maximum = 256
    records = []
    for message in assistants:
        for part in parts_by_message[message['id']]:
            kind = part['type']
            if kind == 'text':
                if any(part.get(flag) not in (None, False) for flag in ('synthetic', 'ignored')):
                    continue
                text = part.get('text')
                if type(text) is not str:
                    text = ''
                record = NativeTurnRecord(part['id'], 'MESSAGE', text)
            elif kind == 'tool':
                tool = part['tool']
                if re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', tool) is None:
                    tool = '原生工具'
                status = '已结束' if part['state']['status'] == 'completed' else '执行失败'
                record = NativeTurnRecord(part['id'], 'TOOL', f'{tool}：{status}。')
            else:
                continue
            if len(records) == maximum:
                return (
                    *records,
                    NativeTurnRecord(
                        'limit:' + assistants[-1]['id'], 'CONTROL', '本轮其余执行记录超出读取上限。'
                    ),
                )
            records.append(record)
    if outcome == 'CANCELLED':
        records.append(
            NativeTurnRecord('error:' + assistants[-1]['id'], 'ERROR', '原生执行已取消。')
        )
    return tuple(records)


class OpenCodeInstanceControl:
    def __init__(self, credential, process, identity, workspace):
        if (
            type(credential) is not OpenCodeControlCredential
            or type(process) is not ObservedProcess
            or type(identity) is not NativeProcessIdentity
            or process.identity != identity
            or type(workspace) is not FileIdentity
            or not workspace.is_directory
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_INSTANCE_REQUIRED')
        self._credential, self._process, self._identity = credential, process, identity
        self._workspace = workspace

    def _request(
        self, method, route, checkpoint, *, timeout_ms, body=None, query=None, expected=200
    ):
        root = local_absolute_path(self._workspace.canonical_path)
        target = (
            route + '?' + urlencode({'directory': str(root), **({} if query is None else query)})
        )
        raw = None if body is None else native_request_bytes(body)
        with LocalPathGuard(root, directory=True) as guard:

            def checked():
                checkpoint()
                if guard.verify() != self._workspace:
                    raise TaskExecutionError('ORIGINAL_OPENCODE_DIRECTORY_DIFFERS')

            checked()
            status, response, _ = self._credential._request(
                self._process,
                self._identity,
                checked,
                method=method,
                target=target,
                timeout_ms=timeout_ms,
                body=raw,
                max_response_bytes=_MAX_NATIVE_JSON,
            )
            checked()
        if status != expected:
            raise TaskExecutionError('ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED')
        if expected == 204:
            if response:
                raise TaskExecutionError('ORIGINAL_OPENCODE_EMPTY_RESPONSE_REQUIRED')
            return None
        try:
            return strict_json_loads(response)
        except ValueError as error:
            raise TaskExecutionError('ORIGINAL_OPENCODE_RESPONSE_UNVERIFIED') from error

    def verify_ready(self, checkpoint, *, timeout_ms):
        with LocalPathGuard(self._workspace.canonical_path, directory=True) as guard:

            def checked():
                checkpoint()
                if guard.verify() != self._workspace:
                    raise TaskExecutionError('ORIGINAL_OPENCODE_DIRECTORY_DIFFERS')

            self._credential.verify_basic_challenge(
                self._process, self._identity, checked, timeout_ms=timeout_ms
            )
            return self._credential.probe_health(
                self._process, self._identity, checked, timeout_ms=timeout_ms
            )

    def configuration(self, checkpoint, *, timeout_ms):
        config = self._request('GET', '/config', checkpoint, timeout_ms=timeout_ms)
        providers = self._request('GET', '/config/providers', checkpoint, timeout_ms=timeout_ms)
        if (
            type(config) is not dict
            or type(providers) is not dict
            or type(providers.get('providers')) is not list
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_CONFIG_UNVERIFIED')
        return config, providers

    def _session(self, value, expected=None):
        if type(value) is not dict:
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_UNVERIFIED')
        native = _identifier(value.get('id'), 'ses')
        directory = value.get('directory')
        if (
            expected is not None
            and native != expected
            or type(directory) is not str
            or local_absolute_path(directory) != local_absolute_path(self._workspace.canonical_path)
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_UNVERIFIED')
        return value

    def session(self, native, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        result = self._request('GET', '/session/' + native, checkpoint, timeout_ms=timeout_ms)
        return self._session(result, native)

    def update_session_permission(self, native, rules, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        rules = native_permission_rules(rules)
        result = self._request(
            'PATCH',
            '/session/' + native,
            checkpoint,
            timeout_ms=timeout_ms,
            body={'permission': rules},
        )
        return self._session(result, native)

    def abort_session(self, native, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        result = self._request(
            'POST', '/session/' + native + '/abort', checkpoint, timeout_ms=timeout_ms
        )
        if result is not True:
            raise TaskExecutionError('ORIGINAL_OPENCODE_ABORT_UNVERIFIED')

    def find_session(self, metadata, checkpoint, *, timeout_ms, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_LIST_LIMIT_INVALID')
        results = self._request(
            'GET',
            '/session',
            checkpoint,
            timeout_ms=timeout_ms,
            query={'limit': limit},
        )
        if type(results) is not list or len(results) >= limit:
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_LIST_INCOMPLETE')
        matches = [
            item
            for item in results
            if type(item) is dict and native_json_equal(item.get('metadata'), metadata)
        ]
        if len(matches) != 1:
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_ASSOCIATION_UNKNOWN')
        original = self._session(matches[0])
        confirmed = self.session(original['id'], checkpoint, timeout_ms=timeout_ms)
        if not native_json_equal(confirmed.get('metadata'), metadata):
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_ASSOCIATION_UNKNOWN')
        return confirmed

    def execution_status(self, native, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        status = self._request('GET', '/session/status', checkpoint, timeout_ms=timeout_ms)
        if (
            type(status) is not dict
            or type(status.get(native)) is not dict
            or status[native].get('type') not in ('idle', 'busy', 'retry')
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_STATUS_UNKNOWN')
        return status[native]

    def _read_settled_turn(self, native, message, checkpoint, *, timeout_ms):
        native, message = _identifier(native, 'ses'), _identifier(message, 'msg')
        rows = self._request(
            'GET',
            '/session/' + native + '/message',
            checkpoint,
            timeout_ms=timeout_ms,
            query={'limit': 64},
        )
        if type(rows) is not list or not 2 <= len(rows) <= 64:
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
        messages = []
        parts_by_message = {}
        for row in rows:
            info = row.get('info') if type(row) is dict else None
            if (
                type(info) is not dict
                or info.get('sessionID') != native
                or info.get('role') not in ('user', 'assistant')
                or type(info.get('time')) is not dict
                or type(info['time'].get('created')) is not int
                or type(row.get('parts')) is not list
            ):
                raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
            identity = _identifier(info.get('id'), 'msg')
            messages.append(info)
            parts_by_message[identity] = row['parts']
        if len({info['id'] for info in messages}) != len(messages):
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
        messages.sort(key=lambda info: (info['time']['created'], info['id']))
        last_user = max(
            (index for index, info in enumerate(messages) if info['role'] == 'user'), default=-1
        )
        if last_user < 0 or messages[last_user]['id'] != message:
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
        assistants = messages[last_user + 1 :]
        if not assistants or any(
            info.get('parentID') != message
            or type(info['time'].get('completed')) is not int
            or info['time']['completed'] < info['time']['created']
            for info in assistants
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
        seen = set()
        for info in messages[last_user:]:
            _settled_parts(parts_by_message[info['id']], native, info['id'], seen)
        last = assistants[-1]
        if (not last.get('finish') or last['finish'] in ('tool-calls', 'unknown')) and type(
            last.get('error')
        ) is not dict:
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_UNVERIFIED')
        return assistants, parts_by_message

    def settled_turn(self, native, message, checkpoint, *, timeout_ms):
        assistants, _ = self._read_settled_turn(native, message, checkpoint, timeout_ms=timeout_ms)
        return assistants[-1]['id']

    def capture_turn_completion(self, native, message, checkpoint, *, timeout_ms):
        assistants, parts = self._read_settled_turn(
            native, message, checkpoint, timeout_ms=timeout_ms
        )
        last = assistants[-1]
        finish, error = last.get('finish'), last.get('error')
        if error is None and finish in ('stop', 'length', 'content-filter'):
            outcome = 'COMPLETED'
        elif (
            type(error) is dict
            and set(error) == {'name', 'data'}
            and error['name'] == 'MessageAbortedError'
            and type(error['data']) is dict
            and set(error['data']) == {'message'}
            and type(error['data']['message']) is str
        ):
            outcome = 'CANCELLED'
        else:
            raise TaskExecutionError('ORIGINAL_OPENCODE_TURN_OUTCOME_UNVERIFIED')
        if not self.original_turn_idle(native, checkpoint, timeout_ms=timeout_ms):
            raise TaskExecutionError('ORIGINAL_OPENCODE_INSTANCE_STILL_ACTIVE')
        for kind in ('question', 'permission'):
            if self._pending_items(kind, checkpoint, timeout_ms=timeout_ms):
                raise TaskExecutionError('ORIGINAL_OPENCODE_INSTANCE_STILL_WAITING')
        return NativeTurnCompletion(
            native, message, last['id'], outcome, _turn_records(assistants, parts, outcome)
        )

    def original_turn_idle(self, native, checkpoint, *, timeout_ms):
        # The pinned status route lists active sessions and removes idle entries.
        # This is only an activity check; the caller also requires the exact
        # original turn's completion and independent process/command evidence.
        _identifier(native, 'ses')
        status = self._request('GET', '/session/status', checkpoint, timeout_ms=timeout_ms)
        if type(status) is not dict or any(
            type(item) is not dict or item.get('type') not in ('idle', 'busy', 'retry')
            for item in status.values()
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_STATUS_UNKNOWN')
        # A second active native session in this one-task instance is also a writer risk.
        return all(row['type'] == 'idle' for row in status.values())

    def message(self, native, message, checkpoint, *, timeout_ms):
        native, message = _identifier(native, 'ses'), _identifier(message, 'msg')
        result = self._request(
            'GET', '/session/' + native + '/message/' + message, checkpoint, timeout_ms=timeout_ms
        )
        if (
            type(result) is not dict
            or type(result.get('info')) is not dict
            or type(result.get('parts')) is not list
            or result['info'].get('id') != message
            or result['info'].get('sessionID') != native
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_UNVERIFIED')
        return result

    def _pending_items(self, kind, checkpoint, *, timeout_ms):
        if kind not in ('question', 'permission'):
            raise TaskExecutionError('ORIGINAL_OPENCODE_PENDING_KIND_INVALID')
        result = self._request('GET', '/' + kind, checkpoint, timeout_ms=timeout_ms)
        if type(result) is not list or any(
            type(row) is not dict or type(row.get('sessionID')) is not str for row in result
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_PENDING_UNVERIFIED')
        prefix = 'que' if kind == 'question' else 'per'
        ids = [_identifier(row.get('id'), prefix) for row in result]
        if len(ids) != len(set(ids)):
            raise TaskExecutionError('ORIGINAL_OPENCODE_PENDING_UNVERIFIED')
        for row in result:
            _identifier(row['sessionID'], 'ses')
        return tuple(result)

    def pending(self, native, kind, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        rows = self._pending_items(kind, checkpoint, timeout_ms=timeout_ms)
        return tuple(row for row in rows if row['sessionID'] == native)

    @contextmanager
    def reply_events(self, checkpoint, *, timeout_ms, ready_timeout_ms):
        root = local_absolute_path(self._workspace.canonical_path)
        target = '/event?' + urlencode({'directory': str(root)})
        with LocalPathGuard(root, directory=True) as guard:

            def checked():
                checkpoint()
                if guard.verify() != self._workspace:
                    raise TaskExecutionError('ORIGINAL_OPENCODE_DIRECTORY_DIFFERS')

            with self._credential._event_stream(
                self._process,
                self._identity,
                checked,
                target=target,
                timeout_ms=timeout_ms,
                ready_timeout_ms=ready_timeout_ms,
            ) as events:
                yield events

    def verify_workspace_paths(self, checkpoint, *, timeout_ms):
        result = self._request('GET', '/path', checkpoint, timeout_ms=timeout_ms)
        root = local_absolute_path(self._workspace.canonical_path)
        if type(result) is not dict or any(
            type(result.get(key)) is not str or local_absolute_path(result[key]) != root
            for key in ('worktree', 'directory')
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_WORKTREE_UNVERIFIED')

    def reply_permission(self, request_id, reply, checkpoint, *, timeout_ms):
        request_id = _identifier(request_id, 'per')
        if reply not in ('once', 'reject'):
            raise TaskExecutionError('ORIGINAL_OPENCODE_PERMISSION_REPLY_INVALID')
        result = self._request(
            'POST',
            '/permission/' + request_id + '/reply',
            checkpoint,
            timeout_ms=timeout_ms,
            body={'reply': reply},
        )
        if result is not True:
            raise TaskExecutionError('ORIGINAL_OPENCODE_PERMISSION_RESPONSE_UNVERIFIED')

    def reply_question(self, request_id, answers, checkpoint, *, timeout_ms):
        request_id = _identifier(request_id, 'que')
        if (
            type(answers) is not list
            or not answers
            or any(
                type(item) is not list or len(item) != 1 or type(item[0]) is not str or not item[0]
                for item in answers
            )
        ):
            raise TaskExecutionError('ORIGINAL_OPENCODE_QUESTION_ANSWERS_INVALID')
        result = self._request(
            'POST',
            '/question/' + request_id + '/reply',
            checkpoint,
            timeout_ms=timeout_ms,
            body={'answers': answers},
        )
        if result is not True:
            raise TaskExecutionError('ORIGINAL_OPENCODE_QUESTION_RESPONSE_UNVERIFIED')

    def create_session(self, payload, checkpoint, *, timeout_ms):
        payload = native_session_input(payload)
        result = self._session(
            self._request('POST', '/session', checkpoint, timeout_ms=timeout_ms, body=payload)
        )
        if not native_json_equal(result.get('metadata'), payload['metadata']):
            raise TaskExecutionError('ORIGINAL_OPENCODE_SESSION_ASSOCIATION_UNKNOWN')
        return result

    def send_message(self, native, payload, checkpoint, *, timeout_ms):
        native = _identifier(native, 'ses')
        payload = native_message_input(payload)
        return self._request(
            'POST',
            '/session/' + native + '/prompt_async',
            checkpoint,
            timeout_ms=timeout_ms,
            body=payload,
            expected=204,
        )

    def verify_message(self, native, payload, checkpoint, *, timeout_ms):
        message = self.message(native, payload['messageID'], checkpoint, timeout_ms=timeout_ms)
        if message['info'].get('role') != 'user':
            raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_ASSOCIATION_UNKNOWN')
        actual = []
        for part in message['parts']:
            if (
                type(part) is not dict
                or part.get('sessionID') != native
                or part.get('messageID') != payload['messageID']
            ):
                raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_ASSOCIATION_UNKNOWN')
            actual.append({key: part.get(key) for key in ('id', 'type', 'text')})
        if actual != payload['parts']:
            raise TaskExecutionError('ORIGINAL_OPENCODE_MESSAGE_ASSOCIATION_UNKNOWN')
        return message
