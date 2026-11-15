"""Original bootstrap plan, real NTFS leases and mutable-parent rejection."""

from hashlib import sha256
from threading import Event

import pytest

from backend.app.infrastructure.runtime_launch_journal import _bytes
from backend.app.infrastructure.windows_access_check import NativeAccessError
from backend.tests.infrastructure import test_v20_guard_bootstrap_preparation as preparations
from backend.tests.infrastructure import test_v20_windows_controller_token as controller_fixtures
from tools import windows_guard_inspection as inspection

programs = preparations.programs
prepared = preparations.prepared
tmp_path = preparations.tmp_path
controller = controller_fixtures.controller
ordinary_controller = controller_fixtures.ordinary_controller


@pytest.fixture
def group(programs, tmp_path):
    root = tmp_path / 'bootstrap'
    destination = tmp_path / 'not-installed'
    plan_sha, _ = preparations.prepare(programs, destination, root)
    return root, plan_sha, destination


def opened(group, **options):
    root, digest, _ = group
    return inspection.GuardBootstrapSources(root, digest, **options)


def rewrite_plan(root, change):
    path = root / inspection.PLAN_NAME
    value = inspection.strict_json_object(path.read_bytes())
    change(value)
    raw = _bytes(value)
    # This changes only a new isolated test input, never repository source.
    with path.open('r+b') as stream:
        stream.write(raw)
        stream.truncate()
    return sha256(raw).hexdigest()


def test_actual_original_sources_are_locked_and_plan_projection_cannot_mutate_owner(
    group, programs
):
    root, _, destination = group
    originals = {path: path.read_bytes() for path in root.iterdir()}
    with opened(group) as held:
        assert held.verify()['scope'] == inspection.PLAN_SCOPE
        assert held.plan['sources']['guard']['manifest_sha256'] == programs[1]
        projection = held.plan
        projection['sources']['guard']['manifest_sha256'] = 'b' * 64
        assert held.plan['sources']['guard']['manifest_sha256'] == programs[1]
        assert held.verify()['sources']['backend']['manifest_sha256'] == programs[3]
        for path in (
            root / inspection.PLAN_NAME,
            root / inspection.DEPLOYMENT_NAME,
            programs[0] / 'guard-program.v1.json',
        ):
            with pytest.raises(PermissionError):
                path.rename(path.with_suffix('.changed'))
        assert not destination.exists()
    for path, raw in originals.items():
        assert path.read_bytes() == raw
        renamed = path.with_suffix('.released')
        path.rename(renamed)
        renamed.rename(path)


@pytest.mark.parametrize(
    'change',
    [
        'extra-field',
        'schema-bool',
        'source-extra',
        'member-bool',
        'member-count',
        'program-ref',
        'service-name',
        'service-account',
        'service-start',
        'service-argument',
        'service-command-line',
        'required-step',
        'wrong-deployment-digest',
        'wrong-installation-ref',
        'backend-sid',
    ],
)
def test_pinned_but_inconsistent_plan_never_accepts_service_or_source_changes(group, change):
    root, _, destination = group

    def alter(value):
        if change == 'extra-field':
            value['ready'] = True
        elif change == 'schema-bool':
            value['schema_version'] = True
        elif change == 'source-extra':
            value['sources']['guard']['ready'] = True
        elif change == 'member-bool':
            value['sources']['guard']['member_count'] = True
        elif change == 'member-count':
            value['sources']['guard']['member_count'] += 1
        elif change == 'program-ref':
            value['sources']['backend']['program_ref'] = 'UNREGISTERED-BACKEND-PROGRAM'
        elif change == 'service-name':
            value['service']['name'] = 'UnrelatedExistingService'
        elif change == 'service-account':
            value['service']['account'] = 'LocalService'
        elif change == 'service-start':
            value['service']['start_type'] = 'AUTO_START'
        elif change == 'service-argument':
            value['service']['arguments'].append('--unregistered')
        elif change == 'service-command-line':
            value['service']['image_path'] += ' & unregistered'
        elif change == 'required-step':
            value['required_steps'].pop()
        elif change == 'wrong-deployment-digest':
            value['deployment_sha256'] = 'b' * 64
        elif change == 'wrong-installation-ref':
            value['installation_ref'] = 'b' * 64
        else:
            value['backend_sid'] = 'S-1-5-18'

    changed = rewrite_plan(root, alter)
    with pytest.raises((RuntimeError, ValueError)):
        inspection.GuardBootstrapSources(root, changed)
    assert not destination.exists()
    root.rename(root.with_name('released-rejected-bootstrap'))


@pytest.mark.parametrize('change', ['duplicate-key', 'noncanonical', 'bad-utf8'])
def test_noncanonical_or_ambiguous_raw_input_is_rejected_before_admission(group, change):
    root, _, destination = group
    path = root / inspection.PLAN_NAME
    raw = path.read_bytes()
    if change == 'duplicate-key':
        raw = raw.replace(b'{', b'{"schema_version":1,', 1)
    elif change == 'noncanonical':
        raw = b' ' + raw
    else:
        raw = b'\xff' + raw
    with path.open('r+b') as stream:
        stream.write(raw)
        stream.truncate()
    with pytest.raises((RuntimeError, ValueError)):
        inspection.GuardBootstrapSources(root, sha256(raw).hexdigest())
    assert not destination.exists()
    root.rename(root.with_name('released-raw-input'))


@pytest.mark.parametrize('member', ['extra-file', 'extra-directory', 'readme-ads', 'plan-hardlink'])
def test_actual_unregistered_input_or_hidden_stream_is_rejected(group, tmp_path, member):
    root, digest, destination = group
    stream = None
    if member == 'extra-file':
        with (root / 'extra').open('xb') as target:
            target.write(b'unregistered')
    elif member == 'extra-directory':
        (root / 'extra').mkdir()
    elif member == 'readme-ads':
        stream = root / 'README.md:hidden'
        with stream.open('xb') as target:
            target.write(b'unregistered')
    else:
        import os

        os.link(root / inspection.PLAN_NAME, tmp_path / 'second-link')
    try:
        with pytest.raises((RuntimeError, ValueError)):
            inspection.GuardBootstrapSources(root, digest)
    finally:
        if stream is not None:
            stream.unlink()
    assert not destination.exists()
    root.rename(root.with_name('released-inventory'))


@pytest.mark.parametrize('drift', ['grow', 'same-size'])
def test_actual_program_source_drift_after_preparation_is_rejected(group, programs, drift):
    target = programs[0] / '_internal/runtime.dat'
    raw = target.read_bytes()
    if drift == 'grow':
        with target.open('ab') as stream:
            stream.write(b'changed after plan preparation')
        reason = 'CONFIG_READ_BYTES_EXCEEDED'
    else:
        with target.open('r+b') as stream:
            stream.write(bytes((raw[0] ^ 1,)) + raw[1:])
        reason = 'MEMBER_BYTES_DIFFER'
    with pytest.raises(RuntimeError, match=reason):
        opened(group)
    target.rename(target.with_suffix('.released'))


def test_added_input_or_program_inventory_cannot_pass_an_existing_owner(group, programs):
    root, _, destination = group
    with opened(group) as held:
        extra = programs[0] / 'new-unregistered'
        extra.mkdir()
        try:
            with pytest.raises(RuntimeError, match='MEMBERS_DIFFER'):
                held.verify()
        finally:
            extra.rmdir()
        assert held.verify()
        with (root / 'extra').open('xb') as stream:
            stream.write(b'new input')
        with pytest.raises(RuntimeError, match='MEMBERS_DIFFER'):
            held.verify()
    assert not destination.exists()


def test_actual_mutable_installation_parent_is_rejected_without_repair(group, ordinary_controller):
    root, _, destination = group
    before = {path: path.read_bytes() for path in root.iterdir()}
    with opened(group) as held:
        with pytest.raises(NativeAccessError, match='CAN_MUTATE'):
            held.verify_parent_access(ordinary_controller[0])
        assert held.verify()
    assert not destination.exists()
    assert before == {path: path.read_bytes() for path in root.iterdir()}


def test_cancellation_and_expired_query_preserve_only_original_inputs(group):
    cancelled = Event()
    with opened(group, cancelled=cancelled.is_set) as held:
        cancelled.set()
        with pytest.raises(RuntimeError, match='CANCELLED_OR_EXPIRED'):
            held.verify()
    with pytest.raises(RuntimeError, match='CANCELLED_OR_EXPIRED'):
        opened(group, cancelled=lambda: True)
    group[0].rename(group[0].with_name('released-cancelled-bootstrap'))
    assert not group[2].exists()


def test_unknown_native_close_keeps_entire_owner_without_retry(group, monkeypatch):
    held = opened(group)
    original = held.backend.close
    calls = []

    def unknown_after_close():
        original()
        calls.append('close')
        raise RuntimeError('Owned native close outcome unknown')

    monkeypatch.setattr(held.backend, 'close', unknown_after_close)
    with pytest.raises(RuntimeError, match='BOOTSTRAP_CLOSE_UNVERIFIED') as first:
        held.close()
    assert first.value.retained_owner is held and calls == ['close']
    with pytest.raises(RuntimeError, match='BOOTSTRAP_CLOSE_PREVIOUSLY_UNVERIFIED') as second:
        held.close()
    assert second.value.retained_owner is held and calls == ['close']
    group[0].rename(group[0].with_name('released-explicit-close-fixture'))


def test_constructor_unknown_child_owner_is_not_closed_again(group, monkeypatch):
    class RetainedChild:
        def close(self):
            pytest.fail('An uncertain original close must never be retried')

    child = RetainedChild()
    failure = RuntimeError('Owned constructor failure')
    failure.retained_owner = child

    def rejected_package(*arguments, **options):
        raise failure

    monkeypatch.setattr(inspection, 'ProgramPackageLease', rejected_package)
    with pytest.raises(RuntimeError, match='BOOTSTRAP_CLOSE_UNVERIFIED') as rejected:
        opened(group)
    owner = rejected.value.retained_owner
    assert owner._orphans == [child]
    with pytest.raises(RuntimeError, match='BOOTSTRAP_CLOSE_PREVIOUSLY_UNVERIFIED'):
        owner.close()
    group[0].rename(group[0].with_name('released-constructor-fixture'))


@pytest.mark.parametrize('timeout', [True, 0, -1, 300001])
def test_invalid_query_limits_do_not_open_any_input(group, monkeypatch, timeout):
    def no_native(*arguments, **options):
        pytest.fail('Invalid limits must fail before opening native resources')

    monkeypatch.setattr(inspection, 'LocalPathGuard', no_native)
    with pytest.raises(RuntimeError, match='BOUNDARY_REQUIRED'):
        opened(group, timeout_ms=timeout)


def test_cancelled_context_entry_closes_actual_original_sources(group):
    cancelled = Event()
    held = opened(group, cancelled=cancelled.is_set)
    cancelled.set()
    with pytest.raises(RuntimeError, match='CANCELLED_OR_EXPIRED'), held:
        pytest.fail('Cancelled context entry must never become usable')
    assert held._closed
    group[0].rename(group[0].with_name('released-cancelled-entry'))


def test_unknown_parent_query_close_prevents_reuse_and_is_never_retried(
    group, ordinary_controller, monkeypatch
):
    held = opened(group)
    original = inspection.ControllerAccessQuery.close
    calls = []

    def unknown_after_native_close(query):
        original(query)
        calls.append(query)
        error = RuntimeError('Owned parent query close outcome unknown')
        error.retained_owner = query
        raise error

    monkeypatch.setattr(inspection.ControllerAccessQuery, 'close', unknown_after_native_close)
    with pytest.raises(RuntimeError, match='Owned parent query close') as error:
        held.verify_parent_access(ordinary_controller[0])
    assert error.value.retained_owner is held and len(calls) == 1
    with pytest.raises(RuntimeError, match='SOURCE_OWNER_UNVERIFIED'):
        held.verify()
    with pytest.raises(RuntimeError, match='BOOTSTRAP_CLOSE_UNVERIFIED'):
        held.close()
    assert len(calls) == 1
    group[0].rename(group[0].with_name('released-parent-unknown-close-fixture'))
