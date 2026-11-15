"""Exercise complete preview bytes and expected-old-value delivery with isolated MinGit."""

import subprocess
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.app.infrastructure.content_manifest import ContentEntry, ContentLimits, compare_content
from backend.app.infrastructure.content_package import (
    CandidatePackageBinding,
    TargetPackageBinding,
    seal_candidate_package,
    seal_target_package,
    verify_candidate_package,
)
from backend.app.infrastructure.content_package_publish import (
    create_candidate_stage,
    publish_candidate_package,
)
from backend.app.infrastructure.content_secret_policy import REFERENCE, load_secret_policy
from backend.app.infrastructure.content_selection import ContentSelection
from backend.app.infrastructure.git_commit_closure import ClosureLimits
from backend.app.infrastructure.git_commit_input import CommitIdentity, build_delivery_commit
from backend.app.infrastructure.git_content_command import content_git_arguments
from backend.app.infrastructure.git_delivery_objects import build_original_delivery_objects
from backend.app.infrastructure.git_object_read import GitObjectReadError
from backend.app.infrastructure.git_ref_protocol import (
    RefAckDecoder,
    abort_bytes,
    commit_bytes,
    delivery_update,
    prepared_ref_observation,
)
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
PROGRAM = ROOT / 'backend/runtime/git/2.56.0.windows.4/win-x64/cmd/git.exe'


def exercise_delivery(root, format):
    environment = owned_git_environment(root)
    actor = CommitIdentity('WALL-E Fixture', 'fixture@example.invalid')
    fixed_date = '2026-11-10T12:00:00+00:00'
    environment.update(
        GIT_AUTHOR_NAME=actor.name,
        GIT_AUTHOR_EMAIL=actor.email,
        GIT_AUTHOR_DATE=fixed_date,
        GIT_COMMITTER_NAME=actor.name,
        GIT_COMMITTER_EMAIL=actor.email,
        GIT_COMMITTER_DATE=fixed_date,
    )

    def execute(arguments, raw=b''):
        completed = subprocess.run(
            [str(PROGRAM), *arguments],
            input=raw,
            capture_output=True,
            timeout=8,
            cwd=root,
            env=environment,
            check=True,
        )
        assert not completed.stderr, completed.stderr
        return completed.stdout

    def package_git(intent, repo, raw, maximum, remaining):
        assert remaining > 0
        data = execute(content_git_arguments(intent, repo), raw)
        assert len(data) <= maximum
        return data

    target_repo = root / 'original.git'
    execute(
        (
            'init',
            '--bare',
            '--template=',
            '--initial-branch=main',
            '--object-format=' + format,
            str(target_repo),
        )
    )
    prefix = ('--git-dir=' + str(target_repo), '--no-replace-objects')

    def git(*arguments, raw=b''):
        return execute((*prefix, *arguments), raw)

    old_raw = b'target only\r\n'
    old_blob = git('hash-object', '-w', '--stdin', '--no-filters', raw=old_raw).strip().decode()
    old_tree = (
        git('mktree', '-z', raw=f'100644 blob {old_blob}\ttarget-only.txt\0'.encode())
        .strip()
        .decode()
    )
    old = git('commit-tree', old_tree, raw=b'original\n').strip().decode()
    git('update-ref', 'refs/heads/delivery', old)

    content = ContentLimits(16384, 65536, 32, 65536)
    bounds = ClosureLimits(128, 256, 16384, 65536, 40)
    active = lambda: None
    source = root / 'writer'
    source.mkdir()
    (source / 'result.txt').write_bytes(b'new candidate\n')
    with LocalPathGuard(source, directory=True) as guard:
        workspace = guard.verify()
    candidate = CandidatePackageBinding(1, 1, 3, 'a' * 32, 1, format)
    target = TargetPackageBinding(2, 1, 3, 'b' * 32, 1, format, old, old_tree)
    store_path = create_private_package(root / 'content-store')
    with PrivatePackageGuard(store_path) as store:
        candidate_path = create_candidate_stage(store, candidate)
        with PrivatePackageGuard(candidate_path) as stage:
            sealed = seal_candidate_package(
                stage,
                candidate,
                source_path=source,
                source_identity=workspace,
                selection=ContentSelection(
                    product_include_paths=['.'],
                    nonproduct_exclude_paths=[],
                    new_file_mode='100644',
                    baseline_entries=[],
                ),
                secret_policy=load_secret_policy(REFERENCE),
                workspace_limits=CandidateWorkspaceLimits(content, 128, 2048, 40),
                git_limits=bounds,
                started_at=monotonic(),
                quiescent=active,
                exchange=package_git,
                materialization_root=root / 'candidate-check',
            )
        target_path = create_candidate_stage(store, target)
        before = (
            ContentEntry(
                'target-only.txt', '100644', old_blob, len(old_raw), sha256(old_raw).hexdigest()
            ),
        )
        with PrivatePackageGuard(target_path) as stage:
            observed = seal_target_package(
                stage,
                target,
                before,
                lambda entry: git('cat-file', 'blob', entry.blob_oid),
                secret_policy_ref=REFERENCE,
                limits=content,
                git_limits=bounds,
                started_at=monotonic(),
                active=active,
                verify_source=lambda: git('cat-file', 'tree', old_tree),
                exchange=package_git,
                materialization_root=root / 'target-check',
            )
        saved = publish_candidate_package(
            store,
            target,
            limits=content,
            git_limits=bounds,
            started_at=monotonic(),
            active=active,
            materialization_root=root / 'target-check',
            expected=observed,
        )
        assert saved.seal.manifest.content_tree_oid == old_tree
        comparison = compare_content(before, sealed.manifest.entries, format=format, limits=content)
        assert [(item.path, item.before is None, item.after is None) for item in comparison] == [
            ('result.txt', True, False),
            ('target-only.txt', False, True),
        ]

        commit = build_delivery_commit(
            format=format,
            tree_oid=sealed.manifest.content_tree_oid,
            parent_oid=old,
            delivery_id=1,
            fixed_unix_seconds=1794312000,
            author=actor,
            committer=actor,
            message_template='Task {task_id}, candidate {candidate_id}',
            task_id=1,
            candidate_id=1,
            max_payload_bytes=4096,
        )

        def read_object(kind, oid, maximum):
            data = git('cat-file', kind, oid)
            assert len(data) <= maximum
            return data

        with PrivatePackageGuard(candidate_path) as package:
            assert (
                build_original_delivery_objects(
                    package,
                    candidate,
                    commit,
                    expected_manifest_sha256=sealed.manifest_sha256,
                    limits=content,
                    git_limits=bounds,
                    started_at=monotonic(),
                    active=active,
                    exchange=lambda intent, raw: git(*intent.arguments(), raw=raw),
                    read_object=read_object,
                )
                == commit.commit_oid
            )
        reads = []

        def read_existing(kind, oid, maximum):
            reads.append((kind, oid))
            return read_object(kind, oid, maximum)

        with PrivatePackageGuard(candidate_path) as package:
            assert (
                build_original_delivery_objects(
                    package,
                    candidate,
                    commit,
                    expected_manifest_sha256=sealed.manifest_sha256,
                    limits=content,
                    git_limits=bounds,
                    started_at=monotonic(),
                    active=active,
                    read_object=read_existing,
                )
                == commit.commit_oid
            )
        assert set(kind for kind, _ in reads) == {'commit', 'tree', 'blob'}
        assert ('commit', old) in reads and ('commit', commit.commit_oid) in reads
        with PrivatePackageGuard(candidate_path) as package:
            with pytest.raises(GitObjectReadError):
                build_original_delivery_objects(
                    package,
                    candidate,
                    commit,
                    expected_manifest_sha256=sealed.manifest_sha256,
                    limits=content,
                    git_limits=bounds,
                    started_at=monotonic(),
                    active=active,
                    read_object=lambda kind, oid, maximum: (
                        b'' if oid == commit.commit_oid else read_object(kind, oid, maximum)
                    ),
                )
        assert git('rev-parse', 'refs/heads/delivery') == old.encode() + b'\n'
        write = delivery_update(1, 'refs/heads/delivery', commit.commit_oid, old, format=format)
        with subprocess.Popen(
            [str(PROGRAM), *prefix, *write.arguments()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=root,
            env=environment,
        ) as original:
            try:
                decoder = RefAckDecoder(max_output_bytes=256)
                original.stdin.write(write.prepare_bytes())
                original.stdin.flush()
                decoder.feed(original.stdout.readline())
                decoder.feed(original.stdout.readline())
                assert decoder.phases == ('START', 'PREPARE')
                original.stdin.write(abort_bytes())
                original.stdin.flush()
                original.stdin.close()
                decoder.feed(original.stdout.readline())
                assert decoder.finish(expected_terminal='ABORT') == ('START', 'PREPARE', 'ABORT')
                assert original.wait(timeout=8) == 0 and not original.stderr.read()
            finally:
                if original.poll() is None:
                    original.kill()
                    original.wait(timeout=8)
        assert git('rev-parse', 'refs/heads/delivery') == old.encode() + b'\n'
        assert not (target_repo / 'refs/heads/delivery.lock').exists()
        with subprocess.Popen(
            [str(PROGRAM), *prefix, *write.arguments()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=root,
            env=environment,
        ) as owned:
            try:
                decoder = RefAckDecoder(max_output_bytes=256)
                owned.stdin.write(write.prepare_bytes())
                owned.stdin.flush()
                decoder.feed(owned.stdout.readline())
                decoder.feed(owned.stdout.readline())
                assert decoder.phases == ('START', 'PREPARE')
                held = git(
                    'for-each-ref',
                    '--format=%(refname)%00%(objectname)%00%(symref)%00',
                    'refs/heads/delivery',
                )
                assert (
                    prepared_ref_observation(held, write, query_exit_code=0, max_output_bytes=512)[
                        'oid'
                    ]
                    == old
                )
                assert git('rev-parse', 'refs/heads/delivery') == old.encode() + b'\n'
                owned.stdin.write(commit_bytes())
                owned.stdin.flush()
                owned.stdin.close()
                decoder.feed(owned.stdout.readline())
                assert decoder.finish(expected_terminal='COMMIT') == ('START', 'PREPARE', 'COMMIT')
                assert owned.wait(timeout=8) == 0 and not owned.stderr.read()
            finally:
                if owned.poll() is None:
                    owned.terminate()
        assert git('rev-parse', 'refs/heads/delivery') == commit.commit_oid.encode() + b'\n'
        stale = subprocess.run(
            [str(PROGRAM), *prefix, *write.arguments()],
            input=write.prepare_bytes(),
            capture_output=True,
            cwd=root,
            env=environment,
            timeout=8,
        )
        assert stale.returncode != 0 and b'prepare: ok' not in stale.stdout
        assert git('rev-parse', 'refs/heads/delivery') == commit.commit_oid.encode() + b'\n'
        # The already sealed preview is still readable after the source branch advanced.
        with PrivatePackageGuard(saved.directory.canonical_path) as original:
            assert (
                verify_candidate_package(
                    original,
                    target,
                    limits=content,
                    git_limits=bounds,
                    started_at=monotonic(),
                    active=active,
                    expected=observed,
                )
                == observed
            )


def worker(root, format):
    try:
        exercise_delivery(root, format)
    except BaseException:
        import traceback

        (root / 'delivery-failure.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise


@pytest.mark.parametrize('format', ['sha1', 'sha256'])
def test_complete_target_and_exact_commit_use_real_git(tmp_path, format):
    code = (
        'import sys; from pathlib import Path; '
        f'sys.path.insert(0,{str(ROOT)!r}); '
        'from backend.tests.infrastructure.test_v20_delivery_git import worker; '
        f'worker(Path({str(tmp_path)!r}), {format!r})'
    )
    job = OwnedJob(active_process_limit=12, job_memory_limit_bytes=512 * 1024**2)
    child = None
    try:
        child = TestSuspendedRoot(job, tmp_path, code)
        child.resume()
        with ObservedProcess(child.pid) as process:
            deadline = monotonic() + 55
            while process.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.025)
            state = process.observe()
        error = tmp_path / 'delivery-failure.txt'
        assert state.state == 'EXITED' and state.exit_code == 0, (
            error.read_text(encoding='utf-8') if error.exists() else state
        )
    finally:
        job.terminate_owned(1)
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if not job.observe_members().process_ids:
                break
            sleep(0.02)
        try:
            assert job.observe_members().complete and not job.observe_members().process_ids
        finally:
            if child is not None:
                child.close()
            job.close()
