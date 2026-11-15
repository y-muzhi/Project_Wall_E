"""Actual fixed MinGit blob/tree vectors in an owned Job; no Guard admission."""

from dataclasses import asdict
import hashlib
import json
import pytest
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

from backend.app.infrastructure import content_manifest as content
from backend.app.infrastructure import git_ref_protocol as refs
from backend.app.infrastructure import git_worktrees as worktrees
from backend.app.infrastructure import git_bundle
from backend.app.infrastructure import git_commit_input as commit
from backend.app.infrastructure.git_local_config import (
    GitConfigError,
    config_source_sha256,
    validate_local_config_output,
)
from backend.app.infrastructure.windows_config_source import LockedConfigSource
from backend.app.infrastructure.windows_worktree_heads import WorktreeHeadLease
from backend.app.infrastructure.windows_job import OwnedJob
from backend.app.infrastructure.windows_process import ObservedProcess
from backend.tests.infrastructure.test_v20_windows_job import TestSuspendedRoot
from backend.tests.requirements.test_v15_foundation import tmp_path
from backend.tests.code_tasks.v20_git_vector_worker import BODIES

ROOT = Path(__file__).resolve().parents[3]
LIMITS = content.ContentLimits(100000, 500000, 10, 16384)


def test_actual_fixed_git_sha1_sha256_empty_tree_and_binary_blobs_match_streaming_verifier(
    tmp_path,
):
    members, _, _ = git_bundle.verify_bundle_bytes()
    assert members == 375
    nonce = uuid4().hex
    with (tmp_path / '.walle-git-vector-owner').open('x', encoding='ascii') as stream:
        stream.write(nonce)
    worker = ROOT / 'backend/tests/code_tasks/v20_git_vector_worker.py'
    code = '\n'.join(
        (
            'import runpy, sys',
            'sys.argv = ' + repr([str(worker), str(tmp_path), nonce]),
            'runpy.run_path(' + repr(str(worker)) + ', run_name="__main__")',
        )
    )
    job = OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    process = None
    empty = False
    try:
        process = TestSuspendedRoot(job, tmp_path, code)
        process.resume()
        with ObservedProcess(process.pid) as observed:
            deadline = monotonic() + 45
            while observed.observe().state == 'RUNNING' and monotonic() < deadline:
                sleep(0.01)
            final = observed.observe()
            assert final.state == 'EXITED'
        with (tmp_path / 'git-vectors.json').open('rb') as stream:
            raw = stream.read(65537)
        assert len(raw) <= 65536
        output = json.loads(raw)
        assert output['run_nonce'] == nonce
        assert output['completed'], (output.get('failed_step'), output.get('failure_kind'))
        assert final.exit_code == 0
        assert output['version'] == 'git version 2.56.0.windows.4'
        assert set(output['formats']) == {'sha1', 'sha256'}
        examples = {key: bytes.fromhex(value) for key, value in output['config_examples'].items()}
        assert examples['implicit'] == b'core.bare\0'
        assert examples['multiline'] == b'user.name\nline one\nline two\0'
        assert b'INCLUDED_SOURCE_MUST_NOT_LOAD' not in examples['include']
        assert examples['include'].startswith(b'include.path\n')
        for name in ('include', 'forbidden'):
            with pytest.raises(GitConfigError, match='KEY_NOT_ALLOWED'):
                validate_local_config_output(
                    examples[name],
                    expected_object_format='sha1',
                    expected_bare=False,
                    max_output_bytes=4096,
                    max_entries=100,
                )
        assert validate_local_config_output(
            examples['implicit'],
            expected_object_format='sha1',
            expected_bare=True,
            max_output_bytes=4096,
            max_entries=100,
        ).bare
        for format, vectors in output['formats'].items():
            config_wire = bytes.fromhex(vectors['config_output'])
            facts = validate_local_config_output(
                config_wire,
                expected_object_format=format,
                expected_bare=True,
                max_output_bytes=4096,
                max_entries=100,
            )
            assert facts.object_format == format and facts.bare
            original_config = tmp_path / ('probe-' + format + '.git') / 'config'
            with LockedConfigSource(original_config, max_file_bytes=4096) as held:
                original = held.verify()
                assert original.sha256 == vectors['config_source_sha256']
                assert config_source_sha256(original.raw, max_file_bytes=4096) == original.sha256
            assert facts.output_sha256 == hashlib.sha256(config_wire).hexdigest()
            empty_manifest = content.build_manifest(
                (),
                content_profile_version_id=1,
                format=format,
                content_tree_oid=vectors['empty_tree'],
                limits=LIMITS,
            )
            assert empty_manifest.entries == ()
            if format == 'sha1':
                assert empty_manifest.content_tree_oid == '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
            entries = []
            for index, (body, oid) in enumerate(zip(BODIES, vectors['blobs'], strict=True)):
                entry = content.ContentEntry(
                    str(index) + '.bin', '100644', oid, len(body), hashlib.sha256(body).hexdigest()
                )
                verifier = content.BlobVerifier(entry, format=format, limits=LIMITS)
                for start in range(0, len(body), 997):
                    verifier.feed(body[start : start + 997])
                assert verifier.finish() == entry
                entries.append(entry)
            # Tree was really built by fixed mktree from these exact written blobs;
            # worker also checks ls-tree and raw cat-file, never a self-reported tree.
            value = content.build_manifest(
                entries,
                content_profile_version_id=1,
                format=format,
                content_tree_oid=vectors['tree'],
                limits=LIMITS,
            )
            encoded = content.encode_manifest(value, LIMITS)
            decoded = content.decode_manifest(encoded, limits=LIMITS, expected_format=format)
            assert [asdict(entry) for entry in decoded.entries] == [
                asdict(entry) for entry in entries
            ]
            delivery = commit.build_delivery_commit(
                format=format,
                tree_oid=vectors['tree'],
                parent_oid=vectors['delivery_parent'],
                delivery_id=31,
                fixed_unix_seconds=1700000000,
                author=commit.CommitIdentity('作者', 'author@example.invalid'),
                committer=commit.CommitIdentity('控制方', 'committer@example.invalid'),
                message_template='任务{task_id}\r\n候选{candidate_id}\r结束',
                task_id=11,
                candidate_id=22,
                max_payload_bytes=16384,
            )
            assert delivery.commit_oid == vectors['delivery_commit']
            assert delivery.payload_sha256 == vectors['delivery_input_sha256']
            assert len(delivery.payload) == vectors['delivery_payload_bytes']
            assert (
                commit.verify_stored_delivery_commit(
                    delivery.payload,
                    format=format,
                    tree_oid=delivery.tree_oid,
                    parent_oid=delivery.parent_oid,
                    delivery_id=31,
                    expected_payload_sha256=delivery.payload_sha256,
                    expected_commit_oid=vectors['delivery_commit'],
                    max_payload_bytes=16384,
                )
                == delivery
            )

            references = vectors['ref_transactions']
            baseline_intent = refs.baseline_create(12, vectors['delivery_parent'], format=format)
            delivery_intent = refs.delivery_update(
                31,
                'refs/heads/vector-target',
                vectors['delivery_commit'],
                vectors['delivery_parent'],
                format=format,
            )
            assert references['baseline']['prepare_hex'] == baseline_intent.prepare_bytes().hex()
            assert (
                references['abort']['prepare_hex']
                == references['commit']['prepare_hex']
                == delivery_intent.prepare_bytes().hex()
            )
            for name, intent, terminal in (
                ('baseline', baseline_intent, 'COMMIT'),
                ('abort', delivery_intent, 'ABORT'),
                ('commit', delivery_intent, 'COMMIT'),
            ):
                raw = bytes.fromhex(references[name]['ack_hex'])
                decoder = refs.RefAckDecoder(max_output_bytes=128)
                for offset in range(0, len(raw), 3):
                    decoder.feed(raw[offset : offset + 3])
                assert decoder.finish(expected_terminal=terminal)[-1] == terminal
                observed = bytes.fromhex(references[name]['prepared_ref_hex'])
                result = refs.prepared_ref_observation(
                    observed, intent, query_exit_code=0, max_output_bytes=4096
                )
                assert result['full_ref'] == intent.full_ref
            for name in ('baseline_collision', 'expected_conflict'):
                assert references[name]['exit_code'] != 0
                reader = refs.RefAckDecoder(max_output_bytes=128)
                reader.feed(bytes.fromhex(references[name]['ack_hex']))
                assert reader.phases == ('START',)
                with pytest.raises(refs.RefProtocolError):
                    reader.finish(expected_terminal='COMMIT')
            symbolic_intent = refs.delivery_update(
                31,
                'refs/heads/vector-alias',
                vectors['delivery_parent'],
                vectors['delivery_commit'],
                format=format,
            )
            assert (
                references['symbolic_abort']['prepare_hex'] == symbolic_intent.prepare_bytes().hex()
            )
            with pytest.raises(refs.RefProtocolError, match='SYMBOLIC_TARGET'):
                refs.prepared_ref_observation(
                    bytes.fromhex(references['symbolic_abort']['prepared_ref_hex']),
                    symbolic_intent,
                    query_exit_code=0,
                    max_output_bytes=4096,
                )
            reader = refs.RefAckDecoder(max_output_bytes=128)
            reader.feed(bytes.fromhex(references['symbolic_abort']['ack_hex']))
            assert reader.finish(expected_terminal='ABORT') == ('START', 'PREPARE', 'ABORT')
            assert references['reflog_hex'] == b'WALLE:31\n'.hex()
            assert (
                references['final_ref_hex']
                == (
                    b'refs/heads/vector-target\0' + vectors['delivery_commit'].encode() + b'\0\0\n'
                ).hex()
            )
            for ref in references['checked_refs']:
                assert refs.branch_ref(ref) == ref
            observed = vectors['worktrees']
            healthy = worktrees.decode_worktrees(
                bytes.fromhex(observed['healthy_hex']),
                format=format,
                query_exit_code=0,
                max_output_bytes=65536,
            )
            branches = worktrees.decode_local_branches(
                bytes.fromhex(observed['heads_hex']),
                format=format,
                query_exit_code=0,
                max_output_bytes=65536,
            )
            assert len(healthy.entries) == 3
            assert sum(entry.bare for entry in healthy.entries) == 1
            attached = next(
                entry for entry in healthy.entries if entry.branch_ref == 'refs/heads/vector-target'
            )
            assert attached.path == observed['attached_path']
            assert attached.locked and attached.head_oid == vectors['delivery_commit']
            detached = next(entry for entry in healthy.entries if entry.detached)
            assert detached.path == observed['detached_path']
            assert detached.locked_reason == 'PRIVATE_LOCK_REASON\nSECOND_LINE'
            private = tmp_path / ('native-private-' + format)
            private.mkdir()
            assert observed['restored_hex'] == observed['healthy_hex']
            with WorktreeHeadLease(
                healthy,
                branches,
                common_directory=tmp_path / ('probe-' + format + '.git'),
                private_roots=(private,),
                max_file_bytes=4096,
                max_open_handles=4096,
            ) as held_heads:
                assert len(held_heads.verify()) == 3
                assert (
                    held_heads.verify_observation(healthy, branches)
                    == held_heads.fingerprint_sha256
                )
            worktrees.require_target_not_checked_out(healthy, branches, 'refs/heads/idle')
            with pytest.raises(worktrees.WorktreeError) as checked_out:
                worktrees.require_target_not_checked_out(
                    healthy, branches, 'refs/heads/vector-target'
                )
            assert checked_out.value.code == 'TARGET_CHECKED_OUT'
            with pytest.raises(worktrees.WorktreeError, match='NOT_DIRECT_COMMIT'):
                worktrees.decode_local_branches(
                    bytes.fromhex(observed['symbolic_heads_hex']),
                    format=format,
                    query_exit_code=0,
                    max_output_bytes=65536,
                )
            broken = worktrees.decode_worktrees(
                bytes.fromhex(observed['prunable_hex']),
                format=format,
                query_exit_code=0,
                max_output_bytes=65536,
            )
            assert len(broken.entries) == 4 and sum(entry.prunable for entry in broken.entries) == 1
            with pytest.raises(worktrees.WorktreeError, match='PRUNABLE_UNVERIFIED'):
                worktrees.require_target_not_checked_out(broken, branches, 'refs/heads/idle')
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
        assert empty, 'Owned CLI Job did not empty; this is not Guard/task STOP evidence'
