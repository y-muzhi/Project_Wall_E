"""Actual fixed MinGit and NTFS package assembly in a privately owned Job."""

import subprocess
from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.app.code_tasks.candidate_materialization import (
    materialize_candidate,
    verify_candidate_check_input,
)
from backend.app.code_tasks.workspace_materialization import WorkspaceMaterializationError
from backend.app.infrastructure import git_bundle
from backend.app.infrastructure.content_manifest import ContentLimits
from backend.app.infrastructure.content_package import (
    CandidatePackageBinding,
    ContentPackageError,
    seal_candidate_package,
    verify_candidate_package,
)
from backend.app.infrastructure.content_package_publish import (
    create_candidate_stage,
    publish_candidate_package,
)
from backend.app.infrastructure.content_paths import ContentPathEntry
from backend.app.infrastructure.content_secret_policy import REFERENCE, load_secret_policy
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.app.infrastructure.git_content_command import content_git_arguments
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_local_paths import LocalPathGuard
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.app.infrastructure.windows_task_workspace_tree import CandidateWorkspaceLimits
from backend.tests.code_tasks.v20_git_vector_worker import owned_git_environment
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path

ROOT = Path(__file__).resolve().parents[3]


def exercise_package(root, format, populated):
    environment = owned_git_environment(root)
    program = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'

    def exchange(intent, repo, raw, maximum, seconds):
        arguments = content_git_arguments(intent, repo)
        output = subprocess.run(
            [str(program), *arguments],
            input=raw,
            capture_output=True,
            timeout=seconds,
            cwd=root,
            env=environment,
            check=True,
        )
        if output.stderr or len(output.stdout) > maximum:
            raise ValueError('Unexpected output from fixed isolated MiniGit')
        return output.stdout

    source = root / 'workspace'
    source.mkdir()
    baseline = []
    if populated:
        (source / 'src' / '中').mkdir(parents=True)
        for name, raw in (
            ('src.txt', b'\xff\0\r\n'),
            ('src/run.sh', b'#!/bin/sh\n'),
            ('src/中/readme.txt', b'\xff\0\r\n'),
            ('src/empty.txt', b''),
        ):
            with (source / name).open('xb') as file:
                file.write(raw)
        baseline.append(ContentPathEntry('src/run.sh', '100755'))
    with LocalPathGuard(source, directory=True) as guard:
        identity = guard.verify()
    selection = ContentSelection(
        product_include_paths=['.'],
        nonproduct_exclude_paths=[],
        new_file_mode='100644',
        baseline_entries=baseline,
    )
    binding = CandidatePackageBinding(11, 12, 2, '1' * 32, 3, format)
    store_path = create_private_package(root / 'store')
    with PrivatePackageGuard(store_path) as store:
        stage = create_candidate_stage(store, binding)
    limits = ContentLimits(4096, 32768, 16, 32768)
    workspace = CandidateWorkspaceLimits(limits, 64, 512, 30)
    reads = ClosureLimits(64, 64, 4096, 32768, 30)
    common = {
        'git_limits': reads,
        'materialization_root': root / 'materialized',
    }
    with PrivatePackageGuard(stage) as package:
        sealed = seal_candidate_package(
            package,
            binding,
            source_path=source,
            source_identity=identity,
            selection=selection,
            secret_policy=load_secret_policy(REFERENCE),
            workspace_limits=workspace,
            started_at=monotonic(),
            quiescent=lambda: None,
            exchange=exchange,
            **common,
        )
        if populated:
            assert [entry.mode for entry in sealed.manifest.entries] == [
                '100644',
                '100644',
                '100755',
                '100644',
            ]
            assert sealed.manifest.entries[0].blob_oid == sealed.manifest.entries[-1].blob_oid
        else:
            assert sealed.manifest.entries == ()

        def reopen():
            return verify_candidate_package(
                package,
                binding,
                expected=sealed,
                limits=limits,
                started_at=monotonic(),
                active=lambda: None,
                **common,
            )

        assert reopen() == sealed

    with (source / 'after-seal.txt').open('xb') as stream:
        stream.write(b'Cannot become part of the sealed candidate')

    with PrivatePackageGuard(store_path) as store:

        def publish():
            return publish_candidate_package(
                store,
                binding,
                limits=limits,
                started_at=monotonic(),
                active=lambda: None,
                **common,
            )

        first = publish()
        assert first.seal == sealed
        assert not stage.exists()
        final = store_path / binding.package_name(staged=False)
        assert first.directory.canonical_path == str(final)
        assert publish() == first
        with pytest.raises(ContentPackageError, match='PACKAGE_KEY_ALREADY_USED'):
            create_candidate_stage(store, binding)

        create_private_package(stage)
        with pytest.raises(ContentPackageError, match='LOCATIONS_CONFLICT'):
            publish()
        stage.rmdir()
        assert publish() == first

        check_root = create_private_package(root / 'checks')
        stage_facts = []
        with PrivatePackageGuard(check_root) as parent:
            copy = materialize_candidate(
                parent,
                '3' * 32,
                first,
                active=lambda: None,
                limits=limits,
                git_limits=reads,
                started_at=monotonic(),
                record_stage=stage_facts.append,
            )
        assert len(stage_facts) == 1 and stage_facts[0].file_id == copy.directory.file_id
        assert copy.seal == first.seal
        integrity = verify_candidate_check_input(copy, active=lambda: None)
        assert integrity.candidate_id == first.seal.binding.candidate_id
        assert integrity.manifest_sha256 == first.seal.manifest_sha256
        target = Path(copy.directory.canonical_path)
        assert not (target / 'after-seal.txt').exists()
        assert {
            item.relative_to(target).as_posix() for item in target.rglob('*') if item.is_file()
        } == {entry.path for entry in first.seal.manifest.entries}
        if populated:
            assert (target / 'src.txt').read_bytes() == b'\xff\0\r\n'
            with (
                LocalPathGuard(target / 'src.txt', directory=False) as one,
                LocalPathGuard(target / 'src/中/readme.txt', directory=False) as two,
            ):
                assert one.verify().file_id != two.verify().file_id
            with (target / 'src.txt').open('ab') as stream:
                stream.write(b'isolated test copy only')
            assert (target / 'src/中/readme.txt').read_bytes() == b'\xff\0\r\n'
            with pytest.raises(WorkspaceMaterializationError, match='INPUT_CHANGED'):
                verify_candidate_check_input(copy, active=lambda: None)
            assert publish() == first

        alternates = final / 'repo.git' / 'objects' / 'info' / 'alternates'
        with alternates.open('xb') as file:
            file.write(b'never passed to Git\\n')
        with pytest.raises(ContentPackageError, match='UNEXPECTED_REPOSITORY_MEMBER'):
            publish()


def run_worker(root, format, populated):
    try:
        exercise_package(root, format, populated)
    except Exception as error:
        import traceback

        with (root / 'worker.md').open('x', encoding='utf-8') as log:
            log.write(''.join(traceback.format_exception(error))[:8192])
            stage = root / 'store' / ('.capture-' + '1' * 32)
            config = stage / 'repo.git' / 'config'
            if config.exists():
                log.write(repr(config.read_bytes()) + '\n')
                log.write(repr(tuple(str(x.relative_to(stage)) for x in stage.rglob('*'))))
        raise


@pytest.mark.parametrize(
    ('format', 'populated'), [('sha1', True), ('sha256', True), ('sha1', False)]
)
def test_fixed_git_candidate_package_round_trip(tmp_path, format, populated):
    git_bundle.verify_bundle_bytes()
    code = (
        'import sys; sys.path.insert(0, ' + repr(str(ROOT)) + '); '
        'from pathlib import Path; '
        'from backend.tests.infrastructure.test_v20_candidate_content_package import run_worker; '
        f'run_worker(Path({str(tmp_path)!r}), {format!r}, {populated!r})'
    )
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    process = None
    try:
        process = TestSuspendedRoot(job, tmp_path, code)
        process.resume()
        with ObservedProcess(process.pid) as observed:
            deadline = monotonic() + 50
            while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.01)
            final = observed.observe()
        failure = tmp_path / 'worker.md'
        details = failure.read_text(encoding='utf-8') if failure.exists() else ''
        assert final.state == 'EXITED' and final.exit_code == 0, details
    finally:
        if process is not None:
            process.close()
        job.close()
