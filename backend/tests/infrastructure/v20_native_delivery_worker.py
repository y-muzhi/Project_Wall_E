"""Run staged delivery against an owned repository through real Guard and Git."""

from contextlib import contextmanager
from functools import partial
from pathlib import Path
from time import monotonic
from uuid import uuid4

from backend.app.infrastructure.git_baseline_ref_transaction import (
    DeliveryRefTransaction,
    RefCommitPermit,
)
from backend.app.infrastructure.git_commit_input import (
    CommitIdentity,
    DeliveryReflogIdentity,
    build_delivery_commit,
)
from backend.app.infrastructure.git_config_command import parse_original_config_output
from backend.app.infrastructure.git_delivery_objects import delivery_object_intent
from backend.app.infrastructure.git_object_read import git_object_id
from backend.app.infrastructure.git_ref_protocol import (
    DeliveryAncestorQuery,
    delivery_update,
    exact_direct_ref_observation,
    prepared_ref_observation,
)
from backend.app.infrastructure.git_repository_location import RepositoryLocationLease
from backend.app.infrastructure.git_repository_metadata import RepositoryMetadataLease
from backend.app.infrastructure.guard_control_git_input import (
    delivery_ancestry_prepare_input,
    delivery_object_prepare_input,
    delivery_ref_prepare_input,
    delivery_target_prepare_input,
    repository_read_prepare_input,
)
from backend.app.infrastructure.guard_git_config_source import open_config_export
from backend.app.infrastructure.guard_git_metadata_source import export_metadata_directories
from backend.app.infrastructure.runtime_launch_journal import LaunchScope
from backend.app.infrastructure.windows_process import NativeProcessIdentity
from backend.app.infrastructure.windows_stdio import BackendStandardIO, GuardStdioBinding
from backend.app.shared.validation import strict_json_object
from backend.tests.infrastructure.v20_guard_control_git_pipe_worker import run_command


def exercise_owned_delivery(root, binding, send):
    original = strict_json_object((root / 'setup-result.json').read_bytes())['oid']
    format = 'sha1' if len(original) == 40 else 'sha256'
    target = 'refs/heads/loose'
    repository = root / 'repository'
    with RepositoryLocationLease(
        repository,
        private_roots=(root / 'private',),
        max_file_bytes=65536,
        max_open_handles=4096,
        max_metadata_entries=4096,
    ) as location:

        def scope(step):
            return binding.scope(71, step, uuid4().hex)

        def metadata():
            return RepositoryMetadataLease(
                location,
                format=format,
                max_entries=4096,
                max_open_handles=24000,
                max_file_bytes=65536,
                max_metadata_bytes=1024 * 1024,
            )

        def config(step):
            registered = scope(step)
            source, export = open_config_export(location, registered)
            with source:
                raw, exit_code = run_command(
                    registered,
                    partial(send, scope_override=registered),
                    export,
                    replay_release=False,
                )
                return parse_original_config_output(
                    raw,
                    location,
                    scope=registered,
                    io_nonce=raw.progress.io_nonce,
                    exit_code=exit_code,
                    max_output_bytes=4096,
                    max_entries=128,
                )

        def execute(step, parsed, maker, body=None, *, expected_exit=0):
            registered = scope(step)
            source, export = open_config_export(location, registered)
            with (
                source,
                export_metadata_directories(location, registered) as dirs,
                metadata() as tree,
            ):
                output, code = run_command(
                    registered,
                    partial(send, scope_override=registered),
                    export,
                    prepare=lambda stdio: maker(stdio, dirs, export, parsed, tree),
                    replay_release=False,
                    body=body,
                    maximum=65536,
                    expected_exit_code=expected_exit,
                )
                assert code == expected_exit and not output.stderr
                return output.stdout

        def batch(parsed, oid):
            raw = execute(
                2,
                parsed,
                partial(repository_read_prepare_input, kind='OBJECT_BATCH'),
                (oid + '\n').encode('ascii'),
            )
            header, _, body = raw.partition(b'\n')
            fields = header.split(b' ')
            assert fields[:2] == [oid.encode('ascii'), b'commit']
            assert body[-1:] == b'\n' and len(body) == int(fields[2]) + 1
            assert git_object_id(body[:-1], format=format, object_type='commit') == oid
            return body[:-1]

        parsed = config(2)
        parent = batch(parsed, original)
        assert parent.startswith(b'tree ')

        def write(kind, oid, body):
            intent = delivery_object_intent(kind, format, oid, body)
            result = execute(2, parsed, partial(delivery_object_prepare_input, intent=intent), body)
            intent.verify_output(result)

        raw = b'fixed native candidate\n'
        blob_oid = git_object_id(raw, format=format, object_type='blob')
        write('WRITE_BLOB', blob_oid, raw)
        tree = b'100644 result.txt\0' + bytes.fromhex(blob_oid)
        tree_oid = git_object_id(tree, format=format, object_type='tree')
        write('WRITE_TREE', tree_oid, f'100644 blob {blob_oid}\tresult.txt\0'.encode('ascii'))
        actor = CommitIdentity('WALL-E Native Test', 'native@example.invalid')
        commit = build_delivery_commit(
            format=format,
            tree_oid=tree_oid,
            parent_oid=original,
            delivery_id=13,
            fixed_unix_seconds=1794312000,
            author=actor,
            committer=actor,
            task_id=1,
            candidate_id=1,
            message_template='Original native delivery {task_id}',
            max_payload_bytes=4096,
        )
        write('WRITE_COMMIT', commit.commit_oid, commit.payload)
        assert batch(parsed, commit.commit_oid) == commit.payload
        ref_config = config(4)
        ref_scope = scope(4)
        send_ref = partial(send, scope_override=ref_scope)
        ref = delivery_update(13, target, commit.commit_oid, original, format=format)
        identity = DeliveryReflogIdentity(actor.name, actor.email, commit.fixed_unix_seconds)
        target_path = location._common.path / Path(target)
        source, export = open_config_export(location, ref_scope)
        with (
            source,
            export_metadata_directories(location, ref_scope) as dirs,
            BackendStandardIO(ref_scope) as stdio,
        ):
            with metadata() as pinned:
                data = delivery_ref_prepare_input(
                    stdio.begin_handoff(), dirs, export, ref_config, pinned, ref, identity
                )
                ack = send_ref('PREPARE', data=data).result
                copied = ack['stdio_binding']
                stdio.acknowledge_copy(
                    GuardStdioBinding(
                        NativeProcessIdentity(**copied['owner']),
                        LaunchScope(**copied['scope']),
                        copied['io_nonce'],
                        copied['guard_io_ref'],
                    )
                )
                stdio.release_child_copies()
                resource = ack['binding_ref']
                send_ref('CREATE_SUSPENDED', reference=resource)
            transaction = DeliveryRefTransaction(
                stdio,
                ref,
                scope=ref_scope,
                deadline=monotonic() + 40,
                cancelled=lambda: False,
                max_output_bytes=4096,
            )
            try:
                send_ref('RESUME', reference=resource)
                prepared = transaction.prepare()
                lock_path = target_path.with_name(target_path.name + '.lock')
                assert lock_path.read_bytes() == (commit.commit_oid + '\n').encode()
                observed = execute(
                    5, config(5), partial(delivery_target_prepare_input, target=target)
                )
                assert (
                    prepared_ref_observation(
                        observed,
                        ref,
                        query_exit_code=0,
                        max_output_bytes=65536,
                    )['oid']
                    == original
                )

                @contextmanager
                def gate(process):
                    assert process == prepared
                    assert target_path.read_text().strip() == original
                    yield RefCommitPermit(process)

                transaction.commit(gate)
            finally:
                transaction.close()
            observed = send_ref('OBSERVE', data={'observed_action': 'RESUME'}, reference=resource)
            assert observed.result['resource']['observation']['exit_code'] == 0
            assert send_ref('STOP', reference=resource).result['native']['fence']['stop_closed']
            assert send_ref('RELEASE', reference=resource).result['native']['cleanup_verified']
        postcheck = config(7)
        after = execute(7, postcheck, partial(delivery_target_prepare_input, target=target))
        ancestor = DeliveryAncestorQuery(format, original, commit.commit_oid)
        reverse = DeliveryAncestorQuery(format, commit.commit_oid, original)
        assert (
            execute(7, postcheck, partial(delivery_ancestry_prepare_input, ancestry=ancestor))
            == b''
        )
        assert (
            execute(
                7,
                postcheck,
                partial(delivery_ancestry_prepare_input, ancestry=reverse),
                expected_exit=1,
            )
            == b''
        )
        current = exact_direct_ref_observation(
            after,
            target,
            format,
            query_exit_code=0,
            max_output_bytes=65536,
        )
        assert current['oid'] == commit.commit_oid
        assert (
            (location._common.path / 'logs' / Path(target)).read_bytes().endswith(b'\tWALLE:13\n')
        )
        return {'target': current['oid'], 'expected': original, 'prepared_then_committed': True}
