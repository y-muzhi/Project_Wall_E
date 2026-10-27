"""C09 trusted input and D-005 complete recovery result."""
from dataclasses import dataclass
from backend.app.documents.snapshot import _time
from backend.app.documents.markdown import DocumentInvalid
from backend.app.shared.validation import object_fields, strict_integer, strict_enum, reject
from backend.app.shared.validation import MISSING, strict_json_object, selected_text, prefix_text, suffix_text
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.resources import FUNCTIONS, ResourceCatalog
from backend.app.shared.http_errors import ERRORS
from backend.app.infrastructure.idempotency import request_key
from backend.app.shared.pagination import page_number, page_metadata
from backend.app.shared.validation import raw_text
from backend.app.shared.validation import instruction
from backend.app.shared.validation import strict_boolean, ordinary_text
from backend.app.messages.contracts import message_read_model

GUIDE_STATUSES = ('RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')
GUIDE_STEPS = ('PREPARING', 'CALLING_MODEL', 'VALIDATING', 'PERSISTING', 'FINISHED')
STATUS_FIELDS = ('id', 'requirement_id', 'action_type', 'function_type', 'source_type', 'source_id', 'scope', 'status', 'current_step',
    'final_result', 'suggestion_batch_id', 'latest_assistant_message_id', 'error_code', 'error_message', 'cancel_reason',
    'retry_of_guide_run_id', 'created_at', 'started_at', 'waiting_user_at', 'ended_at', 'updated_at',
    'operation', 'parent_guide_run_id', 'target', 'discussion_version_snapshot', 'material_summary',
    'application_result', 'progress_result', 'progress_error', 'document_effect')
TASK_ERROR_CODES = frozenset(ERRORS) | {'MODEL_ERROR', 'OUTPUT_INVALID', 'CONTEXT_LIMIT_EXCEEDED', 'INTERRUPTED', 'EXECUTION_TIMEOUT'}


OPERATIONS = ('DISCUSS', 'GENERATE', 'REVISE', 'PROPOSE_CHANGES', 'COMPARE', 'REVIEW')
ACTION_TYPES = {'DISCUSS': 'ASK', 'GENERATE': 'GENERATE', 'REVISE': 'MODIFY', 'PROPOSE_CHANGES': 'MODIFY', 'COMPARE': 'REVIEW', 'REVIEW': 'REVIEW'}


@dataclass(frozen=True)
class CreateGuideRunInput:
    requirement_id: int
    expected_discussion_version: int
    operation: str
    instruction: str
    target: dict | None
    scope: dict | None
    source_refs: list
    proposal_ref: dict | None
    acknowledge_source_changes: bool
    idempotency_key: str

    @property
    def action_type(self):
        return ACTION_TYPES[self.operation]

    def business_input(self):
        return {key: getattr(self, key) for key in ('requirement_id', 'expected_discussion_version', 'operation', 'instruction',
            'target', 'scope', 'source_refs', 'proposal_ref', 'acknowledge_source_changes')}


def create_guide_run_input(payload):
    from backend.app.requirements.discussion import discussion_resources
    from backend.app.shared.validation import normalize_text
    fields = ('requirement_id', 'expected_discussion_version', 'operation', 'instruction', 'target', 'scope', 'source_refs', 'proposal_ref', 'acknowledge_source_changes', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    operation = strict_enum(data['operation'], 'operation', OPERATIONS)
    resources = discussion_resources()
    def named(entry, value):
        try:
            return resources.validate(entry, value)
        except ValueError:
            reject(entry, 'INVALID_FORMAT', 'Invalid collaboration input structure')
    target = None if data['target'] is None else named('Target', data['target'])
    scope = None if data['scope'] is None else named('legacy_scope', data['scope'])
    if type(data['source_refs']) is not list or len(data['source_refs']) > 1000:
        reject('source_refs', 'INVALID_FORMAT', 'Sources must be a bounded array')
    refs = [named('SourceRef', source) for source in data['source_refs']]
    if operation == 'GENERATE':
        if target is None or target['kind'] != 'NEW' or scope is not None:
            reject('target', 'INVALID_FORMAT', 'GENERATE requires NEW and no scope')
        target['name'] = ordinary_text(target['name'], 'name', 1, 80, multiline=False)
    elif operation in ('REVISE', 'PROPOSE_CHANGES'):
        if target is None or target['kind'] != 'EXISTING' or scope is None:
            reject('target', 'INVALID_FORMAT', 'This operation requires EXISTING and an explicit scope')
    else:
        if target is not None and target['kind'] != 'EXISTING':
            reject('target', 'INVALID_FORMAT', 'Read operations cannot allocate a new document')
        if target is None and scope is not None:
            reject('scope', 'INVALID_FORMAT', 'A scope requires its actual target')
        if operation in ('COMPARE', 'REVIEW') and (target is not None and scope is None or target is None and not refs):
            reject('source_refs', 'REQUIRED', 'Analysis requires explicit materials and target scope')
    proposal = data['proposal_ref']
    if proposal is not None:
        proposal = object_fields(proposal, 'proposal_ref', ('message_id', 'card_key'), ('message_id', 'card_key'))
        strict_integer(proposal['message_id'], 'message_id');raw_text(proposal['card_key'], 'card_key', 1, 100)
    text = raw_text(data['instruction'], 'instruction', 1, 10000)
    if not normalize_text(text):
        reject('instruction', 'TOO_SHORT', 'An instruction is required')
    result = CreateGuideRunInput(strict_integer(data['requirement_id'], 'requirement_id'),
        strict_integer(data['expected_discussion_version'], 'expected_discussion_version'), operation, text, target, scope, refs, proposal,
        strict_boolean(data['acknowledge_source_changes'], 'acknowledge_source_changes'), request_key(data['idempotency_key'], 'idempotency_key'))
    try:
        canonical_input(result.business_input())
    except (ValueError, UnicodeError, RecursionError):
        reject('body', 'INVALID_FORMAT', 'Input must be finite valid Unicode JSON')
    return result


@dataclass(frozen=True)
class ContinueGuideRunInput:
    guide_run_id: int
    instruction: str
    expected_discussion_version: int
    idempotency_key: str

    def business_input(self):
        return {'guide_run_id': self.guide_run_id, 'instruction': self.instruction, 'expected_discussion_version': self.expected_discussion_version}


def continue_guide_run_input(payload):
    fields = ('guide_run_id', 'instruction', 'expected_discussion_version', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    text = raw_text(data['instruction'], 'instruction', 1, 10000)
    from backend.app.shared.validation import normalize_text
    if not normalize_text(text):
        reject('instruction', 'TOO_SHORT', 'An instruction is required')
    try: canonical_input({'instruction': text})
    except (ValueError, UnicodeError): reject('instruction', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return ContinueGuideRunInput(strict_integer(data['guide_run_id'], 'guide_run_id'), text,
        strict_integer(data['expected_discussion_version'], 'expected_discussion_version'), request_key(data['idempotency_key'], 'idempotency_key'))


def create_guide_run_result(run, message):
    accepted = guide_run_accepted({key: run[key] for key in ('id', 'requirement_id', 'status', 'current_step')})
    value = message_read_model({key: message[key] for key in ('id', 'requirement_id', 'guide_run_id', 'sequence_no', 'role', 'content', 'message_type', 'reply_to_message_id', 'created_at')} | {'structured_content': None, 'card_state': None})
    if value['guide_run_id'] != accepted['id'] or value['requirement_id'] != accepted['requirement_id'] or value['message_type'] != 'TEXT' or value['role'] != 'USER':
        raise ValueError('Accepted user instruction must belong to the accepted run')
    return {'code': 'GUIDE_ACCEPTED', 'data': {'guide_run': accepted, 'user_message': value}, 'details': None}


def continue_guide_run_result(run):
    return {'code': 'GUIDE_CONTINUED', 'data': guide_run_accepted({key: run[key] for key in ('id', 'requirement_id', 'status', 'current_step')}), 'details': None}


@dataclass(frozen=True)
class SubmitCardResponsesInput:
    message_id: int
    answers_json: str
    expected_discussion_version: int
    idempotency_key: str

    @property
    def answers(self):
        import json
        return json.loads(self.answers_json)

    def business_input(self):
        return {'message_id': self.message_id, 'expected_discussion_version': self.expected_discussion_version, **self.answers}


def submit_card_responses_input(payload):
    fields = ('message_id', 'schema_version', 'responses', 'expected_discussion_version', 'execution_selection', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    version = strict_integer(data['schema_version'], 'schema_version', 1, 1)
    answers = data['responses']
    if type(answers) is not list: reject('responses', 'INVALID_TYPE', '必须为完整回答数组')
    if not 1 <= len(answers) <= 5: reject('responses', 'OUT_OF_RANGE', '整组回答必须为1～5项')
    normalized = []
    for index, answer in enumerate(answers):
        field = f'responses[{index}]'
        item = object_fields(answer, field, ('card_key', 'selected_option_keys', 'custom_answer', 'skipped'), ('card_key', 'selected_option_keys', 'custom_answer', 'skipped'))
        key = raw_text(item['card_key'], field+'.card_key', 1, 100)
        selected = item['selected_option_keys']
        if type(selected) is not list: reject(field+'.selected_option_keys', 'INVALID_TYPE', '必须为选项键数组')
        if len(selected) > 8: reject(field+'.selected_option_keys', 'TOO_LONG', '最多8个选项键')
        selected = [raw_text(value, field+'.selected_option_keys', 1, 100) for value in selected]
        if len(set(selected)) != len(selected): reject(field+'.selected_option_keys', 'INVALID_FORMAT', '选项键不能重复')
        custom = item['custom_answer']
        custom = None if custom is None else ordinary_text(custom, field+'.custom_answer', 1, 2000)
        normalized.append({'card_key': key, 'selected_option_keys': selected, 'custom_answer': custom, 'skipped': strict_boolean(item['skipped'], field+'.skipped')})
    if len({item['card_key'] for item in normalized}) != len(normalized): reject('responses', 'INVALID_FORMAT', '卡片键不能重复')
    try:
        from backend.app.requirements.discussion import discussion_resources
        stored = discussion_resources().validate('StoredResponses', {'schema_version': version, 'responses': normalized, 'execution_selection': data['execution_selection']})
        encoded = canonical_input(stored)
    except (ValueError, UnicodeError): reject('responses', 'INVALID_FORMAT', '回答必须使用有效Unicode码点')
    return SubmitCardResponsesInput(strict_integer(data['message_id'], 'message_id'), encoded, strict_integer(data['expected_discussion_version'], 'expected_discussion_version'), request_key(data['idempotency_key'], 'idempotency_key'))


def submit_card_responses_result(run, message):
    accepted = guide_run_accepted({key: run[key] for key in ('id', 'requirement_id', 'status', 'current_step')})
    value = message_read_model(message)
    if value['role'] != 'USER' or value['message_type'] != 'CARD_RESPONSE' or value['guide_run_id'] != accepted['id'] or value['requirement_id'] != accepted['requirement_id'] or value['structured_content'] is None:
        raise ValueError('Formal response must belong to its accepted run')
    return {'code': 'CARDS_ACCEPTED', 'data': {'response_message': value, 'guide_run': accepted, 'card_state': 'ANSWERED'}, 'details': None}


@dataclass(frozen=True)
class ModifyFromCommentInput:
    comment_id: int
    expected_content_version: int
    expected_discussion_version: int
    idempotency_key: str
    scope_mode: str | None = None

    def business_input(self):
        value = {key: getattr(self, key) for key in ('comment_id', 'expected_content_version', 'expected_discussion_version')}
        # An omitted mode must replay pre-deployment requests byte-for-byte.
        if self.scope_mode is not None:
            value['scope_mode'] = self.scope_mode
        return value


def modify_from_comment_input(payload):
    fields = ('comment_id', 'expected_content_version', 'expected_discussion_version', 'idempotency_key')
    value = object_fields(payload, 'body', (*fields, 'scope_mode'), fields)
    return ModifyFromCommentInput(strict_integer(value['comment_id'], 'comment_id'), strict_integer(value['expected_content_version'], 'expected_content_version'),
        strict_integer(value['expected_discussion_version'], 'expected_discussion_version'), request_key(value['idempotency_key'], 'idempotency_key'),
        strict_enum(value['scope_mode'], 'scope_mode', ('COMMENT', 'BLOCK', 'SECTION', 'DOCUMENT')) if 'scope_mode' in value else None)


def modify_from_comment_result(connection, run, catalog):
    from backend.app.infrastructure.guide_repository import GuideRepository
    message, batches = GuideRepository(connection).status_references(run)
    return {'code': 'GUIDE_ACCEPTED', 'data': get_guide_run_result(connection, run, message, batches, catalog=catalog), 'details': None}


@dataclass(frozen=True)
class RetryGuideRunInput:
    guide_run_id: int
    idempotency_key: str

    def business_input(self):
        return {'guide_run_id': self.guide_run_id}


def retry_guide_run_input(payload):
    fields = ('guide_run_id', 'idempotency_key')
    value = object_fields(payload, 'body', fields, fields)
    return RetryGuideRunInput(strict_integer(value['guide_run_id'], 'guide_run_id'), request_key(value['idempotency_key'], 'idempotency_key'))


def retry_guide_run_result(connection, run, catalog):
    from backend.app.infrastructure.guide_repository import GuideRepository
    message, batches = GuideRepository(connection).status_references(run)
    return {'code': 'GUIDE_RETRY_ACCEPTED', 'data': get_guide_run_result(connection, run, message, batches, catalog=catalog), 'details': None}


def get_guide_run_input(value: object = MISSING) -> int:
    return strict_integer(value, 'guide_run_id')


def _nullable_identity(value, field):
    return None if value is None else strict_integer(value, field)


def _scope(kind: str, reference: object) -> dict:
    strict_enum(kind, 'scope_type', ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'))
    if kind == 'DOCUMENT':
        if reference is not None:
            raise ValueError('Whole document scope has no reference')
    else:
        fields = ('block_id', 'selected_text', 'prefix_text', 'suffix_text') if kind == 'SELECTION' else ('block_id',)
        object_fields(reference, 'scope_ref', fields, fields)
        strict_integer(reference['block_id'], 'block_id')
        if kind == 'SELECTION':
            selected_text(reference['selected_text']); prefix_text(reference['prefix_text']); suffix_text(reference['suffix_text'])
    value = {'scope_type': kind, 'scope_ref': reference}
    canonical_input(value)
    return value


def _guide_model(data: object, *, summary: bool) -> dict:
    from backend.app.requirements.discussion import discussion_resources
    fields = tuple(field for field in STATUS_FIELDS if not summary or field != 'final_result')
    value = object_fields(data, 'read_model', fields if summary else (*fields, 'returned_responses'), fields)
    resources = discussion_resources()
    for field in ('id', 'requirement_id', 'discussion_version_snapshot'):
        strict_integer(value[field], field)
    strict_enum(value['operation'], 'operation', OPERATIONS)
    if value['action_type'] != ACTION_TYPES[value['operation']] or value['function_type'] != 'collaboration_v1':
        raise ValueError('Run function/action must match its operation')
    strict_enum(value['source_type'], 'source_type', ('USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT'))
    for field in ('source_id', 'suggestion_batch_id', 'latest_assistant_message_id', 'retry_of_guide_run_id', 'parent_guide_run_id'):
        _nullable_identity(value[field], field)
    if value['id'] in (value['retry_of_guide_run_id'], value['parent_guide_run_id']):
        raise ValueError('Run cannot reference itself')
    if (value['source_type'] == 'USER_INSTRUCTION') != (value['source_id'] is None):
        raise ValueError('Source kind and identity disagree')
    if value['target'] is not None:
        resources.validate('Target', value['target'])
    if value['scope'] is not None:
        resources.validate('legacy_scope', value['scope'])
    strict_enum(value['status'], 'status', GUIDE_STATUSES);strict_enum(value['current_step'], 'current_step', GUIDE_STEPS)
    terminal = value['status'] != 'RUNNING'
    if terminal != (value['ended_at'] is not None) or terminal != (value['current_step'] == 'FINISHED') or value['waiting_user_at'] is not None:
        raise ValueError('Run terminal step/time is inconsistent')
    created, updated = _time(value['created_at']), _time(value['updated_at'])
    if created > updated:
        raise ValueError('Run time moved backwards')
    for field in ('started_at', 'ended_at'):
        if value[field] is not None and not created <= _time(value[field]) <= updated:
            raise ValueError('Run event is outside its activity interval')
    if value['status'] == 'FAILED':
        strict_enum(value['error_code'], 'error_code', TASK_ERROR_CODES);raw_text(value['error_message'], 'error_message', 1, 10000)
    elif value['error_code'] is not None or value['error_message'] is not None:
        raise ValueError('Only failed runs expose errors')
    if (value['status'] == 'CANCELLED') != (value['cancel_reason'] is not None):
        raise ValueError('Cancellation reason differs from its state')
    if value['material_summary'] is not None:
        keys = ('document_count', 'block_count', 'history_count', 'pending_count', 'omitted_count')
        counts = object_fields(value['material_summary'], 'material_summary', keys, keys)
        for key in keys:
            strict_integer(counts[key], key, minimum=0)
    for field, options in [('application_result', ('NOT_REQUESTED', 'APPLIED', 'NO_CHANGE', 'NOT_APPLIED')),
            ('progress_result', ('NOT_REQUESTED', 'APPLIED', 'NO_CHANGE', 'REJECTED'))]:
        if value[field] is None:
            if terminal:
                raise ValueError('Terminal run requires explicit application outcomes')
        else:
            strict_enum(value[field], field, options)
    if (value['progress_result'] == 'REJECTED') != (value['progress_error'] is not None):
        raise ValueError('Rejected progress requires its safe reason')
    if value['progress_error'] is not None:
        raw_text(value['progress_error'], 'progress_error', 1, 1000)
    if value['document_effect'] is not None:
        from backend.app.documents.contracts import document_effect
        value['document_effect'] = document_effect(value['document_effect'])
    if value['application_result'] == 'APPLIED' and value['document_effect'] is None and value['suggestion_batch_id'] is None:
        raise ValueError('Application outcome requires an actual content or batch effect')
    if not summary:
        responses = value.setdefault('returned_responses', [])
        if type(responses) is not list:
            raise ValueError('Returned responses must be an array')
        for response in responses:
            keys = ('llm_use_id', 'call_no', 'attempt_no', 'content')
            object_fields(response, 'returned_response', keys, keys)
            for key in keys[:-1]:
                strict_integer(response[key], key)
            raw_text(response['content'], 'content', 0)
        if value['status'] == 'COMPLETED':
            keys = ('summary', 'assistant_message_id', 'current_document_version', 'suggestion_batch_id', 'analysis')
            final = object_fields(value['final_result'], 'final_result', keys, keys)
            raw_text(final['summary'], 'summary', 1, 10000)
            for field in keys[1:4]:
                _nullable_identity(final[field], field)
            if final['analysis'] is not None:
                resources.validate('Analysis', final['analysis'])
        elif value['final_result'] is not None:
            raise ValueError('Only a completed run exposes a final result')
    return json_detached(value)


def guide_run_read_model(data):
    return _guide_model(data, summary=False)


def guide_run_summary(data):
    return _guide_model(data, summary=True)


def json_detached(value):
    import json
    return json.loads(canonical_input(value))


def get_guide_run_result(connection, row, message, batches, *, catalog=None, summary=False):
    import json
    if row is None:
        raise ValueError('An actual run is required')
    full = connection.execute('SELECT * FROM guide_runs WHERE id=?', (row['id'],)).fetchone()
    basis = strict_json_object(full['execution_basis_json'])
    if basis.get('schema_version') != 1 or basis['requirement']['id'] != full['requirement_id'] or basis['discussion_version'] != full['discussion_version_snapshot']:
        raise ValueError('Run execution basis identity is inconsistent')
    request = basis['request']
    synthetic = {'scope', 'final_result', 'suggestion_batch_id', 'latest_assistant_message_id', 'target', 'material_summary',
        'application_result', 'progress_result', 'progress_error', 'document_effect'}
    value = {field: full[field] for field in STATUS_FIELDS if field not in synthetic}
    value.update(scope=request['scope'], target=request['target'], suggestion_batch_id=None if not batches else batches[0]['id'],
        latest_assistant_message_id=None if message is None else message['id'], material_summary=None, application_result=None,
        progress_result=None, progress_error=None, document_effect=None)
    if full['status'] != 'RUNNING':
        value['application_result'] = 'NOT_APPLIED' if full['operation'] in ('GENERATE', 'REVISE', 'PROPOSE_CHANGES') else 'NOT_REQUESTED'
        value['progress_result'] = 'NOT_REQUESTED'
    for call in connection.execute('SELECT request_snapshot_json FROM llm_uses WHERE guide_run_id=? ORDER BY id DESC', (full['id'],)):
        context = json.loads(call['request_snapshot_json']).get('context_basis')
        if context is None:
            continue
        (catalog or ResourceCatalog()).collaboration.validate('ContextBasis', context)
        selected = context['selected'];ids = {identity for item in selected for identity in item['message_ids']}
        value['material_summary'] = {'document_count': len({item['document_id'] for item in selected if item['document_id'] is not None}),
            'block_count': len({(item['document_id'], identity) for item in selected for identity in item['block_ids']}),
            'history_count': len({identity for item in selected if 'HISTORY' in item['roles'] for identity in item['message_ids']}),
            'pending_count': len(ids.intersection(context['canonical']['discussion']['pending_user_message_ids'])), 'omitted_count': len(context['omitted'])}
        break
    effects = None if full['final_result_json'] is None else strict_json_object(full['final_result_json'])
    if full['status'] == 'COMPLETED':
        if effects is None:
            raise ValueError('Completed run has no persisted result')
        for field in ('application_result', 'progress_result', 'progress_error', 'document_effect'):
            value[field] = effects[field]
        effect = value['document_effect']
        if effect is not None and effect['result'] != 'NO_CHANGE':
            event = connection.execute("SELECT 1 FROM document_change_audits WHERE guide_run_id=? AND document_id=? AND revision_id=? AND event_type='CONTENT_COMMITTED' AND after_content_version=?",
                (full['id'], effect['document_id'], effect['revision_id'], effect['after_content_version'])).fetchone()
            if event is None:
                raise ValueError('Content outcome has no actual committed event')
        if message is not None and effects['assistant_message_id'] != message['id']:
            raise ValueError('Completed message identity differs from its result')
    if not summary:
        value['final_result'] = None if effects is None else {'summary': effects['summary'], 'assistant_message_id': effects['assistant_message_id'],
            'current_document_version': None if effects['document_effect'] is None else effects['document_effect']['after_content_version'],
            'suggestion_batch_id': value['suggestion_batch_id'], 'analysis': effects['analysis']}
        from .response_display import returned_responses
        value['returned_responses'] = returned_responses(connection, full['id']) if full['status'] in ('FAILED', 'CANCELLED') or effects is not None and (effects.get('validation_error') is not None or effects.get('progress_error') is not None) else []
    return guide_run_summary(value) if summary else guide_run_read_model(value)


@dataclass(frozen=True)
class RecoverRunsInput:
    recovery_reason: str
    live_run_ids: frozenset[int]
    operation_time: str


def recover_runs_input(payload: object) -> RecoverRunsInput:
    fields = ('recovery_reason', 'live_run_ids', 'operation_time')
    data = object_fields(payload, 'body', fields, fields)
    reason = strict_enum(data['recovery_reason'], 'recovery_reason', ('STARTUP', 'NO_PROGRESS'))
    if type(data['live_run_ids']) not in (set, frozenset):
        reject('live_run_ids', 'INVALID_TYPE', '必须由内部任务集合提供Set[ID]')
    live = frozenset(strict_integer(identity, 'live_run_ids') for identity in data['live_run_ids'])
    try:
        at = _time(data['operation_time'])
    except DocumentInvalid:
        reject('operation_time', 'INVALID_FORMAT', '必须为有效UTC毫秒时间')
    return RecoverRunsInput(reason, live, at)


def recover_runs_result(request: RecoverRunsInput, recovered: list[int], repaired: list[int], unchanged: list[int]) -> dict:
    if set(repaired) & set(unchanged):
        raise ValueError('A requirement cannot be both repaired and unchanged')
    for identities in (recovered, repaired, unchanged):
        if identities != sorted(set(identities)):
            raise ValueError('Recovery result identities must be unique and ordered')
        for identity in identities:
            strict_integer(identity, 'identity')
    return {'code': 'RECOVERED' if recovered or repaired else 'RECOVERY_NO_CHANGE',
        'data': {'recovery_reason': request.recovery_reason, 'operation_time': request.operation_time,
                 'recovered_run_ids': recovered, 'repaired_requirement_ids': repaired, 'unchanged_requirement_ids': unchanged}, 'details': None}


@dataclass(frozen=True)
class CancelGuideRunInput:
    guide_run_id: int
    idempotency_key: str

    def business_input(self) -> dict:
        return {'guide_run_id': self.guide_run_id}


def cancel_guide_run_input(payload: object) -> CancelGuideRunInput:
    fields = ('guide_run_id', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    return CancelGuideRunInput(strict_integer(data['guide_run_id'], 'guide_run_id'), request_key(data['idempotency_key'], 'idempotency_key'))


def guide_run_accepted(data: object) -> dict:
    value = object_fields(data, 'accepted', ('id', 'requirement_id', 'status', 'current_step'), ('id', 'requirement_id', 'status', 'current_step'))
    strict_integer(value['id'], 'id'); strict_integer(value['requirement_id'], 'requirement_id')
    strict_enum(value['status'], 'status', GUIDE_STATUSES); strict_enum(value['current_step'], 'current_step', GUIDE_STEPS)
    return json_detached(value)


def cancel_guide_run_result(row) -> dict:
    if row['status'] != 'CANCELLED' or row['current_step'] != 'FINISHED' or row['cancel_reason'] != 'USER_REQUESTED' or row['final_result_json'] is not None:
        raise ValueError('Cancellation result must reflect the persisted cancellation')
    if not _time(row['created_at']) <= _time(row['ended_at']) <= _time(row['updated_at']):
        raise ValueError('Cancellation times are inconsistent')
    return {'code': 'GUIDE_CANCELLED', 'data': guide_run_accepted({key: row[key] for key in ('id', 'requirement_id', 'status', 'current_step')}), 'details': None}


@dataclass(frozen=True)
class ListGuideRunsInput:
    requirement_id: int
    status: tuple[str, ...]
    action_type: tuple[str, ...]
    page: int


def list_guide_runs_input(payload: object) -> ListGuideRunsInput:
    data = object_fields(payload, 'query', ('requirement_id', 'status', 'action_type', 'page'), ('requirement_id',))
    def choices(field, allowed):
        values = data.get(field, [])
        if type(values) is not list:
            reject(field, 'INVALID_TYPE', '必须是枚举数组且不能为null')
        result = tuple(dict.fromkeys(strict_enum(value, f'{field}[{index}]', allowed) for index, value in enumerate(values)))
        return () if set(result) == set(allowed) else result
    return ListGuideRunsInput(strict_integer(data['requirement_id'], 'requirement_id'), choices('status', GUIDE_STATUSES),
        choices('action_type', ('ASK', 'GENERATE', 'REVIEW', 'MODIFY')), page_number(data.get('page', 1)))


def list_guide_runs_result(items: list[dict], request: ListGuideRunsInput, total: int) -> dict:
    if type(items) is not list or len(items) > 20:
        raise ValueError('Guide history must contain at most one fixed page')
    values = [guide_run_summary(item) for item in items]
    if any(item['requirement_id'] != request.requirement_id for item in values):
        raise ValueError('History contains another requirement')
    return {'items': values, **page_metadata(request.page, total)}


@dataclass(frozen=True)
class FailGuideRunInput:
    guide_run_id: int
    error_code: str
    safe_message: str


def fail_guide_run_input(payload: object) -> FailGuideRunInput:
    fields = ('guide_run_id', 'error_code', 'safe_message')
    data = object_fields(payload, 'body', fields, fields)
    message = raw_text(data['safe_message'], 'safe_message', 1)
    try:
        message.encode('utf-8')
    except UnicodeEncodeError:
        reject('safe_message', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return FailGuideRunInput(strict_integer(data['guide_run_id'], 'guide_run_id'), strict_enum(data['error_code'], 'error_code', TASK_ERROR_CODES), message)


def fail_guide_run_result(row, released: bool, *, unchanged: bool) -> dict:
    strict_integer(row['id'], 'guide_run_id'); strict_enum(row['status'], 'status', GUIDE_STATUSES)
    if type(released) is not bool or (unchanged and released) or (not unchanged and row['status'] != 'FAILED'):
        raise ValueError('Failure result contradicts its actual transition')
    ended = None if row['ended_at'] is None else _time(row['ended_at'])
    if (row['status'] in ('COMPLETED', 'FAILED', 'CANCELLED')) != (ended is not None):
        raise ValueError('Failure result has inconsistent terminal time')
    return {'code': 'RUN_FINAL_UNCHANGED' if unchanged else 'RUN_FAILED', 'data': {'guide_run_id': row['id'], 'status': row['status'], 'ended_at': ended, 'occupancy_released': released}, 'details': None}


def get_model_context_input(guide_run_id: object = MISSING) -> int:
    return strict_integer(guide_run_id, 'guide_run_id')


def execute_guide_run_input(payload):
    value = object_fields(payload, 'body', ('guide_run_id',), ('guide_run_id',))
    return strict_integer(value['guide_run_id'], 'guide_run_id')


def execute_guide_run_result(code, row, last_call_no):
    if code not in ('AI_FINISHED', 'AI_WAITING_USER', 'AI_STOPPED'):
        raise ValueError('Unknown ORCH result')
    identity = strict_integer(row['id'], 'guide_run_id')
    status = strict_enum(row['status'], 'status', GUIDE_STATUSES)
    step = strict_enum(row['current_step'], 'current_step', GUIDE_STEPS)
    if code == 'AI_FINISHED' and (status, step) != ('COMPLETED', 'FINISHED') or code == 'AI_WAITING_USER' and (status, step) != ('WAITING_USER', 'WAITING_USER'):
        raise ValueError('ORCH result must reflect the committed state')
    if code == 'AI_STOPPED' and status == 'RUNNING': raise ValueError('A live run was not stopped')
    if last_call_no is not None: strict_integer(last_call_no, 'last_call_no')
    return {'code': code, 'data': {'guide_run_id': identity, 'status': status,
        'current_step': step, 'last_call_no': last_call_no}, 'details': None}


@dataclass(frozen=True)
class PersistAIResultInput:
    guide_run_id: int
    llm_use_id: int
    trusted_output: object


def persist_ai_result_input(payload):
    from .trusted_output import require_receipt
    fields=('guide_run_id','llm_use_id','trusted_output')
    value=object_fields(payload,'body',fields,fields)
    return PersistAIResultInput(strict_integer(value['guide_run_id'],'guide_run_id'),strict_integer(value['llm_use_id'],'llm_use_id'),require_receipt(value['trusted_output']))


def persist_ai_result_result(effects):
    fields=('guide_run_id','status','assistant_message_id','current_document','suggestion_batch_id')
    value=object_fields(effects,'C07 result',fields,fields)
    strict_integer(value['guide_run_id'],'guide_run_id');strict_integer(value['assistant_message_id'],'assistant_message_id')
    strict_enum(value['status'],'status',('COMPLETED','WAITING_USER'))
    if value['current_document'] is not None:
        document=object_fields(value['current_document'],'current_document',('id','content_version'),('id','content_version'))
        strict_integer(document['id'],'id');strict_integer(document['content_version'],'content_version')
        if value['status'] != 'COMPLETED' or value['suggestion_batch_id'] is not None:raise ValueError('CURRENT effect only completes initialization')
    if value['suggestion_batch_id'] is not None:
        strict_integer(value['suggestion_batch_id'],'suggestion_batch_id')
        if value['status'] != 'COMPLETED':raise ValueError('Suggestion result cannot be waiting')
    import json
    return {'code':'AI_RESULT_PERSISTED','data':json.loads(canonical_input(value)),'details':None}


def get_model_context_result(value: dict) -> dict:
    fields = ('run', 'requirement', 'current_document', 'template', 'scope',
              'allowed_targets', 'user_input', 'history', 'source', 'read_manifest')
    object_fields(value, 'model_context', fields, fields)
    # Each component is projected and validated from the same read transaction.
    # Detach all JSON values before releasing that snapshot to the caller.
    import json
    return {'code': 'READ_OK', 'data': json.loads(canonical_input(value)), 'details': None}
