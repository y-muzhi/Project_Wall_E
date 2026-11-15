"""Seal and verify one original CONTENT20-STORE-1 candidate package."""

import hashlib
import os
import re
import zlib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic

from backend.app.shared.time import utc_milliseconds
from backend.app.shared.validation import MAX_SAFE_INTEGER, strict_json_object

from .content_manifest import (
    CONTENT_POLICY,
    ContentEntry,
    ContentLimits,
    ContentManifest,
    _canonical,
    build_manifest,
    decode_manifest,
    encode_manifest,
    git_oid,
    manifest_sha256,
    object_format,
)
from .content_paths import materialized_path
from .content_secret_policy import load_secret_policy
from .git_commit_closure import ClosureLimits
from .git_content_command import (
    CONTENT_REF,
    ContentGitIntent,
    content_config_bytes,
)
from .git_fixed_content import reject_lfs_pointer
from .git_object_read import git_object_id, verify_git_object
from .windows_config_source import LockedFileSource
from .windows_private_package import PrivatePackageGuard
from .windows_task_workspace_tree import CandidateWorkspaceLimits, hold_candidate_workspace

_SMALL_FILE_BYTES = 4096


class ContentPackageError(RuntimeError):
    code = 'CONTENT_NOT_READY'


def _positive(value):
    return type(value) is int and 0 < value <= MAX_SAFE_INTEGER


@dataclass(frozen=True)
class CandidatePackageBinding:
    operation_id: int
    candidate_id: int
    control_generation: int
    content_store_key: str
    content_profile_version_id: int
    object_format: str

    def __post_init__(self):
        for value in (
            self.operation_id,
            self.candidate_id,
            self.control_generation,
            self.content_profile_version_id,
        ):
            if not _positive(value):
                raise ContentPackageError('CONTENT_PACKAGE_IDENTITY_INVALID')
        if (
            type(self.content_store_key) is not str
            or re.fullmatch(r'[0-9a-f]{32}', self.content_store_key) is None
        ):
            raise ContentPackageError('CONTENT_PACKAGE_STORE_KEY_INVALID')
        object_format(self.object_format)

    def package_name(self, *, staged):
        return ('.capture-' if staged else 'content-') + self.content_store_key

    def seal(self, manifest, digest, captured_at):
        return {
            'schema_version': 1,
            'operation_id': self.operation_id,
            'resource_kind': 'CANDIDATE',
            'resource_id': self.candidate_id,
            'control_generation': self.control_generation,
            'content_store_key': self.content_store_key,
            'content_policy_version': CONTENT_POLICY,
            'manifest_sha256': digest,
            'content_tree_oid': manifest.content_tree_oid,
            'captured_at': captured_at,
        }


@dataclass(frozen=True)
class TargetPackageBinding:
    operation_id: int
    plan_id: int
    control_generation: int
    content_store_key: str
    content_profile_version_id: int
    object_format: str
    target_commit: str
    target_tree: str

    def __post_init__(self):
        if not all(
            _positive(value)
            for value in (
                self.operation_id,
                self.plan_id,
                self.control_generation,
                self.content_profile_version_id,
            )
        ):
            raise ContentPackageError('TARGET_PACKAGE_IDENTITY_INVALID')
        if (
            type(self.content_store_key) is not str
            or re.fullmatch(r'[0-9a-f]{32}', self.content_store_key) is None
        ):
            raise ContentPackageError('CONTENT_PACKAGE_STORE_KEY_INVALID')
        git_oid(self.target_commit, self.object_format)
        git_oid(self.target_tree, self.object_format)

    def package_name(self, *, staged):
        return ('.capture-' if staged else 'content-') + self.content_store_key

    def seal(self, manifest, digest, captured_at):
        if manifest.content_tree_oid != self.target_tree:
            raise ContentPackageError('TARGET_PACKAGE_TREE_DIFFERS')
        return {
            'schema_version': 1,
            'operation_id': self.operation_id,
            'resource_kind': 'DELIVERY_PLAN',
            'resource_id': self.plan_id,
            'control_generation': self.control_generation,
            'content_store_key': self.content_store_key,
            'content_policy_version': CONTENT_POLICY,
            'manifest_sha256': digest,
            'content_tree_oid': self.target_tree,
            'captured_at': captured_at,
        }


@dataclass(frozen=True)
class SealedCandidate:
    binding: CandidatePackageBinding | TargetPackageBinding
    manifest: ContentManifest
    manifest_sha256: str
    captured_at: str


class _PackageGit:
    def __init__(self, package, binding, exchange, limits, started_at, active):
        if (
            type(package) is not PrivatePackageGuard
            or package.is_control_git_read_package
            or type(binding) not in (CandidatePackageBinding, TargetPackageBinding)
            or type(limits) is not ClosureLimits
            or limits.max_objects > 4096
            or type(started_at) not in (int, float)
            or not 0 <= started_at <= monotonic()
            or (exchange is not None and not callable(exchange))
            or not callable(active)
        ):
            raise ContentPackageError('ORIGINAL_CONTENT_PACKAGE_REQUIRED')
        if package.path.name not in (
            binding.package_name(staged=True),
            binding.package_name(staged=False),
        ):
            raise ContentPackageError('CONTENT_PACKAGE_LOCATION_DIFFERS')
        self.package = package
        self.repo = package.path / 'repo.git'
        self.binding = binding
        self.exchange = exchange
        self.limits = limits
        self.deadline = started_at + limits.max_seconds
        self.active = active
        self.format = binding.object_format
        self.identity = package.verify()
        self.output_bytes = 0

    def checkpoint(self):
        if self.active() is not None or self.package.verify() != self.identity:
            raise ContentPackageError('CONTENT_PACKAGE_CONTROL_CHANGED')
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise ContentPackageError('CONTENT_PACKAGE_DEADLINE_EXCEEDED')
        return remaining

    def run(self, kind, *, object_id=None, raw=b'', maximum=4096):
        if self.exchange is None:
            raise ContentPackageError('CONTENT_PACKAGE_GUARDED_GIT_REQUIRED')
        intent = ContentGitIntent(
            self.binding.content_store_key,
            self.format,
            kind,
            object_id,
            len(raw),
            hashlib.sha256(raw).hexdigest(),
        )
        if kind != 'INIT':
            self.package.verify_member('repo.git', directory=True)
        # Trusted transport owns the fixed program, process containment, stripped
        # environment, successful exit and bounded complete stdout/stderr.
        result = self.exchange(intent, self.repo, raw, maximum, self.checkpoint())
        self.checkpoint()
        if type(result) is not bytes or len(result) > maximum:
            raise ContentPackageError('CONTENT_PACKAGE_GIT_OUTPUT_INVALID')
        return result

    def write_blob(self, raw):
        if len(raw) > self.limits.max_object_bytes:
            raise ContentPackageError('CONTENT_PACKAGE_OBJECT_LIMIT_EXCEEDED')
        oid = git_object_id(raw, format=self.format, object_type='blob')
        result = self.run('WRITE_BLOB', raw=raw, maximum=65)
        if result != oid.encode('ascii') + b'\n':
            raise ContentPackageError('CONTENT_PACKAGE_BLOB_ID_DIFFERS')
        return oid

    def object_bound(self, maximum):
        available = self.limits.max_total_bytes - self.output_bytes
        return max(1, min(maximum, available, self.limits.max_object_bytes))

    def verify_object(self, kind, oid, maximum, raw):
        bound = self.object_bound(maximum)
        available = self.limits.max_total_bytes - self.output_bytes
        if len(raw) > maximum or len(raw) > available:
            raise ContentPackageError('CONTENT_PACKAGE_OBJECT_BYTES_EXCEEDED')
        self.output_bytes += len(raw)
        return verify_git_object(
            raw, format=self.format, object_type=kind, oid=oid, max_output_bytes=bound
        )


@dataclass(frozen=True)
class _Tree:
    oid: str
    raw: bytes
    mktree_input: bytes


def _package_trees(entries, *, format, limits):
    directories = {'': {}}
    objects = set()
    edge_count = 1
    for entry in entries:
        parent, _, filename = entry.path.rpartition('/')
        directories.setdefault(parent, {})[filename] = (entry.mode, entry.blob_oid)
        objects.add(entry.blob_oid)
        edge_count += 1
        while parent:
            ancestor, _, name = parent.rpartition('/')
            siblings = directories.setdefault(ancestor, {})
            if name in siblings:
                break
            siblings[name] = ('40000', None)
            edge_count += 1
            parent = ancestor
        if edge_count > limits.max_edges or len(objects) > limits.max_objects:
            raise ContentPackageError('CONTENT_PACKAGE_GRAPH_LIMIT_EXCEEDED')
    tree_ids, trees = {}, []
    for prefix in sorted(directories, key=lambda path: (-path.count('/'), not path, path)):
        children = directories[prefix]
        records, inputs = [], []
        for name, (mode, oid) in sorted(
            children.items(),
            key=lambda item: (item[0] + ('/' if item[1][1] is None else '')).encode(),
        ):
            directory = oid is None
            if directory:
                oid = tree_ids[(prefix + '/' if prefix else '') + name]
            encoded = name.encode('utf-8')
            records.append(mode.encode() + b' ' + encoded + b'\0' + bytes.fromhex(oid))
            kind = b'tree' if directory else b'blob'
            wire_mode = b'040000' if directory else mode.encode()
            inputs.append(wire_mode + b' ' + kind + b' ' + oid.encode() + b'\t' + encoded + b'\0')
        raw = b''.join(records)
        if len(raw) > limits.max_object_bytes:
            raise ContentPackageError('CONTENT_PACKAGE_TREE_BYTES_EXCEEDED')
        oid = git_object_id(raw, format=format, object_type='tree')
        tree_ids[prefix] = oid
        if oid not in objects:
            trees.append(_Tree(oid, raw, b''.join(inputs)))
            objects.add(oid)
        if len(objects) > limits.max_objects:
            raise ContentPackageError('CONTENT_PACKAGE_GRAPH_LIMIT_EXCEEDED')
    return tree_ids[''], tuple(trees), objects


def _static_repo_files(root_oid):
    return {
        'HEAD': b'ref: refs/heads/walle-content\n',
        CONTENT_REF: root_oid.encode('ascii') + b'\n',
    }


def _repo_inventory(git, objects, *, root_oid):
    files = _static_repo_files(root_oid)
    files['config'] = content_config_bytes(git.format)
    files.update({f'objects/{oid[:2]}/{oid[2:]}': None for oid in objects})
    directories = {
        'objects',
        'objects/info',
        'objects/pack',
        'refs',
        'refs/heads',
        'refs/tags',
        'refs/walle',
    }
    directories.update(f'objects/{oid[:2]}' for oid in objects)
    return files, directories


def _scan_inventory(git, files, directories):
    actual_files, actual_directories = set(), set()
    pending = ['']
    while pending:
        prefix = pending.pop()
        git.checkpoint()
        with os.scandir(git.repo / prefix) as entries:
            for entry in entries:
                relative = prefix + entry.name
                if relative in directories:
                    git.package.verify_member('repo.git/' + relative, directory=True)
                    actual_directories.add(relative)
                    pending.append(relative + '/')
                elif relative in files:
                    actual_files.add(relative)
                else:
                    raise ContentPackageError('CONTENT_PACKAGE_UNEXPECTED_REPOSITORY_MEMBER')
    if actual_files != files.keys() or actual_directories != directories:
        raise ContentPackageError('CONTENT_PACKAGE_MISSING_REPOSITORY_MEMBER')


@contextmanager
def _hold_repository(git, objects, *, root_oid):
    files, directories = _repo_inventory(git, objects, root_oid=root_oid)
    _scan_inventory(git, files, directories)
    with ExitStack() as handles:
        readers = {}
        for path, expected in files.items():
            git.checkpoint()
            relative = 'repo.git/' + path
            identity = git.package.verify_member(relative, directory=False)
            # zlib loose-object framing has bounded overhead over the raw object.
            maximum = min(MAX_SAFE_INTEGER, git.limits.max_object_bytes * 2 + _SMALL_FILE_BYTES)
            reader = handles.enter_context(
                LockedFileSource(
                    git.package.path / relative,
                    max_file_bytes=_SMALL_FILE_BYTES if expected is not None else maximum,
                    expected_file=identity,
                    capture_raw=expected is not None,
                    checkpoint=git.checkpoint,
                )
            )
            if expected is not None and reader.snapshot.raw != expected:
                raise ContentPackageError('CONTENT_PACKAGE_GIT_METADATA_DIFFERS')
            if expected is None:
                readers[path] = reader
        yield readers
        _scan_inventory(git, files, directories)


def _read_loose_object(reader, kind, length):
    header = kind.encode('ascii') + b' ' + str(length).encode('ascii') + b'\0'
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(reader.verified_raw(), len(header) + length + 1)
    except zlib.error as error:
        raise ContentPackageError('CONTENT_PACKAGE_LOOSE_OBJECT_INVALID') from error
    if (
        not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
        or not decoded.startswith(header)
        or len(decoded) != len(header) + length
    ):
        raise ContentPackageError('CONTENT_PACKAGE_LOOSE_OBJECT_DIFFERS')
    return decoded[len(header) :]


def _verify_repository(git, manifest, trees, objects, consume_file=None, *, through_git=False):
    with _hold_repository(git, objects, root_oid=manifest.content_tree_oid) as readers:
        if through_git:
            reference = git.run('READ_REF', maximum=256)
            expected = CONTENT_REF.encode() + b'\0' + manifest.content_tree_oid.encode() + b'\0\0\n'
            if reference != expected:
                raise ContentPackageError('CONTENT_PACKAGE_REF_DIFFERS')

        def read_object(kind, oid, length):
            maximum = git.object_bound(length)
            if maximum < length:
                raise ContentPackageError('CONTENT_PACKAGE_OBJECT_BYTES_EXCEEDED')
            git.checkpoint()
            if through_git:
                raw = git.run(
                    'READ_TREE' if kind == 'tree' else 'READ_BLOB', object_id=oid, maximum=maximum
                )
            else:
                raw = _read_loose_object(readers[f'objects/{oid[:2]}/{oid[2:]}'], kind, length)
            git.checkpoint()
            return git.verify_object(kind, oid, length, raw)

        for tree in trees:
            observed = read_object('tree', tree.oid, len(tree.raw))
            if observed.raw != tree.raw:
                raise ContentPackageError('CONTENT_PACKAGE_TREE_DIFFERS')
        checked = {}
        for entry in manifest.entries:
            digest = (entry.byte_count, entry.sha256)
            if entry.blob_oid not in checked or consume_file is not None:
                blob = read_object('blob', entry.blob_oid, entry.byte_count)
                checked[entry.blob_oid] = (blob.byte_count, blob.sha256)
                if checked[entry.blob_oid] != digest:
                    raise ContentPackageError('CONTENT_PACKAGE_BLOB_DIFFERS')
                if consume_file is not None and consume_file(entry, blob.raw) is not None:
                    raise ContentPackageError('CONTENT_PACKAGE_CONSUMER_UNVERIFIED')
            elif checked[entry.blob_oid] != digest:
                raise ContentPackageError('CONTENT_PACKAGE_BLOB_DIFFERS')


def _flush_repository(git, objects, root_oid):
    files, directories = _repo_inventory(git, objects, root_oid=root_oid)
    _scan_inventory(git, files, directories)
    # Git writes and fsyncs loose objects and the ref before making them
    # read-only. The init metadata is flushed separately by the controller.
    for path in ('HEAD', 'config'):
        git.checkpoint()
        relative = 'repo.git/' + path
        identity = git.package.verify_member(relative, directory=False)
        with (git.package.path / relative).open('r+b') as stream:
            os.fsync(stream.fileno())
        if git.package.verify_member(relative, directory=False) != identity:
            raise ContentPackageError('CONTENT_PACKAGE_MEMBER_CHANGED')


def _write_record(git, name, raw):
    git.checkpoint()
    with (git.package.path / name).open('xb') as stream:
        if stream.write(raw) != len(raw):
            raise ContentPackageError('CONTENT_PACKAGE_RECORD_WRITE_INCOMPLETE')
        stream.flush()
        os.fsync(stream.fileno())
    with _hold_record(git, name, len(raw)) as stored:
        if stored != raw:
            raise ContentPackageError('CONTENT_PACKAGE_RECORD_DIFFERS')


@contextmanager
def _hold_record(git, name, maximum):
    git.checkpoint()
    identity = git.package.verify_member(name, directory=False)
    with LockedFileSource(
        git.package.path / name, max_file_bytes=maximum, expected_file=identity, capture_raw=True
    ) as source:
        yield source.snapshot.raw
        source.verify()


def _check_package_paths(package_path, format):
    oid_length = 40 if format == 'sha1' else 64
    materialized_path(package_path, 'repo.git/objects/ab/' + '0' * (oid_length - 2))


def _check_package_members(git, expected):
    git.checkpoint()
    with os.scandir(git.package.path) as rows:
        remaining = set(expected)
        for row in rows:
            if row.name not in remaining:
                raise ContentPackageError('CONTENT_PACKAGE_UNEXPECTED_MEMBER')
            remaining.remove(row.name)
        if remaining:
            raise ContentPackageError('CONTENT_PACKAGE_MISSING_MEMBER')


def seal_candidate_package(
    package,
    binding,
    *,
    source_path,
    source_identity,
    selection,
    secret_policy,
    workspace_limits,
    git_limits,
    started_at,
    quiescent,
    exchange,
    materialization_root,
    final_quiescent=None,
):
    """Build a fresh staged package while the caller retains the original fence.

    The caller owns the persisted package key, process boundary and reconciliation.
    This operation does not publish a directory or write a candidate database row.
    """
    git = _PackageGit(package, binding, exchange, git_limits, started_at, quiescent)
    if (
        package.path.name != binding.package_name(staged=True)
        or not callable(exchange)
        or (final_quiescent is not None and not callable(final_quiescent))
        or type(workspace_limits) is not CandidateWorkspaceLimits
        or git_limits.max_seconds != workspace_limits.max_seconds
        or materialization_root is None
    ):
        raise ContentPackageError('CONTENT_PACKAGE_PREPARATION_DIFFERS')
    _check_package_paths(package.path, git.format)
    _check_package_members(git, ())
    with hold_candidate_workspace(
        source_path,
        source_identity,
        selection=selection,
        secret_policy=secret_policy,
        limits=workspace_limits,
        quiescent=quiescent,
        started_at=started_at,
    ) as source:
        git.run('INIT')
        entries = []
        for item in source.entries:
            raw = source.read(item)
            oid = git.write_blob(raw)
            entries.append(ContentEntry(item.path, item.mode, oid, item.byte_count, item.sha256))

        def source_final():
            if final_quiescent is not None and final_quiescent() is not None:
                raise ContentPackageError('CONTENT_PACKAGE_FINAL_WRITER_CHECK_UNVERIFIED')
            source.finish_capture()

        return _seal_package_tree(
            git, entries, workspace_limits.content, materialization_root, source_final
        )


def _seal_package_tree(git, entries, limits, materialization_root, verify_source):
    root, trees, objects = _package_trees(entries, format=git.format, limits=git.limits)
    binding = git.binding
    if type(binding) is TargetPackageBinding and root != binding.target_tree:
        raise ContentPackageError('TARGET_PACKAGE_TREE_DIFFERS')
    manifest = build_manifest(
        entries,
        content_profile_version_id=binding.content_profile_version_id,
        format=git.format,
        content_tree_oid=root,
        limits=limits,
        materialization_root=materialization_root,
    )
    for tree in trees:
        output = git.run('WRITE_TREE', raw=tree.mktree_input, maximum=65)
        if output != tree.oid.encode('ascii') + b'\n':
            raise ContentPackageError('CONTENT_PACKAGE_TREE_ID_DIFFERS')
    git.run('CREATE_REF', object_id=root)
    _flush_repository(git, objects, root)
    _verify_repository(git, manifest, trees, objects, through_git=True)
    raw = encode_manifest(manifest, limits, materialization_root=materialization_root)
    _write_record(git, 'manifest.json', raw)
    verify_source()
    captured_at = utc_milliseconds(datetime.now(UTC))
    digest = manifest_sha256(raw)
    _write_record(git, 'seal.json', _canonical(binding.seal(manifest, digest, captured_at)))
    _check_package_members(git, ('repo.git', 'manifest.json', 'seal.json'))
    return SealedCandidate(binding, manifest, digest, captured_at)


def seal_target_package(
    package,
    binding,
    entries,
    read_blob,
    *,
    secret_policy_ref,
    limits,
    git_limits,
    started_at,
    active,
    verify_source,
    exchange,
    materialization_root,
):
    """Seal a fixed Git tree with original commit provenance and no path filtering."""
    if (
        type(binding) is not TargetPackageBinding
        or type(limits) is not ContentLimits
        or type(entries) is not tuple
        or not callable(read_blob)
        or not callable(verify_source)
        or not callable(exchange)
        or materialization_root is None
    ):
        raise ContentPackageError('TARGET_PACKAGE_PREPARATION_REQUIRED')
    git = _PackageGit(package, binding, exchange, git_limits, started_at, active)
    if package.path.name != binding.package_name(staged=True):
        raise ContentPackageError('CONTENT_PACKAGE_LOCATION_DIFFERS')
    _check_package_paths(package.path, git.format)
    _check_package_members(git, ())
    # Validate the full path, count and byte inventory before creating any object.
    manifest = build_manifest(
        entries,
        content_profile_version_id=binding.content_profile_version_id,
        format=git.format,
        content_tree_oid=binding.target_tree,
        limits=limits,
        materialization_root=materialization_root,
    )
    if manifest.entries != entries:
        raise ContentPackageError('TARGET_PACKAGE_ENTRY_ORDER_DIFFERS')
    secret = load_secret_policy(secret_policy_ref)
    git.run('INIT')
    for item in entries:
        secret.check_path(item.path)
        git.checkpoint()
        raw = read_blob(item)
        if (
            type(raw) is not bytes
            or len(raw) != item.byte_count
            or hashlib.sha256(raw).hexdigest() != item.sha256
            or git_object_id(raw, format=git.format, object_type='blob') != item.blob_oid
        ):
            raise ContentPackageError('TARGET_PACKAGE_BLOB_DIFFERS')
        reject_lfs_pointer(raw)
        secret.check_bytes(item.path, raw)
        if git.write_blob(raw) != item.blob_oid:
            raise ContentPackageError('TARGET_PACKAGE_BLOB_DIFFERS')
    return _seal_package_tree(git, entries, limits, materialization_root, verify_source)


def verify_candidate_package(
    package,
    binding,
    *,
    limits,
    git_limits,
    started_at,
    active,
    materialization_root=None,
    expected=None,
    consume_file=None,
):
    """Reopen the exact prepared package using only its immutable bytes."""
    if (
        type(limits) is not ContentLimits
        or (consume_file is not None and not callable(consume_file))
        or (
            expected is not None
            and (type(expected) is not SealedCandidate or expected.binding != binding)
        )
    ):
        raise ContentPackageError('ORIGINAL_CONTENT_SEAL_REQUIRED')
    git = _PackageGit(package, binding, None, git_limits, started_at, active)
    _check_package_paths(package.path, git.format)
    _check_package_members(git, ('repo.git', 'manifest.json', 'seal.json'))
    with (
        _hold_record(git, 'seal.json', _SMALL_FILE_BYTES) as seal,
        _hold_record(git, 'manifest.json', limits.max_manifest_bytes) as raw,
    ):
        digest = manifest_sha256(raw)
        manifest = decode_manifest(
            raw,
            limits=limits,
            expected_sha256=digest,
            expected_format=git.format,
            expected_profile_version_id=git.binding.content_profile_version_id,
            materialization_root=materialization_root,
        )
        captured_at = _read_captured_at(seal)
        verified = SealedCandidate(binding, manifest, digest, captured_at)
        if seal != _canonical(binding.seal(manifest, digest, captured_at)) or (
            expected is not None and verified != expected
        ):
            raise ContentPackageError('CONTENT_PACKAGE_ORIGINAL_SEAL_DIFFERS')
        root, trees, objects = _package_trees(
            manifest.entries, format=git.format, limits=git.limits
        )
        if root != manifest.content_tree_oid:
            raise ContentPackageError('CONTENT_PACKAGE_ROOT_DIFFERS')
        _verify_repository(git, manifest, trees, objects, consume_file)
        _check_package_members(git, ('repo.git', 'manifest.json', 'seal.json'))
    return verified


def _read_captured_at(seal):
    try:
        captured_at = strict_json_object(seal)['captured_at']
        if (
            type(captured_at) is not str
            or utc_milliseconds(datetime.fromisoformat(captured_at)) != captured_at
        ):
            raise ValueError('Capture timestamp is not canonical')
    except (KeyError, ValueError) as error:
        raise ContentPackageError('CONTENT_PACKAGE_CAPTURE_TIME_INVALID') from error
    return captured_at
