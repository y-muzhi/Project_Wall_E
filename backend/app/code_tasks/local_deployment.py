"""Pinned local startup configuration, never HTTP input or runtime admission."""

import os
import re
from contextlib import ExitStack, contextmanager
from dataclasses import fields
from time import monotonic

from backend.app.infrastructure.deployment_manifest import (
    LocalDeploymentError,
    absolute_path,
    digest,
)
from backend.app.infrastructure.windows_config_source import ConfigReadError, LockedFileSource
from backend.app.infrastructure.windows_executable_pin import ExecutablePin, ExecutablePinError
from backend.app.infrastructure.windows_guard_pipe import pipe_name
from backend.app.infrastructure.windows_local_paths import (
    LocalPathGuard,
    PathBoundaryError,
)
from backend.app.infrastructure.windows_private_package import (
    PackageSecurityError,
    current_operator_sid,
)
from backend.app.infrastructure.windows_process import ObservedProcess, ProcessObservationError
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_integer, strict_json_object

from .repository_git_runner import RegistrationReadLimits
from .repository_registration_worker import RegistrationInstallation

MANIFEST_ENV = 'WALLE_CODE_DEPLOYMENT_MANIFEST'
DIGEST_ENV = 'WALLE_CODE_DEPLOYMENT_SHA256'
PROTOCOL = 'DEPLOY20-BACKEND-1'
PROTOCOL_V2 = 'DEPLOY20-BACKEND-2'
MAX_BYTES = 2 * 1024 * 1024
_SID = re.compile(r'S-1-(?:5-21(?:-[0-9]+){4}|12-1(?:-[0-9]+){4})')


def _registration(value, backend_sid):
    value = exact(
        value,
        (
            'installation_ref',
            'backend_sid',
            'guard_image',
            'journal_root',
            'private_roots',
            'limits',
            'workspace_root',
        ),
    )
    if (
        type(value['backend_sid']) is not str
        or _SID.fullmatch(value['backend_sid']) is None
        or value['backend_sid'] != backend_sid
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_BACKEND_DIFFERS')
    reference = value['installation_ref']
    pipe_name(reference)
    image = exact(value['guard_image'], ('path', 'byte_count', 'sha256'))
    size = strict_integer(image['byte_count'], 'guard_image.byte_count', maximum=512 * 1024 * 1024)
    roots = value['private_roots']
    if type(roots) is not list or len(roots) > 64:
        raise LocalDeploymentError('CODE_DEPLOYMENT_PRIVATE_ROOTS_REQUIRED')
    roots = tuple(absolute_path(path) for path in roots)
    if len(set(roots)) != len(roots):
        raise LocalDeploymentError('CODE_DEPLOYMENT_PRIVATE_ROOTS_DUPLICATED')
    names = tuple(field.name for field in fields(RegistrationReadLimits))
    limits = exact(value['limits'], names)
    limits = RegistrationReadLimits(**{name: strict_integer(limits[name], name) for name in names})
    return RegistrationInstallation(
        reference,
        backend_sid,
        absolute_path(image['path']),
        size,
        digest(image['sha256']),
        absolute_path(value['journal_root']),
        roots,
        limits,
        workspace_root=None
        if value['workspace_root'] is None
        else absolute_path(value['workspace_root']),
    )


def decode_local_deployment(raw, *, backend_sid, environment=None):
    """Build the existing private installation from strictly bounded, nonsecret bytes."""
    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
            raise LocalDeploymentError('CODE_DEPLOYMENT_SIZE_REQUIRED')
        value = strict_json_object(raw)
        version = value.get('schema_version')
        if (
            type(version) is not int
            or version not in (1, 2)
            or value.get('protocol_version') != (PROTOCOL if version == 1 else PROTOCOL_V2)
        ):
            raise LocalDeploymentError('CODE_DEPLOYMENT_VERSION_DIFFERS')
        names = ('schema_version', 'protocol_version', 'registration', 'task')
        if version == 1:
            exact(value, names)
        else:
            exact(value, (*names, 'checks', *(('models',) if 'models' in value else ())))
        installation = _registration(value['registration'], backend_sid)
        if value['task'] is not None:
            from .task_deployment_configuration import decode_task_deployment

            installation = decode_task_deployment(value['task'], installation)
        if version == 2 and value['checks'] is not None:
            from .check_deployment_configuration import decode_check_deployment

            installation = decode_check_deployment(value['checks'], installation)
        if version == 2 and value.get('models') is not None:
            from .model_deployment_configuration import decode_model_deployment

            installation = decode_model_deployment(
                value['models'], installation, environment=environment
            )
        return installation
    except LocalDeploymentError:
        raise
    except (TypeError, ValueError, RuntimeError) as error:
        if getattr(error, 'retained_owner', None) is not None:
            raise
        raise LocalDeploymentError('CODE_DEPLOYMENT_INVALID') from None


def _current_backend_sid():
    with ObservedProcess(os.getpid()) as process:
        observed = process.observe()
        identity = observed.identity
        if (
            observed.state != 'RUNNING'
            or identity.is_elevated
            or identity.is_appcontainer
            or identity.appcontainer_sid is not None
            or identity.is_lpac is not False
            or identity.user_sid != current_operator_sid()
        ):
            raise LocalDeploymentError('CODE_DEPLOYMENT_BACKEND_IDENTITY_REQUIRED')
        return identity.user_sid


@contextmanager
def hold_configured_deployment(environ=None):
    """Pin the explicit deployment source until the original application has stopped."""
    environment = os.environ if environ is None else environ
    manifest, expected = environment.get(MANIFEST_ENV), environment.get(DIGEST_ENV)
    if manifest is None and expected is None:
        yield None
        return
    if manifest is None or expected is None:
        raise LocalDeploymentError('CODE_DEPLOYMENT_SOURCE_PAIR_REQUIRED')
    with ExitStack() as held:
        try:
            path, expected = absolute_path(manifest), digest(expected)
            deadline = monotonic() + 120

            def checkpoint():
                if monotonic() >= deadline:
                    raise LocalDeploymentError('CODE_DEPLOYMENT_READ_EXPIRED')

            source = held.enter_context(
                LockedFileSource(path, max_file_bytes=MAX_BYTES, checkpoint=checkpoint)
            )
            snapshot = source.snapshot
            if snapshot.sha256 != expected:
                raise LocalDeploymentError('CODE_DEPLOYMENT_SOURCE_DIGEST_DIFFERS')
            installation = decode_local_deployment(
                snapshot.raw, backend_sid=_current_backend_sid(), environment=environment
            )
            roots = {installation.journal_root, *installation.private_roots}
            if installation.workspace_root is not None:
                roots.add(installation.workspace_root)
            for root in roots:
                checkpoint()
                held.enter_context(LocalPathGuard(root, directory=True)).verify()
            held.enter_context(
                ExecutablePin(
                    installation.guard_image,
                    expected_byte_count=installation.guard_image_bytes,
                    expected_sha256=installation.guard_image_sha256,
                )
            ).verify()
            from .task_deployment_configuration import hold_task_deployment

            hold_task_deployment(held, installation, deadline=deadline)
            from .check_deployment_configuration import hold_backend_check_sources

            hold_backend_check_sources(held, installation, deadline=deadline)
            checkpoint()
        except LocalDeploymentError:
            raise
        except (
            OSError,
            ValueError,
            ConfigReadError,
            PathBoundaryError,
            PackageSecurityError,
            ProcessObservationError,
            ExecutablePinError,
            RuntimeError,
        ) as error:
            if getattr(error, 'retained_owner', None) is not None:
                raise
            raise LocalDeploymentError('CODE_DEPLOYMENT_SOURCE_UNVERIFIED') from None
        # Application errors belong to the application, not deployment parsing.
        yield installation
