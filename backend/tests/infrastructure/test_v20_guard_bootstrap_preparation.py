"""Actual bootstrap resource preparation; target installation is never created."""

import json
from hashlib import sha256

import pytest

from backend.app.infrastructure.guard_deployment_configuration import decode_guard_deployment
from backend.app.infrastructure.program_manifest import BACKEND_PROGRAM_POLICY
from backend.tests.infrastructure import test_v20_guard_package_preparation as guard_fixtures
from backend.tests.infrastructure.test_v20_backend_package_preparation import (
    package as backend_files,
)
from backend.tests.requirements import test_v15_foundation as foundation_fixtures
from tools import windows_guard_bootstrap as bootstrap
from tools.windows_program_package import package_manifest

# Reuse the original native-path fixtures without replacing pytest storage rules.
prepared = guard_fixtures.prepared
tmp_path = foundation_fixtures.tmp_path


@pytest.fixture
def programs(prepared, tmp_path):
    guard, guard_digest = prepared
    backend = backend_files(tmp_path)
    raw, backend_digest, _, _ = package_manifest(
        backend, 'WALLE-BACKEND-BOOTSTRAP-FIXTURE', policy=BACKEND_PROGRAM_POLICY
    )
    with (backend / BACKEND_PROGRAM_POLICY.manifest_name).open('xb') as stream:
        stream.write(raw)
    return guard, guard_digest, backend, backend_digest


def prepare(programs, destination, output):
    guard, guard_digest, backend, backend_digest = programs
    return bootstrap.prepare(
        guard, guard_digest, backend, backend_digest, destination, 'a' * 64, output
    )


def test_actual_plan_has_original_digests_and_no_installation_side_effects(programs, tmp_path):
    destination, output = tmp_path / 'not-installed', tmp_path / 'prepared-bootstrap'
    plan_digest, deployment_digest = prepare(programs, destination, output)
    assert not destination.exists()
    assert {path.name for path in output.iterdir()} == {
        'guard-deployment.json',
        'install-plan.v1.json',
        'README.md',
    }
    raw = (output / 'guard-deployment.json').read_bytes()
    assert sha256(raw).hexdigest() == deployment_digest
    spec = decode_guard_deployment(raw)
    assert spec.installation_ref == 'a' * 64
    assert spec.task is None and spec.runtime is None and spec.checks is None
    assert spec.backend_program_root == destination / 'backend'
    plan_raw = (output / 'install-plan.v1.json').read_bytes()
    assert sha256(plan_raw).hexdigest() == plan_digest
    plan = json.loads(plan_raw)
    assert plan['deployment_sha256'] == deployment_digest
    assert plan['sources']['guard']['manifest_sha256'] == programs[1]
    assert plan['sources']['backend']['manifest_sha256'] == programs[3]
    assert plan['service']['start_type'] == 'DEMAND_START'
    assert plan['service']['account'] == 'LocalSystem'
    arguments = plan['service']['arguments']
    assert arguments[arguments.index('--program-sha256') + 1] == programs[1]
    assert arguments[arguments.index('--sha256') + 1] == deployment_digest
    assert plan['scope'] == 'BOOTSTRAP_ONLY_NO_TASK_CHECK_OR_MODEL'
    assert 'ready' not in plan and 'os_admission' not in plan
    assert not list(tmp_path.glob('.we-gp-*'))


@pytest.mark.parametrize(
    'failure',
    [
        'existing-installation',
        'existing-output',
        'guard-digest',
        'backend-digest',
        'source-overlap',
        'long-destination',
        'same-installation-output',
    ],
)
def test_unsafe_or_stale_preparation_never_publishes_over_existing_data(
    programs, tmp_path, monkeypatch, failure
):
    guard, guard_digest, backend, backend_digest = programs
    destination, output = tmp_path / 'not-installed', tmp_path / 'prepared-bootstrap'
    original_output = output
    if failure == 'existing-installation':
        destination.mkdir()
        with (destination / 'user-marker').open('xb') as stream:
            stream.write(b'preserve')
    elif failure == 'existing-output':
        output.mkdir()
        with (output / 'user-marker').open('xb') as stream:
            stream.write(b'preserve')
    elif failure == 'guard-digest':
        guard_digest = 'b' * 64
    elif failure == 'backend-digest':
        backend_digest = 'b' * 64
    elif failure == 'source-overlap':
        output = guard / 'must-not-write-in-source'

        def no_temporary_mutation(*args, **kwargs):
            pytest.fail('No temporary output may be created inside a source package')

        monkeypatch.setattr(bootstrap, 'TemporaryDirectory', no_temporary_mutation)
    elif failure == 'long-destination':
        destination = tmp_path / ('long-installation-' * 11)
    else:
        output = destination
    with pytest.raises((RuntimeError, ValueError)):
        bootstrap.prepare(
            guard, guard_digest, backend, backend_digest, destination, 'a' * 64, output
        )
    if failure == 'existing-output':
        assert (original_output / 'user-marker').read_bytes() == b'preserve'
    else:
        assert not original_output.exists()
    if failure == 'existing-installation':
        assert (destination / 'user-marker').read_bytes() == b'preserve'
    assert not list(tmp_path.glob('.we-gp-*'))
    assert not list(guard.glob('.we-gp-*'))


@pytest.mark.parametrize('member', ['guard-deployment.json', 'install-plan.v1.json', 'README.md'])
@pytest.mark.parametrize('failure', ['short-write', 'same-size-corruption', 'flush-error'])
def test_actual_output_write_fault_never_publishes_a_partial_bootstrap(
    programs, tmp_path, monkeypatch, member, failure
):
    from pathlib import Path

    destination, output = tmp_path / 'not-installed', tmp_path / 'prepared-bootstrap'
    originals = {
        path: path.read_bytes()
        for path in (
            programs[0] / 'guard-program.v1.json',
            programs[2] / 'backend-program.v1.json',
        )
    }
    real_open = Path.open
    injected = []

    class FaultedOutput:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *arguments):
            return self.stream.__exit__(*arguments)

        def write(self, raw):
            injected.append(failure)
            if failure == 'short-write':
                return self.stream.write(raw[:-1])
            if failure == 'same-size-corruption':
                raw = bytes((raw[0] ^ 1,)) + raw[1:]
            return self.stream.write(raw)

        def flush(self):
            if failure == 'flush-error':
                raise OSError('OWNED_OUTPUT_FLUSH_FAILURE')
            self.stream.flush()

        def fileno(self):
            return self.stream.fileno()

    def fault_only_owned_preparation(path, *arguments, **options):
        stream = real_open(path, *arguments, **options)
        if (
            path.name == member
            and any(part.startswith('.we-gp-') for part in path.parts)
            and arguments
            and arguments[0] == 'xb'
        ):
            return FaultedOutput(stream)
        return stream

    monkeypatch.setattr(Path, 'open', fault_only_owned_preparation)
    reason = {
        'short-write': 'PREPARED_FILE_WRITE_INCOMPLETE',
        'same-size-corruption': 'PREPARED_FILE_BYTES_DIFFER',
        'flush-error': 'OWNED_OUTPUT_FLUSH_FAILURE',
    }[failure]
    with pytest.raises((RuntimeError, OSError), match=reason):
        prepare(programs, destination, output)
    assert injected == [failure]
    assert not destination.exists() and not output.exists()
    assert not list(tmp_path.glob('.we-gp-*'))
    for path, raw in originals.items():
        assert path.read_bytes() == raw
        renamed = path.with_suffix('.released')
        path.rename(renamed)
        renamed.rename(path)
