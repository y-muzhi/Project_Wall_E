"""Authenticated delivery reference writer and independent locked-target observation."""

import json
from hashlib import sha256
from pathlib import Path
from time import monotonic

import pytest

from backend.app.infrastructure.guard_control_git_transport import GuardControlGitServer
from backend.app.infrastructure.guard_controller_records import GuardControllerRecords
from backend.app.infrastructure.runtime_launch_journal import LaunchJournal
from backend.app.infrastructure.windows_executable_pin import ExecutablePin
from backend.app.infrastructure.windows_private_package import create_private_package
from backend.tests.infrastructure.test_v20_git_metadata_command import setup_repository
from backend.tests.infrastructure.test_v20_guard_control_git_transport import (
    connected,
    program_port as program_port,
)
from backend.tests.requirements.test_v15_foundation import tmp_path  # noqa: F401


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_original_delivery_reference_observes_prepare_before_native_commit(
    tmp_path, program_port, format
):  # noqa: F811
    setup_repository(tmp_path, format)
    (tmp_path / 'private').mkdir()
    result = tmp_path / 'control-git-pipe-result.json'
    diagnostic = tmp_path / 'owned-guard-worker-error.txt'
    repository = tmp_path / 'repository'
    untouched = (repository / 'fixture.txt').read_bytes()
    original_index = (repository / '.git/index').read_bytes()
    with connected(tmp_path, 'DELIVERY_NATIVE') as (frames, backend, reference):
        image = Path(backend.identity.image_path)
        raw = image.read_bytes()
        with (
            ExecutablePin(
                image, expected_byte_count=len(raw), expected_sha256=sha256(raw).hexdigest()
            ) as pin,
            LaunchJournal(create_private_package(tmp_path / 'delivery-guard')) as journal,
            GuardControllerRecords(journal) as records,
        ):
            guard = GuardControlGitServer(
                records, reference, package_root=tmp_path, manifest_sha256='a' * 64
            )
            deadline = monotonic() + 160
            try:
                while not result.exists() and monotonic() < deadline:
                    try:
                        guard.serve(
                            frames,
                            expected_backend=backend.identity,
                            backend_image=pin,
                            timeout_ms=25000,
                            cancelled=lambda: result.exists() or diagnostic.exists(),
                        )
                    except (RuntimeError, OSError):
                        backend._kernel.WaitForSingleObject(backend._handle, 1000)
                        if diagnostic.exists():
                            pytest.fail(diagnostic.read_text(encoding='utf-8'))
                        if not result.exists():
                            raise
                assert result.exists()
                assert guard._owners
                (owner,) = guard._owners.values()
                assert len(owner.registry._preparations) == 14
                assert all(row.handles_released for row in owner.registry._preparations.values())
                observed = json.loads(result.read_bytes())
                assert observed['prepared_then_committed'] is True
                assert observed['target'] != observed['expected']
            finally:
                guard.close()
    assert (repository / 'fixture.txt').read_bytes() == untouched
    assert (repository / '.git/index').read_bytes() == original_index
    assert (repository / '.git/HEAD').read_bytes() == b'ref: refs/heads/main\n'
