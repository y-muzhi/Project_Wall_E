"""Strict nonsecret config facts; original native copy/parse still required."""

from dataclasses import asdict
import hashlib
import pytest

from backend.app.infrastructure.git_local_config import GitConfigError, validate_local_config_output


def check(raw, format='sha1', bare=False, limit=4096, entries=100):
    return validate_local_config_output(
        raw,
        expected_object_format=format,
        expected_bare=bare,
        max_output_bytes=limit,
        max_entries=entries,
    )


def test_successful_empty_and_nonsecret_defaults_and_output_identity():
    result = check(b'')
    assert result.object_format == 'sha1' and result.bare is False
    assert result.entry_count == result.repository_format_version == 0
    raw = (
        b'core.repositoryformatversion\n0\0core.bare\nfalse\0'
        b'user.name\nPRIVATE_USER\0remote.origin.url\nhttps://PRIVATE_PASSWORD@example.invalid/x\0'
        b'remote.origin.fetch\n+refs/heads/*:refs/remotes/origin/*\0'
        b'remote.origin.fetch\n+refs/tags/*:refs/tags/*\0'
        b'branch.main.remote\norigin\0branch.main.merge\nrefs/heads/main\0'
    )
    result = check(raw)
    assert result.output_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.entry_count == 8
    assert 'PRIVATE' not in repr(result)
    assert set(asdict(result)) == {
        'output_sha256',
        'entry_count',
        'object_format',
        'bare',
        'repository_format_version',
    }


@pytest.mark.parametrize('value', [b'true', b'YES', b'on', b'1', None])
def test_standard_true_and_implicit_boolean(value):
    record = b'core.bare' + (b'' if value is None else b'\n' + value) + b'\0'
    assert check(record, bare=True).bare
    with pytest.raises(GitConfigError, match='BARE_DIFFERS'):
        check(record, bare=False)


@pytest.mark.parametrize('value', [b'false', b'NO', b'off', b'0', b''])
def test_standard_false_and_empty_are_not_missing(value):
    raw = b'core.bare\n' + value + b'\0'
    assert check(raw).bare is False
    with pytest.raises(GitConfigError, match='BARE_DIFFERS'):
        check(raw, bare=True)


@pytest.mark.parametrize(
    'key',
    [
        'include.path',
        'includeif.gitdir:private.path',
        'core.worktree',
        'core.hookspath',
        'core.fsmonitor',
        'extensions.worktreeconfig',
        'extensions.unknown',
        'credential.helper',
        'alias.x',
        'filter.lfs.clean',
        'gpg.program',
        'commit.gpgsign',
        'remote.origin.uploadpack',
        'remote.origin.proxy',
        'branch.main.mergeoptions',
        'core.pager',
        'safe.directory',
        'protocol.allow',
        'user.signingkey',
    ],
)
def test_all_unknown_execution_path_include_or_signing_keys_fail_without_echo(key):
    marker = 'PRIVATE_SECRET_URL_VALUE'
    with pytest.raises(GitConfigError) as caught:
        check((key + '\n' + marker + '\0').encode())
    assert str(caught.value) == 'GIT_CONFIG_KEY_NOT_ALLOWED'
    assert key not in str(caught.value) and marker not in str(caught.value)


@pytest.mark.parametrize(
    'raw,format,bare',
    [
        (b'extensions.objectformat\nsha256\0', 'sha256', False),
        (b'core.repositoryformatversion\n1\0', 'sha256', False),
        (b'core.repositoryformatversion\n0\0extensions.objectformat\nsha256\0', 'sha256', False),
        (b'core.repositoryformatversion\n2\0', 'sha1', False),
        (b'extensions.objectformat\nsha1\0', 'sha1', False),
        (b'core.repositoryformatversion\n1\0extensions.objectformat\nsha256\0', 'sha1', False),
        (b'core.repositoryformatversion\n0\0core.repositoryformatversion\n1\0', 'sha1', False),
        (b'core.bare\ntrue\0core.bare\nfalse\0', 'sha1', False),
        (b'extensions.refstorage\nreftable\0', 'sha1', False),
        (b'', 'sha1', True),
    ],
)
def test_conflicts_never_hide_behind_last_value_or_defaults(raw, format, bare):
    with pytest.raises(GitConfigError):
        check(raw, format, bare)


def test_sha256_files_layout_and_approved_inert_values():
    raw = (
        b'core.repositoryformatversion\n1\0core.bare\ntrue\0extensions.objectformat\nsha256\0'
        b'extensions.refstorage\nfiles\0core.filemode\nfalse\0core.ignorecase\ntrue\0'
        b'core.symlinks\0core.logallrefupdates\nalways\0'
        b'branch.Topic/A.rebase\nmerges\0branch.Topic/B.rebase\ni\0'
        b'user.name\nline one\nline two\0'
    )
    result = check(raw, 'sha256', True)
    assert result.object_format == 'sha256' and result.repository_format_version == 1
    assert result.entry_count == 11
    assert 'line one' not in repr(result)


@pytest.mark.parametrize(
    'raw',
    [
        b'\0',
        b'\0\0',
        b'core.bare\nfalse',
        b'core.bare\nfalse\0\0',
        b'\nfalse\0',
        b'user.name\n\xff\0',
        b'core.bare\nmaybe\0',
        b'core.bare\n2\0',
        b'core.bare\n false\0',
        b'user.name\0',
        b'core.repositoryformatversion\0',
        b'core.repositoryformatversion\n01\0',
        b'Core.bare\nfalse\0',
        b'branch..merge\nmain\0',
    ],
)
def test_bad_output_or_unapproved_values_fail_as_fixed_reason(raw):
    with pytest.raises(GitConfigError):
        check(raw)


def test_capacity_is_bounded_before_decoding_and_limits_are_strict():
    raw = b'user.name\nx\0'
    assert check(raw, limit=len(raw), entries=1).entry_count == 1
    for kwargs in (
        {'limit': len(raw) - 1},
        {'entries': 1, 'limit': True},
        {'entries': 0},
        {'limit': 0},
        {'format': 'sha512'},
        {'bare': 0},
    ):
        with pytest.raises(GitConfigError):
            check(raw, **kwargs)
    with pytest.raises(GitConfigError, match='ENTRY_LIMIT'):
        check(raw + raw, entries=1)
    with pytest.raises(GitConfigError):
        check(bytearray(raw))


def test_source_bytes_are_bounded_and_nul_cannot_forge_output_records():
    from backend.app.infrastructure.git_local_config import config_source_sha256

    raw = b'[core]\n bare=false\n'
    assert config_source_sha256(raw, max_file_bytes=len(raw)) == hashlib.sha256(raw).hexdigest()
    assert config_source_sha256(b'', max_file_bytes=1) == hashlib.sha256(b'').hexdigest()
    for raw, limit in (
        (b'user.name=x\0core.bare=true', 100),
        (b'x', 0),
        (b'xx', 1),
        (bytearray(b'x'), 1),
    ):
        with pytest.raises(GitConfigError):
            config_source_sha256(raw, max_file_bytes=limit)
