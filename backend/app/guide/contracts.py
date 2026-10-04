"""C09 trusted input and D-005 complete recovery result."""
from dataclasses import dataclass
from backend.app.documents.snapshot import _time
from backend.app.documents.markdown import DocumentInvalid
from backend.app.shared.validation import object_fields, strict_integer, strict_enum, reject


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
