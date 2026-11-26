"""Complete bounded Git worktree/heads metadata, never filesystem admission.

Only actual successful original command outputs are inputs. Lexical local paths
and matching HEADs do not prove original native directory/file identities.
"""

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import git_oid, object_format
from .git_ref_protocol import RefProtocolError, branch_namespace, branch_ref
from backend.app.shared.json_canonical import canonical_input
from .windows_local_paths import PathBoundaryError, local_absolute_path


class WorktreeError(ValueError):
    def __init__(self, reason, *, code='REPOSITORY_UNSUPPORTED'):
        self.reason, self.code = reason, code
        super().__init__(reason)


def _bound(raw, exit_code, maximum):
    if type(maximum) is not int or not 1 <= maximum <= MAX_SAFE_INTEGER:
        raise WorktreeError('GIT_METADATA_LIMIT_INVALID')
    if type(exit_code) is not int or exit_code != 0:
        raise WorktreeError('GIT_METADATA_QUERY_UNVERIFIED')
    if type(raw) is not bytes or len(raw) > maximum:
        raise WorktreeError('GIT_METADATA_OUTPUT_INVALID')


def _text(raw):
    try:
        return raw.decode('utf-8', errors='strict')
    except UnicodeError:
        raise WorktreeError('GIT_METADATA_UTF8_INVALID') from None


def _oid(raw, format):
    value = _text(raw)
    try:
        git_oid(value, format)
    except ValueError:
        raise WorktreeError('GIT_METADATA_OID_INVALID') from None
    if set(value) == {'0'}:
        raise WorktreeError('GIT_METADATA_UNBORN_OR_ZERO_HEAD')
    return value


def _format(value):
    try:
        return object_format(value)
    except ValueError:
        raise WorktreeError('GIT_METADATA_OBJECT_FORMAT_INVALID') from None


def _branches(values):
    try:
        return branch_namespace(values)
    except RefProtocolError:
        raise WorktreeError('GIT_METADATA_BRANCH_ALIAS_OR_FORMAT') from None


@dataclass(frozen=True)
class WorktreeRecord:
    path: str = field(repr=False)
    head_oid: str | None
    branch_ref: str | None
    bare: bool
    detached: bool
    locked: bool
    prunable: bool
    locked_reason: str | None = field(repr=False)
    prunable_reason: str | None = field(repr=False)


@dataclass(frozen=True)
class WorktreeListing:
    object_format: str
    entries: tuple[WorktreeRecord, ...]
    listing_sha256: str


@dataclass(frozen=True)
class LocalBranch:
    full_ref: str
    commit_oid: str


def _listing_path(value, platform):
    if platform == 'windows':
        return str(local_absolute_path(value))
    if (
        platform != 'linux'
        or not value.startswith('/')
        or any(part in ('', '.', '..') for part in value[1:].split('/'))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or len(value.encode('utf-8')) > 4096
    ):
        raise ValueError('Git worktree path is not absolute and canonical')
    return str(PurePosixPath(value))


def _record(fields, format, platform):
    first = fields[0]
    if not first.startswith(b'worktree ') or len(first) == 9:
        raise WorktreeError('GIT_WORKTREE_FIRST_FIELD_INVALID')
    try:
        path = _listing_path(_text(first[9:]), platform)
    except (PathBoundaryError, TypeError, ValueError):
        raise WorktreeError('GIT_WORKTREE_LOCAL_PATH_INVALID') from None
    known = {}
    for raw in fields[1:]:
        key, separator, value = raw.partition(b' ')
        if (
            key not in (b'HEAD', b'branch', b'bare', b'detached', b'locked', b'prunable')
            or key in known
        ):
            raise WorktreeError('GIT_WORKTREE_FIELD_DUPLICATE_OR_UNKNOWN')
        if key in (b'bare', b'detached') and separator:
            raise WorktreeError('GIT_WORKTREE_BOOLEAN_VALUE_INVALID')
        if key in (b'HEAD', b'branch') and (not separator or not value):
            raise WorktreeError('GIT_WORKTREE_VALUE_REQUIRED')
        known[key] = _text(value) if separator else None
    bare = b'bare' in known
    detached = b'detached' in known
    branch = known.get(b'branch')
    if bare:
        if b'HEAD' in known or branch is not None or detached:
            raise WorktreeError('GIT_WORKTREE_BARE_FIELDS_INVALID')
        head = None
    else:
        has_branch = branch is not None
        if b'HEAD' not in known or has_branch == detached:
            raise WorktreeError('GIT_WORKTREE_HEAD_MODE_INVALID')
        head = _oid(known[b'HEAD'].encode('utf-8'), format)
        if branch is not None:
            _branches((branch,))
    return WorktreeRecord(
        path,
        head,
        branch,
        bare,
        detached,
        b'locked' in known,
        b'prunable' in known,
        known.get(b'locked'),
        known.get(b'prunable'),
    )


def decode_worktrees(raw, *, format, query_exit_code, max_output_bytes, platform='windows'):
    _bound(raw, query_exit_code, max_output_bytes)
    format = _format(format)
    if not raw or not raw.endswith(b'\0\0'):
        raise WorktreeError('GIT_WORKTREE_ENUMERATION_INCOMPLETE')
    records = raw[:-2].split(b'\0\0')
    entries = []
    paths = set()
    for record in records:
        if not record:
            raise WorktreeError('GIT_WORKTREE_EMPTY_RECORD')
        entry = _record(record.split(b'\0'), format, platform)
        identity = entry.path.casefold() if platform == 'windows' else entry.path
        if identity in paths:
            raise WorktreeError('GIT_WORKTREE_PATH_ALIAS_OR_DUPLICATE')
        paths.add(identity)
        entries.append(entry)
    _branches(tuple(entry.branch_ref for entry in entries if entry.branch_ref is not None))
    ordered = tuple(sorted(entries, key=lambda entry: entry.path.encode('utf-8')))
    digest = hashlib.sha256(
        canonical_input(
            {
                'object_format': format,
                'entries': [asdict(entry) for entry in ordered],
            }
        ).encode('utf-8')
    ).hexdigest()
    return WorktreeListing(format, ordered, digest)


def decode_local_branches(raw, *, format, query_exit_code, max_output_bytes):
    """for-each-ref refs/heads/: refname NUL objectname NUL objecttype NUL symref NUL LF."""
    _bound(raw, query_exit_code, max_output_bytes)
    format = _format(format)
    if not raw:
        return ()
    # LF in a refname is invalid; NUL-LF is therefore the complete record ending.
    if not raw.endswith(b'\0\n'):
        raise WorktreeError('GIT_BRANCH_ENUMERATION_INCOMPLETE')
    entries = []
    seen = set()
    for record in raw[:-2].split(b'\0\n'):
        fields = record.split(b'\0')
        if len(fields) != 4:
            raise WorktreeError('GIT_BRANCH_FIELDS_INVALID')
        full = _text(fields[0])
        _branches((full,))
        if full in seen:
            raise WorktreeError('GIT_BRANCH_DUPLICATE')
        if fields[2] != b'commit' or fields[3]:
            raise WorktreeError('GIT_BRANCH_NOT_DIRECT_COMMIT')
        seen.add(full)
        entries.append(LocalBranch(full, _oid(fields[1], format)))
    _branches(tuple(entry.full_ref for entry in entries))
    return tuple(sorted(entries, key=lambda entry: entry.full_ref.encode('utf-8')))


def validated_branch_map(listing, branches):
    if type(listing) is not WorktreeListing or type(branches) is not tuple:
        raise WorktreeError('ORIGINAL_GIT_METADATA_REQUIRED')
    if any(type(branch) is not LocalBranch for branch in branches):
        raise WorktreeError('ORIGINAL_GIT_METADATA_REQUIRED')
    format = _format(listing.object_format)
    for branch in branches:
        if type(branch.commit_oid) is not str:
            raise WorktreeError('GIT_METADATA_OID_INVALID')
        _oid(branch.commit_oid.encode('utf-8'), format)
    refs = {branch.full_ref: branch.commit_oid for branch in branches}
    if len(refs) != len(branches):
        raise WorktreeError('GIT_BRANCH_DUPLICATE')
    _branches(tuple(refs))
    return refs


def validate_worktree_links(listing, branches):
    refs = validated_branch_map(listing, branches)
    _branches(
        tuple(refs)
        + tuple(entry.branch_ref for entry in listing.entries if entry.branch_ref is not None)
    )
    for entry in listing.entries:
        if entry.prunable:
            raise WorktreeError('GIT_WORKTREE_PRUNABLE_UNVERIFIED')
        if entry.branch_ref is not None and refs.get(entry.branch_ref) != entry.head_oid:
            raise WorktreeError('GIT_WORKTREE_HEAD_BRANCH_DIFFERS')
    return refs


def require_target_not_checked_out(listing, branches, target_ref):
    """Metadata relation check only; caller still needs all original native HEADs."""
    refs = validated_branch_map(listing, branches)
    try:
        branch_ref(target_ref)
    except RefProtocolError:
        raise WorktreeError('GIT_TARGET_BRANCH_INVALID') from None
    _branches(tuple(refs) + (target_ref,))
    if target_ref not in refs:
        raise WorktreeError('GIT_TARGET_BRANCH_MISSING', code='NOT_FOUND')
    validate_worktree_links(listing, branches)
    if any(entry.branch_ref == target_ref for entry in listing.entries):
        raise WorktreeError('GIT_TARGET_CHECKED_OUT', code='TARGET_CHECKED_OUT')
