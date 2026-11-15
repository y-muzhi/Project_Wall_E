"""Canonical fixed program inventories shared by backend and RuntimeGuard packages."""

import hashlib
from dataclasses import dataclass

from backend.app.shared.validation import strict_json_object

from .content_paths import ContentPathIndex, relative_content_path
from .runtime_launch_journal import _bytes, _hex, _resource

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MEMBERS = 4096
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class ProgramManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgramPolicy:
    kind: str
    version: str
    manifest_name: str
    entry_name: str


BACKEND_PROGRAM_POLICY = ProgramPolicy(
    'BACKEND', 'BACKEND20-PROTECTED-1', 'backend-program.v1.json', 'walle-backend.exe'
)
GUARD_PROGRAM_POLICY = ProgramPolicy(
    'GUARD', 'GUARD20-PROTECTED-1', 'guard-program.v1.json', 'walle-runtime-guard.exe'
)


@dataclass(frozen=True)
class ProgramFile:
    path: str
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class ProgramSpec:
    program_ref: str
    entry: str
    files: tuple[ProgramFile, ...]
    manifest_sha256: str

    @property
    def directories(self):
        result = set()
        for item in self.files:
            parts = item.path.split('/')
            result.update('/'.join(parts[:count]) for count in range(1, len(parts)))
        return frozenset(result)


def decode_program_manifest(raw, *, expected_sha256, policy, error_type=ProgramManifestError):
    _hex(expected_sha256)
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_MANIFEST_BYTES:
        raise error_type(f'{policy.kind}_PROGRAM_MANIFEST_SIZE_INVALID')
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise error_type(f'{policy.kind}_PROGRAM_MANIFEST_DIGEST_DIFFERS')
    value = strict_json_object(raw)
    if (
        set(value) != {'policy_version', 'program_ref', 'entry', 'files'}
        or value['policy_version'] != policy.version
        or type(value['entry']) is not str
    ):
        raise error_type(f'REGISTERED_{policy.kind}_PROGRAM_MANIFEST_REQUIRED')
    _resource(value['program_ref'])
    entry = relative_content_path(value['entry'])
    if entry.split('/')[-1] != policy.entry_name:
        raise error_type(f'DEDICATED_REGISTERED_{policy.kind}_EXECUTABLE_REQUIRED')
    if policy.kind == 'GUARD' and entry != policy.entry_name:
        raise error_type('DEDICATED_REGISTERED_GUARD_EXECUTABLE_REQUIRED')
    rows = value['files']
    if type(rows) is not list or not 1 <= len(rows) <= MAX_MEMBERS:
        raise error_type(f'{policy.kind}_PROGRAM_MEMBER_LIMIT')
    namespace = ContentPathIndex()
    namespace.add_file(policy.manifest_name, '100644')
    members = []
    total = 0
    for row in rows:
        if type(row) is not dict or set(row) != {'path', 'byte_count', 'sha256'}:
            raise error_type(f'{policy.kind}_PROGRAM_MEMBER_FIELDS_INVALID')
        path = namespace.add_file(row['path'], '100644').path
        size = row['byte_count']
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise error_type(f'{policy.kind}_PROGRAM_MEMBER_SIZE_INVALID')
        total += size
        if total > MAX_TOTAL_BYTES:
            raise error_type(f'{policy.kind}_PROGRAM_TOTAL_SIZE_LIMIT')
        members.append(ProgramFile(path, size, _hex(row['sha256'])))
    if (
        members != sorted(members, key=lambda member: member.path.encode('utf-8'))
        or entry not in {member.path for member in members}
        or _bytes(value) != raw
    ):
        raise error_type(f'{policy.kind}_PROGRAM_MANIFEST_NOT_CANONICAL')
    return ProgramSpec(value['program_ref'], entry, tuple(members), expected_sha256)
