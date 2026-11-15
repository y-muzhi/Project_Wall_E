"""Publish one original Testing pack below the protected install-time root."""

import os
from contextlib import ExitStack, contextmanager

from backend.app.infrastructure.check_fixture import verify_fixed_members
from backend.app.infrastructure.check_runner_bundle import CheckResourceError
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_private_package import (
    PrivatePackageGuard,
    create_private_package,
)


from .pack_compile import digest


def pack_content_ref(pack_id, operation_id):
    return f'pack-{pack_id}-{operation_id}'


def _write_member(package, name, raw, checkpoint):
    destination = package.path / name
    stage_name = '.pending-' + name
    stage = package.path / stage_name
    try:
        stage.lstat()
    except FileNotFoundError:
        pass
    else:
        package.verify_member(stage_name, directory=False)
        stage.unlink()
    checkpoint()
    if destination.exists():
        return
    # This private sibling may be left by a process crash, but only the
    # no-replace rename below makes it an original member.
    try:
        with stage.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        checkpoint()
        package.verify_member(stage_name, directory=False)
        os.rename(stage, destination)
    finally:
        try:
            stage.lstat()
        except FileNotFoundError:
            pass
        else:
            package.verify_member(stage_name, directory=False)
            stage.unlink()


def _hold_member(held, package, name, expected, checkpoint):
    count = expected[0]
    member = package.verify_member(name, directory=False)
    source = held.enter_context(
        LockedFileSource(
            package.path / name,
            max_file_bytes=max(1, count),
            expected_file=member,
            capture_raw=False,
            checkpoint=checkpoint,
        )
    )
    if (source.snapshot.byte_count, source.snapshot.sha256) != expected:
        raise CheckResourceError('TESTING_PACK_ORIGINAL_MEMBER_DIFFERS')


@contextmanager
def hold_published_pack(installation, compiled, operation_id, checkpoint):
    ref = pack_content_ref(compiled.pack_id, operation_id)
    root_identity = installation.pack_directory
    with PrivatePackageGuard(root_identity.canonical_path) as root:
        if root.verify() != root_identity:
            raise CheckResourceError('TESTING_PACK_ROOT_DIFFERS')
        checkpoint()
        directory = root.path / ref
        try:
            directory.lstat()
        except FileNotFoundError:
            create_private_package(directory)
        with PrivatePackageGuard(directory) as package, ExitStack() as held:
            identity = package.verify()
            if identity.volume_serial != root_identity.volume_serial:
                raise CheckResourceError('TESTING_PACK_VOLUME_DIFFERS')
            expected = {name: (len(raw), digest(raw)) for name, raw in compiled.files}
            allowed = set(expected) | {'.pending-' + name for name in expected}
            with os.scandir(package.path) as listing:
                for entry in listing:
                    if entry.name not in allowed:
                        raise CheckResourceError('TESTING_PACK_UNRECOGNIZED_MEMBER')
            # The manifest is committed only after every constituent member.
            for name, raw in compiled.files:
                _write_member(package, name, raw, checkpoint)
                _hold_member(held, package, name, expected[name], checkpoint)
            verify_fixed_members(package, identity, expected, checkpoint)
            if root.verify() != root_identity:
                raise CheckResourceError('TESTING_PACK_ROOT_CHANGED')
            yield ref


@contextmanager
def hold_sealed_pack(installation, compiled, original_operation, checkpoint):
    """Read an already published, exact sealed closure without modifying it."""
    reference = pack_content_ref(compiled.pack_id, original_operation)
    original = installation.pack_directory
    with PrivatePackageGuard(original.canonical_path) as root:
        if root.verify() != original:
            raise CheckResourceError('TESTING_PACK_ROOT_DIFFERS')
        with PrivatePackageGuard(root.path / reference) as package, ExitStack() as held:
            directory = package.verify()
            if directory.volume_serial != original.volume_serial:
                raise CheckResourceError('TESTING_PACK_VOLUME_DIFFERS')
            expected = {name: (len(raw), digest(raw)) for name, raw in compiled.files}
            for name, facts in expected.items():
                _hold_member(held, package, name, facts, checkpoint)
            verify_fixed_members(package, directory, expected, checkpoint)
            if root.verify() != original:
                raise CheckResourceError('TESTING_PACK_ROOT_CHANGED')
            yield reference
