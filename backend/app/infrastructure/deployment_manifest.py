"""Strict nonsecret primitives shared by trusted local process startup."""

import re

from backend.app.shared.strict_objects import exact

from .windows_local_paths import FileIdentity, local_absolute_path

_SHA = re.compile('[0-9a-f]{64}')


class LocalDeploymentError(RuntimeError):
    pass


def digest(value):
    if type(value) is not str or _SHA.fullmatch(value) is None or value == '0' * 64:
        raise LocalDeploymentError('CODE_DEPLOYMENT_DIGEST_REQUIRED')
    return value


def absolute_path(value):
    if type(value) is not str or value != value.strip():
        raise LocalDeploymentError('CODE_DEPLOYMENT_ABSOLUTE_PATH_REQUIRED')
    return local_absolute_path(value)


def file_identity(value, *, directory):
    value = exact(
        value, ('canonical_path', 'volume_serial', 'file_id', 'is_directory', 'filesystem')
    )
    if (
        value['is_directory'] is not directory
        or value['filesystem'] != 'NTFS'
        or type(value['volume_serial']) is not str
        or re.fullmatch('[0-9a-f]{16}', value['volume_serial']) is None
        or type(value['file_id']) is not str
        or re.fullmatch('[0-9a-f]{32}', value['file_id']) is None
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_FILE_IDENTITY_REQUIRED')
    return FileIdentity(
        str(absolute_path(value['canonical_path'])),
        value['volume_serial'],
        value['file_id'],
        directory,
        'NTFS',
    )
