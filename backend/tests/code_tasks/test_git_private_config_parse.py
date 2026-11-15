"""Whole private-copy borrow held through original fixed Git peer exit."""

import json
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest

from backend.app.infrastructure.git_bundle import verify_bundle_bytes
from backend.app.infrastructure.git_local_config import validate_local_config_output
from backend.app.infrastructure.windows_config_source import LockedConfigSource, ConfigReadError
from backend.app.infrastructure.windows_config_copy import PrivateConfigCopy
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_original_source_private_copy_fixed_git_parse_and_exact_cleanup(tmp_path, format):
    assert verify_bundle_bytes()[0] == 375
    raw = (
        '[core]\n repositoryformatversion='
        + ('0' if format == 'sha1' else '1')
        + '\n bare=false\n[user]\n name="PRIVATE NAME\\nLINE TWO"\n'
        + '[remote "origin"]\n url=https://synthetic:PRIVATE@example.invalid/repo\n'
        + ('[extensions]\n objectformat=sha256\n refstorage=files\n' if format == 'sha256' else '')
    ).encode('utf-8')
    original_path = tmp_path / 'original.config'
    with original_path.open('xb') as stream:
        stream.write(raw)
    package_path = create_private_package(tmp_path / 'private')
    peer_root = create_private_package(tmp_path / 'parse-peer')
    nonce = uuid4().hex
    with (peer_root / '.walle-config-owner').open('x', encoding='ascii') as stream:
        stream.write(nonce)
    with (
        LockedConfigSource(original_path, max_file_bytes=4096) as original,
        PrivatePackageGuard(package_path) as package,
    ):
        with PrivateConfigCopy(original, package) as copy:
            with copy.parse_path() as path:
                worker = ROOT / 'backend/tests/code_tasks/v20_git_config_copy_worker.py'
                code = '\n'.join(
                    (
                        'import runpy,sys',
                        'sys.argv=' + repr([str(worker), str(peer_root), nonce, path]),
                        'runpy.run_path(' + repr(str(worker)) + ',run_name="__main__")',
                    )
                )
                job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
                process = None
                empty = False
                try:
                    process = TestSuspendedRoot(job, peer_root, code)
                    with ObservedProcess(process.pid) as observed:
                        process.resume()
                        deadline = monotonic() + 40
                        while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                            sleep(0.01)
                        final = observed.observe()
                        assert final.state == 'EXITED'
                    with (peer_root / 'config-result.json').open('rb') as stream:
                        output = json.loads(stream.read(16385))
                    assert output['completed'], (
                        output.get('failed_step'),
                        output.get('failure_kind'),
                    )
                    assert final.exit_code == 0
                    assert output['run_nonce'] == nonce
                    assert output['nonrepository']
                    wire = bytes.fromhex(output['wire_hex'])
                    facts = validate_local_config_output(
                        wire,
                        expected_object_format=format,
                        expected_bare=False,
                        max_output_bytes=4096,
                        max_entries=100,
                    )
                    assert facts.object_format == format
                    assert 'PRIVATE' not in repr(facts)
                    assert copy.verify().raw == original.verify().raw == raw
                    with pytest.raises(ConfigReadError, match='IN_USE'):
                        original.close()
                finally:
                    job.terminate_owned(1)
                    deadline = monotonic() + 8
                    while monotonic() < deadline:
                        members = job.observe_members()
                        if members.complete and not members.process_ids:
                            empty = True
                            break
                        sleep(0.01)
                    job.close()
                    if process is not None:
                        process.close()
                    assert empty, 'Original owned parse peer Job did not empty'
            assert copy.verify().sha256 == original.snapshot.sha256
        assert not copy._path.exists() and list(package_path.iterdir()) == []
        assert original._borrows == 0 and original.verify().raw == raw
    assert original_path.read_bytes() == raw
