"""Build and atomically publish immutable Schema200 resources and a real code pin.

This prepares repository resources only. It never opens a user database or
activates/upgrades an application service. Existing release directories remain.
"""

import argparse
import os
from pathlib import Path
import re
import shutil
from tempfile import mkdtemp, NamedTemporaryFile

from .database import SchemaMismatch
from .schema_v20_release import (
    build_candidate,
    digest,
    _load_verified_release,
    RELEASE_PARENT,
)
from .sqlite_runtime import require_active

PIN_PATH = Path(__file__).with_name('schema_v20_admission.py')


def _pin_bytes(release_id, manifest_sha256):
    return (
        '"""Generated Schema200 resource pin; prepare a new release to change it."""\n\n'
        + 'RELEASE_DIRECTORY = '
        + repr(release_id)
        + '\n'
        + 'MANIFEST_SHA256 = '
        + repr(manifest_sha256)
        + '\n'
    ).encode('utf-8')


def _save_pin(data, expected):
    target = PIN_PATH
    temporary = None
    ending = b'\r\n' if expected is not None and b'\r\n' in expected else b'\n'
    content = data.replace(b'\r\n', b'\n').replace(b'\n', ending)
    mode = target.stat().st_mode if expected is not None else None
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix='.schema-pin-', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        actual = target.read_bytes() if target.exists() else None
        if actual != expected:
            raise SchemaMismatch('Schema pin changed concurrently; preserve published resources')
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def publish_release(release_id):
    require_active()
    if type(release_id) is not str or re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', release_id) is None:
        raise ValueError('A bounded explicit release identity is required')
    destination = RELEASE_PARENT / release_id
    if destination.exists() or destination.is_symlink():
        raise SchemaMismatch('A new immutable schema release directory is required')
    expected_pin = PIN_PATH.read_bytes() if PIN_PATH.exists() else None
    files = build_candidate(release_id)
    manifest_sha256 = digest(files['manifest.json'])
    RELEASE_PARENT.mkdir(exist_ok=True)
    staged = Path(mkdtemp(prefix='.schema-stage-', dir=RELEASE_PARENT))
    try:
        for name, data in files.items():
            with (staged / name).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        candidate = _load_verified_release(staged, manifest_sha256)
        if candidate.release_id != release_id:
            raise SchemaMismatch('Published schema identity differs')
        # Windows same-filesystem rename never replaces an existing directory.
        # No cross-volume move/copy fallback and no overwrite/merge.
        if os.name != 'nt':
            raise SchemaMismatch('Atomic non-replacing Windows release publication is required')
        os.rename(staged, destination)
        _load_verified_release(destination, manifest_sha256)
        # The compiled pin is the LAST atomic publication. A prior pin is intact
        # on failure; the new immutable unreferenced directory is retained.
        _save_pin(_pin_bytes(release_id, manifest_sha256), expected_pin)
        return candidate
    finally:
        if staged.exists():
            # Staged schema resources contain no normal data; not maintenance assets.
            resolved = staged.resolve(strict=True)
            if (
                resolved.parent != RELEASE_PARENT.resolve(strict=True)
                or staged.is_symlink()
                or staged.is_junction()
                or not staged.name.startswith('.schema-stage-')
            ):
                raise SchemaMismatch('Staging cleanup path is outside the owned release directory')
            shutil.rmtree(resolved)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Prepare immutable Schema200 repository resources; no database maintenance'
    )
    parser.add_argument('--release-id', required=True)
    arguments = parser.parse_args(argv)
    release = publish_release(arguments.release_id)
    print('Schema200 ' + release.release_id + '; manifest SHA256 ' + release.manifest_sha256)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
