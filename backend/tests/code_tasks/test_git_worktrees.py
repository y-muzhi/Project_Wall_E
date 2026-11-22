"""Complete private Git worktree metadata, without filesystem readiness claims."""

from dataclasses import FrozenInstanceError
import pytest

from backend.app.infrastructure import git_worktrees as metadata
from backend.app.infrastructure.git_ref_protocol import branch_namespace, RefProtocolError

OID = 'a' * 40
OTHER = 'b' * 40
REF = 'refs/heads/main'


def record(path='C:/repo', head=OID, branch=REF, *, bare=False, detached=False, extra=()):
    fields = [b'worktree ' + path.encode('utf-8')]
    if bare:
        fields.append(b'bare')
    else:
        fields.append(b'HEAD ' + head.encode('ascii'))
        if branch is not None:
            fields.append(b'branch ' + branch.encode('utf-8'))
        if detached:
            fields.append(b'detached')
    return b'\0'.join(fields + list(extra)) + b'\0\0'


def parse(raw, format='sha1', **options):
    return metadata.decode_worktrees(
        raw,
        format=format,
        query_exit_code=options.get('exit', 0),
        max_output_bytes=options.get('limit', 65536),
        platform=options.get('platform', 'windows'),
    )


def branches(*pairs, format='sha1'):
    raw = b''.join(name.encode() + b'\0' + oid.encode() + b'\0commit\0\0\n' for name, oid in pairs)
    return metadata.decode_local_branches(
        raw, format=format, query_exit_code=0, max_output_bytes=65536
    )


def test_complete_bare_attached_detached_locked_prunable_and_private_reasons():
    raw = (
        record('C:/bare.git', bare=True)
        + record('C:/attached', extra=(b'locked',))
        + record(
            'C:/detached', branch=None, detached=True, extra=(b'locked PRIVATE_REASON\nLINE_TWO',)
        )
        + record('C:/missing', branch=None, detached=True, extra=(b'prunable PRIVATE_PATH',))
    )
    value = parse(raw)
    assert len(value.entries) == 4
    by_path = {entry.path: entry for entry in value.entries}
    assert by_path[r'C:\bare.git'].bare
    assert by_path[r'C:\bare.git'].head_oid is None
    assert by_path[r'C:\attached'].locked and by_path[r'C:\attached'].locked_reason is None
    assert by_path[r'C:\detached'].detached
    assert by_path[r'C:\detached'].locked_reason == 'PRIVATE_REASON\nLINE_TWO'
    assert by_path[r'C:\missing'].prunable
    assert 'PRIVATE' not in repr(value) and 'C:' not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.entries[0].bare = False


def test_fingerprint_is_order_independent_and_sensitive_to_actual_fields():
    a = record('C:/a', extra=(b'locked one',))
    b = record('C:/b', branch=None, detached=True)
    assert parse(a + b).listing_sha256 == parse(b + a).listing_sha256
    assert (
        parse(a + b).listing_sha256
        != parse(record('C:/a', extra=(b'locked two',)) + b).listing_sha256
    )
    assert (
        parse(a + b).listing_sha256
        != parse(record('C:/a', head=OTHER, extra=(b'locked one',)) + b).listing_sha256
    )


@pytest.mark.parametrize(
    'raw',
    [
        b'',
        b'worktree C:/repo\0bare\0',
        b'worktree C:/repo\0bare\n\n',
        b'\0\0',
        b'worktree C:/repo\0bare\0\0\0\0',
        b'HEAD ' + OID.encode() + b'\0worktree C:/repo\0detached\0\0',
        b'worktree\0bare\0\0',
        b'worktree \0bare\0\0',
        b'worktree C:/repo\0unknown x\0bare\0\0',
        b'worktree C:/repo\0bare true\0\0',
        b'worktree C:/repo\0bare\0bare\0\0',
        b'worktree C:/repo\0bare\0HEAD ' + OID.encode() + b'\0\0',
        b'worktree C:/repo\0HEAD\0detached\0\0',
        b'worktree C:/repo\0HEAD ' + OID.encode() + b'\0\0',
        record(branch=REF, detached=True),
        record(branch=None),
        record(head='0' * 40),
        record(head='A' * 40),
        record(extra=(b'locked', b'locked one')),
        record(extra=(b'prunable x', b'prunable y')),
        b'worktree C:/repo\0HEAD ' + OID.encode() + b'\0branch refs/heads/\xff\0\0',
    ],
)
def test_missing_ambiguous_unknown_or_bad_head_is_never_empty_success(raw):
    with pytest.raises(metadata.WorktreeError):
        parse(raw)


@pytest.mark.parametrize(
    'path',
    [
        'relative',
        '/unix',
        '//server/share',
        'C:/a/../b',
        'C:/a//b',
        'C:/CON',
        'C:/a:stream',
        'C:/trailing.',
        'C:/bad\nname',
    ],
)
def test_only_unambiguous_lexical_local_windows_paths(path):
    with pytest.raises(metadata.WorktreeError):
        parse(record(path, bare=True))


def test_paths_with_spaces_are_literal_and_duplicate_or_case_alias_fails():
    value = parse(record('C:/work tree', bare=True))
    assert value.entries[0].path == r'C:\work tree'
    for other in ('C:/work tree', 'c:/WORK TREE'):
        with pytest.raises(metadata.WorktreeError, match='ALIAS_OR_DUPLICATE'):
            parse(record('C:/work tree', bare=True) + record(other, bare=True))


def test_linux_paths_use_literal_case_and_refuse_lexical_aliases():
    first = record('/repos/Task A', bare=True)
    second = record('/repos/task a', bare=True)
    assert len(parse(first + second, platform='linux').entries) == 2
    with pytest.raises(metadata.WorktreeError, match='ALIAS_OR_DUPLICATE'):
        parse(first + first, platform='linux')
    for invalid in ('/repos//a', '/repos/../a', 'relative', '/repos/one\nother'):
        with pytest.raises(metadata.WorktreeError, match='LOCAL_PATH_INVALID'):
            parse(record(invalid, bare=True), platform='linux')


@pytest.mark.parametrize('exit_code', [None, False, True, 1, 128, -1])
def test_failed_queries_never_claim_readable_listing_or_empty_branches(exit_code):
    with pytest.raises(metadata.WorktreeError, match='QUERY_UNVERIFIED'):
        parse(record(bare=True), exit=exit_code)
    with pytest.raises(metadata.WorktreeError, match='QUERY_UNVERIFIED'):
        metadata.decode_local_branches(
            b'', format='sha1', query_exit_code=exit_code, max_output_bytes=1
        )


def test_capacity_format_and_original_bytes_type_are_strict():
    raw = record(bare=True)
    assert parse(raw, limit=len(raw)).entries[0].bare
    for limit in (None, False, 0, -1, 1.5, 2**53, len(raw) - 1):
        with pytest.raises(metadata.WorktreeError):
            parse(raw, limit=limit)
    for raw in (None, bytearray(b'x'), 'worktree C:/repo'):
        with pytest.raises(metadata.WorktreeError):
            parse(raw)
    with pytest.raises(metadata.WorktreeError):
        parse(record(bare=True), format='sha512')


def test_sha256_full_heads_and_direct_branch_union():
    oid = 'c' * 64
    listing = parse(record(head=oid), format='sha256')
    head = branches((REF, oid), ('refs/heads/idle', 'd' * 64), format='sha256')
    metadata.require_target_not_checked_out(listing, head, 'refs/heads/idle')
    with pytest.raises(metadata.WorktreeError) as caught:
        metadata.require_target_not_checked_out(listing, head, REF)
    assert caught.value.code == 'TARGET_CHECKED_OUT'


def test_locked_is_not_proof_target_is_free_and_prunable_is_not_ignored():
    actual = branches((REF, OID), ('refs/heads/idle', OTHER))
    with pytest.raises(metadata.WorktreeError, match='TARGET_CHECKED_OUT'):
        metadata.require_target_not_checked_out(
            parse(record(extra=(b'locked portable',))), actual, REF
        )
    listing = parse(
        record() + record('C:/gone', branch=None, detached=True, extra=(b'prunable missing',))
    )
    with pytest.raises(metadata.WorktreeError, match='PRUNABLE_UNVERIFIED'):
        metadata.require_target_not_checked_out(listing, actual, 'refs/heads/idle')


def test_missing_or_changed_head_branch_is_not_safe_or_latest():
    actual = branches((REF, OTHER))
    with pytest.raises(metadata.WorktreeError, match='HEAD_BRANCH_DIFFERS'):
        metadata.require_target_not_checked_out(parse(record()), actual, REF)
    with pytest.raises(metadata.WorktreeError) as caught:
        metadata.require_target_not_checked_out(parse(record()), actual, 'refs/heads/absent')
    assert caught.value.code == 'NOT_FOUND'
    with pytest.raises(metadata.WorktreeError, match='HEAD_BRANCH_DIFFERS'):
        metadata.require_target_not_checked_out(
            parse(record(branch='refs/heads/missing')), actual, REF
        )


def test_all_branch_names_and_parent_namespace_aliases_are_checked_without_content_path_rules():
    with pytest.raises(RefProtocolError):
        branch_namespace(('refs/heads/Foo/one', 'refs/heads/foo/two'))
    with pytest.raises(RefProtocolError):
        branch_namespace(('refs/heads/foo', 'refs/heads/foo/bar'))
    assert branch_namespace((REF, REF)) == (REF, REF)
    assert branch_namespace(('refs/heads/e\u0301',)) == ('refs/heads/e\u0301',)
    with pytest.raises(metadata.WorktreeError, match='BRANCH_ALIAS'):
        parse(
            record('C:/one', branch='refs/heads/Foo/one')
            + record('C:/two', branch='refs/heads/foo/two')
        )


def test_branch_lists_are_complete_direct_commit_metadata_and_sorted():
    values = branches(('refs/heads/z', OTHER), ('refs/heads/a', OID))
    assert [v.full_ref for v in values] == ['refs/heads/a', 'refs/heads/z']
    assert branches() == ()
    base = REF.encode() + b'\0' + OID.encode()
    for raw in (
        base + b'\0commit\0refs/heads/alias\0\n',
        base + b'\0tag\0\0\n',
        base + b'\0commit\0\0',
        base + b'\0commit\0\0\n' + base + b'\0commit\0\0\n',
    ):
        with pytest.raises(metadata.WorktreeError):
            metadata.decode_local_branches(
                raw, format='sha1', query_exit_code=0, max_output_bytes=65536
            )
    with pytest.raises(metadata.WorktreeError):
        branches(('refs/heads/Foo/one', OID), ('refs/heads/foo/two', OTHER))


def test_target_alias_is_rejected_instead_of_declared_free():
    listing = parse(record())
    actual = branches((REF, OID), ('refs/heads/Foo/idle', OTHER))
    with pytest.raises(metadata.WorktreeError, match='ALIAS'):
        metadata.require_target_not_checked_out(listing, actual, 'refs/heads/foo/idle')


def test_branch_metadata_of_another_object_format_is_not_bound_to_bare_listing():
    with pytest.raises(metadata.WorktreeError, match='OID_INVALID'):
        metadata.require_target_not_checked_out(
            parse(record(bare=True)), branches((REF, 'c' * 64), format='sha256'), REF
        )
