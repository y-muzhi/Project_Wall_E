"""Strict V2.1 discussion input; model execution still uses the existing GuideRun."""

from dataclasses import dataclass

from backend.app.infrastructure.idempotency import request_key
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.validation import (
    normalize_text,
    object_fields,
    raw_text,
    reject,
    strict_boolean,
    strict_enum,
    strict_integer,
)

from .types import nullable, proposal, reference, source


def target_selection(value, field='target'):
    fields = (
        'discussion_step_ref',
        'discussion_branch_ref',
        'branch_intent',
        'branch_resume_basis',
    )
    item = object_fields(value, field, fields, fields)
    step = nullable(
        item['discussion_step_ref'],
        field + '.discussion_step_ref',
        lambda v, f: reference(v, f, 'STEP'),
    )
    branch = nullable(
        item['discussion_branch_ref'],
        field + '.discussion_branch_ref',
        lambda v, f: reference(v, f, 'BRANCH'),
    )
    intent = nullable(
        item['branch_intent'],
        field + '.branch_intent',
        lambda v, f: strict_enum(v, f, ('ENTER', 'RESUME')),
    )
    basis = item['branch_resume_basis']
    if basis is not None:
        names = ('expected_branch_status', 'expected_branch_event_id')
        basis = object_fields(basis, field + '.branch_resume_basis', names, names)
        basis = {
            'expected_branch_status': strict_enum(
                basis['expected_branch_status'],
                field + '.branch_resume_basis.expected_branch_status',
                ('DEFERRED', 'RESOLVED'),
            ),
            'expected_branch_event_id': strict_integer(
                basis['expected_branch_event_id'],
                field + '.branch_resume_basis.expected_branch_event_id',
            ),
        }
    if branch is None:
        if intent is not None or basis is not None:
            reject(field, 'INVALID_FORMAT', '未选择支线时不得携带支线意图或恢复依据')
    elif step is None or intent is None or (intent == 'RESUME') != (basis is not None):
        reject(field, 'INVALID_FORMAT', '支线必须绑定步骤及明确进入／恢复意图')
    return dict(zip(fields, (step, branch, intent, basis)))


@dataclass(frozen=True)
class FormationDiscussInput:
    requirement_id: int
    document_id: int
    expected_discussion_version: int
    operation: str
    instruction: str
    target: dict
    scope: dict | None
    source_refs: list
    proposal_ref: dict | None
    acknowledge_source_changes: bool
    proposal_intent: str | None
    idempotency_key: str

    @property
    def action_type(self):
        return 'ASK'

    def business_input(self):
        return {
            name: getattr(self, name)
            for name in (
                'requirement_id',
                'document_id',
                'expected_discussion_version',
                'operation',
                'instruction',
                'target',
                'scope',
                'source_refs',
                'proposal_ref',
                'acknowledge_source_changes',
                'proposal_intent',
            )
        }


def formation_discuss_input(payload):
    from backend.app.requirements.discussion import discussion_resources

    fields = (
        'requirement_id',
        'document_id',
        'expected_discussion_version',
        'operation',
        'instruction',
        'target',
        'scope',
        'source_refs',
        'proposal_ref',
        'acknowledge_source_changes',
        'proposal_intent',
        'idempotency_key',
    )
    item = object_fields(payload, 'body', fields, fields)
    strict_enum(item['operation'], 'operation', ('DISCUSS',))
    text = raw_text(item['instruction'], 'instruction', 1, 10000)
    if not normalize_text(text):
        reject('instruction', 'TOO_SHORT', '请输入本轮讨论指令')
    try:
        scope = (
            None
            if item['scope'] is None
            else discussion_resources().validate('legacy_scope', item['scope'])
        )
    except ValueError:
        reject('scope', 'INVALID_FORMAT', '范围结构不符合当前严格契约')
    refs = item['source_refs']
    if type(refs) is not list or len(refs) > 1000:
        reject('source_refs', 'INVALID_FORMAT', '来源必须是有界集合')
    refs = [source(value, f'source_refs[{index}]') for index, value in enumerate(refs)]
    proposed = nullable(item['proposal_ref'], 'proposal_ref', proposal)
    intent = nullable(
        item['proposal_intent'],
        'proposal_intent',
        lambda v, f: strict_enum(v, f, ('ADJUST_WRITE', 'ADJUST_PATH')),
    )
    if (proposed is None) != (intent is None):
        reject('proposal_intent', 'INVALID_FORMAT', '调整意图必须同时绑定原提案')
    result = FormationDiscussInput(
        strict_integer(item['requirement_id'], 'requirement_id'),
        strict_integer(item['document_id'], 'document_id'),
        strict_integer(item['expected_discussion_version'], 'expected_discussion_version'),
        'DISCUSS',
        text,
        target_selection(item['target']),
        scope,
        refs,
        proposed,
        strict_boolean(item['acknowledge_source_changes'], 'acknowledge_source_changes'),
        intent,
        request_key(item['idempotency_key']),
    )
    try:
        canonical_input(result.business_input())
    except (ValueError, UnicodeError, RecursionError):
        reject('body', 'INVALID_FORMAT', '请求必须是有效Unicode及有限JSON')
    return result
