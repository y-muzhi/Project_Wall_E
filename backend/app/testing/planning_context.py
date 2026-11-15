"""Freeze the admitted design-only TEST20-PLAN-1 input and validate draft output."""

from dataclasses import dataclass, field
from hashlib import sha256

from backend.app.code_tasks.coding_model_admission import _fixed_price
from backend.app.code_tasks.coding_model_listener import CodingGatewayError
from backend.app.code_tasks.costs import ApplicablePrices
from backend.app.code_tasks.usage import UsageContract
from backend.app.infrastructure.audit_data import MAX_AUDIT_BYTES
from backend.app.infrastructure.check_runner_bundle import reference, valid_sha256
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.model_gateway import ModelGateway
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.shared.validation import object_fields, strict_integer, strict_json_object

from .asset_installation import TestingAssetInstallation
from .pack_compile import case_targets
from .plan_content import _read_basis, invalid_basis, parse_plan_content
from .tasks import materials_for

PROMPT = (
    '你负责独立测试设计。依据固定原文逐项定义可观察行为、覆盖与有依据的预期。'
    '只使用登记能力。不能确定时列入unresolved_questions；不得补业务规则、编造已运行结果或声明已发布。'
    '只输出给定结构JSON，不执行工具。'
)
_PROTOCOL = 'TEST20-PLAN-1'
_CHAT_FRAMING_TOKENS = 256
_DRAFT_FIELDS = ('behaviors', 'cases', 'unresolved_questions')
_ID = {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$'}
_TEXT = {'type': 'string'}
_VALUE = {}
_LOCATOR = {
    'oneOf': [
        {
            'type': 'object',
            'additionalProperties': False,
            'required': ['kind', 'value'],
            'properties': {'kind': {'const': 'TEST_ID'}, 'value': _ID},
        },
        {
            'type': 'object',
            'additionalProperties': False,
            'required': ['kind', 'value', 'name'],
            'properties': {
                'kind': {'const': 'ROLE'},
                'value': _TEXT,
                'name': {'type': ['string', 'null']},
            },
        },
    ]
}


def _object(**fields):
    return {
        'type': 'object',
        'properties': fields,
        'required': list(fields),
        'additionalProperties': False,
    }


def _list(items, maximum, *, minimum=0):
    return {'type': 'array', 'items': items, 'maxItems': maximum, 'minItems': minimum}


def _enum(*values):
    return {'enum': list(values)}


def _op(identity, op, **fields):
    return _object(**{identity: _ID}, op={'const': op}, **fields)


def _case_schema(driver, steps, assertions):
    return _object(
        case_id=_ID,
        name={'type': 'string', 'maxLength': 256},
        behavior_ids=_list(_ID, 4096, minimum=1),
        visibility=_enum('PUBLIC', 'HELD_OUT'),
        driver_kind={'const': driver},
        steps=_list({'oneOf': steps}, 256, minimum=1),
        assertions=_list({'oneOf': assertions}, 256, minimum=1),
        timeout_seconds={'type': 'integer', 'minimum': 1, 'maximum': 3600},
    )


_STEPS = 'step_id'
_ASSERTIONS = 'assertion_id'
_BYTES = {'type': 'string', 'contentEncoding': 'base64'}
_HTTP_METHODS = _enum('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
_CASE_SCHEMAS = (
    _case_schema(
        'CLI',
        [_op(_STEPS, 'RUN', command_id=_ID, stdin=_BYTES)],
        [
            _op(
                _ASSERTIONS,
                'EXIT_CODE',
                expected={'type': 'integer', 'minimum': 0, 'maximum': 2**32 - 1},
            ),
            _op(_ASSERTIONS, 'STDOUT_BYTES', expected=_BYTES),
        ],
    ),
    _case_schema(
        'HTTP',
        [
            _op(
                _STEPS,
                'REQUEST',
                endpoint_ref=_ID,
                path=_TEXT,
                method=_HTTP_METHODS,
                body=_BYTES,
                headers={
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        name: _TEXT
                        for name in (
                            'accept',
                            'content-type',
                            'content-language',
                            'if-match',
                            'if-none-match',
                        )
                    },
                },
            )
        ],
        [
            _op(
                _ASSERTIONS,
                'STATUS',
                step_id=_ID,
                expected={'type': 'integer', 'minimum': 100, 'maximum': 599},
            ),
            _op(_ASSERTIONS, 'BODY_BYTES', step_id=_ID, expected=_BYTES),
            _op(_ASSERTIONS, 'HEADER', step_id=_ID, header=_TEXT, expected=_TEXT),
            _op(_ASSERTIONS, 'JSON_POINTER', step_id=_ID, pointer=_TEXT, expected=_VALUE),
        ],
    ),
    _case_schema(
        'BROWSER',
        [
            _op(_STEPS, 'NAVIGATE', endpoint_ref=_ID, path=_TEXT),
            _op(_STEPS, 'CLICK', locator=_LOCATOR),
            *[
                _op(_STEPS, action, locator=_LOCATOR, value=_TEXT)
                for action in ('FILL', 'SELECT', 'PRESS')
            ],
        ],
        [
            _op(_ASSERTIONS, 'VISIBLE', locator=_LOCATOR, expected={'type': 'boolean'}),
            _op(_ASSERTIONS, 'TEXT', locator=_LOCATOR, expected=_TEXT),
            _op(
                _ASSERTIONS,
                'COUNT',
                locator=_LOCATOR,
                expected={'type': 'integer', 'minimum': 0, 'maximum': 100000},
            ),
        ],
    ),
)
_DRAFT_SCHEMA = _object(
    behaviors=_list(
        _object(
            behavior_id=_ID,
            name={'type': 'string', 'maxLength': 256},
            basis_refs=_list(
                _object(
                    document_id={'type': 'integer', 'minimum': 1},
                    revision_id={'type': 'integer', 'minimum': 1},
                    quote={'type': 'string', 'maxLength': 4096},
                ),
                256,
                minimum=1,
            ),
            stages=_list(_enum('BACKEND', 'FRONTEND', 'INTEGRATION', 'ACCEPTANCE'), 4, minimum=1),
            importance=_enum('BLOCKER', 'CRITICAL', 'NORMAL'),
            mode=_enum('AUTO', 'MANUAL', 'NOT_APPLICABLE', 'UNCOVERED'),
            case_ids=_list(_ID, 4096),
            explanation={'type': 'string', 'maxLength': 2000},
        ),
        4096,
    ),
    cases=_list({'oneOf': list(_CASE_SCHEMAS)}, 4096),
    unresolved_questions=_list({'type': 'string', 'minLength': 1, 'maxLength': 2000}, 256),
)
PROMPT_SHA256 = sha256(
    canonical_input({'protocol': _PROTOCOL, 'system': PROMPT, 'schema': _DRAFT_SCHEMA}).encode()
).hexdigest()


class DraftContextUnavailable(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TestingModelAdmission:
    evidence_ref: str
    model_snapshot_ref: str
    billing_scope_ref: str
    price_sha256: str
    prompt_sha256: str
    model: ModelProfile = field(repr=False)
    usage: UsageContract
    max_duration_seconds: int
    max_request_bytes: int
    input_cap: int

    def __post_init__(self):
        for value in (self.evidence_ref, self.model_snapshot_ref, self.billing_scope_ref):
            reference(value)
        if (
            type(self.model) is not ModelProfile
            or type(self.usage) is not UsageContract
            or self.usage.final_source != 'COMPLETE_BODY'
            or set(self.usage.required_dimensions)
            - {'input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens'}
            or set(self.usage.cache_dimensions) - {'cached_tokens'}
            or not valid_sha256(self.price_sha256)
            or self.prompt_sha256 != PROMPT_SHA256
        ):
            raise ValueError('Original Testing model admission differs')
        strict_integer(self.max_duration_seconds, 'max_duration_seconds', maximum=180)
        strict_integer(self.max_request_bytes, 'max_request_bytes', maximum=MAX_AUDIT_BYTES)
        strict_integer(self.input_cap, 'input_cap')


@dataclass(frozen=True)
class TestingPlanningInstallation:
    admissions: tuple[TestingModelAdmission, ...]
    gateway: ModelGateway = field(default_factory=ModelGateway, repr=False)

    def __post_init__(self):
        if (
            type(self.admissions) is not tuple
            or any(type(row) is not TestingModelAdmission for row in self.admissions)
            or len({row.evidence_ref for row in self.admissions}) != len(self.admissions)
            or type(self.gateway) is not ModelGateway
        ):
            raise ValueError('Exact Testing planning installation required')


@dataclass(frozen=True)
class DraftModelInput:
    system: str
    input_json: str = field(repr=False)
    output_cap: int


@dataclass(frozen=True)
class FrozenDraft:
    basis: dict
    targets: tuple
    model_input: DraftModelInput
    facts: dict
    admission: TestingModelAdmission
    prices: ApplicablePrices
    timeout_seconds: int


def _targets(catalog, profile):
    installed = getattr(catalog, 'testing_assets', None)
    if type(installed) is not TestingAssetInstallation:
        return ()
    declared_commands = {row['command_id'] for row in profile['commands']}
    return tuple(
        target
        for target in installed.targets
        if target.runner_ref in profile['runner_refs']
        and set(target.command_ids).issubset(declared_commands)
        and set(target.environment_refs).issubset(profile['environment_refs'])
    )


def freeze_draft(connection, catalog, task, profile, at):
    installed = getattr(catalog, 'testing_planning', None)
    binding = profile['model_binding']
    if type(installed) is not TestingPlanningInstallation or binding is None:
        raise DraftContextUnavailable('CONFIG_NOT_READY')
    admissions = [
        row for row in installed.admissions if row.evidence_ref == binding['admission_ref']
    ]
    if len(admissions) != 1 or binding['admission_ref'] not in profile['admission_refs']:
        raise DraftContextUnavailable('CONFIG_NOT_READY')
    admission = admissions[0]
    if (
        admission.model.profile_id != binding['model_profile_ref']
        or admission.model_snapshot_ref != binding['model_snapshot_ref']
        or admission.input_cap > binding['input_cap_tokens']
        or binding['output_cap_tokens'] > admission.model.output_limit
    ):
        raise DraftContextUnavailable('CONFIG_NOT_READY')
    price = connection.execute(
        'SELECT * FROM model_price_versions WHERE id=?', (binding['price_version_id'],)
    ).fetchone()
    try:
        prices = _fixed_price(price, admission, at)
    except CodingGatewayError as error:
        raise DraftContextUnavailable('CONFIG_NOT_READY') from error

    basis = {key: task[key] for key in ('requirement_id', 'document_id', 'design_revision_id')}
    basis['material_refs'] = materials_for(connection, task['id'])
    field, original = _read_basis(connection, basis, True)
    if field is not None:
        raise DraftContextUnavailable('CONTENT_NOT_READY')
    targets = _targets(catalog, profile)
    sources = [
        {'document_id': ids[0], 'revision_id': ids[1], 'markdown': markdown}
        for ids, markdown in original.items()
    ]
    capabilities = [
        {
            'driver_kind': row.driver_kind,
            'command_ids': list(row.command_ids),
            'endpoint_refs': list(row.endpoint_refs),
        }
        for row in targets
    ]
    model_input = DraftModelInput(
        PROMPT,
        canonical_input(
            {
                'fixed_design_and_materials': sources,
                'registered_capabilities': capabilities,
                'output_schema': _DRAFT_SCHEMA,
                'budget_limit_cny': task['budget_limit_cny'],
                'output_cap_tokens': binding['output_cap_tokens'],
            }
        ),
        binding['output_cap_tokens'],
    )
    body = admission.model.testing_request(model_input, output_cap=model_input.output_cap)
    request = canonical_input(body).encode()
    request_sha256 = sha256(request).hexdigest()
    if admission.model.api_key.encode('ascii') in request or len(request) > min(
        admission.max_request_bytes,
        admission.input_cap - _CHAT_FRAMING_TOKENS,
        profile['limits']['max_input_bytes'],
        MAX_AUDIT_BYTES,
    ):
        raise DraftContextUnavailable('CONTENT_NOT_READY')
    timeout = min(
        admission.max_duration_seconds,
        profile['limits']['max_active_seconds'],
        profile['limits']['send_timeout_seconds'],
    )
    return FrozenDraft(
        basis,
        targets,
        model_input,
        {
            'protocol': _PROTOCOL,
            'prompt_sha256': PROMPT_SHA256,
            'request_sha256': request_sha256,
            'authorization_id': task['authorization_id'],
            'profile_version_id': task['profile_version_id'],
            'price_version_id': binding['price_version_id'],
            'model_snapshot_ref': binding['model_snapshot_ref'],
            'admission_ref': admission.evidence_ref,
            'input_cap': admission.input_cap,
            'output_cap': model_input.output_cap,
            'query_timeout_seconds': profile['limits']['query_timeout_seconds'],
            'timeout_seconds': timeout,
            'design': [
                {
                    **{key: row[key] for key in ('document_id', 'revision_id')},
                    'sha256': sha256(row['markdown'].encode()).hexdigest(),
                }
                for row in sources
            ],
            'capability_sha256': sha256(
                canonical_input({'capabilities': capabilities}).encode()
            ).hexdigest(),
        },
        admission,
        prices,
        timeout,
    )


def parse_draft(raw):
    return object_fields(strict_json_object(raw), 'draft', _DRAFT_FIELDS, _DRAFT_FIELDS)


def validate_draft(connection, parsed, frozen):
    value = parse_plan_content({**frozen.basis, **parsed})
    if not (value['behaviors'] or value['unresolved_questions']):
        raise ValueError('Original Testing draft is empty')
    if invalid_basis(connection, value, require_confirmed=True) is not None:
        raise ValueError('Original Testing draft basis does not match')
    if value['cases']:
        case_targets(value, frozen.targets)
    return value
