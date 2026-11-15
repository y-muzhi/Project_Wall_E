"""Prepare existing offline runtime bytes; never install, execute or admit them."""

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from . import opencode_runtime_bundle as bundle
from .content_paths import ContentPathIndex, relative_content_path
from backend.app.shared.json_canonical import canonical_input
from .windows_config_source import LockedFileSource
from .windows_local_paths import LocalPathGuard, local_absolute_path

MAX_ENTRIES = 100_000


@dataclass(frozen=True)
class PreparedRuntimeManifest:
    raw: bytes
    reference: str
    file_count: int


def prepare_runtime_manifest(root, *, deadline, cancelled):
    """Read and then revisit the exact original inventory with the existing validator."""
    root = local_absolute_path(root)

    def checkpoint():
        if cancelled() or monotonic() >= deadline:
            raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_CHECK_INTERRUPTED')

    checkpoint()
    namespace = ContentPathIndex(materialization_root=root)
    rows, identities = [], {}
    entries = total = 0
    with LocalPathGuard(root, directory=True) as original:
        identity = original.verify()
        pending = [('', root, identity)]
        while pending:
            prefix, path, expected = pending.pop()
            with LocalPathGuard(path, directory=True) as directory, os.scandir(path) as children:
                if directory.verify() != expected:
                    raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
                for child in children:
                    checkpoint()
                    entries += 1
                    if entries > MAX_ENTRIES:
                        raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_ENTRY_LIMIT')
                    name = prefix + child.name
                    relative_content_path(name)
                    target = path / child.name
                    if child.is_dir(follow_symlinks=False):
                        with LocalPathGuard(target, directory=True) as nested:
                            current = nested.verify()
                            identities[name] = current
                            pending.append((name + '/', target, current))
                        continue
                    if len(rows) >= bundle.MAX_FILES:
                        raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_FILE_LIMIT')
                    namespace.add_file(name, '100644')
                    maximum = bundle.MAX_BYTES - total
                    if name in bundle.CONTROLS:
                        maximum = min(maximum, bundle.MAX_CONTROL_BYTES)
                    with LockedFileSource(
                        target,
                        max_file_bytes=max(1, maximum),
                        capture_raw=False,
                        checkpoint=checkpoint,
                    ) as lease:
                        blob = lease.snapshot
                        total += blob.byte_count
                        if total > bundle.MAX_BYTES:
                            raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_BYTE_LIMIT')
                        identities[name] = blob.file
                        rows.append(
                            {'path': name, 'byte_count': blob.byte_count, 'sha256': blob.sha256}
                        )
                directory.verify()
        rows.sort(key=lambda row: row['path'].encode('utf-8'))
        raw = (
            canonical_input(
                {'schema_version': 1, 'configuration_policy': 'OC20-CONFIG-1', 'members': rows}
            )
            + '\n'
        ).encode('utf-8')
        if len(raw) > bundle.MAX_MANIFEST_BYTES:
            raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_TOO_LARGE')
        files, directories = bundle._inventory(raw, root, checkpoint)
        controls, _ = bundle._verify_tree(
            root, identity, files, directories, checkpoint, original=identities
        )
        bundle._verify_control_files(controls, files)
        if original.verify() != identity:
            raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
        checkpoint()
    return PreparedRuntimeManifest(
        raw, bundle.REF_PREFIX + hashlib.sha256(raw).hexdigest(), len(rows)
    )


def publish_runtime_manifest(root, destination, *, deadline, cancelled):
    """Verify a same-directory temporary manifest and atomically publish without overwrite."""
    root, destination = local_absolute_path(root), local_absolute_path(destination)
    if destination.is_relative_to(root):
        raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_MUST_BE_OUTSIDE_TREE')
    if destination.exists() or destination.is_symlink():
        raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_MANIFEST_ALREADY_EXISTS')
    prepared = prepare_runtime_manifest(root, deadline=deadline, cancelled=cancelled)
    temporary = None
    with LocalPathGuard(destination.parent, directory=True) as parent:
        original_parent = parent.verify()
        descriptor, name = tempfile.mkstemp(
            dir=destination.parent, prefix='.opencode-manifest-', suffix='.tmp'
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(prepared.raw)
                stream.flush()
                os.fsync(stream.fileno())
            count = bundle.verify_opencode_runtime_bundle(
                bundle.OpenCodeRuntimeBundle(temporary, root),
                prepared.reference,
                deadline=deadline,
                cancelled=cancelled,
            )
            if count != prepared.file_count or parent.verify() != original_parent:
                raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_DIRECTORY_CHANGED')
            if cancelled() or monotonic() >= deadline:
                raise bundle.OpenCodeRuntimeBundleError('OPENCODE_RUNTIME_CHECK_INTERRUPTED')
            # Same-volume hard-link publication is atomic and fails for an existing name.
            # Removing our temporary name leaves the original published file untouched.
            os.link(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return prepared
