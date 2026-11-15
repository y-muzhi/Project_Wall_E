"""WFP install ABI and transaction tests without any machine policy write."""

import ctypes
from uuid import UUID, uuid4

import pytest

from backend.app.infrastructure import guard_task_network as network
from backend.app.infrastructure import windows_wfp as wfp
from backend.app.infrastructure import windows_wfp_filters as filters
from backend.tests.infrastructure.test_v20_guard_task_network import input_network
from backend.tests.infrastructure.test_v20_windows_wfp import Engine


@pytest.mark.parametrize(
    'outcome', ['success', 'add_failed', 'commit_unknown', 'cancel', 'wrong_sublayer']
)
def test_wfp_add_all_persistent_rules_in_one_original_transaction(monkeypatch, outcome):
    engine = Engine()
    provider, sublayer = uuid4(), uuid4()
    marker = b'private-owner-marker-01234567890'
    rules = None
    kernel, security = filters.security_api()
    row = filters._SubLayer()
    row.key = filters._guid(sublayer)
    row.provider = ctypes.pointer(
        filters._guid(provider if outcome != 'wrong_sublayer' else uuid4())
    )
    row.flags = filters.PERSISTENT
    added = []

    def begin(handle, flags):
        assert handle.value == 23 and flags == 0
        engine.events.append('WRITE_BEGIN')
        return 0

    def sublayer_read(handle, key, result):
        assert handle.value == 23 and bytes(key._obj) == sublayer.bytes_le
        ctypes.cast(result, ctypes.POINTER(ctypes.POINTER(filters._SubLayer)))[0] = ctypes.pointer(
            row
        )
        engine.events.append('SUBLAYER')
        return 0

    def add(handle, native, descriptor, result):
        assert handle.value == 23 and descriptor.value
        engine.events.append('ADD')
        current = native._obj
        expected = rules[len(added)]
        if outcome == 'add_failed' and added:
            return 5
        current.id = len(added) + 1
        current.effective_weight = current.weight
        assert (
            filters._verify_filter(
                current,
                expected,
                provider,
                sublayer,
                marker,
                lambda sid: filters._sid_text(kernel, security, sid),
            )
            == current.id
        )
        result._obj.value = current.id
        added.append(expected.key)
        return 0

    def commit(handle):
        assert handle.value == 23
        assert added == [rule.key for rule in rules]
        engine.events.append('COMMIT')
        return 1726 if outcome == 'commit_unknown' else 0

    engine.FwpmTransactionBegin0 = begin
    engine.FwpmSubLayerGetByKey0 = sublayer_read
    engine.FwpmFilterAdd0 = add
    engine.FwpmTransactionCommit0 = commit
    monkeypatch.setattr(wfp, '_api', lambda: engine)
    with network._lpac_security_capabilities('walle-win20-' + uuid4().hex) as capability:
        pointer = capability.appcontainer_sid
        sid = filters._sid_text(kernel, security, pointer)
        rules = network._rules(marker, sid, network._endpoints(input_network()['network']))

        def invoke():
            filters._install_owned_filters(
                rules,
                provider,
                sublayer,
                marker,
                sid_pointer=pointer,
                cancelled=lambda: outcome == 'cancel' and len(added) == 1,
            )

        if outcome == 'success':
            invoke()
        else:
            expected_error = {
                'add_failed': 'RULE_ADD_UNVERIFIED',
                'commit_unknown': 'COMMIT_RESULT_UNKNOWN',
                'cancel': 'INSTALL_INTERRUPTED',
                'wrong_sublayer': 'SUBLAYER_DIFFERS',
            }[outcome]
            with pytest.raises(wfp.WfpObservationError, match=expected_error):
                invoke()

    assert engine.events[:3] == ['OPEN', 'WRITE_BEGIN', 'SUBLAYER']
    assert engine.events.count('WRITE_BEGIN') == 1
    if outcome in ('success', 'commit_unknown'):
        assert engine.events[-2:] == ['COMMIT', 'CLOSE']
        assert 'ABORT' not in engine.events
        assert len(added) == 12
    else:
        assert engine.events[-2:] == ['ABORT', 'CLOSE']
        assert 'COMMIT' not in engine.events
        assert len(added) == (0 if outcome == 'wrong_sublayer' else 1)


@pytest.mark.parametrize(
    'outcome',
    [
        'clean',
        'foreign',
        'same_sid',
        'wildcard',
        'missing',
        'duplicate',
        'read_error',
        'external_soft_permit',
        'external_hard_permit',
        'external_callout',
        'external_other_package',
        'external_disabled',
        'external_unknown',
        'redirect_callout',
        'redirect_other_package',
        'redirect_read_denied',
        'release',
        'release_partial',
        'release_wrong_owner',
        'release_delete_failed',
        'release_unknown',
    ],
)
def test_owned_filter_inventory_and_release_share_native_transaction(monkeypatch, outcome):
    engine = Engine()
    provider, sublayer = uuid4(), uuid4()
    marker = b'private-owner-marker-01234567890'
    kernel, security = filters.security_api()
    rows = {}
    by_layer = {}
    active = {}
    retained = []
    target_layer = wfp._REQUIRED_LAYERS[0][0]
    sublayer_row = filters._SubLayer()
    sublayer_row.key = filters._guid(sublayer)
    sublayer_row.flags = filters.PERSISTENT
    sublayer_row.provider = ctypes.pointer(filters._guid(provider))
    pending = []

    def read_sublayer(handle, key, result):
        assert handle.value == 23 and bytes(key._obj) == sublayer.bytes_le
        output = ctypes.cast(result, ctypes.POINTER(ctypes.POINTER(filters._SubLayer)))
        output[0] = ctypes.pointer(sublayer_row)
        return 0

    def read_redirect_layer(handle, key, out):
        assert handle.value == 23
        layer = UUID(bytes_le=bytes(key._obj))
        assert layer in wfp._REDIRECT_LAYERS
        if outcome == 'redirect_read_denied':
            return 5
        field = filters._guid(wfp._PACKAGE_SID)
        fields = (wfp._Field * 1)(wfp._Field(ctypes.pointer(field), 0, 0))
        row = wfp._Layer()
        row.key = key._obj
        row.flags = wfp.FWPM_LAYER_BUILTIN_KERNEL
        row.field_count = 1
        row.fields = fields
        row.id = wfp._REDIRECT_LAYERS.index(layer) + 40
        retained.append((field, fields, row))
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(wfp._Layer)))[0] = ctypes.pointer(row)
        return 0

    def begin(handle, flags):
        assert handle.value == 23 and flags in (0, 1)
        engine.events.append('BEGIN' if flags == 1 else 'WRITE_BEGIN')
        return 0

    def delete(handle, key):
        assert handle.value == 23
        identity = UUID(bytes_le=bytes(key._obj))
        assert identity in rows and identity not in pending and not active
        engine.events.append('DELETE')
        if outcome == 'release_delete_failed' and pending:
            return 5
        pending.append(identity)
        return 0

    def commit(handle):
        assert handle.value == 23 and len(pending) == len(rows) == 12
        engine.events.append('COMMIT')
        rows.clear()
        by_layer.clear()
        return 1726 if outcome == 'release_unknown' else 0

    def get(handle, key, out):
        assert handle.value == 23
        engine.events.append('GET')
        rule = rows.get(UUID(bytes_le=bytes(key._obj)))
        if rule is None:
            return filters._FILTER_NOT_FOUND
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(filters._Filter)))[0] = ctypes.pointer(rule)
        return 0

    def create(handle, template, result):
        assert handle.value == 23
        query = template._obj
        assert not query.provider and query.action_mask == 0xFFFFFFFF and query.flags == 0x18
        assert not active
        active[17] = UUID(bytes_le=bytes(query.layer))
        result._obj.value = 17
        engine.events.append('ENUM_CREATE')
        return 0

    def enum_page(handle, cursor, limit, out, count):
        assert handle.value == 23 and cursor.value in active and limit == 64
        layer = active[cursor.value]
        engine.events.append('ENUM_READ')
        if outcome == 'read_error' and layer == target_layer:
            return 5
        page = (ctypes.POINTER(filters._Filter) * len(by_layer.get(layer, ())))(
            *(ctypes.pointer(row) for row in by_layer.get(layer, ()))
        )
        retained.append(page)
        ctypes.cast(out, ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(filters._Filter))))[0] = (
            ctypes.cast(page, ctypes.POINTER(ctypes.POINTER(filters._Filter)))
        )
        count._obj.value = len(page)
        return 0

    def destroy(handle, cursor):
        assert handle.value == 23 and active.pop(cursor.value) is not None
        engine.events.append('ENUM_DESTROY')
        return 0

    engine.FwpmLayerGetByKey0 = read_redirect_layer
    engine.FwpmFilterGetByKey0 = get
    engine.FwpmSubLayerGetByKey0 = read_sublayer
    engine.FwpmTransactionBegin0 = begin
    engine.FwpmTransactionCommit0 = commit
    engine.FwpmFilterDeleteByKey0 = delete
    engine.FwpmFilterCreateEnumHandle0 = create
    engine.FwpmFilterEnum0 = enum_page
    engine.FwpmFilterDestroyEnumHandle0 = destroy
    monkeypatch.setattr(wfp, '_api', lambda: engine)
    with (
        network._lpac_security_capabilities('walle-win20-' + uuid4().hex) as original,
        network._lpac_security_capabilities('walle-win20-' + uuid4().hex) as foreign,
    ):
        pointer = original.appcontainer_sid
        sid = filters._sid_text(kernel, security, pointer)
        rules = network._rules(marker, sid, network._endpoints(input_network()['network']))
        for identity, rule in enumerate(rules, 1):
            row = filters._native_filter(rule, provider, sublayer, marker, pointer, sid)
            row.id = identity
            row.effective_weight = row.weight
            rows[rule.key] = row
            by_layer.setdefault(rule.layer, []).append(row)
        target = by_layer[target_layer]
        if outcome.startswith('release'):
            if outcome == 'release_partial':
                del rows[rules[-1].key]
            elif outcome == 'release_wrong_owner':
                rows[rules[-1].key].provider = ctypes.pointer(filters._guid(uuid4()))

            def release():
                filters._release_owned_filters(
                    rules, provider, sublayer, marker, cancelled=lambda: False
                )

            if outcome == 'release':
                release()
            else:
                failure = {
                    'release_partial': 'RELEASE_RULE_GROUP_INCOMPLETE',
                    'release_wrong_owner': 'RULE_DIFFERS',
                    'release_delete_failed': 'RULE_DELETE_UNVERIFIED',
                    'release_unknown': 'COMMIT_RESULT_UNKNOWN',
                }[outcome]
                with pytest.raises(wfp.WfpObservationError, match=failure):
                    release()
            assert engine.events[:2] == ['OPEN', 'WRITE_BEGIN']
            if outcome in ('release', 'release_unknown'):
                assert len(pending) == 12 and engine.events[-2:] == ['COMMIT', 'CLOSE']
                filters._verify_owned_filters_absent(rules, provider, sublayer, marker)
                assert engine.events.count('WRITE_BEGIN') == 1
                assert engine.events.count('BEGIN') == 1
            else:
                assert 'COMMIT' not in engine.events
                assert len(pending) == int(outcome == 'release_delete_failed')
                assert engine.events[-2:] == ['ABORT', 'CLOSE']
            return
        if outcome in ('foreign', 'same_sid', 'wildcard'):
            foreign_pointer = foreign.appcontainer_sid if outcome == 'foreign' else pointer
            subject = filters._sid_text(kernel, security, foreign_pointer)
            rule = network._rules(
                b'different-owner', subject, network._endpoints(input_network()['network'])
            )[0]
            extra = filters._native_filter(
                rule, provider, sublayer, marker, foreign_pointer, subject
            )
            if outcome == 'wildcard':
                extra.count = 0
            target.append(extra)
        elif outcome.startswith('external'):
            foreign_pointer = (
                foreign.appcontainer_sid if outcome == 'external_other_package' else pointer
            )
            subject = filters._sid_text(kernel, security, foreign_pointer)
            rule = network._rules(
                b'external', subject, network._endpoints(input_network()['network'])
            )[0]
            extra = filters._native_filter(
                rule, provider, uuid4(), marker, foreign_pointer, subject
            )
            extra.action.kind = {
                'external_callout': 0x5003,
                'external_unknown': 0xFFFF,
            }.get(outcome, filters.PERMIT)
            extra.flags = 0 if outcome == 'external_soft_permit' else filters.CLEAR_ACTION_RIGHT
            if outcome == 'external_disabled':
                extra.flags |= filters._DISABLED
            target.append(extra)
        elif outcome in ('redirect_callout', 'redirect_other_package'):
            redirect = wfp._REDIRECT_LAYERS[-1]
            foreign_pointer = (
                foreign.appcontainer_sid if outcome == 'redirect_other_package' else pointer
            )
            subject = filters._sid_text(kernel, security, foreign_pointer)
            rule = network._rules(
                b'redirect', subject, network._endpoints(input_network()['network'])
            )[0]
            extra = filters._native_filter(
                rule, provider, uuid4(), marker, foreign_pointer, subject
            )
            extra.layer = filters._guid(redirect)
            extra.action.kind = 0x5003
            by_layer[redirect] = [extra]
        elif outcome == 'missing':
            target.pop()
        elif outcome == 'duplicate':
            target.append(target[0])

        def read():
            return filters.read_owned_filters(
                rules,
                provider,
                sublayer,
                marker,
                check_external=outcome.startswith(('external', 'redirect')),
            )

        if outcome in (
            'clean',
            'foreign',
            'external_soft_permit',
            'external_other_package',
            'external_disabled',
            'redirect_other_package',
        ):
            assert read() == 12
            expected_layers = 10 if outcome.startswith(('external', 'redirect')) else 6
            assert engine.events.count('ENUM_DESTROY') == expected_layers
        else:
            failure = {
                'same_sid': 'INVENTORY_HAS_EXTRA_RULE',
                'wildcard': 'INVENTORY_HAS_EXTRA_RULE',
                'missing': 'INVENTORY_INCOMPLETE',
                'duplicate': 'INVENTORY_REPEATED_RULE',
                'read_error': 'INVENTORY_UNAVAILABLE',
                'external_hard_permit': 'EXTERNAL_ARBITRATION_UNVERIFIED',
                'external_callout': 'EXTERNAL_ARBITRATION_UNVERIFIED',
                'external_unknown': 'EXTERNAL_ARBITRATION_UNVERIFIED',
                'redirect_callout': 'EXTERNAL_ARBITRATION_UNVERIFIED',
                'redirect_read_denied': 'ALE_LAYER_UNAVAILABLE',
            }[outcome]
            with pytest.raises(wfp.WfpObservationError, match=failure):
                read()

    assert engine.events[:2] == ['OPEN', 'BEGIN']
    assert engine.events.count('GET') == 12
    assert engine.events[-3:] == ['ENUM_DESTROY', 'ABORT', 'CLOSE']
    assert not active
