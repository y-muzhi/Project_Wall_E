"""Execution profile references against actual registered resources and DB rows."""

from backend.app.infrastructure.resources import ConfigInvalid

from .check_set_versions import _find

RESOURCE_KINDS = (
    'EXECUTOR',
    'GIT',
    'MODEL',
    'RUNTIME',
    'COMMAND',
    'SCOPE',
    'PRICE',
    'SECRET_REF',
    'CAPABILITY',
    'CONTENT_POLICY',
)


def resource_snapshot(catalog):
    return {kind: catalog.code_configuration_options(kind) for kind in RESOURCE_KINDS}


def reference_error(connection, content, snapshot):
    """No arbitrary client command, supplier secret or fabricated price is admitted."""
    for kind, field in (('EXECUTOR', 'executor'), ('GIT', 'git')):
        matches = [row for row in snapshot[kind] if row['value'] == content[field]]
        if len(matches) > 1:
            raise ConfigInvalid('Ambiguous fixed execution resource')
        if not matches:
            return field
    for profile in [
        content['models']['primary_profile_ref'],
        *content['models']['auxiliary_profile_refs'],
    ]:
        if _find(snapshot, 'MODEL', 'model_profile_ref', profile) is None:
            return 'models'
    for i, binding in enumerate(content['models']['bindings']):
        here = f'models.bindings[{i}]'
        price = connection.execute(
            'SELECT * FROM model_price_versions WHERE id=?', (binding['price_version_id'],)
        ).fetchone()
        if price is None or (
            price['model_profile_ref'] != binding['model_profile_ref']
            or price['model_snapshot_ref'] != binding['model_snapshot_ref']
            or price['channel'] != 'ARK_CN_BEIJING'
            or price['service_tier'] != 'default'
        ):
            return here + '.price_version_id'
        registered_price = _find(snapshot, 'PRICE', 'price_version_id', binding['price_version_id'])
        if (
            registered_price is None
            or registered_price['value']['model_profile_ref'] != binding['model_profile_ref']
        ):
            return here + '.price_version_id'
        admission = _find(snapshot, 'CAPABILITY', 'evidence_ref', binding['admission_ref'])
        if admission is None or admission['value']['capability_code'] != 'Q20-MODEL':
            return here + '.admission_ref'
    environment = content['environment']
    for field, kind in (('python_ref', 'PYTHON'), ('node_ref', 'NODE')):
        if environment[field] is not None:
            option = _find(snapshot, 'RUNTIME', 'runtime_ref', environment[field])
            if option is None or option['value']['runtime_kind'] != kind:
                return 'environment.' + field
    for ref in environment['package_manager_refs']:
        option = _find(snapshot, 'RUNTIME', 'runtime_ref', ref)
        if option is None or option['value']['runtime_kind'] != 'PACKAGE_MANAGER':
            return 'environment.package_manager_refs'
    for ref in environment['secret_refs']:
        if _find(snapshot, 'SECRET_REF', 'secret_ref', ref) is None:
            return 'environment.secret_refs'
    for i, command in enumerate(content['commands']):
        option = _find(snapshot, 'COMMAND', 'command_id', command['command_id'])
        if option is None or option['value'] != command:
            return f'commands[{i}]'
        if command['network_scope_ref'] is not None:
            scope = _find(snapshot, 'SCOPE', 'scope_ref', command['network_scope_ref'])
            if scope is None or scope['value']['scope_kind'] != 'NETWORK_TARGET':
                return f'commands[{i}].network_scope_ref'
    policy = content['capture_rules']
    if not any(
        row['value']
        == {key: policy[key] for key in ('content_policy_version', 'secret_policy_ref')}
        for row in snapshot['CONTENT_POLICY']
    ):
        return 'capture_rules'
    for ref in content['capability_evidence_refs']:
        if _find(snapshot, 'CAPABILITY', 'evidence_ref', ref) is None:
            return 'capability_evidence_refs'
    check = connection.execute(
        'SELECT owner_module FROM code_check_set_versions WHERE id=?',
        (content['check_set_version_id'],),
    ).fetchone()
    if check is None or check['owner_module'] != 'CODING':
        return 'check_set_version_id'
    return None


def readiness(content, snapshot, checks):
    # Catalogue labels cannot prove source/usage semantics, account pricing or
    # per-binding token caps. The normal catalogue has no published, verified
    # Coding deployment yet. The private gateway checks its own exact evidence.
    codes = {'Q20-MODEL'}
    for kind in ('EXECUTOR', 'GIT', 'CONTENT_POLICY'):
        expected = content[
            {'EXECUTOR': 'executor', 'GIT': 'git', 'CONTENT_POLICY': 'capture_rules'}[kind]
        ]
        if kind == 'CONTENT_POLICY':
            expected = {
                key: expected[key] for key in ('content_policy_version', 'secret_policy_ref')
            }
        matching = [row for row in snapshot[kind] if row['value'] == expected]
        if not matching:
            codes.add('Q20-CONFIG')
        for row in matching:
            if row['ready'] is not True:
                codes.update(row['unresolved_capability_codes'] or ['Q20-CONFIG'])
    selections = [
        ('MODEL', 'model_profile_ref', ref)
        for ref in [
            content['models']['primary_profile_ref'],
            *content['models']['auxiliary_profile_refs'],
        ]
    ]
    environment = content['environment']
    selections.extend(
        ('RUNTIME', 'runtime_ref', ref)
        for ref in [
            environment['python_ref'],
            environment['node_ref'],
            *environment['package_manager_refs'],
        ]
        if ref is not None
    )
    selections.extend(('SECRET_REF', 'secret_ref', ref) for ref in environment['secret_refs'])
    selections.extend(
        ('CAPABILITY', 'evidence_ref', ref) for ref in content['capability_evidence_refs']
    )
    for binding in content['models']['bindings']:
        selections.append(('PRICE', 'price_version_id', binding['price_version_id']))
        selections.append(('CAPABILITY', 'evidence_ref', binding['admission_ref']))
    for command in content['commands']:
        selections.append(('COMMAND', 'command_id', command['command_id']))
        if command['network_scope_ref'] is not None:
            selections.append(('SCOPE', 'scope_ref', command['network_scope_ref']))
    for kind, key, ref in selections:
        selected = _find(snapshot, kind, key, ref)
        if selected is None:
            codes.add('Q20-CONFIG')
        elif not selected['ready']:
            codes.update(selected['unresolved_capability_codes'] or ['Q20-CONFIG'])
    if not checks['ready']:
        codes.add('Q20-CHECKS')
    return {'ready': False, 'unresolved_capability_codes': sorted(codes)}
