"""Original TASK preparation's private WFP plan and exact filter observation."""

import hashlib
from contextlib import contextmanager
from ipaddress import ip_address
from uuid import UUID, uuid5

from backend.app.shared.validation import strict_json_object

from .guard_action_journal import GuardActionJournal
from .guard_action_records import mutation_input_sha256
from .guard_request_header import GuardRequestHeader
from .runtime_launch_journal import LaunchScope, TestingLaunchScope, _bytes
from .windows_config_source import LockedFileSource
from .windows_job import _lpac_security_capabilities, task_lpac_profile
from .windows_private_package import _api as security_api
from .windows_private_package import _sid_text, current_operator_sid
from .windows_private_record import PrivateRecordAppend
from .windows_wfp import (
    _LOCAL_ADDRESS,
    _LOCAL_PORT,
    _PACKAGE_SID,
    _PROTOCOL,
    _REMOTE_ADDRESS,
    _REMOTE_PORT,
    _REQUIRED_LAYERS,
    WfpObservationError,
)
from .windows_wfp_filters import (
    ADDRESS_V6,
    BLOCK,
    CLEAR_ACTION_RIGHT,
    PERMIT,
    PERSISTENT,
    SID,
    UINT8,
    UINT16,
    UINT32,
    WfpRule,
    _install_owned_filters,
    _release_owned_filters,
    _verify_owned_filters_absent,
    read_owned_filters,
)

_NAMESPACE = UUID('ef4e03a1-b0d8-4c5c-b27b-2f680c8f0276')
_BLOCK_WEIGHT = 1
_PERMIT_WEIGHT = 2
_TCP = (_PROTOCOL, UINT8, 6)
_MAX_ENDPOINTS = 16
_MAX_PLAN_BYTES = 16384
_NETWORK_PLAN = '.task-network.json'
_INSTALL_DISPATCH = '.task-network-install.json'
_ROLES = ('model', 'forward', 'control', 'application')


def _endpoints(value, *, check_mode=None):
    if type(value) is not dict or set(value) != set(_ROLES):
        raise WfpObservationError('WFP_TASK_ENDPOINT_GROUPS_REQUIRED')
    result = {}
    used = set()
    for role in _ROLES:
        endpoints = value[role]
        if check_mode is None:
            minimum, maximum = int(role in ('model', 'control')), _MAX_ENDPOINTS
        else:
            minimum = maximum = int(check_mode == 'HTTP' and role == 'application')
        if type(endpoints) is not list or not minimum <= len(endpoints) <= maximum:
            raise WfpObservationError('WFP_TASK_ENDPOINT_COUNT_DIFFERS')
        exact = []
        for endpoint in endpoints:
            if type(endpoint) is not dict or set(endpoint) != {'address', 'port'}:
                raise WfpObservationError('WFP_TASK_ENDPOINT_FIELDS_DIFFER')
            address, port = endpoint['address'], endpoint['port']
            if (
                type(address) is not str
                or address not in ('127.0.0.1', '::1')
                or type(port) is not int
                or not 1 <= port <= 65535
                or (address, port) in used
                or check_mode == 'HTTP'
                and (address != '127.0.0.1' or port < 49152)
            ):
                raise WfpObservationError('WFP_TASK_EXACT_LOOPBACK_ENDPOINT_REQUIRED')
            used.add((address, port))
            exact.append((address, port))
        result[role] = tuple(sorted(exact))
    return result


def decode_check_network(value, scope):
    mode = 'HTTP' if type(value) is dict and value.get('application') else 'CLI'
    if mode == 'HTTP' and type(scope) is not TestingLaunchScope:
        raise WfpObservationError('WFP_ORIGINAL_HTTP_TESTING_OWNER_REQUIRED')
    return _endpoints(value, check_mode=mode), mode


def _sid(directory_nonce):
    kernel, advapi = security_api()
    with _lpac_security_capabilities(task_lpac_profile(directory_nonce)) as security:
        return _sid_text(kernel, advapi, security.appcontainer_sid)


def _rules(marker, sid, endpoints):
    identity = (_PACKAGE_SID, SID, sid)
    planned = []

    def add(layer_index, rule_name, conditions, *, permit=False):
        key = uuid5(_NAMESPACE, marker.hex() + ':' + rule_name)
        layer = _REQUIRED_LAYERS[layer_index][0]
        planned.append(
            WfpRule(
                key,
                layer,
                PERMIT if permit else BLOCK,
                PERSISTENT if permit else PERSISTENT | CLEAR_ACTION_RIGHT,
                _PERMIT_WEIGHT if permit else _BLOCK_WEIGHT,
                (identity, *conditions),
            )
        )

    for index in range(len(_REQUIRED_LAYERS)):
        add(index, 'block:' + str(index), ())
    for role in _ROLES:
        for address, port in endpoints[role]:
            loopback = ip_address(address)
            v6 = loopback.version == 6
            kind = ADDRESS_V6 if v6 else UINT32
            value = loopback.packed if v6 else int(loopback)
            local_address = (_LOCAL_ADDRESS, kind, value)
            remote_address = (_REMOTE_ADDRESS, kind, value)
            token = f'{role}:{address}:{port}'
            if role in ('model', 'forward'):
                conditions = (local_address, remote_address, (_REMOTE_PORT, UINT16, port), _TCP)
                add(int(v6), 'connect:' + token, conditions, permit=True)
            else:
                listen = (local_address, (_LOCAL_PORT, UINT16, port))
                add(2 + int(v6), 'listen:' + token, listen, permit=True)
                add(4 + int(v6), 'receive:' + token, (*listen, remote_address, _TCP), permit=True)
    return tuple(planned)


@contextmanager
def _original_scope(actions, scope, epoch, provider, sublayer):
    if (
        type(actions) is not GuardActionJournal
        or not isinstance(scope, LaunchScope)
        or type(provider) is not UUID
        or provider.int == 0
        or type(sublayer) is not UUID
        or sublayer.int == 0
    ):
        raise WfpObservationError('WFP_ORIGINAL_TASK_PREPARE_REQUIRED')
    with actions._journal._scope(scope):
        original = actions.find(scope, 'PREPARE')
        if (
            original is None
            or original.owner_epoch != epoch
            or original.allocated_binding_ref is None
            or original.directory_nonce is None
        ):
            raise WfpObservationError('WFP_ORIGINAL_TASK_PREPARE_UNVERIFIED')
        marker = hashlib.sha256(
            _bytes(
                {
                    'scope': scope.key,
                    'input': original.input_sha256,
                    'binding': original.allocated_binding_ref,
                    'epoch': original.owner_epoch,
                }
            )
        ).digest()
        yield original, marker


def _plan_bytes(original, marker, endpoints, provider, sublayer, *, check_mode=None):
    payload = {
        'schema_version': 1,
        'scope': original.scope.key,
        'prepare_input_sha256': original.input_sha256,
        'owner_marker': marker.hex(),
        'provider': str(provider),
        'sublayer': str(sublayer),
        'endpoints': {
            role: [{'address': address, 'port': port} for address, port in endpoints[role]]
            for role in _ROLES
        },
    }
    if check_mode is not None:
        payload['execution_purpose'] = 'CHECK' if check_mode == 'CLI' else 'HTTP_CHECK'
    return _bytes(payload)


@contextmanager
def _original_plan(actions, request, provider, sublayer):
    if (
        type(request) is not GuardRequestHeader
        or request.action != 'PREPARE'
        or request.recovery is not None
        or request.input.get('run_kind') not in ('TASK', 'CHECK_DRIVER')
    ):
        raise WfpObservationError('WFP_ORIGINAL_TASK_PREPARE_REQUIRED')
    purpose = request.input.get('execution_purpose')
    if purpose not in (None, 'CHECK'):
        raise WfpObservationError('WFP_ORIGINAL_TASK_PURPOSE_UNVERIFIED')
    network = request.input.get('network')
    if purpose == 'CHECK':
        endpoints, mode = decode_check_network(network, request.target_scope)
        if request.input['run_kind'] == 'CHECK_DRIVER' and mode != 'CLI':
            raise WfpObservationError('WFP_ORIGINAL_DRIVER_NETWORK_MUST_BE_OFFLINE')
    elif request.input['run_kind'] == 'CHECK_DRIVER':
        raise WfpObservationError('WFP_ORIGINAL_DRIVER_PURPOSE_REQUIRED')
    else:
        endpoints, mode = _endpoints(network), None
    with _original_scope(
        actions, request.target_scope, request.owner_epoch, provider, sublayer
    ) as (original, marker):
        if original.input_sha256 != mutation_input_sha256(request):
            raise WfpObservationError('WFP_ORIGINAL_TASK_PREPARE_UNVERIFIED')
        yield (
            original,
            marker,
            endpoints,
            _plan_bytes(original, marker, endpoints, provider, sublayer, check_mode=mode),
        )


def _sealed_bytes(actions, scope, *, suffix=_NETWORK_PLAN):
    package = actions._journal._package
    name = scope.key + suffix
    target = package.path / name
    try:
        target.lstat()
    except FileNotFoundError:
        return None
    identity = package.verify_member(name, directory=False)
    with LockedFileSource(target, max_file_bytes=_MAX_PLAN_BYTES, expected_file=identity) as source:
        return source.snapshot.raw


def has_sealed_task_network(actions, scope):
    """Identify an existing private TASK scope before choosing an action handler."""
    with actions._journal._scope(scope):
        return _sealed_bytes(actions, scope) is not None


def task_network_unlaunched_after_stop(actions, scope, fence):
    return (
        fence is not None
        and fence.stop_closed
        and fence.create_state == 'NONE'
        and actions.find(scope, 'CREATE_SUSPENDED') is None
        and actions.find(scope, 'RESUME') is None
    )


def _require_network_scope_open(actions, original):
    journal = actions._journal
    journal._require_controller_open(original.scope)
    fence = journal.inspect(original.scope)
    if (
        original.scope.key in journal._volatile_closed
        or (fence is not None and fence.stop_closed)
        or actions.find(original.scope, 'STOP') is not None
    ):
        raise WfpObservationError('WFP_ORIGINAL_PLAN_STOP_CLOSED')


def _install_dispatch(raw, marker):
    return _bytes(
        {
            'schema_version': 1,
            'owner_marker': marker.hex(),
            'plan_sha256': hashlib.sha256(raw).hexdigest(),
            'phase': 'MAY_HAVE_BEEN_SENT',
        }
    )


def _publish_once(actions, original, suffix, raw):
    with PrivateRecordAppend(
        actions._journal._package,
        original.scope.key + suffix,
        raw,
        max_record_bytes=_MAX_PLAN_BYTES,
    ) as pending:
        pending.publish()


def seal_original_task_network(actions, request, *, provider, sublayer):
    """Publish one immutable Guard plan before any WFP allocation."""
    with _original_plan(actions, request, provider, sublayer) as (original, marker, _, raw):
        existing = _sealed_bytes(actions, original.scope)
        if existing is None:
            if original.phase != 'MAY_HAVE_BEEN_SENT':
                raise WfpObservationError('WFP_ORIGINAL_PLAN_CANNOT_BE_CREATED_LATE')
            with actions._journal._gate:
                _require_network_scope_open(actions, original)
                _publish_once(actions, original, _NETWORK_PLAN, raw)
            existing = _sealed_bytes(actions, original.scope)
        if existing != raw:
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS')
        return marker.hex()


def observe_original_task_network(actions, request, *, provider, sublayer):
    """Require the sealed original plan before querying any WFP filter."""
    with _original_plan(actions, request, provider, sublayer) as (original, marker, endpoints, raw):
        if _sealed_bytes(actions, original.scope) != raw:
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS')
        rules = _rules(marker, _sid(original.directory_nonce), endpoints)
        return read_owned_filters(rules, provider, sublayer, marker)


@contextmanager
def _sealed_task_plan(actions, scope, epoch, provider, sublayer):
    with _original_scope(actions, scope, epoch, provider, sublayer) as (original, marker):
        raw = _sealed_bytes(actions, original.scope)
        if raw is None:
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS')
        try:
            value = strict_json_object(raw)
            purpose = value.get('execution_purpose')
            network = value.get('endpoints')
            if purpose in ('CHECK', 'HTTP_CHECK'):
                endpoints, mode = decode_check_network(network, scope)
            else:
                endpoints, mode = _endpoints(network), None
        except (ValueError, WfpObservationError) as error:
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS') from error
        if raw != _plan_bytes(original, marker, endpoints, provider, sublayer, check_mode=mode):
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS')
        yield original, marker, endpoints, raw


def observe_sealed_task_network(actions, scope, epoch, *, provider, sublayer):
    """Read only the original sealed scope after Guard has verified caller authority."""
    with _sealed_task_plan(actions, scope, epoch, provider, sublayer) as (
        original,
        marker,
        endpoints,
        _,
    ):
        rules = _rules(marker, _sid(original.directory_nonce), endpoints)
        return read_owned_filters(rules, provider, sublayer, marker)


def original_network_install_dispatched(actions, original, marker, raw):
    dispatch = _sealed_bytes(actions, original.scope, suffix=_INSTALL_DISPATCH)
    if dispatch is None:
        return False
    if dispatch != _install_dispatch(raw, marker):
        raise WfpObservationError('WFP_ORIGINAL_INSTALL_DISPATCH_DIFFERS')
    return True


def verify_installed_task_network(
    actions, scope, epoch, *, provider, sublayer, policy_checkpoint=None, check_mode=None
):
    with _sealed_task_plan(actions, scope, epoch, provider, sublayer) as (
        original,
        marker,
        endpoints,
        raw,
    ):
        _require_network_scope_open(actions, original)
        purpose = strict_json_object(raw).get('execution_purpose')
        if {None: None, 'CHECK': 'CLI', 'HTTP_CHECK': 'HTTP'}[purpose] != check_mode:
            raise WfpObservationError('WFP_ORIGINAL_NETWORK_PURPOSE_DIFFERS')
        if not original_network_install_dispatched(actions, original, marker, raw):
            raise WfpObservationError('WFP_ORIGINAL_INSTALL_DISPATCH_REQUIRED')
        rules = _rules(marker, _sid(original.directory_nonce), endpoints)
        if policy_checkpoint is None:
            count = read_owned_filters(rules, provider, sublayer, marker)
        else:
            policy_checkpoint()
            count = read_owned_filters(
                rules, provider, sublayer, marker, check_external=True, checkpoint=policy_checkpoint
            )
            policy_checkpoint()
        with actions._journal._gate:
            _require_network_scope_open(actions, original)
        return count


def install_original_task_network(actions, request, *, provider, sublayer, cancelled):
    """Write once under the original Guard intent, then only observe original filters."""
    if current_operator_sid() != 'S-1-5-18':
        raise WfpObservationError('WFP_GUARD_SYSTEM_IDENTITY_REQUIRED')
    with _original_plan(actions, request, provider, sublayer) as (original, marker, endpoints, raw):
        _require_network_scope_open(actions, original)
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_INSTALL_INTERRUPTED')
        if _sealed_bytes(actions, original.scope) != raw:
            raise WfpObservationError('WFP_ORIGINAL_PLAN_DIFFERS')
        dispatch = _install_dispatch(raw, marker)
        dispatched = original_network_install_dispatched(actions, original, marker, raw)
        kernel, security = security_api()
        with _lpac_security_capabilities(
            task_lpac_profile(original.directory_nonce)
        ) as capabilities:
            sid_pointer = capabilities.appcontainer_sid
            rules = _rules(marker, _sid_text(kernel, security, sid_pointer), endpoints)
            if not dispatched:
                if original.phase != 'MAY_HAVE_BEEN_SENT':
                    raise WfpObservationError('WFP_ORIGINAL_INSTALL_CANNOT_START_LATE')
                with actions._journal._gate:
                    _require_network_scope_open(actions, original)
                    _publish_once(actions, original, _INSTALL_DISPATCH, dispatch)
                    if _sealed_bytes(actions, original.scope, suffix=_INSTALL_DISPATCH) != dispatch:
                        raise WfpObservationError('WFP_ORIGINAL_INSTALL_DISPATCH_UNVERIFIED')
                _install_owned_filters(
                    rules, provider, sublayer, marker, sid_pointer=sid_pointer, cancelled=cancelled
                )
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_INSTALL_INTERRUPTED')
        count = read_owned_filters(rules, provider, sublayer, marker)
        with actions._journal._gate:
            _require_network_scope_open(actions, original)
        return count


def release_unlaunched_task_network(actions, request, *, provider, sublayer, cancelled):
    """Handle only network cleanup after Guard admission and durable no-create closure."""
    return _release_task_network(actions, request, provider, sublayer, cancelled, None)


def release_stopped_task_network(actions, request, *, provider, sublayer, cancelled, native):
    from .windows_task_native_launch import TaskNativeLaunch

    if type(native) is not TaskNativeLaunch or native._scope != request.target_scope:
        raise WfpObservationError('WFP_ORIGINAL_NATIVE_STOP_REQUIRED')
    return _release_task_network(
        actions, request, provider, sublayer, cancelled, native.stopped_evidence
    )


def _release_task_network(actions, request, provider, sublayer, cancelled, verify_native_stop):
    if current_operator_sid() != 'S-1-5-18':
        raise WfpObservationError('WFP_GUARD_SYSTEM_IDENTITY_REQUIRED')
    if type(request) is not GuardRequestHeader or request.action != 'RELEASE':
        raise WfpObservationError('WFP_ORIGINAL_RELEASE_REQUIRED')
    expected_input = {}
    if request.recovery is not None:
        expected_input['recovery'] = {
            'controller_ref': request.recovery.controller_ref,
            'owner_epoch': request.recovery.owner_epoch,
        }
    if request.input != expected_input:
        raise WfpObservationError('WFP_ORIGINAL_RELEASE_REQUIRED')
    scope = request.target_scope
    epoch = request.owner_epoch if request.recovery is None else request.recovery.owner_epoch
    with _sealed_task_plan(actions, scope, epoch, provider, sublayer) as (
        original,
        marker,
        endpoints,
        raw,
    ):
        fence = actions._journal.inspect(scope)
        if request.binding_ref != original.allocated_binding_ref:
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_UNLAUNCHED_SCOPE_REQUIRED')
        if verify_native_stop is None:
            if not task_network_unlaunched_after_stop(actions, scope, fence):
                raise WfpObservationError('WFP_ORIGINAL_RELEASE_UNLAUNCHED_SCOPE_REQUIRED')
        else:
            stop = actions.find(scope, 'STOP')
            if (
                stop is None
                or stop.phase != 'ACKNOWLEDGED'
                or stop.binding_ref != request.binding_ref
            ):
                raise WfpObservationError('WFP_ORIGINAL_NATIVE_STOP_REQUIRED')
            verify_native_stop()
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_INTERRUPTED')
        dispatched = original_network_install_dispatched(actions, original, marker, raw)
        rules = _rules(marker, _sid(original.directory_nonce), endpoints)
        release = actions.begin(request)
        if release.first_accepted and dispatched:
            _release_owned_filters(rules, provider, sublayer, marker, cancelled=cancelled)
        if cancelled():
            raise WfpObservationError('WFP_ORIGINAL_RELEASE_INTERRUPTED')
        _verify_owned_filters_absent(rules, provider, sublayer, marker)
        if verify_native_stop is not None:
            verify_native_stop()
        return True
