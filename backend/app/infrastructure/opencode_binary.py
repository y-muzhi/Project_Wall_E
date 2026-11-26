"""Verify the fixed official OpenCode binary without installing or executing it."""

import hashlib
import io
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from stat import S_IFMT, S_IFREG
from time import monotonic
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from .opencode_runtime_bundle import OpenCodeRuntimeBundle
from .windows_config_source import LockedFileSource
from .windows_executable_pin import PE_HEADER_LIMIT, READ_CHUNK, ExecutablePin, _pe_x64
from .windows_local_paths import local_absolute_path

VERSION = '1.19.5'
RELEASE_SHA256 = '09a6e693157f0887e504f2cf4357a8cbddc5ead5d0dffb9a269dcc47c48640f5'
IMAGE_SHA256 = 'd7b473388cb62555970e400ce54cdfb6d6573608beea6f8fdf382cd1a698a3fa'
ARCHIVE_NAME = 'opencode-windows-x64.zip'
IMAGE_NAME = 'opencode.exe'
MAX_ARCHIVE_BYTES = 96 * 1024 * 1024
MAX_IMAGE_BYTES = 512 * 1024 * 1024


class OpenCodeBinaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenCodeBinarySource:
    """Trusted deployment paths and the two immutable configuration references."""

    archive: Path = field(repr=False)
    image: Path = field(repr=False)
    binary_ref: str
    runtime_bundle_ref: str
    openapi: Path | None = field(default=None, repr=False)
    bundle: OpenCodeRuntimeBundle | None = field(default=None, repr=False)

    def __post_init__(self):
        archive = local_absolute_path(self.archive)
        image = local_absolute_path(self.image)
        if archive.name.casefold() != ARCHIVE_NAME or image.name.casefold() != IMAGE_NAME:
            raise OpenCodeBinaryError('OPENCODE_FIXED_BINARY_NAMES_REQUIRED')
        if any(
            type(value) is not str or not value.strip() or value != value.strip()
            for value in (self.binary_ref, self.runtime_bundle_ref)
        ):
            raise OpenCodeBinaryError('OPENCODE_FIXED_INSTALLATION_REFS_REQUIRED')
        object.__setattr__(self, 'archive', archive)
        object.__setattr__(self, 'image', image)
        if self.openapi is not None:
            object.__setattr__(self, 'openapi', local_absolute_path(self.openapi))
        if self.bundle is not None and type(self.bundle) is not OpenCodeRuntimeBundle:
            raise OpenCodeBinaryError('OPENCODE_RUNTIME_BUNDLE_SOURCE_REQUIRED')

    def matches(self, executor):
        return (
            executor['version'] == VERSION
            and executor['binary_ref'] == self.binary_ref
            and executor['runtime_bundle_ref'] == self.runtime_bundle_ref
        )


@dataclass(frozen=True)
class OpenCodeArchiveImage:
    byte_count: int
    sha256: str


def _checkpoint(deadline, cancelled):
    if cancelled() or monotonic() >= deadline:
        raise OpenCodeBinaryError('OPENCODE_BINARY_CHECK_CANCELLED_OR_EXPIRED')


def verify_opencode_archive(path, *, deadline, cancelled):
    """Return the exact executable member proof from the fixed official archive."""
    _checkpoint(deadline, cancelled)
    path = local_absolute_path(path)
    with LockedFileSource(path, max_file_bytes=MAX_ARCHIVE_BYTES) as source:
        snapshot = source.snapshot
        if snapshot.sha256 != RELEASE_SHA256:
            raise OpenCodeBinaryError('OPENCODE_OFFICIAL_ARCHIVE_DIGEST_DIFFERS')
        try:
            with ZipFile(io.BytesIO(snapshot.raw)) as archive:
                _checkpoint(deadline, cancelled)
                matches = [
                    row for row in archive.infolist() if row.filename.casefold() == IMAGE_NAME
                ]
                if len(matches) != 1:
                    raise OpenCodeBinaryError('OPENCODE_ARCHIVE_IMAGE_NOT_UNIQUE')
                (entry,) = matches
                if (
                    entry.filename != IMAGE_NAME
                    or entry.is_dir()
                    or entry.flag_bits & 1
                    or entry.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                    or S_IFMT(entry.external_attr >> 16) not in (0, S_IFREG)
                    or not 1 <= entry.file_size <= MAX_IMAGE_BYTES
                ):
                    raise OpenCodeBinaryError('OPENCODE_ARCHIVE_IMAGE_UNSUPPORTED')
                digest = hashlib.sha256()
                count = 0
                header = bytearray()
                with archive.open(entry) as raw:
                    while chunk := raw.read(READ_CHUNK):
                        _checkpoint(deadline, cancelled)
                        count += len(chunk)
                        if count > entry.file_size:
                            raise OpenCodeBinaryError('OPENCODE_ARCHIVE_IMAGE_SIZE_DIFFERS')
                        digest.update(chunk)
                        remaining = PE_HEADER_LIMIT + 26 - len(header)
                        if remaining > 0:
                            header.extend(chunk[:remaining])
                if count != entry.file_size:
                    raise OpenCodeBinaryError('OPENCODE_ARCHIVE_IMAGE_SIZE_DIFFERS')
                _pe_x64(header, count)
                _checkpoint(deadline, cancelled)
                return OpenCodeArchiveImage(count, digest.hexdigest())
        except BadZipFile as error:
            raise OpenCodeBinaryError('OPENCODE_ARCHIVE_INVALID') from error


def pin_opencode_binary(source, executor, *, deadline, cancelled):
    if type(source) is not OpenCodeBinarySource or not source.matches(executor):
        raise OpenCodeBinaryError('OPENCODE_BINARY_INSTALLATION_DIFFERS')
    member = verify_opencode_archive(source.archive, deadline=deadline, cancelled=cancelled)
    _checkpoint(deadline, cancelled)
    return ExecutablePin(
        source.image, expected_byte_count=member.byte_count, expected_sha256=member.sha256
    )


@contextmanager
def open_opencode_binary(source, executor, *, deadline, cancelled):
    """Retain the actual installation image as the proven ZIP member."""
    with pin_opencode_binary(source, executor, deadline=deadline, cancelled=cancelled) as image:
        _checkpoint(deadline, cancelled)
        yield image
