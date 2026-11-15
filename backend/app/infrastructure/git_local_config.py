"""GIT20-LOCAL-1 local-config whitelist over complete fixed Git NUL output.

No Git/file/credential IO. The caller must prove successful bounded parsing of a
private copy, original metadata identity, no config.worktree and final recheck.
Only nonsecret facts escape this module, never a config key/value or remote URL.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .content_manifest import object_format


class GitConfigError(ValueError):
    code = 'REPOSITORY_UNSUPPORTED'

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _positive(value):
    if type(value) is not int or not 1 <= value <= MAX_SAFE_INTEGER:
        raise GitConfigError('GIT_CONFIG_LIMIT_INVALID')
    return value


def config_source_sha256(raw, *, max_file_bytes):
    """Bind the bounded original copy before Git; embedded NUL is unsupported."""
    limit = _positive(max_file_bytes)
    if type(raw) is not bytes or len(raw) > limit or b'\0' in raw:
        raise GitConfigError('GIT_CONFIG_SOURCE_BYTES_UNSUPPORTED')
    return hashlib.sha256(raw).hexdigest()


def _boolean(value):
    if value is None:
        return True
    lower = value.lower()
    if lower in ('true', 'yes', 'on', '1'):
        return True
    if lower in ('false', 'no', 'off', '0', ''):
        return False
    raise GitConfigError('GIT_CONFIG_BOOLEAN_UNSUPPORTED')


@dataclass(frozen=True)
class LocalConfigFacts:
    output_sha256: str
    entry_count: int
    object_format: str
    bare: bool
    repository_format_version: int


def _descriptor(key, value):
    # Only these inert descriptive keys are allowed. Subsection case is retained.
    if key in ('user.name', 'user.email'):
        if value is None:
            raise GitConfigError('GIT_CONFIG_DESCRIPTION_VALUE_REQUIRED')
        return True
    found = re.fullmatch(r'(remote|branch)\.(.+)\.([a-z][a-z0-9-]*)', key)
    if found is None:
        return False
    section, _, name = found.groups()
    allowed = ('url', 'fetch') if section == 'remote' else ('remote', 'merge', 'rebase')
    if name not in allowed:
        return False
    if name == 'rebase':
        if value is not None and value.lower() in ('merges', 'm', 'interactive', 'i'):
            return True
        _boolean(value)
    elif value is None:
        raise GitConfigError('GIT_CONFIG_DESCRIPTION_VALUE_REQUIRED')
    return True


def _records(raw, max_output_bytes, max_entries):
    if type(raw) is not bytes or len(raw) > _positive(max_output_bytes):
        raise GitConfigError('GIT_CONFIG_OUTPUT_LIMIT_OR_TYPE')
    count_limit = _positive(max_entries)
    if raw and (not raw.endswith(b'\0') or b'\0\0' in raw):
        raise GitConfigError('GIT_CONFIG_OUTPUT_INCOMPLETE')
    if raw.count(b'\0') > count_limit:
        raise GitConfigError('GIT_CONFIG_ENTRY_LIMIT_EXCEEDED')
    result = []
    for record in raw[:-1].split(b'\0') if raw else ():
        try:
            text = record.decode('utf-8', errors='strict')
        except UnicodeError:
            raise GitConfigError('GIT_CONFIG_OUTPUT_UTF8_INVALID') from None
        key, separator, value = text.partition('\n')
        if not key or any(unicodedata.category(char) == 'Cc' for char in key):
            raise GitConfigError('GIT_CONFIG_KEY_INVALID')
        result.append((key, value if separator else None))
    return result


def validate_local_config_output(
    raw, *, expected_object_format, expected_bare, max_output_bytes, max_entries
):
    """Validate completed config --file <private> --no-includes --null --list."""
    records = _records(raw, max_output_bytes, max_entries)
    count = len(records)
    try:
        format = object_format(expected_object_format)
    except ValueError:
        raise GitConfigError('GIT_CONFIG_OBJECT_FORMAT_UNSUPPORTED') from None
    if type(expected_bare) is not bool:
        raise GitConfigError('GIT_CONFIG_LAYOUT_BOOLEAN_REQUIRED')
    versions, formats, booleans = [], [], []
    for key, value in records:
        if key == 'core.repositoryformatversion':
            if value not in ('0', '1'):
                raise GitConfigError('GIT_CONFIG_REPOSITORY_FORMAT_UNSUPPORTED')
            versions.append(int(value))
        elif key == 'core.bare':
            bare = _boolean(value)
            if bare != expected_bare:
                raise GitConfigError('GIT_CONFIG_BARE_DIFFERS')
            booleans.append(bare)
        elif key in ('core.filemode', 'core.ignorecase', 'core.symlinks'):
            _boolean(value)
        elif key == 'core.logallrefupdates':
            if value is None or value.lower() != 'always':
                _boolean(value)
        elif key == 'extensions.objectformat':
            if value != format:
                raise GitConfigError('GIT_CONFIG_OBJECT_FORMAT_DIFFERS')
            formats.append(value)
        elif key == 'extensions.refstorage':
            if value != 'files':
                raise GitConfigError('GIT_CONFIG_REFERENCE_BACKEND_UNSUPPORTED')
        elif not _descriptor(key, value):
            raise GitConfigError('GIT_CONFIG_KEY_NOT_ALLOWED')
    version = versions[-1] if versions else 0
    if any(value != version for value in versions):
        raise GitConfigError('GIT_CONFIG_REPOSITORY_FORMAT_CONFLICT')
    if (not booleans and expected_bare) or (format == 'sha256' and not formats):
        raise GitConfigError('GIT_CONFIG_LAYOUT_DEFAULT_DIFFERS')
    if (formats and version != 1) or (format == 'sha256' and version != 1):
        raise GitConfigError('GIT_CONFIG_EXTENSION_VERSION_DIFFERS')
    return LocalConfigFacts(hashlib.sha256(raw).hexdigest(), count, format, expected_bare, version)


def infer_local_config_output(raw, *, expected_bare, max_output_bytes, max_entries):
    records = _records(raw, max_output_bytes, max_entries)
    formats = [value for key, value in records if key == 'extensions.objectformat']
    # SHA-1 is Git's defined files-backend default, not a model fallback.
    format = formats[-1] if formats else 'sha1'
    return validate_local_config_output(
        raw,
        expected_object_format=format,
        expected_bare=expected_bare,
        max_output_bytes=max_output_bytes,
        max_entries=max_entries,
    )
