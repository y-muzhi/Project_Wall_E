"""Atomically publish a new Schema210 package and its final source pin."""

import os
import re
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, mkdtemp

from .database import SchemaMismatch
from .formation_schema_release import RELEASE_PARENT, build_candidate, digest, load_verified
from .sqlite_runtime import require_active

PIN_PATH = Path(__file__).with_name('formation_schema_admission.py')


def _save_pin(content, expected):
    target = PIN_PATH
    temporary = None
    if expected is not None and b'\r\n' in expected:
        content = content.replace(b'\n', b'\r\n')
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix='.formation-pin-', suffix='.tmp', delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None:
            os.chmod(temporary, target.stat().st_mode)
        if (target.read_bytes() if target.exists() else None) != expected:
            raise SchemaMismatch('Schema210 source pin changed concurrently')
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def publish_release(release_id):
    require_active()
    if type(release_id) is not str or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', release_id) is None:
        raise ValueError('An explicit bounded immutable release identity is required')
    destination = RELEASE_PARENT / release_id
    if destination.exists() or destination.is_symlink():
        raise SchemaMismatch('A new immutable Schema210 directory is required')
    previous = PIN_PATH.read_bytes() if PIN_PATH.exists() else None
    files = build_candidate(release_id)
    manifest_hash = digest(files['manifest.json'])
    RELEASE_PARENT.mkdir(parents=True, exist_ok=True)
    staged = Path(mkdtemp(prefix='.formation-stage-', dir=RELEASE_PARENT))
    try:
        for name, content in files.items():
            with (staged / name).open('xb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        release = load_verified(staged, manifest_hash)
        if release.release_id != release_id:
            raise SchemaMismatch('Schema210 candidate identity differs')
        if os.name != 'nt':
            raise SchemaMismatch(
                'Schema210 publication requires atomic non-replacing Windows rename'
            )
        os.rename(staged, destination)
        load_verified(destination, manifest_hash)
        content = (
            '"""Generated Schema210 source pin; publish a new package to change it."""\n\n'
            + 'RELEASE_DIRECTORY = '
            + repr(release_id)
            + '\n'
            + 'MANIFEST_SHA256 = '
            + repr(manifest_hash)
            + '\n'
        ).encode('utf-8')
        _save_pin(content, previous)
        return release
    finally:
        if staged.exists():
            resolved = staged.resolve()
            if resolved.parent != RELEASE_PARENT.resolve() or not resolved.name.startswith(
                '.formation-stage-'
            ):
                raise SchemaMismatch(
                    'Refusing cleanup outside the owned Schema210 staging directory'
                )
            shutil.rmtree(resolved)
