"""Prepare registered Control Git commands under the original admitted owner."""

from dataclasses import asdict

from backend.app.shared.validation import strict_json_object

from .git_bundle import BUNDLE_PARENT, GIT_MANIFEST_SHA256
from .git_config_command import ConfigParseCommand
from .git_content_command import ContentGitCommandError, GuardContentGitCommand
from .git_metadata_command import GuardRepositoryCommand
from .guard_action_journal import GuardActionJournal
from .guard_control_git_input import PrepareControlGit, decode_control_git_action
from .guard_git_config_source import MAX_GUARD_CONFIG_BYTES, copy_original_config_source
from .guard_git_metadata_source import GuardMetadataDirectories
from .runtime_control_git import ControlGitRegistry
from .runtime_launch_journal import LaunchOutcomeUnknown
from .windows_attribute_handles import GuardAttributeHandles
from .windows_config_copy import PrivateConfigCopy
from .windows_config_source import LockedConfigSource
from .windows_empty_directory import ReadOnlyEmptyDirectory, create_readonly_empty_directory
from .windows_executable_pin import ExecutablePin
from .windows_job import OwnedJob
from .windows_local_paths import LocalPathGuard
from .windows_private_package import PrivatePackageGuard, create_control_git_read_package
from .windows_stdio import GuardStandardIO

GIT_ROOT = BUNDLE_PARENT / 'win-x64'


def _open_image():
    with LockedConfigSource(GIT_ROOT / 'manifest.json', max_file_bytes=1024 * 1024) as manifest:
        snapshot = manifest.verify()
    if snapshot.sha256 != GIT_MANIFEST_SHA256:
        raise LaunchOutcomeUnknown('REGISTERED_CONTROL_GIT_MANIFEST_DIFFERS')
    data = strict_json_object(snapshot.raw)
    member = next(row for row in data['members'] if row['path'] == 'cmd/git.exe')
    return ExecutablePin(
        GIT_ROOT / 'cmd/git.exe',
        expected_byte_count=member['byte_count'],
        expected_sha256=member['sha256'],
    )


def _private_read_package(owner, registry):
    controller = registry._controller
    parent = registry._journal._package

    def read_package():
        path = create_control_git_read_package(parent, owner.intent.directory_nonce, controller)
        return PrivatePackageGuard(path, control_git_reader=controller).__enter__()

    return owner.allocate('READ_PACKAGE', read_package)


def _original_config_source(owner, registry, export):
    return owner.allocate(
        'CONFIG_SOURCE',
        lambda: copy_original_config_source(
            registry._controller, export, scope=owner.scope, max_file_bytes=MAX_GUARD_CONFIG_BYTES
        ),
    )


def _private_config_resources(owner, registry, export):
    package = _private_read_package(owner, registry)
    source = _original_config_source(owner, registry, export)
    copied = owner.allocate('CONFIG_COPY', lambda: PrivateConfigCopy(source, package))
    empty = owner.allocate('GLOBAL_CONFIG', lambda: PrivateConfigCopy.create_empty_global(package))
    directory = owner.allocate(
        'DIRECTORY', lambda: LocalPathGuard(package.path, directory=True).__enter__()
    )
    command = owner.allocate(
        'COMMAND', lambda: ConfigParseCommand(copied, empty.empty_global_reader)
    )
    return directory, command


def _metadata_config_released(decoded, actions, binding):
    parsed = decoded.metadata.parsed
    prepared, stopped, released = (
        actions.find(parsed.scope, name) for name in ('PREPARE', 'STOP', 'RELEASE')
    )
    if any(
        record is None
        or record.phase != 'ACKNOWLEDGED'
        or record.owner_epoch != binding.owner_epoch
        for record in (prepared, stopped, released)
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_METADATA_CONFIG_ACKS_REQUIRED')
    prepare_result, stop_result, release_result = (
        record.result for record in (prepared, stopped, released)
    )
    if set(prepare_result) != {
        'binding_ref',
        'guard_run_ref',
        'stdio_binding',
        'native_receipt',
        'config_export',
    }:
        raise LaunchOutcomeUnknown('ORIGINAL_METADATA_CONFIG_COMMAND_DIFFERS')
    export = decoded.config_export
    config = prepare_result['config_export']
    if (
        config
        != {
            'file': asdict(export.file),
            'sha256': export.sha256,
            'byte_count': export.byte_count,
        }
        or prepare_result['stdio_binding'].get('io_nonce') != parsed.io_nonce
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_METADATA_CONFIG_RECEIPT_DIFFERS')
    reference = prepare_result['binding_ref']
    stop_native, release_native = stop_result['native'], release_result['native']
    observation = stop_native.get('observation')
    fence = stop_native.get('fence')
    if (
        stopped.binding_ref != reference
        or released.binding_ref != reference
        or fence is None
        or fence['stop_closed'] is not True
        or fence['resume_state'] != 'ACKNOWLEDGED'
        or observation is None
        or observation['state'] != 'EXITED'
        or type(observation['exit_code']) is not int
        or observation['exit_code'] != 0
        or release_native.get('cleanup_verified') is not True
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_METADATA_CONFIG_EXIT_OR_CLEANUP_UNVERIFIED')


def _private_metadata_resources(owner, registry, decoded):
    metadata = decoded.metadata
    controller = registry._controller
    directories = owner.allocate(
        'METADATA_DIRECTORIES',
        lambda: GuardMetadataDirectories(controller, metadata.directories, scope=owner.scope),
    )
    source = _original_config_source(owner, registry, decoded.config_export)
    package = _private_read_package(owner, registry)
    empty = owner.allocate('GLOBAL_CONFIG', lambda: PrivateConfigCopy.create_empty_global(package))
    hooks = owner.allocate(
        'HOOKS',
        lambda: ReadOnlyEmptyDirectory(
            create_readonly_empty_directory(package, 'hooks'), control_git_reader=controller
        ),
    )
    directory = owner.allocate(
        'DIRECTORY', lambda: LocalPathGuard(package.path, directory=True).__enter__()
    )
    command = owner.allocate(
        'COMMAND',
        lambda: GuardRepositoryCommand(
            directories,
            source,
            package,
            empty.empty_global_reader,
            hooks,
            metadata.parsed,
            metadata.metadata_sha256,
            kind=metadata.kind,
            ref_intent=metadata.ref_intent,
            object_intent=metadata.object_intent,
            reflog_identity=metadata.reflog_identity,
            target_ref=metadata.target_ref,
            ancestry=metadata.ancestry,
        ),
    )
    return directory, command


def _private_content_resources(owner, registry, decoded):
    controller = registry._controller
    intent, originals = decoded.content
    directories = owner.allocate(
        'CONTENT_DIRECTORIES',
        lambda: GuardAttributeHandles(
            controller,
            decoded.stdio.owner,
            originals,
            error_type=ContentGitCommandError,
            error_prefix='ORIGINAL_CONTENT_GIT_DIRECTORY',
        ),
    )
    package = _private_read_package(owner, registry)
    empty = owner.allocate('GLOBAL_CONFIG', lambda: PrivateConfigCopy.create_empty_global(package))
    hooks = owner.allocate(
        'HOOKS',
        lambda: ReadOnlyEmptyDirectory(
            create_readonly_empty_directory(package, 'hooks'),
            control_git_reader=controller,
        ),
    )
    directory = owner.allocate(
        'DIRECTORY',
        lambda: LocalPathGuard(package.path, directory=True).__enter__(),
    )
    repo = intent.paths(originals['parent'][0].canonical_path)['repository']
    command = owner.allocate(
        'COMMAND',
        lambda: GuardContentGitCommand(
            intent, directories, package, empty.empty_global_reader, hooks, repo
        ),
    )
    return directory, command


def prepare_control_git(request, binding, actions, registry, *, content_parent=None):
    """Use inside the current controller owner's verified admission context."""
    decoded = decode_control_git_action(request, binding, content_parent=content_parent)
    if type(decoded) is not PrepareControlGit:
        raise TypeError('Registered Control Git PREPARE required')
    if (
        type(actions) is not GuardActionJournal
        or type(registry) is not ControlGitRegistry
        or actions._journal is not registry._journal
        or registry._controller_ref != binding.controller_ref
        or registry._controller._expected != binding.controller
    ):
        raise LaunchOutcomeUnknown('ORIGINAL_CONTROL_GIT_PREPARATION_OWNER_DIFFERS')
    if decoded.metadata is not None:
        _metadata_config_released(decoded, actions, binding)
    start = actions.begin(request)
    if not start.first_accepted:
        return start.record
    owner = registry.begin_preparation(actions, start)
    image = owner.allocate('PROGRAM', _open_image)
    job = owner.allocate(
        'JOB', lambda: OwnedJob(active_process_limit=16, job_memory_limit_bytes=512 * 1024 * 1024)
    )
    export = decoded.config_export
    if decoded.metadata is not None:
        directory, command = _private_metadata_resources(owner, registry, decoded)
    elif decoded.content is not None:
        directory, command = _private_content_resources(owner, registry, decoded)
    elif export is None:
        directory = owner.allocate(
            'DIRECTORY', lambda: LocalPathGuard(GIT_ROOT, directory=True).__enter__()
        )
        command = ('--version',)
    else:
        directory, command = _private_config_resources(owner, registry, export)
    streams = owner.allocate(
        'STDIO',
        lambda: GuardStandardIO(registry._controller, decoded.stdio, scope=request.scope),
    )
    receipt = registry.register(
        request.scope, image, job, streams, directory, arguments=command, preparation=owner
    )
    result = {
        'binding_ref': owner.binding_ref,
        'guard_run_ref': registry.guard_run_ref,
        'stdio_binding': asdict(streams.binding),
        'native_receipt': asdict(receipt),
    }
    if export is not None:
        result['config_export'] = {
            'file': asdict(export.file),
            'sha256': export.sha256,
            'byte_count': export.byte_count,
        }
    if decoded.metadata is not None:
        result['metadata_source'] = {
            'command_ref': request.input['command_ref'],
            'location_sha256': decoded.metadata.directories.location_sha256,
            'metadata_sha256': decoded.metadata.metadata_sha256,
            'config_nonce': decoded.metadata.parsed.scope.nonce,
            'config_output_sha256': decoded.metadata.parsed.local.output_sha256,
        }
        if decoded.metadata.ref_intent is not None:
            result['metadata_source']['ref_intent_sha256'] = (
                decoded.metadata.ref_intent.input_sha256
            )
        if decoded.metadata.object_intent is not None:
            result['metadata_source']['object_intent_sha256'] = (
                decoded.metadata.object_intent.digest
            )
        if decoded.metadata.ancestry is not None:
            result['metadata_source']['ancestry_sha256'] = decoded.metadata.ancestry.digest
        if decoded.metadata.target_ref is not None:
            result['metadata_source']['target_ref'] = decoded.metadata.target_ref
        if decoded.metadata.reflog_identity is not None:
            result['metadata_source']['reflog_sha256'] = decoded.metadata.reflog_identity.digest
    if decoded.content is not None:
        result['content_source'] = request.input['content_source']['intent']
    return actions.acknowledge(start.record, result)
