"""Bind model calls to the exact approved Coding profile, account, and price."""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.shared.validation import strict_integer, strict_json_loads, strict_json_object

from .authorizations import project_grant
from .check_set_versions import _find
from .coding_model_listener import CodingGatewayError
from .coding_model_request import ALIASES, CodingRequestContract
from .costs import ApplicablePrices, CachePrice, parse_money
from .repository_operations import _time
from .usage import UsageContract

_SHA = re.compile(r'[0-9a-f]{64}')


@dataclass(frozen=True)
class CodingModelAdmission:
    """Deployment evidence already reviewed outside the request path."""

    evidence_ref: str
    model_snapshot_ref: str
    billing_scope_ref: str
    price_sha256: str
    model: ModelProfile = field(repr=False)
    usage: UsageContract
    max_duration_seconds: int
    input_cap: int
    context_cap: int
    output_cap: int
    chunk_usage: bool = False
    optional_fields: frozenset[str] = frozenset()

    def __post_init__(self):
        if (
            any(
                type(value) is not str or not value or value.strip() != value
                for value in (
                    self.evidence_ref,
                    self.model_snapshot_ref,
                    self.billing_scope_ref,
                )
            )
            or type(self.price_sha256) is not str
            or not _SHA.fullmatch(self.price_sha256)
            or type(self.model) is not ModelProfile
            or type(self.usage) is not UsageContract
            or self.usage.final_source == 'COMPLETE_BODY'
            or set(self.usage.cache_dimensions) - {'cached_tokens'}
            or type(self.max_duration_seconds) is not int
            or not 1 <= self.max_duration_seconds <= 180
        ):
            raise ValueError('Exact Coding model admission evidence is required')
        self.contract('walle-code', self.output_cap)
        if self.output_cap > self.model.output_limit:
            raise ValueError('Coding output bound exceeds the registered provider profile')

    def contract(self, alias, authorized_output):
        return CodingRequestContract(
            alias,
            self.model.model_name,
            self.input_cap,
            self.context_cap,
            self.output_cap,
            authorized_output,
            self.chunk_usage,
            self.optional_fields,
        )


@dataclass(frozen=True)
class EffectiveCodingBinding:
    admission: CodingModelAdmission
    contract: CodingRequestContract
    price_version_id: int
    prices: ApplicablePrices
    profile_version_id: int
    max_requests: int
    max_consecutive_failures: int
    budget_micro: int


def _ready_option(catalog, kind, key, value):
    option = _find({kind: catalog.code_configuration_options(kind)}, kind, key, value)
    if option is None or option['ready'] is not True:
        raise CodingGatewayError('hold')
    return option['value']


def _fixed_price(row, admission, at):
    if (
        row is None
        or hashlib.sha256(_bytes(dict(row))).hexdigest() != admission.price_sha256
        or row['model_profile_ref'] != admission.model.profile_id
        or row['model_snapshot_ref'] != admission.model_snapshot_ref
        or row['billing_scope_ref'] != admission.billing_scope_ref
        or row['channel'] != 'ARK_CN_BEIJING'
        or row['currency'] != 'CNY'
        or row['service_tier'] != 'default'
        or row['rounding_rule'] != 'TOTAL_HALF_UP_6DP'
    ):
        raise CodingGatewayError('hold')
    try:
        clock = strict_json_object(row['tariff_rules'])
        # First executable proof covers one immutable flat price throughout the
        # request, including completion in the account's Beijing time zone.
        if clock != {'kind': 'FLAT', 'pricing_clock': 'COMPLETED_AT', 'timezone': 'Asia/Shanghai'}:
            raise CodingGatewayError('hold')
        for instant in (at, row['valid_from'], row['valid_until']):
            if instant is not None:
                _time(instant, nullable=False)
                if not instant.endswith('Z'):
                    raise CodingGatewayError('hold')
        beginning, now = datetime.fromisoformat(row['valid_from']), datetime.fromisoformat(at)
        end = None if row['valid_until'] is None else datetime.fromisoformat(row['valid_until'])
        if now < beginning or (
            end is not None and now + timedelta(seconds=admission.max_duration_seconds) >= end
        ):
            raise CodingGatewayError('hold')
        rules = strict_json_loads(row['cache_price_rules'])
        if type(rules) is not list or any(
            type(rule) is not dict or set(rule) != {'dimension', 'price_per_million'}
            for rule in rules
        ):
            raise CodingGatewayError('hold')
        cache = tuple(
            CachePrice(rule['dimension'], parse_money(rule['price_per_million'])) for rule in rules
        )
        if {item.dimension for item in cache} != set(admission.usage.cache_dimensions):
            raise CodingGatewayError('hold')
        return ApplicablePrices(
            parse_money(row['input_price_per_million']),
            parse_money(row['output_price_per_million']),
            cache,
        )
    except (TypeError, ValueError, OverflowError):
        raise CodingGatewayError('hold') from None


def effective_coding_binding(connection, catalog, admissions, window, alias, at):
    task = connection.execute('SELECT * FROM code_tasks WHERE id=?', (window.task_id,)).fetchone()
    if (
        task is None
        or task['control_generation'] != window.generation
        or task['active_session_id'] != window.execution_session_id
    ):
        raise CodingGatewayError('hold')
    profile = connection.execute(
        'SELECT models,limits FROM code_execution_profile_versions WHERE id=?',
        (task['execution_profile_version_id'],),
    ).fetchone()
    grant_row = connection.execute(
        "SELECT * FROM code_authorizations WHERE id=? AND status='EFFECTIVE'",
        (task['authorization_id'],),
    ).fetchone()
    if profile is None or grant_row is None:
        raise CodingGatewayError('hold')
    grant = project_grant(grant_row)
    models, limits = strict_json_object(profile['models']), strict_json_object(profile['limits'])
    candidates = [row for row in models['bindings'] if row['native_model_id'] == alias]
    if (
        len(candidates) != 1
        or grant['task_id'] != task['id']
        or grant['profile_version_id'] != task['execution_profile_version_id']
    ):
        raise CodingGatewayError('hold')
    selected = candidates[0]
    admission = admissions.get(selected['admission_ref'])
    if (
        type(admission) is not CodingModelAdmission
        or admission.evidence_ref != selected['admission_ref']
        or selected['purpose'] != ALIASES[alias]
        or selected['model_profile_ref'] != admission.model.profile_id
        or selected['model_snapshot_ref'] != admission.model_snapshot_ref
        or selected['model_profile_ref'] not in grant['scope']['model_profile_refs']
        or (
            selected['input_cap_tokens'],
            selected['context_cap_tokens'],
            selected['output_cap_tokens'],
        )
        != (admission.input_cap, admission.context_cap, admission.output_cap)
    ):
        raise CodingGatewayError('hold')
    _ready_option(catalog, 'MODEL', 'model_profile_ref', selected['model_profile_ref'])
    capability = _ready_option(catalog, 'CAPABILITY', 'evidence_ref', admission.evidence_ref)
    price_option = _ready_option(catalog, 'PRICE', 'price_version_id', selected['price_version_id'])
    if (
        capability.get('capability_code') != 'Q20-MODEL'
        or price_option.get('model_profile_ref') != admission.model.profile_id
    ):
        raise CodingGatewayError('hold')
    price = connection.execute(
        'SELECT * FROM model_price_versions WHERE id=?', (selected['price_version_id'],)
    ).fetchone()
    prices = _fixed_price(price, admission, at)

    def authorized(key):
        return min(
            strict_integer(limits[key], key), strict_integer(grant['scope']['limits'][key], key)
        )

    return EffectiveCodingBinding(
        admission,
        admission.contract(alias, authorized('max_output_tokens')),
        selected['price_version_id'],
        prices,
        task['execution_profile_version_id'],
        authorized('max_model_requests'),
        authorized('max_consecutive_failures'),
        parse_money(task['budget_limit_cny']),
    )
