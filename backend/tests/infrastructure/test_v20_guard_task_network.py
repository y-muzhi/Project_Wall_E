"""Original TASK PREPARE identity and in-memory native WFP rule read-back."""

import ctypes
from uuid import uuid4

import pytest

from backend.app.infrastructure import guard_task_network as network
from backend.app.infrastructure import windows_wfp_filters as filters
from backend.app.infrastructure.guard_action_journal import GuardActionJournal
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal, LaunchOutcomeUnknown
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.test_v20_guard_action_journal import packet
from backend.tests.infrastructure.test_v20_guard_recovery import facts


@pytest.fixture
def context(tmp_path):
    binding = facts()[0].binding
    with LaunchJournal(create_private_package(tmp_path / 'task-network')) as journal:
        yield GuardActionJournal(journal), journal, binding, packet(binding)


def input_network():
    return {
        'run_kind': 'TASK',
        'network': {
            'model': [{'address': '127.0.0.1', 'port': 42000}],
            'forward': [{'address': '::1', 'port': 42001}],
            'control': [{'address': '127.0.0.1', 'port': 42002}],
            'application': [{'address': '::1', 'port': 42003}],
        },
    }


def test_original_durable_scope_bounds_sid_and_filter_identity(context, monkeypatch):
    actions, _, binding, _ = context
    original = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    sightings = []

    def read(rules, actual_provider, actual_sublayer, marker):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        sightings.append((rules, marker))
        return len(rules)

    monkeypatch.setattr(network, 'read_owned_filters', read)
    with pytest.raises(network.WfpObservationError, match='PREPARE_UNVERIFIED'):
        network.observe_original_task_network(
            actions, original, provider=provider, sublayer=sublayer
        )
    original_record = actions.begin(original).record
    with pytest.raises(network.WfpObservationError, match='PLAN_DIFFERS'):
        network.observe_original_task_network(
            actions, original, provider=provider, sublayer=sublayer
        )
    original_marker = network.seal_original_task_network(
        actions, original, provider=provider, sublayer=sublayer
    )
    assert (
        network.seal_original_task_network(actions, original, provider=provider, sublayer=sublayer)
        == original_marker
    )
    with pytest.raises(network.WfpObservationError, match='PLAN_DIFFERS'):
        network.seal_original_task_network(actions, original, provider=provider, sublayer=uuid4())
    assert len(list(actions._journal.root.glob('*.task-network.json'))) == 1
    for _ in range(2):
        assert (
            network.observe_original_task_network(
                actions, original, provider=provider, sublayer=sublayer
            )
            == 12
        )
    assert sightings[0] == sightings[1]
    rules, marker = sightings[0]
    assert len(marker) == 32 and len({rule.key for rule in rules}) == 12
    assert len({rule.layer for rule in rules}) == 6
    sid = network._sid(original_record.directory_nonce)
    assert sid.startswith('S-1-15-2-')
    for rule in rules:
        assert rule.conditions[0] == (network._PACKAGE_SID, filters.SID, sid)
        if rule.action == filters.BLOCK:
            assert len(rule.conditions) == 1
            assert rule.weight == 1 and rule.flags == 9
        else:
            assert rule.weight == 2 and rule.flags == 1
    listen_keys = {entry[0] for entry in network._REQUIRED_LAYERS[2:4]}
    assert all(network._TCP not in rule.conditions for rule in rules if rule.layer in listen_keys)
    other_input = input_network()
    other_input['network']['model'][0]['port'] = 43000
    modified = packet(binding, action_input=other_input)
    with pytest.raises(network.WfpObservationError, match='PREPARE_UNVERIFIED'):
        network.observe_original_task_network(
            actions, modified, provider=provider, sublayer=sublayer
        )
    assert len(sightings) == 2
    other_scope = packet(binding, number=18, action_input=input_network())
    actions.begin(other_scope)
    network.seal_original_task_network(actions, other_scope, provider=provider, sublayer=sublayer)
    network.observe_original_task_network(
        actions, other_scope, provider=provider, sublayer=sublayer
    )
    assert sightings[-1][1] != marker
    assert {rule.key for rule in rules}.isdisjoint({rule.key for rule in sightings[-1][0]})
    assert sightings[-1][0][0].conditions[0][2] != sid


@pytest.mark.parametrize(
    ('address', 'port'),
    [('0.0.0.0', 42000), ('::ffff:127.0.0.1', 42000), ('127.0.0.1', True), ('::1', 65536)],
)
def test_network_never_accepts_wildcard_alias_or_invalid_port(address, port):
    raw = input_network()['network']
    raw['model'] = [{'address': address, 'port': port}]
    with pytest.raises(network.WfpObservationError, match='EXACT_LOOPBACK'):
        network._endpoints(raw)


def guid(value):
    return filters._Guid.from_buffer_copy(value.bytes_le)


@pytest.mark.parametrize('rule_index', [-1, -3])
def test_native_readback_detects_changes_to_action_weights_owner_or_match(rule_index):
    marker = b'M' * 32
    provider, sublayer = uuid4(), uuid4()
    sid = 'S-1-15-2-example'
    rule = network._rules(marker, sid, network._endpoints(input_network()['network']))[rule_index]
    row = filters._Filter()
    row.key, row.layer, row.sublayer = guid(rule.key), guid(rule.layer), guid(sublayer)
    row.provider = ctypes.pointer(guid(provider))
    data = ctypes.create_string_buffer(marker)
    row.provider_data = filters._Blob(len(marker), ctypes.cast(data, ctypes.c_void_p))
    row.flags = rule.flags
    row.action.kind = rule.action
    row.id = 42
    row.weight.kind = row.effective_weight.kind = filters.UINT64
    row.weight.data.uint64 = ctypes.pointer(ctypes.c_uint64(rule.weight))
    row.effective_weight.data.uint64 = ctypes.pointer(ctypes.c_uint64(rule.weight))
    rows = (filters._Condition * len(rule.conditions))()
    for index, (key, kind, value) in enumerate(reversed(rule.conditions)):
        row_condition = rows[index]
        row_condition.field = guid(key)
        row_condition.value.kind = kind
        if kind == filters.SID:
            row_condition.value.data.sid = 123
        elif kind == filters.ADDRESS_V6:
            row_condition.value.data.address_v6 = ctypes.pointer((ctypes.c_ubyte * 16)(*value))
        elif kind == filters.UINT8:
            row_condition.value.data.uint8 = value
        elif kind == filters.UINT16:
            row_condition.value.data.uint16 = value
        elif kind == filters.UINT32:
            row_condition.value.data.uint32 = value
        else:
            pytest.fail('Unexpected fixture type')
    row.conditions, row.count = rows, len(rows)

    def verify(actual_provider=provider):
        return filters._verify_filter(row, rule, actual_provider, sublayer, marker, lambda _: sid)

    assert verify() == 42
    with pytest.raises(network.WfpObservationError, match='RULE_DIFFERS'):
        verify(uuid4())
    row.action.kind = filters.BLOCK
    with pytest.raises(network.WfpObservationError, match='RULE_DIFFERS'):
        verify()
    row.action.kind = rule.action
    row.effective_weight.data.uint64.contents.value = rule.weight + 1
    with pytest.raises(network.WfpObservationError, match='WEIGHT_DIFFERS'):
        verify()
    row.effective_weight.data.uint64.contents.value = rule.weight
    rows[0].match = 1
    with pytest.raises(network.WfpObservationError, match='MATCH_DIFFERS'):
        verify()
    rows[0].match = 0
    rows[0].value.data.uint8 = 17
    with pytest.raises(network.WfpObservationError, match='CONDITIONS_DIFFER'):
        verify()


def test_confirmed_preparation_cannot_retroactively_seal_a_new_plan(context):
    actions, _, binding, _ = context
    request = packet(binding, action_input=input_network())
    original = actions.begin(request).record
    actions.acknowledge(original, {'binding_ref': original.allocated_binding_ref})
    with pytest.raises(network.WfpObservationError, match='CANNOT_BE_CREATED_LATE'):
        network.seal_original_task_network(actions, request, provider=uuid4(), sublayer=uuid4())
    assert not list(actions._journal.root.glob('*.task-network.json'))


def test_real_wfp_refuses_uninstalled_rules_even_with_original_private_plan(context):
    actions, _, binding, _ = context
    request = packet(binding, action_input=input_network())
    actions.begin(request)
    provider, sublayer = uuid4(), uuid4()
    network.seal_original_task_network(actions, request, provider=provider, sublayer=sublayer)
    with pytest.raises(network.WfpObservationError) as error:
        network.observe_original_task_network(
            actions, request, provider=provider, sublayer=sublayer
        )
    assert str(error.value) in {
        'WFP_LOCAL_ENGINE_UNAVAILABLE',
        'WFP_READ_TRANSACTION_UNAVAILABLE',
        'WFP_ORIGINAL_RULE_UNAVAILABLE',
    }
    assert error.value.native_error in (5, 0x80320003)


@pytest.mark.parametrize('fence_only', [True, False])
def test_stop_closes_original_scope_before_new_network_plan(context, fence_only):
    actions, journal, binding, _ = context
    request = packet(binding, action_input=input_network())
    actions.begin(request)
    if fence_only:
        journal.close_nonce(request.scope)
    else:
        actions.begin(packet(binding, action='STOP', action_input={}))
    with pytest.raises(network.WfpObservationError, match='PLAN_STOP_CLOSED'):
        network.seal_original_task_network(actions, request, provider=uuid4(), sublayer=uuid4())
    assert not list(journal.root.glob('*.task-network.json'))


def test_after_restart_only_original_sealed_epoch_and_deployment_are_read(tmp_path, monkeypatch):
    binding = facts()[0].binding
    request = packet(binding, action_input=input_network())
    root = create_private_package(tmp_path / 'restart-network')
    provider, sublayer = uuid4(), uuid4()
    seen = []

    def read(rules, actual_provider, actual_sublayer, marker):
        seen.append((rules, actual_provider, actual_sublayer, marker))
        return len(rules)

    monkeypatch.setattr(network, 'read_owned_filters', read)
    with LaunchJournal(root) as first:
        actions = GuardActionJournal(first)
        actions.begin(request)
        network.seal_original_task_network(actions, request, provider=provider, sublayer=sublayer)
        assert (
            network.observe_original_task_network(
                actions, request, provider=provider, sublayer=sublayer
            )
            == 12
        )
    with LaunchJournal(root) as reopened:
        actions = GuardActionJournal(reopened)
        with pytest.raises(network.WfpObservationError, match='PREPARE_UNVERIFIED'):
            network.observe_sealed_task_network(
                actions, request.scope, str(uuid4()), provider=provider, sublayer=sublayer
            )
        with pytest.raises(network.WfpObservationError, match='PLAN_DIFFERS'):
            network.observe_sealed_task_network(
                actions, request.scope, request.owner_epoch, provider=uuid4(), sublayer=sublayer
            )
        assert (
            network.observe_sealed_task_network(
                actions, request.scope, request.owner_epoch, provider=provider, sublayer=sublayer
            )
            == 12
        )
        assert len(list(reopened.root.glob('*.task-network.json'))) == 1
    assert seen[0] == seen[1] and len(seen) == 2


@pytest.mark.parametrize('outcome', ['success', 'lost_commit', 'lost_readback'])
def test_guard_install_uses_durable_one_shot_then_only_observes(context, monkeypatch, outcome):
    actions, journal, binding, _ = context
    request = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    actions.begin(request)
    marker = network.seal_original_task_network(
        actions, request, provider=provider, sublayer=sublayer
    )
    events = []
    frozen = []

    def install(rules, actual_provider, actual_sublayer, owner, *, sid_pointer, cancelled):
        assert sid_pointer and not cancelled()
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert owner.hex() == marker
        assert len(list(journal.root.glob('*.task-network-install.json'))) == 1
        frozen.append(rules)
        events.append('INSTALL')
        if outcome == 'lost_commit':
            raise network.WfpObservationError('WFP_ORIGINAL_COMMIT_RESULT_UNKNOWN')

    def observe(rules, actual_provider, actual_sublayer, owner):
        assert (actual_provider, actual_sublayer) == (provider, sublayer)
        assert owner.hex() == marker and frozen == [rules]
        events.append('READ')
        if outcome == 'lost_readback' and events.count('READ') == 1:
            raise network.WfpObservationError('WFP_ORIGINAL_RULE_UNAVAILABLE')
        return len(rules)

    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(network, '_install_owned_filters', install)
    monkeypatch.setattr(network, 'read_owned_filters', observe)

    def invoke(cancelled=lambda: False):
        return network.install_original_task_network(
            actions, request, provider=provider, sublayer=sublayer, cancelled=cancelled
        )

    def verify():
        return network.verify_installed_task_network(
            actions, request.scope, request.owner_epoch, provider=provider, sublayer=sublayer
        )

    with pytest.raises(network.WfpObservationError, match='INSTALL_DISPATCH_REQUIRED'):
        verify()
    assert not events
    with pytest.raises(network.WfpObservationError, match='INSTALL_INTERRUPTED'):
        invoke(lambda: True)
    assert not list(journal.root.glob('*.task-network-install.json'))
    if outcome == 'success':
        assert invoke() == 12
    else:
        with pytest.raises(network.WfpObservationError):
            invoke()
    assert invoke() == 12
    assert events == (
        ['INSTALL', 'READ'] if outcome == 'lost_commit' else ['INSTALL', 'READ', 'READ']
    )
    assert verify() == 12
    assert events[-1] == 'READ'
    journal.close_nonce(request.scope)
    with pytest.raises(network.WfpObservationError, match='PLAN_STOP_CLOSED'):
        verify()
    with pytest.raises(network.WfpObservationError, match='PLAN_STOP_CLOSED'):
        invoke()


def test_non_guard_identity_cannot_write_or_reserve_wfp_dispatch(context, monkeypatch):
    actions, journal, binding, _ = context
    request = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    actions.begin(request)
    network.seal_original_task_network(actions, request, provider=provider, sublayer=sublayer)
    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-21-1-2-3-1000')
    with pytest.raises(network.WfpObservationError, match='SYSTEM_IDENTITY_REQUIRED'):
        network.install_original_task_network(
            actions, request, provider=provider, sublayer=sublayer, cancelled=lambda: False
        )
    assert not list(journal.root.glob('*.task-network-install.json'))


def test_failed_durable_stop_blocks_network_install_in_current_guard(context, monkeypatch):
    actions, journal, binding, _ = context
    prepare = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    actions.begin(prepare)
    network.seal_original_task_network(actions, prepare, provider=provider, sublayer=sublayer)

    def fail_to_save(*_):
        raise OSError('fixture refuses durable STOP')

    with monkeypatch.context() as fixture:
        fixture.setattr(journal, '_save', fail_to_save)
        with pytest.raises(OSError, match='durable STOP'):
            journal.close_nonce(prepare.scope)
    assert journal.inspect(prepare.scope) is None
    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-18')
    with pytest.raises(network.WfpObservationError, match='PLAN_STOP_CLOSED'):
        network.install_original_task_network(
            actions, prepare, provider=provider, sublayer=sublayer, cancelled=lambda: False
        )
    assert not list(journal.root.glob('*.task-network-install.json'))


@pytest.mark.parametrize('outcome', ['success', 'commit_unknown', 'no_install', 'create_unknown'])
def test_release_unlaunched_network_mutates_once_after_original_closure(
    context, monkeypatch, outcome
):
    actions, journal, binding, _ = context
    prepare = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    original = actions.begin(prepare).record
    marker = network.seal_original_task_network(
        actions, prepare, provider=provider, sublayer=sublayer
    )
    events = []
    frozen = []

    def install(rules, *_, **__):
        frozen.extend(rules)

    def remove(rules, actual_provider, actual_sublayer, owner, *, cancelled):
        assert not cancelled() and list(rules) == frozen
        assert (actual_provider, actual_sublayer, owner.hex()) == (provider, sublayer, marker)
        assert actions.find(prepare.scope, 'RELEASE').phase == 'MAY_HAVE_BEEN_SENT'
        events.append('DELETE')
        if outcome == 'commit_unknown':
            raise network.WfpObservationError('WFP_ORIGINAL_COMMIT_RESULT_UNKNOWN')

    def observe_absence(rules, actual_provider, actual_sublayer, owner):
        assert (actual_provider, actual_sublayer, owner.hex()) == (provider, sublayer, marker)
        assert outcome == 'no_install' or list(rules) == frozen
        events.append('ABSENT')

    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(network, '_install_owned_filters', install)
    monkeypatch.setattr(network, 'read_owned_filters', lambda rules, *_: len(rules))
    monkeypatch.setattr(network, '_release_owned_filters', remove)
    monkeypatch.setattr(network, '_verify_owned_filters_absent', observe_absence)

    release = packet(
        binding, action='RELEASE', binding_ref=original.allocated_binding_ref, action_input={}
    )

    def invoke(request=release):
        return network.release_unlaunched_task_network(
            actions, request, provider=provider, sublayer=sublayer, cancelled=lambda: False
        )

    if outcome != 'no_install':
        network.install_original_task_network(
            actions, prepare, provider=provider, sublayer=sublayer, cancelled=lambda: False
        )
    with pytest.raises(network.WfpObservationError, match='UNLAUNCHED_SCOPE_REQUIRED'):
        invoke()
    if outcome == 'create_unknown':
        actions.acknowledge(original, {'binding_ref': original.allocated_binding_ref})
        journal.prepare(prepare.scope, original.input_sha256)
        actions.begin(
            packet(
                binding,
                action='CREATE_SUSPENDED',
                binding_ref=original.allocated_binding_ref,
                action_input={},
            )
        )
    journal.close_nonce(prepare.scope)
    with pytest.raises(network.WfpObservationError, match='UNLAUNCHED_SCOPE_REQUIRED'):
        invoke(packet(binding, action='RELEASE', binding_ref=uuid4().hex, action_input={}))
    if outcome == 'create_unknown':
        with pytest.raises(network.WfpObservationError, match='UNLAUNCHED_SCOPE_REQUIRED'):
            invoke()
        assert not events and actions.find(prepare.scope, 'RELEASE') is None
        return
    if outcome == 'commit_unknown':
        with pytest.raises(network.WfpObservationError, match='COMMIT_RESULT_UNKNOWN'):
            invoke()
        assert events == ['DELETE']
    else:
        assert invoke()
    assert invoke()
    assert (
        events
        == {
            'success': ['DELETE', 'ABSENT', 'ABSENT'],
            'commit_unknown': ['DELETE', 'ABSENT'],
            'no_install': ['ABSENT', 'ABSENT'],
        }[outcome]
    )
    assert actions.find(prepare.scope, 'RELEASE').phase == 'MAY_HAVE_BEEN_SENT'


def test_controller_close_before_network_dispatch_blocks_install(context, monkeypatch):
    actions, journal, binding, _ = context
    prepare = packet(binding, action_input=input_network())
    provider, sublayer = uuid4(), uuid4()
    actions.begin(prepare)
    network.seal_original_task_network(actions, prepare, provider=provider, sublayer=sublayer)
    native_sid_text = network._sid_text

    def close_controller_while_deriving_sid(*args):
        journal._volatile_closed_controllers.add(prepare.scope.controller_ref)
        return native_sid_text(*args)

    monkeypatch.setattr(network, 'current_operator_sid', lambda: 'S-1-5-18')
    monkeypatch.setattr(network, '_sid_text', close_controller_while_deriving_sid)
    with pytest.raises(LaunchOutcomeUnknown, match='CONTROLLER_CLOSURE_UNVERIFIED'):
        network.install_original_task_network(
            actions, prepare, provider=provider, sublayer=sublayer, cancelled=lambda: False
        )
    assert not list(journal.root.glob('*.task-network-install.json'))


def test_offline_project_check_binds_only_block_rules_to_its_original_sid(context, monkeypatch):
    actions, _, binding, _ = context
    provider, sublayer = uuid4(), uuid4()
    endpoints = {role: [] for role in network._ROLES}
    original = packet(
        binding,
        action_input={'run_kind': 'TASK', 'execution_purpose': 'CHECK', 'network': endpoints},
    )
    record = actions.begin(original).record
    marker = network.seal_original_task_network(
        actions, original, provider=provider, sublayer=sublayer
    )
    assert len(marker) == 64
    expected_sid = network._sid(record.directory_nonce)

    def read(rules, actual_provider, actual_sublayer, actual_marker, **options):
        assert (actual_provider, actual_sublayer, actual_marker.hex()) == (
            provider,
            sublayer,
            marker,
        )
        assert len(rules) == len(network._REQUIRED_LAYERS)
        assert all(
            rule.action == filters.BLOCK
            and rule.conditions == ((network._PACKAGE_SID, filters.SID, expected_sid),)
            for rule in rules
        )
        return len(rules)

    monkeypatch.setattr(network, 'read_owned_filters', read)
    with pytest.raises(network.WfpObservationError, match='INSTALL_DISPATCH_REQUIRED'):
        network.verify_installed_task_network(
            actions,
            original.scope,
            binding.owner_epoch,
            provider=provider,
            sublayer=sublayer,
            check_mode='CLI',
        )
    raw = network._sealed_bytes(actions, original.scope)
    network._publish_once(
        actions,
        record,
        network._INSTALL_DISPATCH,
        network._install_dispatch(raw, bytes.fromhex(marker)),
    )
    with pytest.raises(network.WfpObservationError, match='NETWORK_PURPOSE_DIFFERS'):
        network.verify_installed_task_network(
            actions, original.scope, binding.owner_epoch, provider=provider, sublayer=sublayer
        )
    assert (
        network.verify_installed_task_network(
            actions,
            original.scope,
            binding.owner_epoch,
            provider=provider,
            sublayer=sublayer,
            check_mode='CLI',
        )
        == 6
    )
    for role in endpoints:
        invalid = {**endpoints, role: [{'address': '127.0.0.1', 'port': 5173}]}
        with pytest.raises(network.WfpObservationError, match='COUNT_DIFFERS'):
            network._endpoints(invalid, check_mode='CLI')
