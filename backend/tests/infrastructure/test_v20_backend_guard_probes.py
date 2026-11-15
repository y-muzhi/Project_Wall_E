"""Real stdin-pipe framing and strict no-business frozen-backend probe inputs."""

import subprocess
import sys
from pathlib import Path

import pytest

from backend.tests.requirements import test_v15_foundation as foundation
from tools import windows_backend_guard_probe as probe
from tools.quality_gate import environment, stop_owned

tmp_path = foundation.tmp_path
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    'payload,expected,marker',
    [
        (b'', 0, 'READER_CONTROL_STOPPED'),
        (b'STOP\n', 0, 'READER_CONTROL_STOPPED'),
        (b'ST', 1, 'BACKEND_READER_INCOMPLETE_COMMAND'),
        (b'RUN\n', 1, 'BACKEND_READER_COMMAND_REJECTED'),
        (b'STOP\r\n', 1, 'BACKEND_READER_COMMAND_REJECTED'),
        (b'STOP\nignored', 1, 'BACKEND_READER_COMMAND_REJECTED'),
        (b'x' * 17, 1, 'BACKEND_READER_COMMAND_LIMIT'),
        (b'\xff', 1, 'BACKEND_READER_COMMAND_REJECTED'),
    ],
)
def test_actual_original_stdin_pipe_is_bounded_and_cannot_execute_input(
    tmp_path, payload, expected, marker
):
    code = (
        'import sys,time\n'
        f'sys.path.insert(0,{str(ROOT)!r})\n'
        'from tools.windows_backend_guard_probe import ReaderControlPipe,BackendGuardProbeError\n'
        'control=ReaderControlPipe()\n'
        'deadline=time.monotonic()+5\n'
        'try:\n'
        ' while not control.stopped():\n'
        '  if time.monotonic()>=deadline:raise RuntimeError("owned pipe test deadline")\n'
        '  time.sleep(0.01)\n'
        ' print("READER_CONTROL_STOPPED",flush=True)\n'
        'except BackendGuardProbeError as error:\n'
        ' print(str(error),flush=True)\n'
        ' raise SystemExit(1)\n'
    )
    process = subprocess.Popen(
        [sys.executable, '-B', '-c', code],
        cwd=tmp_path,
        env=environment(str(tmp_path)),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        output, _ = process.communicate(payload, timeout=20)
        assert process.returncode == expected, output.decode('utf-8', 'replace')
        assert marker.encode() in output
    finally:
        if process.poll() is None:
            stop_owned(process)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    'arguments',
    [
        [],
        ['--hold-installation-reader'],
        ['--hold-installation-reader', '--program-sha256', 'a' * 64, '--port', '8000'],
        ['--hold-installation-reader', '--program-sha256', 'a' * 64, '--verify-runtime'],
        ['--hold-installation-reader', '--program-sha256', 'a' * 64, '--verify-guard'],
        ['--hold-installation-reader', '--program-sha256', 'a' * 64, '--guard-sha256', 'b' * 64],
        ['--verify-guard', '--program-sha256', 'a' * 64],
        ['--verify-guard', '--program-sha256', 'a' * 64, '--installation-ref', 'b' * 64],
    ],
)
def test_probe_modes_reject_missing_or_mixed_arguments_before_any_resource(monkeypatch, arguments):
    def no_probe(*arguments, **options):
        pytest.fail('Invalid mode must not open program, process or service resources')

    monkeypatch.setattr(probe, 'hold_installation_reader', no_probe)
    monkeypatch.setattr(probe, 'verify_guard', no_probe)
    with pytest.raises(SystemExit) as result:
        probe.main(arguments)
    assert result.value.code == 2


def test_source_python_cannot_impersonate_the_frozen_backend(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'frozen', False, raising=False)

    def no_resource(*arguments, **options):
        pytest.fail('Source Python must fail before opening native resources')

    monkeypatch.setattr(probe, 'ProgramPackageLease', no_resource)
    assert probe.main(['--hold-installation-reader', '--program-sha256', 'a' * 64]) == 1
    assert capsys.readouterr().err.strip() == 'BACKEND_DEPLOYMENT_PROBE_REJECTED'


def test_probe_import_does_not_load_business_database_or_service(tmp_path):
    code = (
        'import sys\n'
        f'sys.path.insert(0,{str(ROOT)!r})\n'
        'import tools.windows_backend_guard_probe\n'
        'assert not any(name==prefix or name.startswith(prefix+".") '
        'for name in sys.modules for prefix in '
        '("backend.app.service","backend.app.infrastructure.database"))\n'
        'print("NO_BUSINESS_DATABASE_OR_SERVICE_IMPORTED",flush=True)\n'
    )
    process = subprocess.Popen(
        [sys.executable, '-B', '-c', code],
        cwd=tmp_path,
        env=environment(str(tmp_path)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        output, _ = process.communicate(timeout=20)
        assert process.returncode == 0, output.decode('utf-8', 'replace')
        assert b'NO_BUSINESS_DATABASE_OR_SERVICE_IMPORTED' in output
    finally:
        if process.poll() is None:
            stop_owned(process)
    assert list(tmp_path.iterdir()) == []
