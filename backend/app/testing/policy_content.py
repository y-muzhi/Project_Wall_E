"""Fixed Testing configuration uses the existing registered resource identities."""

from backend.app.code_tasks.check_set_versions import _find
from backend.app.code_tasks.execution_profile_content import commands
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import (
    object_fields,
    ordinary_text,
    raw_text,
    reject,
    strict_integer,
)

PROFILE_FIELDS = (
    'name',
    'runner_refs',
    'environment_refs',
    'commands',
    'model_binding',
    'limits',
    'admission_refs',
)
MODEL_FIELDS = (
    'model_profile_ref',
    'model_snapshot_ref',
    'price_version_id',
    'input_cap_tokens',
    'output_cap_tokens',
    'admission_ref',
)
LIMIT_FIELDS = (
    'max_model_requests',
    'max_active_seconds',
    'max_check_output_bytes',
    'max_check_cases',
    'max_case_steps',
    'max_case_payload_bytes',
    'max_input_bytes',
    'query_timeout_seconds',
    'send_timeout_seconds',
    'graceful_stop_seconds',
    'force_stop_wait_seconds',
)
_KINDS = ('RUNNER', 'RUNTIME', 'COMMAND', 'SCOPE', 'MODEL', 'PRICE', 'CAPABILITY')


def _refs(value, field):
    if type(value) is not list or not 1 <= len(value) <= 256:
        reject(field, 'INVALID_TYPE', '必须选择已登记的非空资源列表')
    selected = [raw_text(item, field, 1, 512) for item in value]
    if len(set(selected)) != len(selected):
        reject(field, 'DUPLICATE_PARAMETER', '同一资源不得重复')
    return selected


def profile_name(value):
    result = ordinary_text(value, 'name', 1, 200)
    if '\0' in result:
        reject('name', 'INVALID_FORMAT', '名称不能包含空字符')
    return result


def parse_profile(value):
    source = object_fields(value, 'profile_content', PROFILE_FIELDS, PROFILE_FIELDS)
    limits = object_fields(source['limits'], 'limits', LIMIT_FIELDS, LIMIT_FIELDS)
    definitions = commands(source['commands'], HTTP_REQUEST_BYTES)
    for index, command in enumerate(definitions):
        if command['purpose'] not in ('CHECK', 'SERVICE'):
            reject(f'commands[{index}].purpose', 'INVALID_ENUM', '独立测试只采用检查或服务命令')
    model = source['model_binding']
    if model is not None:
        model = object_fields(model, 'model_binding', MODEL_FIELDS, MODEL_FIELDS)
        model = {
            field: strict_integer(model[field], field)
            if field in ('price_version_id', 'input_cap_tokens', 'output_cap_tokens')
            else raw_text(model[field], 'model_binding.' + field, 1, 512)
            for field in MODEL_FIELDS
        }
    return {
        'name': profile_name(source['name']),
        'runner_refs': _refs(source['runner_refs'], 'runner_refs'),
        'environment_refs': _refs(source['environment_refs'], 'environment_refs'),
        'commands': definitions,
        'model_binding': model,
        'limits': {
            field: strict_integer(limits[field], 'limits.' + field, maximum=HTTP_REQUEST_BYTES)
            if field == 'max_input_bytes'
            else strict_integer(limits[field], 'limits.' + field)
            for field in LIMIT_FIELDS
        },
        'admission_refs': _refs(source['admission_refs'], 'admission_refs'),
    }


def resource_snapshot(catalog):
    try:
        return {kind: catalog.code_configuration_options(kind) for kind in _KINDS}
    except ConfigInvalid:
        return None


def _resources(connection, content, snapshot):
    missing, selected = [], []

    def add(kind, key, identity, field, predicate=lambda _: True):
        row = _find(snapshot, kind, key, identity)
        if row is None or not predicate(row['value']):
            missing.append(field)
        else:
            selected.append(row)

    for field, kind, key in (
        ('runner_refs', 'RUNNER', 'runner_ref'),
        ('environment_refs', 'RUNTIME', 'runtime_ref'),
        ('admission_refs', 'CAPABILITY', 'evidence_ref'),
    ):
        for index, identity in enumerate(content[field]):
            add(kind, key, identity, f'{field}[{index}]')
    for index, command in enumerate(content['commands']):
        field = f'commands[{index}]'
        add(
            'COMMAND',
            'command_id',
            command['command_id'],
            field,
            lambda value, fixed=command: value == fixed,
        )
        scope = command['network_scope_ref']
        if scope is not None:
            add(
                'SCOPE',
                'scope_ref',
                scope,
                field + '.network_scope_ref',
                lambda value: value.get('scope_kind') == 'NETWORK_TARGET',
            )
    model = content['model_binding']
    if model is not None:
        add(
            'MODEL',
            'model_profile_ref',
            model['model_profile_ref'],
            'model_binding.model_profile_ref',
        )
        add(
            'PRICE',
            'price_version_id',
            model['price_version_id'],
            'model_binding.price_version_id',
            lambda value: value.get('model_profile_ref') == model['model_profile_ref'],
        )
        add(
            'CAPABILITY',
            'evidence_ref',
            model['admission_ref'],
            'model_binding.admission_ref',
            lambda value: value.get('capability_code') == 'Q20-MODEL',
        )
        price = connection.execute(
            'SELECT model_profile_ref,model_snapshot_ref FROM model_price_versions WHERE id=?',
            (model['price_version_id'],),
        ).fetchone()
        if price is None or any(
            price[field] != model[field] for field in ('model_profile_ref', 'model_snapshot_ref')
        ):
            missing.append('model_binding.price_version_id')
    return tuple(dict.fromkeys(missing)), selected


def profile_resource_facts(connection, content, snapshot):
    unavailable = {'ready': False, 'reason_codes': ['Q20-CHECKS', 'Q20-CONFIG']}
    if snapshot is None:
        return None, unavailable
    try:
        missing, selected = _resources(connection, content, snapshot)
    except ConfigInvalid:
        return None, unavailable
    # An independently admitted Testing executor has not been installed. A
    # registered Coding project check or a label cannot make this path executable.
    reasons = {'Q20-CHECKS'}
    if missing:
        reasons.add('Q20-CONFIG')
    for row in selected:
        if row['ready'] is not True:
            reasons.update(row.get('unresolved_capability_codes') or ['Q20-CONFIG'])
    return missing, {'ready': False, 'reason_codes': sorted(reasons)}
