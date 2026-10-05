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

GUIDE_STATUSES = ('RUNNING', 'WAITING_USER', 'COMPLETED', 'FAILED', 'CANCELLED')
GUIDE_STEPS = ('PREPARING', 'CALLING_MODEL', 'VALIDATING', 'PERSISTING', 'WAITING_USER', 'FINISHED')
STATUS_FIELDS = ('id', 'requirement_id', 'action_type', 'function_type', 'source_type', 'source_id', 'scope', 'status', 'current_step',
    'final_result', 'suggestion_batch_id', 'latest_assistant_message_id', 'error_code', 'error_message', 'cancel_reason',
    'retry_of_guide_run_id', 'created_at', 'started_at', 'waiting_user_at', 'ended_at', 'updated_at')
TASK_ERROR_CODES = frozenset(ERRORS) | {'MODEL_ERROR', 'OUTPUT_INVALID', 'CONTEXT_LIMIT_EXCEEDED', 'INTERRUPTED', 'EXECUTION_TIMEOUT'}


@dataclass(frozen=True)
class CreateGuideRunInput:
    requirement_id: int
    expected_content_version: int
    action_type: str
    instruction: str
    scope_type: str
    scope_ref_json: str
    source_type: str
    source_id: int | None
    idempotency_key: str

    @property
    def scope_ref(self):
        import json
        return json.loads(self.scope_ref_json)

    def business_input(self):
        return {field: getattr(self, field) for field in ('requirement_id', 'expected_content_version', 'action_type', 'instruction', 'scope_type', 'source_type', 'source_id')} | {'scope_ref': self.scope_ref}


def create_guide_run_input(payload):
    fields = ('requirement_id', 'expected_content_version', 'action_type', 'instruction', 'scope_type', 'scope_ref', 'source_type', 'source_id', 'idempotency_key')
    data = object_fields(payload, 'body', fields, tuple(field for field in fields if field not in ('scope_ref', 'source_id')))
    kind = strict_enum(data['scope_type'], 'scope_type', ('DOCUMENT', 'SECTION', 'BLOCK', 'SELECTION'))
    reference = data.get('scope_ref')
    if kind == 'DOCUMENT':
        if reference is not None: reject('scope_ref', 'INVALID_FORMAT', '全文范围必须省略引用或为null')
    else:
        if 'scope_ref' not in data: reject('scope_ref', 'REQUIRED', '此范围必须提供引用')
        _scope(kind, reference)
    source = strict_enum(data['source_type'], 'source_type', ('USER_INSTRUCTION', 'REVIEW_RESULT'))
    identity = data.get('source_id')
    if source == 'USER_INSTRUCTION':
        if identity is not None: reject('source_id', 'INVALID_FORMAT', '用户指令来源必须省略身份或为null')
    else:
        identity = strict_integer(data.get('source_id', MISSING), 'source_id')
    text = instruction(data['instruction'])
    try:
        import json
        canonical_input({'scope_ref': reference, 'instruction': text})
        encoded_ref = json.dumps(reference, ensure_ascii=False, separators=(',', ':'))
    except (ValueError, UnicodeError, RecursionError): reject('body', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return CreateGuideRunInput(strict_integer(data['requirement_id'], 'requirement_id'), strict_integer(data['expected_content_version'], 'expected_content_version'),
        strict_enum(data['action_type'], 'action_type', ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY')), text, kind, encoded_ref, source, identity, request_key(data['idempotency_key'], 'idempotency_key'))


@dataclass(frozen=True)
class ContinueGuideRunInput:
    guide_run_id: int
    instruction: str
    idempotency_key: str

    def business_input(self):
        return {'guide_run_id': self.guide_run_id, 'instruction': self.instruction}


def continue_guide_run_input(payload):
    fields = ('guide_run_id', 'instruction', 'idempotency_key')
    data = object_fields(payload, 'body', fields, fields)
    text = instruction(data['instruction'])
    try: canonical_input({'instruction': text})
    except (ValueError, UnicodeError): reject('instruction', 'INVALID_FORMAT', '文本必须由有效Unicode码点组成')
    return ContinueGuideRunInput(strict_integer(data['guide_run_id'], 'guide_run_id'), text, request_key(data['idempotency_key'], 'idempotency_key'))


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
    idempotency_key: str

    @property
    def answers(self):
        import json
        return json.loads(self.answers_json)

    def business_input(self):
        return {'message_id': self.message_id, **self.answers}


def submit_card_responses_input(payload):
    fields = ('message_id', 'schema_version', 'responses', 'idempotency_key')
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
    try: encoded = canonical_input({'schema_version': version, 'responses': normalized})
    except (ValueError, UnicodeError): reject('responses', 'INVALID_FORMAT', '回答必须使用有效Unicode码点')
    return SubmitCardResponsesInput(strict_integer(data['message_id'], 'message_id'), encoded, request_key(data['idempotency_key'], 'idempotency_key'))


def submit_card_responses_result(run, message):
    accepted = guide_run_accepted({key: run[key] for key in ('id', 'requirement_id', 'status', 'current_step')})
    value = message_read_model(message)
    if value['role'] != 'USER' or value['message_type'] != 'CARD_RESPONSE' or value['guide_run_id'] != accepted['id'] or value['requirement_id'] != accepted['requirement_id'] or value['structured_content'] is None:
        raise ValueError('Formal response must belong to its accepted run')
    return {'code': 'CARDS_ACCEPTED', 'data': {'response_message': value, 'guide_run': accepted, 'card_state': 'ANSWERED'}, 'details': None}


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
    fields = tuple(field for field in STATUS_FIELDS if not summary or field != 'final_result')
    value = object_fields(data, 'read_model', fields, fields)
    for field in ('id', 'requirement_id'):
        strict_integer(value[field], field)
    strict_enum(value['action_type'], 'action_type', ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY'))
    strict_enum(value['source_type'], 'source_type', ('USER_INSTRUCTION', 'REVIEW_RESULT', 'COMMENT'))
    if FUNCTIONS.get((value['action_type'], value['source_type']), (None,))[0] != value['function_type']:
        raise ValueError('Run Function must match its action and source')
    _nullable_identity(value['source_id'], 'source_id')
    if (value['source_type'] == 'USER_INSTRUCTION') != (value['source_id'] is None):
        raise ValueError('Source kind and identity disagree')
    scope = object_fields(value['scope'], 'scope', ('scope_type', 'scope_ref'), ('scope_type', 'scope_ref'))
    _scope(scope['scope_type'], scope['scope_ref'])
    strict_enum(value['status'], 'status', GUIDE_STATUSES)
    strict_enum(value['current_step'], 'current_step', GUIDE_STEPS)
    for field in ('suggestion_batch_id', 'latest_assistant_message_id', 'retry_of_guide_run_id'):
        _nullable_identity(value[field], field)
    if value['retry_of_guide_run_id'] == value['id']:
        raise ValueError('Retry cannot refer to itself')
    if (value['status'] in ('COMPLETED', 'FAILED', 'CANCELLED')) != (value['ended_at'] is not None):
        raise ValueError('Run terminal time is inconsistent')
    created, updated = _time(value['created_at']), _time(value['updated_at'])
    if created > updated:
        raise ValueError('Run activity time precedes creation')
    for field in ('started_at', 'waiting_user_at', 'ended_at'):
        if value[field] is not None and not created <= _time(value[field]) <= updated:
            raise ValueError('Run event time is outside its activity interval')
    if value['status'] == 'FAILED':
        strict_enum(value['error_code'], 'error_code', TASK_ERROR_CODES)
        if type(value['error_message']) is not str or not value['error_message']:
            raise ValueError('Failed runs require a program-produced safe message')
    elif value['error_code'] is not None or value['error_message'] is not None:
        raise ValueError('Only failed runs expose errors')
    if value['status'] == 'CANCELLED':
        if type(value['cancel_reason']) is not str or not value['cancel_reason']:
            raise ValueError('Cancelled run requires its reason')
    elif value['cancel_reason'] is not None:
        raise ValueError('Only cancelled runs expose cancellation reason')
    if not summary and value['status'] == 'COMPLETED':
        final = object_fields(value['final_result'], 'final_result', ('summary', 'assistant_message_id', 'current_document_version', 'suggestion_batch_id'), ('summary', 'assistant_message_id', 'current_document_version', 'suggestion_batch_id'))
        if type(final['summary']) is not str or not final['summary']:
            raise ValueError('Completed result needs a safe readable summary')
        for field in ('assistant_message_id', 'current_document_version', 'suggestion_batch_id'):
            _nullable_identity(final[field], field)
        if final['suggestion_batch_id'] != value['suggestion_batch_id']:
            raise ValueError('Completed batch references disagree')
    elif not summary and value['final_result'] is not None:
        raise ValueError('Only completed runs expose a final result')
    return json_detached(value)


def guide_run_read_model(data: object) -> dict:
    return _guide_model(data, summary=False)


def guide_run_summary(data: object) -> dict:
    return _guide_model(data, summary=True)


def json_detached(value: dict) -> dict:
    import json
    return json.loads(canonical_input(value))


def get_guide_run_result(connection, row, message, batches, *, catalog: ResourceCatalog | None = None, summary: bool = False) -> dict:
    value = {field: row[field] for field in STATUS_FIELDS if field not in ('scope', 'final_result', 'suggestion_batch_id', 'latest_assistant_message_id')}
    reference = None if row['scope_ref_json'] is None else strict_json_object(row['scope_ref_json'], 'scope_ref_json')
    value['scope'] = _scope(row['scope_type'], reference)
    value['suggestion_batch_id'] = None if not batches else batches[0]['id']
    if batches and row['action_type'] != 'MODIFY':
        raise ValueError('Only a MODIFY run can own a suggestion batch')
    value['latest_assistant_message_id'] = None if message is None else message['id']
    if not summary:
        value['final_result'] = None
    if not summary and row['status'] == 'COMPLETED':
        # D-005 C07 business result, never raw model output or a Prompt snapshot.
        effects = strict_json_object(row['final_result_json'], 'final_result_json')
        fields = ('guide_run_id', 'status', 'assistant_message_id', 'current_document', 'suggestion_batch_id')
        object_fields(effects, 'final_result_json', (*fields, 'review_result'), fields)
        if 'review_result' in effects:
            if row['action_type'] != 'REVIEW':
                raise ValueError('Only a REVIEW run can retain a review_result')
            if effects['review_result'] is not None:
                resources = catalog if catalog is not None else ResourceCatalog()
                resources.freeze('REVIEW', 'USER_INSTRUCTION').validate_review_result(effects['review_result'])
        strict_integer(effects['guide_run_id'], 'guide_run_id')
        _nullable_identity(effects['suggestion_batch_id'], 'suggestion_batch_id')
        if effects['guide_run_id'] != row['id'] or effects['status'] != 'COMPLETED' or effects['suggestion_batch_id'] != value['suggestion_batch_id']:
            raise ValueError('Completed effect record contradicts its actual run')
        assistant_id = _nullable_identity(effects['assistant_message_id'], 'assistant_message_id')
        if assistant_id is not None:
            assistant = connection.execute("SELECT 1 FROM conversation_messages WHERE id=? AND requirement_id=? AND guide_run_id=? AND role='ASSISTANT'", (assistant_id, row['requirement_id'], row['id'])).fetchone()
            if assistant is None:
                raise ValueError('Completed assistant reference is not owned by this run')
        version = None
        if effects['current_document'] is not None:
            if row['action_type'] != 'INITIALIZE':
                raise ValueError('Only INITIALIZE can write CURRENT during AI result submission')
            current = object_fields(effects['current_document'], 'current_document', ('id', 'content_version'), ('id', 'content_version'))
            strict_integer(current['id'], 'current_document.id'); version = strict_integer(current['content_version'], 'current_document.content_version')
            actual = connection.execute("SELECT id,content_version FROM requirement_documents WHERE requirement_id=? AND document_type='CURRENT'", (row['requirement_id'],)).fetchall()
            if len(actual) != 1 or actual[0]['id'] != current['id'] or actual[0]['content_version'] < version:
                raise ValueError('Completed document effect does not belong to this actual CURRENT history')
        summaries = {'INITIALIZE': '初始化任务已完成', 'ASK': '回答任务已完成', 'REVIEW': '检查任务已完成', 'MODIFY': '修改任务已完成'}
        summary_text = '修改建议已生成' if row['action_type'] == 'MODIFY' and batches else summaries[row['action_type']]
        value['final_result'] = {'summary': summary_text, 'assistant_message_id': assistant_id, 'current_document_version': version, 'suggestion_batch_id': value['suggestion_batch_id']}
    if connection.execute('SELECT 1 FROM requirements WHERE id=?', (row['requirement_id'],)).fetchone() is None:
        raise ValueError('Run requirement is missing')
    if row['source_type'] != 'USER_INSTRUCTION':
        table = 'guide_runs' if row['source_type'] == 'REVIEW_RESULT' else 'comments'
        fields = 'requirement_id,action_type,status' if table == 'guide_runs' else 'requirement_id'
        source = connection.execute('SELECT '+fields+' FROM '+table+' WHERE id=?', (row['source_id'],)).fetchone()
        if source is None or source['requirement_id'] != row['requirement_id']:
            raise ValueError('Run source belongs to another requirement')
        if table == 'guide_runs' and (source['action_type'] != 'REVIEW' or source['status'] != 'COMPLETED'):
            raise ValueError('Review source must be a completed REVIEW run')
    if row['retry_of_guide_run_id'] is not None:
        previous = connection.execute('SELECT requirement_id,status,created_at FROM guide_runs WHERE id=?', (row['retry_of_guide_run_id'],)).fetchone()
        if previous is None or previous['requirement_id'] != row['requirement_id'] or previous['status'] != 'FAILED' or previous['created_at'] > row['created_at']:
            raise ValueError('Retry source is not a prior failed run of this requirement')
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
        choices('action_type', ('INITIALIZE', 'ASK', 'REVIEW', 'MODIFY')), page_number(data.get('page', 1)))


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
