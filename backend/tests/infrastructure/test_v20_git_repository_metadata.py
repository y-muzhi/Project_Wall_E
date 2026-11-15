"""Original files-backend namespace and bounded tree, not object-closure proof."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from backend.app.infrastructure.git_ref_metadata import (
    RefMetadataError,
    decode_loose_ref,
    decode_packed_refs,
)
from backend.app.infrastructure.git_ref_protocol import RefProtocolError
from backend.app.infrastructure.git_repository_metadata import (
    MetadataTreeError,
    RepositoryMetadataLease,
)
from backend.tests.infrastructure.test_v20_git_repository_location import (
    acquire,
    cohort,
    layout,
    write_new,
)
from backend.tests.requirements.test_v15_foundation import tmp_path


@pytest.mark.parametrize('format,length', [('sha1', 40), ('sha256', 64)])
def test_exact_packed_and_loose_refs_preserve_peeled_and_remote_symbols(format, length):
    oid = 'a' * length
    raw = (
        '# pack-refs with: peeled fully-peeled sorted \n'
        + oid
        + ' refs/heads/main\n'
        + oid
        + ' refs/tags/v1\n^'
        + oid
        + '\n'
    ).encode()
    rows = decode_packed_refs(raw, format=format, max_output_bytes=4096, max_refs=10)
    assert rows[0].name == 'refs/heads/main' and rows[1].peeled_oid == oid
    assert decode_loose_ref('refs/heads/main', (oid + '\n').encode(), format=format) == (
        'DIRECT',
        oid,
    )
    assert decode_loose_ref(
        'refs/remotes/origin/HEAD', b'ref: refs/remotes/origin/main\n', format=format
    ) == ('SYMBOLIC', 'refs/remotes/origin/main')


@pytest.mark.parametrize(
    'raw',
    [
        b'a' * 40 + b' refs/heads/main',
        b'a' * 40 + b' refs/replace/name\n',
        b'a' * 40 + b' refs/heads/main\n^' + b'b' * 40 + b'\n',
        b'^' + b'a' * 40 + b'\n',
        b'a' * 40 + b' refs/heads/main\n' + b'b' * 40 + b' refs/heads/main\n',
        b'a' * 40 + b' refs/heads/Foo\n' + b'b' * 40 + b' refs/heads/foo\n',
        b'a' * 40 + b' refs/heads/foo\n' + b'b' * 40 + b' refs/heads/foo/bar\n',
        b'a' * 40 + b' refs/heads/main\0\n',
        b'a' * 40 + b' refs/tags/x\r\n',
        b'0' * 40 + b' refs/heads/main\n',
    ],
)
def test_corrupt_packed_namespace_is_not_silently_repaired(raw):
    with pytest.raises((RefMetadataError, RefProtocolError)):
        decode_packed_refs(raw, format='sha1', max_output_bytes=4096, max_refs=10)


def test_head_symref_is_rejected_instead_of_resolved_to_an_alias():
    with pytest.raises(RefMetadataError, match='HEAD_SYMREF'):
        decode_loose_ref('refs/heads/alias', b'ref: refs/heads/main\n', format='sha1')


def metadata(location, **changes):
    return RepositoryMetadataLease(
        location,
        format='sha1',
        max_entries=changes.pop('max_entries', 1000),
        max_open_handles=changes.pop('max_open_handles', 10000),
        max_file_bytes=changes.pop('max_file_bytes', 4096),
        max_metadata_bytes=changes.pop('max_metadata_bytes', 1024 * 1024),
        **changes,
    )


def test_actual_original_tree_merges_loose_over_packed_and_requires_unchanged_listings(layout):
    write_new(
        layout.common / 'packed-refs',
        b'# pack-refs with: peeled \n' + b'a' * 40 + b' refs/heads/main\n',
    )
    write_new(layout.common / 'refs/heads/main', b'b' * 40 + b'\n')
    write_new(layout.common / 'objects/ab/binary', b'\0\xff')
    with acquire(layout) as location, metadata(location) as held:
        original = held.verify()
        assert original.heads == (('refs/heads/main', 'b' * 40),)
        with held.hold():
            with pytest.raises(MetadataTreeError, match='IN_USE'):
                held.close()
            with pytest.raises(Exception, match='IN_USE'):
                location.close()
        write_new(layout.common / 'refs/heads/new', b'a' * 40 + b'\n')
        with pytest.raises(MetadataTreeError, match='LIST_CHANGED'):
            held.verify()


def test_original_baseline_reference_resolves_loose_over_packed_without_following_symbols(layout):
    prefix = layout.common / 'refs/walle/baselines'
    prefix.mkdir(parents=True)
    write_new(
        layout.common / 'packed-refs',
        b'a' * 40
        + b' refs/walle/baselines/1\n'
        + b'a' * 40
        + b' refs/walle/baselines/2\n'
        + b'a' * 40
        + b' refs/Walle/baselines/4\n',
    )
    write_new(prefix / '2', b'b' * 40 + b'\n')
    write_new(prefix / '3', b'ref: refs/walle/baselines/1\n')
    with acquire(layout) as location, metadata(location) as held:
        packed = held.reference('refs/walle/baselines/1')
        assert (packed.kind, packed.value) == ('DIRECT', 'a' * 40)
        assert packed.file.canonical_path.endswith('packed-refs')
        loose = held.reference('refs/walle/baselines/2')
        assert (loose.kind, loose.value) == ('DIRECT', 'b' * 40)
        symbol = held.reference('refs/walle/baselines/3')
        assert (symbol.kind, symbol.value) == ('SYMBOLIC', 'refs/walle/baselines/1')
        assert held.reference('refs/walle/baselines/9') is None
        with pytest.raises(MetadataTreeError, match='REF_NAME_ALIAS'):
            held.reference('refs/walle/baselines/4')


@pytest.mark.parametrize(
    'limit,value', [('max_entries', 1), ('max_open_handles', 1), ('max_metadata_bytes', 1)]
)
def test_metadata_budgets_refuse_without_unbounded_acquisition(layout, limit, value):
    with acquire(layout) as location:
        with pytest.raises(MetadataTreeError):
            metadata(location, **{limit: value})
        assert location.verify()


def test_packed_only_replace_ref_and_head_symref_are_rejected_before_query(layout):
    write_new(layout.common / 'packed-refs', b'a' * 40 + b' refs/replace/hidden\n')
    with acquire(layout) as location:
        with pytest.raises(RefMetadataError, match='REPLACE'):
            metadata(location)
    (layout.common / 'packed-refs').unlink()
    write_new(layout.common / 'refs/heads/alias', b'ref: refs/heads/main\n')
    with acquire(layout) as location:
        with pytest.raises(RefMetadataError, match='HEAD_SYMREF'):
            metadata(location)


def test_failure_of_native_close_retains_metadata_and_location_until_retry(layout):
    from types import SimpleNamespace

    with acquire(layout) as location:
        held = metadata(location)
        original = held._kernel
        try:
            held._kernel = SimpleNamespace(CloseHandle=lambda handle: False)
            with pytest.raises(MetadataTreeError) as error:
                held.close()
            assert error.value.retained_owner is held and held._nodes and location._users == 1
        finally:
            held._kernel = original
            held.close()
        assert location._users == 0


def test_other_worktree_config_is_not_ignored(layout):
    write_new(layout.admin / 'config.worktree', b'[core]\n bare=false\n')
    with acquire(layout) as location:
        with pytest.raises(MetadataTreeError, match='UNSUPPORTED_WORKTREE'):
            metadata(location)


def test_complete_command_output_checks_original_binding_bytes_flags_and_exit():
    from dataclasses import replace
    from uuid import uuid4

    from backend.app.infrastructure.windows_pipe_capture import (
        CapturedOutput,
        OutputCaptureError,
        OutputProgress,
        require_complete_output,
    )
    from backend.tests.infrastructure.test_v20_windows_stdio import scope

    nonce = str(uuid4())
    progress = OutputProgress(scope(), nonce, 3, 0, True, True, False, None)
    output = CapturedOutput(progress, b'abc', b'')
    assert (
        require_complete_output(
            output, scope=scope(), io_nonce=nonce, exit_code=0, max_output_bytes=3
        )
        is output
    )
    for changes in [
        {'stdout_eof': 1},
        {'stderr_eof': False},
        {'limit_exceeded': True},
        {'failure_reason': 'unknown'},
        {'stdout_bytes': True},
        {'stdout_bytes': 2},
        {'scope': scope(2)},
    ]:
        with pytest.raises(OutputCaptureError):
            require_complete_output(
                replace(output, progress=replace(progress, **changes)),
                scope=scope(),
                io_nonce=nonce,
                exit_code=0,
                max_output_bytes=100,
            )
    for code in (True, 1, None):
        with pytest.raises(OutputCaptureError):
            require_complete_output(
                output, scope=scope(), io_nonce=nonce, exit_code=code, max_output_bytes=100
            )
    for invalid_nonce in ('foreign', nonce.upper(), '00000000-0000-1000-8000-000000000000'):
        with pytest.raises(OutputCaptureError):
            require_complete_output(
                output, scope=scope(), io_nonce=invalid_nonce, exit_code=0, max_output_bytes=100
            )


def test_config_format_is_inferred_then_all_existing_whitelist_rules_still_apply():
    from backend.app.infrastructure.git_local_config import (
        GitConfigError,
        infer_local_config_output,
    )

    assert (
        infer_local_config_output(
            b'core.bare\nfalse\0', expected_bare=False, max_output_bytes=4096, max_entries=10
        ).object_format
        == 'sha1'
    )
    assert (
        infer_local_config_output(
            b'core.repositoryformatversion\n1\0core.bare\nfalse\0extensions.objectformat\nsha256\0',
            expected_bare=False,
            max_output_bytes=4096,
            max_entries=10,
        ).object_format
        == 'sha256'
    )
    for raw in (
        b'extensions.objectformat\0',
        b'extensions.objectformat\nsha256\0',
        b'extensions.objectformat\nother\0',
        b'core.hooksPath\nprivate\0',
    ):
        with pytest.raises(GitConfigError):
            infer_local_config_output(
                raw, expected_bare=False, max_output_bytes=4096, max_entries=10
            )
