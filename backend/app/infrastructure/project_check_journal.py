"""Append the exact original project CHECK mutations before dispatch."""

from dataclasses import asdict
from hashlib import sha256

from backend.app.shared.validation import strict_json_object

from .execution_display_text import UNAVAILABLE_EXECUTION_TEXT, execution_display_text
from .guard_action_records import MUTATIONS, mutation_input_sha256
from .guard_control_git_reply import GuardReply, _check_task_mutation
from .guard_task_files import _publish_original, _read_original
from .guard_task_launch_protocol import check_task_prepare_ack
from .project_check_http_journal import ProjectCheckHttpJournal
from .project_check_result import (
    ProjectCheckDispatchResult,
    ProjectCheckDisplay,
    ProjectCheckOutput,
    ProjectCheckStream,
    project_command_result,
)
from .runtime_launch_journal import (
    LaunchJournal,
    LaunchOutcomeUnknown,
    LaunchScope,
    TestingLaunchScope,
    _bytes,
    _hex,
)
from .windows_local_paths import FileIdentity

_LIMIT = 16384
_COMPLETION_LIMIT = 32768


class ProjectCheckJournal:
    def __init__(self, journal, scope, owner_epoch, active):
        if (
            type(journal) is not LaunchJournal
            or not isinstance(scope, LaunchScope)
            or not callable(active)
        ):
            raise TypeError('Original project check journal scope required')
        self._journal, self._scope, self._epoch, self._active = journal, scope, owner_epoch, active

    def http(self):
        return ProjectCheckHttpJournal(self._journal, self._scope, self._epoch, self._active)

    def _path(self, action, phase):
        if action not in MUTATIONS or phase not in ('intent', 'ack'):
            raise ValueError('Original check action and phase required')
        return f'{self._scope.key}.project-check-{action.lower().replace("_", "-")}-{phase}.json'

    def _read(self, action, phase):
        raw = _read_original(self._journal._package, self._path(action, phase), _LIMIT)
        if raw is None:
            return None
        data = strict_json_object(raw)
        if (
            set(data) != {'scope', 'owner_epoch', 'action', 'phase', 'input_sha256', 'result'}
            or data['scope'] != asdict(self._scope)
            or data['owner_epoch'] != self._epoch
            or data['action'] != action
            or data['phase'] != phase
            or not _hex(data['input_sha256'])
            or (data['result'] is None) != (phase == 'intent')
            or _bytes(data) != raw
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_JOURNAL_DIFFERS')
        return data

    def _write(self, action, phase, digest, result):
        data = {
            'scope': asdict(self._scope),
            'owner_epoch': self._epoch,
            'action': action,
            'phase': phase,
            'input_sha256': digest,
            'result': result,
        }
        name = self._path(action, phase)
        _publish_original(self._journal._package, name, _bytes(data), _LIMIT)
        if self._read(action, phase) != data:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_JOURNAL_WRITE_UNVERIFIED')

    def intent_saved(self, action):
        with self._journal._scope(self._scope):
            return self._read(action, 'intent') is not None

    def require_no_dispatch(self):
        with self._journal._scope(self._scope):
            if any(
                self._read(action, phase) is not None
                for action in MUTATIONS
                for phase in ('intent', 'ack')
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPATCH_MAY_EXIST')

    def original_ack(self, action):
        with self._journal._scope(self._scope):
            row = self._read(action, 'ack')
            return None if row is None else row['result']

    def verify_observed_intent(self, action, observation):
        if observation.get('observed_action') != action:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_INTENT_DIFFERS')
        with self._journal._scope(self._scope):
            intent = self._read(action, 'intent')
            if intent is None or intent['input_sha256'] != observation.get('input_sha256'):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_INTENT_DIFFERS')

    def verify_existing_intent(self, request):
        self._require(request)
        with self._journal._scope(self._scope):
            row = self._read(request.action, 'intent')
            if row is None or row['input_sha256'] != mutation_input_sha256(request):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_RECOVERY_INTENT_DIFFERS')

    def record_export(self, identity):
        if type(identity) is not FileIdentity or identity.is_directory:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXPORT_IDENTITY_REQUIRED')
        name = self._scope.key + '.project-check-export.json'
        raw = _bytes(
            {
                'scope': asdict(self._scope),
                'owner_epoch': self._epoch,
                'file': asdict(identity),
            }
        )
        with self._journal._scope(self._scope):
            _publish_original(self._journal._package, name, raw, _LIMIT)
            if self.read_export() != identity:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXPORT_RECORD_DIFFERS')

    def read_export(self):
        name = self._scope.key + '.project-check-export.json'
        with self._journal._scope(self._scope):
            raw = _read_original(self._journal._package, name, _LIMIT)
            if raw is None:
                return None
            data = strict_json_object(raw)
            if (
                set(data) != {'scope', 'owner_epoch', 'file'}
                or data['scope'] != asdict(self._scope)
                or data['owner_epoch'] != self._epoch
                or _bytes(data) != raw
            ):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_EXPORT_RECORD_DIFFERS')
            return FileIdentity(**data['file'])

    def _require(self, request):
        epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
        if request.target_scope != self._scope or epoch != self._epoch:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_JOURNAL_SCOPE_DIFFERS')

    def before(self, request):
        self._require(request)
        action = request.action
        with self._journal._scope(self._scope):
            if action not in ('STOP', 'RELEASE') and self._active() is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_JOURNAL_FENCED')
            if self._read(action, 'intent') is not None:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ACTION_REQUIRES_OBSERVATION')
            if action == 'STOP' and self._read('PREPARE', 'intent') is None:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_PREPARE_REQUIRED')
            previous = {
                'CREATE_SUSPENDED': 'PREPARE',
                'RESUME': 'CREATE_SUSPENDED',
                'RELEASE': 'STOP',
            }
            if action in previous and self._read(previous[action], 'ack') is None:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_PREDECESSOR_UNVERIFIED')
            self._write(action, 'intent', mutation_input_sha256(request), None)

    def _ack(self, action, digest, result):
        with self._journal._scope(self._scope):
            intent = self._read(action, 'intent')
            if intent is None or intent['input_sha256'] != digest or type(result) is not dict:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ACK_DIFFERS')
            existing = self._read(action, 'ack')
            if existing is None:
                self._write(action, 'ack', digest, result)
            elif (existing['input_sha256'], existing['result']) != (digest, result):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ACK_DIFFERS')

    def acknowledge(self, request, result):
        self._require(request)
        self._ack(request.action, mutation_input_sha256(request), result)

    def acknowledge_observed(self, action, observation):
        if (
            observation.get('observed_action') != action
            or observation.get('action_phase') != 'ACKNOWLEDGED'
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_ACK_DIFFERS')
        self._ack(action, observation.get('input_sha256'), observation.get('acknowledgement'))

    def _display(self, rows, output, resource):
        if (
            type(self._scope) is not LaunchScope
            or resource['process_state'] != 'EXITED'
            or type(rows) is not list
            or not 1 <= len(rows) <= 2
            or any(type(item) is not dict or set(item) != {'stream', 'text'} for item in rows)
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_DIFFERS')
        preview = tuple(ProjectCheckDisplay(**item) for item in rows)
        if output.problem is not None:
            if preview != (ProjectCheckDisplay('UNAVAILABLE', UNAVAILABLE_EXECUTION_TEXT),):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_DIFFERS')
            return preview
        expected = tuple(
            (stream, summary)
            for stream, summary in (('STDOUT', output.stdout), ('STDERR', output.stderr))
            if summary.byte_count > 0
        )
        if tuple(record.stream for record in preview) != tuple(stream for stream, _ in expected):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_STREAM_DIFFERS')
        for record, (_, summary) in zip(preview, expected, strict=True):
            if record.text == UNAVAILABLE_EXECUTION_TEXT:
                continue
            raw = record.text.encode('utf-8')
            if (len(raw), sha256(raw).hexdigest()) != (summary.byte_count, summary.sha256):
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_DISPLAY_BYTES_DIFFER')
        return preview

    def _completed(self, check, maximum, data):
        base = {'scope', 'owner_epoch', 'release', 'output', 'interruption'}
        if (
            type(data) is not dict
            or set(data) not in (base, base | {'display'})
            or data['scope'] != asdict(self._scope)
            or data['owner_epoch'] != self._epoch
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_SCOPE_DIFFERS')
        release = data['release']
        released = self._read('RELEASE', 'ack')
        stopped = self._read('STOP', 'ack')
        if (
            released is None
            or stopped is None
            or released['input_sha256'] != release['input_sha256']
            or released['result'] != release['acknowledgement']
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_ACK_DIFFERS')
        reference = release['binding_ref']
        prepared = self._read('PREPARE', 'ack')
        created = self._read('CREATE_SUSPENDED', 'ack')
        if prepared is not None:
            check_task_prepare_ack(self._scope, reference, prepared['result'])
        if created is not None:
            _check_task_mutation(self._scope, reference, 'CREATE_SUSPENDED', created['result'])
        _check_task_mutation(self._scope, reference, 'STOP', stopped['result'])
        _check_task_mutation(self._scope, reference, 'RELEASE', released['result'])
        if (
            (created is not None and release['resource']['process_state'] == 'NOT_CREATED')
            or (
                release['resource']['process_state'] == 'EXITED'
                and (prepared is None or not self.intent_saved('CREATE_SUSPENDED'))
            )
            or stopped['result']['native']['process_identity']
            != release['resource']['process_identity']
            or (
                created is not None
                and (
                    created['result']['native']['process_identity']
                    != release['resource']['process_identity']
                )
            )
        ):
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_PROCESS_DIFFERS')
        output = data['output']
        if type(output) is not dict or set(output) != {'stdout', 'stderr', 'problem'}:
            raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_OUTPUT_DIFFERS')
        summary = ProjectCheckOutput(
            None if output['stdout'] is None else ProjectCheckStream(**output['stdout']),
            None if output['stderr'] is None else ProjectCheckStream(**output['stderr']),
            output['problem'],
        )
        result = project_command_result(
            GuardReply('OBSERVED', _bytes(release).decode('utf-8')),
            self._scope,
            check,
            summary,
            maximum=maximum,
            interruption=data['interruption'],
        )
        display = (
            self._display(data['display'], summary, release['resource'])
            if 'display' in data
            else ()
        )
        http = None
        if type(self._scope) is TestingLaunchScope and created is not None:
            http = self.http().original_outcome(created['result']['native']['receipt_sha256'])
        return ProjectCheckDispatchResult(
            result,
            None if prepared is None else prepared['result'],
            None if created is None else created['result'],
            stopped['result'],
            released['result'],
            http,
            display,
        )

    def complete(self, check, maximum, release, output, interruption, display=()):
        """After original cleanup, save enough evidence for a later SQLite writer."""
        data = {
            'scope': asdict(self._scope),
            'owner_epoch': self._epoch,
            'release': release,
            'output': asdict(output),
            'interruption': interruption,
        }
        if display:
            data['display'] = [
                asdict(
                    ProjectCheckDisplay(
                        item.stream, execution_display_text(item.text, max_bytes=2048)
                    )
                )
                for item in display
            ]
        raw = _bytes(data)
        name = self._scope.key + '.project-check-completion.json'
        with self._journal._scope(self._scope):
            completion = self._completed(check, maximum, data)
            existing = _read_original(self._journal._package, name, _COMPLETION_LIMIT)
            if existing is None:
                _publish_original(self._journal._package, name, raw, _COMPLETION_LIMIT)
                existing = _read_original(self._journal._package, name, _COMPLETION_LIMIT)
            if existing != raw:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_DIFFERS')
            return completion

    def read_completion(self, check, maximum):
        with self._journal._scope(self._scope):
            raw = _read_original(
                self._journal._package,
                self._scope.key + '.project-check-completion.json',
                _COMPLETION_LIMIT,
            )
            if raw is None:
                return None
            data = strict_json_object(raw)
            if _bytes(data) != raw:
                raise LaunchOutcomeUnknown('ORIGINAL_PROJECT_CHECK_COMPLETION_DIFFERS')
            return self._completed(check, maximum, data)
