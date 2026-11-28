"""Historical release observations respect only the prerequisites of their own phase."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.infrastructure.environment_files import EnvironmentFailure, canonical, digest


@pytest.mark.parametrize(
    'case',
    (
        'confirmed_after_boot_and_tool_change',
        'confirmed_different_policy',
        'dispatched_before_boot_change',
        'dispatched_without_systemd_run',
        'dispatched_without_systemctl',
        'dispatched_without_account',
        'new_without_systemd_run',
    ),
)
def test_release_readback_uses_current_tools_only_when_needed(case, monkeypatch, tmp_path):
    pytest.importorskip('fcntl')
    from backend.app.management import release_runtime as runtime
    from backend.app.management.attachment_observation import now
    from backend.app.management.runtime_capacity import MINIMUM

    scope = {key: str(uuid4()) for key in ('manager_id', 'host_id', 'registry_generation')}
    catalog = SimpleNamespace(scope=scope, directory=tmp_path)
    operation, run, boot = (str(uuid4()) for _ in range(3))
    boot_changed = case in ('confirmed_after_boot_and_tool_change', 'dispatched_before_boot_change')
    live_boot = str(uuid4()) if boot_changed else boot
    project = tmp_path / 'project'
    launcher = project / 'tools/linux_runtime/serve_environment.py'
    open_path = tmp_path / runtime.OPEN_POLICY
    environment = SimpleNamespace(
        project=project, environment_id=str(uuid4()), description={'purpose': 'INTEGRATION'}
    )
    selection = {
        'environment_id': environment.environment_id,
        'data_generation': str(uuid4()),
        'deployment_id': str(uuid4()),
        'configuration_sha256': 'a' * 64,
        'control_sha256': 'b' * 64,
        'transition_sha256': 'c' * 64,
        'control_revision': 12,
    }
    operation_path = tmp_path / runtime.POLICY
    open_pin = 'd' * 64
    launch_pin = 'e' * 64
    args = SimpleNamespace(
        root=tmp_path,
        sha256='f' * 64,
        release_operation_id=operation,
        managed_release_open_policy=operation_path,
        managed_release_open_policy_sha256=launch_pin,
    )
    policy = {
        'format_version': 1,
        **scope,
        'operation_id': operation,
        'release_open_policy': {'path': str(open_path), 'sha256': open_pin},
        'launcher': {'path': str(launcher), 'sha256': '1' * 64},
        **{key: str(tmp_path / key) for key in runtime.PATHS},
        **{key: '2' * 64 for key in runtime.EXECUTABLE_PINS},
    }
    request = {
        'operation_id': operation,
        'run_id': run,
        'boot_id': boot,
        'limits': dict(MINIMUM),
        'capacity_sha256': '3' * 64,
        'open_policy_sha256': open_pin,
        'selection_receipt_sha256': digest(canonical(selection)),
        'launch_policy_sha256': launch_pin,
        **{key: selection[key] for key in runtime.TARGET},
    }
    timestamp = now()
    opening = {
        'status': 'RELEASE_OPEN_CONFIRMED',
        'operation_id': operation,
        'run_id': run,
        **{key: request[key] for key in runtime.TARGET},
        'admission': 'OPEN',
        'control_revision': selection['control_revision'] + 1,
        'open_receipt_sha256': '4' * 64,
        'opened_at': timestamp,
    }
    reference = {'path': str(tmp_path / runtime.RUNTIME_POLICY), 'sha256': '5' * 64}
    observation = {
        'proof_id': str(uuid4()),
        'environment_id': environment.environment_id,
        'observed_at': timestamp,
        'state': 'RUNNING',
        'reason_code': runtime.READY,
    }
    confirmed = runtime.confirmed_opening(opening, reference, observation, request, selection)
    unit = f'walle-env-{environment.environment_id}-{operation}.service'
    facts = {}
    if case != 'new_without_systemd_run':
        facts[runtime.DISPATCH] = {'format_version': 1, 'unit': unit, 'request': request}
    if case.startswith('confirmed'):
        facts[runtime.OPENED] = confirmed
    if case == 'confirmed_different_policy':
        args.managed_release_open_policy_sha256 = '6' * 64
    missing = {
        'confirmed_after_boot_and_tool_change': 'serve_environment.py',
        'dispatched_before_boot_change': 'serve_environment.py',
        'dispatched_without_systemd_run': 'systemd-run',
        'dispatched_without_systemctl': 'systemctl',
        'new_without_systemd_run': 'systemd-run',
    }.get(case)
    events = []

    def installed(path, expected):
        assert path == operation_path and expected == args.managed_release_open_policy_sha256
        return policy

    def verify_tool(path, pin, *, script=False):
        label = Path(path).name
        events.append(label)
        if label == missing:
            raise EnvironmentFailure('QA_NATIVE_TOOL_CHANGED')

    def verify_account(*_):
        events.append('accounts')
        if case == 'dispatched_without_account':
            raise KeyError('original account is unavailable')

    def confirm(_catalog, _args, _entry, setup, expected, selected, *, wait):
        events.append('observe')
        assert expected == request and selected == selection and not wait
        assert setup[3] == unit
        return confirmed

    def store(_fd, name, value):
        assert name == runtime.OPENED and name not in facts
        assert value == confirmed
        events.append('record opening')
        facts[name] = value

    def forbid(*_args, **_kwargs):
        pytest.fail('Original dispatch must not reserve or launch again')

    capacity = SimpleNamespace(
        profile=lambda _: request['limits'],
        sha256=request['capacity_sha256'],
    )
    monkeypatch.setattr(runtime, 'installed_record', installed)
    monkeypatch.setattr(runtime, 'trusted_executable', verify_tool)
    monkeypatch.setattr(runtime, 'verify_accounts_and_paths', verify_account)
    monkeypatch.setattr(runtime, 'open_inputs', lambda *_: {**selection, 'run_id': run})
    monkeypatch.setattr(runtime, 'machine_clock', lambda: (live_boot, 4))
    monkeypatch.setattr(
        runtime,
        'load_capacity',
        (lambda _: capacity) if case == 'new_without_systemd_run' else forbid,
    )
    monkeypatch.setattr(runtime, 'optional_fact', lambda _, name: facts.get(name))
    monkeypatch.setattr(runtime, 'write_fact', store)
    monkeypatch.setattr(runtime, 'confirm_dispatch', confirm)
    monkeypatch.setattr(runtime, 'manager_command', forbid)
    monkeypatch.setattr(runtime, 'run_bounded', forbid)
    target = runtime.SelectedDeployment(
        environment,
        selection,
        {'candidate_ref': str(uuid4()), 'sha256': '7' * 64},
        'ordinary',
        'admit',
    )
    initial = dict(facts)

    with (tmp_path / 'receipt').open('xb') as record:

        def start():
            return runtime.start_selected_deployment(
                catalog,
                object(),
                args,
                {'verify_runtime': forbid},
                object(),
                record.fileno(),
                target,
            )

        if case in ('confirmed_after_boot_and_tool_change', 'dispatched_without_systemd_run'):
            assert start() == confirmed
        else:
            reason = {
                'confirmed_different_policy': runtime.CHANGED,
                'dispatched_before_boot_change': runtime.UNVERIFIED,
                'dispatched_without_systemctl': runtime.UNVERIFIED,
                'dispatched_without_account': runtime.UNVERIFIED,
                'new_without_systemd_run': 'QA_NATIVE_TOOL_CHANGED',
            }[case]
            with pytest.raises(EnvironmentFailure, match=reason) as blocked:
                start()
            assert blocked.value.uncertain is (reason == runtime.UNVERIFIED)

    if case == 'dispatched_without_systemd_run':
        assert events == [
            'serve_environment.py',
            'systemctl',
            'accounts',
            'observe',
            'record opening',
        ]
        assert facts == {**initial, runtime.OPENED: confirmed}
    else:
        expected_events = {
            'new_without_systemd_run': ['serve_environment.py', 'systemctl', 'systemd-run'],
            'dispatched_without_systemctl': ['serve_environment.py', 'systemctl'],
            'dispatched_without_account': ['serve_environment.py', 'systemctl', 'accounts'],
        }
        assert events == expected_events.get(case, [])
        assert facts == initial
