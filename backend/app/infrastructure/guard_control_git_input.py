"""Strict private inputs for registered CONTROL_GIT reads."""

import re
from dataclasses import asdict, dataclass, replace

from backend.app.shared.validation import MAX_SAFE_INTEGER

from .git_bundle import GIT_MANIFEST_SHA256
from .git_commit_input import DeliveryReflogIdentity
from .git_config_command import ParsedRepositoryConfig
from .git_content_command import (
    CONTENT_COMMAND_REF,
    ContentGitIntent,
    decode_content_git_source,
    encode_content_git_source,
)
from .git_delivery_objects import DeliveryObjectIntent
from .git_local_config import LocalConfigFacts
from .git_ref_protocol import (
    DeliveryAncestorQuery,
    RefPrepareInput,
    baseline_create,
    branch_ref,
    delivery_update,
)
from .git_repository_metadata import RepositoryMetadataLease
from .guard_action_records import MUTATIONS
from .guard_controller_binding import GuardControllerBinding
from .guard_git_config_source import (
    MAX_GUARD_CONFIG_BYTES,
    ConfigReadDescriptor,
    verify_config_export_descriptor,
)
from .guard_git_metadata_source import (
    ROLES,
    DirectoryHandle,
    MetadataDirectoryExport,
    _verify_export,
)
from .guard_request_header import GuardRequestHeader
from .runtime_launch_journal import LaunchScope, _hex
from .windows_local_paths import FileIdentity
from .windows_stdio import ChildStdioDescriptor, _descriptor

VERSION_COMMAND_REF = 'GIT20-VERSION-1'
CONFIG_COMMAND_REF = 'GIT20-CONFIG-PARSE-1'
METADATA_COMMANDS = {
    'GIT20-WORKTREES-1': 'WORKTREES',
    'GIT20-LOCAL-BRANCHES-1': 'LOCAL_BRANCHES',
}
OBJECT_BATCH_COMMAND_REF = 'GIT20-OBJECT-BATCH-1'
REPOSITORY_READ_COMMANDS = {**METADATA_COMMANDS, OBJECT_BATCH_COMMAND_REF: 'OBJECT_BATCH'}
BASELINE_REF_COMMAND_REF = 'GIT20-BASELINE-CREATE-1'
DELIVERY_OBJECT_COMMAND_REF = 'GIT20-DELIVERY-OBJECT-1'
DELIVERY_REF_COMMAND_REF = 'GIT20-DELIVERY-UPDATE-1'
DELIVERY_TARGET_COMMAND_REF = 'GIT20-DELIVERY-TARGET-1'
DELIVERY_ANCESTOR_COMMAND_REF = 'GIT20-DELIVERY-ANCESTOR-1'
REPOSITORY_COMMANDS = {
    **REPOSITORY_READ_COMMANDS,
    BASELINE_REF_COMMAND_REF: 'BASELINE_REF',
    DELIVERY_OBJECT_COMMAND_REF: 'DELIVERY_OBJECT',
    DELIVERY_REF_COMMAND_REF: 'DELIVERY_REF',
    DELIVERY_TARGET_COMMAND_REF: 'DELIVERY_TARGET',
    DELIVERY_ANCESTOR_COMMAND_REF: 'DELIVERY_ANCESTOR',
}
GIT_RUNTIME_BUNDLE_REF = 'git-bundle:sha256:' + GIT_MANIFEST_SHA256
STDIO_FIELDS = frozenset(('io_nonce', 'stdin_handle', 'stdout_handle', 'stderr_handle'))


class ControlGitInputError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetadataPrepare:
    kind: str
    directories: MetadataDirectoryExport
    parsed: ParsedRepositoryConfig
    metadata_sha256: str
    ref_intent: RefPrepareInput | None = None
    object_intent: DeliveryObjectIntent | None = None
    reflog_identity: DeliveryReflogIdentity | None = None
    target_ref: str | None = None
    ancestry: DeliveryAncestorQuery | None = None


@dataclass(frozen=True)
class PrepareControlGit:
    stdio: ChildStdioDescriptor
    config_export: ConfigReadDescriptor | None = None
    metadata: MetadataPrepare | None = None
    content: tuple | None = None


@dataclass(frozen=True)
class ObserveControlGit:
    observed_action: str


def version_prepare_input(descriptor):
    """Serialize only the backend's original child endpoints and their IO nonce."""
    _descriptor(descriptor)
    return {
        'run_kind': 'CONTROL_GIT',
        'runtime_bundle_ref': GIT_RUNTIME_BUNDLE_REF,
        'command_ref': VERSION_COMMAND_REF,
        'stdio': {name: getattr(descriptor, name) for name in STDIO_FIELDS},
    }


def content_prepare_input(stdio, intent, pins, *, expected_parent):
    if type(intent) is not ContentGitIntent or stdio.scope.step_no not in (2, 3):
        raise ControlGitInputError('ORIGINAL_PACKAGE_GIT_STEP_REQUIRED')
    source = encode_content_git_source(intent, pins)
    decode_content_git_source(source, expected_parent=expected_parent)
    return {
        **version_prepare_input(stdio),
        'command_ref': CONTENT_COMMAND_REF,
        'content_source': source,
    }


def config_prepare_input(stdio, export):
    value = version_prepare_input(stdio)
    verify_config_export_descriptor(export, max_file_bytes=MAX_GUARD_CONFIG_BYTES)
    if export.owner != stdio.owner or export.scope != stdio.scope:
        raise ControlGitInputError('ORIGINAL_CONTROL_GIT_CONFIG_SCOPE_DIFFERS')
    value['command_ref'] = CONFIG_COMMAND_REF
    value['config_export'] = {
        'file': asdict(export.file),
        'sha256': export.sha256,
        'byte_count': export.byte_count,
        'handle': export.handle,
    }
    return value


def _decode_config_export(value, binding, scope):
    if (
        type(value) is not dict
        or set(value) != {'file', 'sha256', 'byte_count', 'handle'}
        or type(value['file']) is not dict
        or set(value['file']) != set(FileIdentity.__dataclass_fields__)
    ):
        raise ControlGitInputError('ORIGINAL_CONTROL_GIT_CONFIG_EXPORT_REQUIRED')
    export = ConfigReadDescriptor(
        binding.controller,
        scope,
        FileIdentity(**value['file']),
        value['sha256'],
        value['byte_count'],
        value['handle'],
    )
    verify_config_export_descriptor(export, max_file_bytes=MAX_GUARD_CONFIG_BYTES)
    return export


def _metadata_binding(directories, config_export, parsed, metadata_sha256):
    _verify_export(directories)
    verify_config_export_descriptor(config_export, max_file_bytes=MAX_GUARD_CONFIG_BYTES)
    _hex(metadata_sha256)
    if (
        type(parsed) is not ParsedRepositoryConfig
        or type(parsed.scope) is not LaunchScope
        or type(parsed.local) is not LocalConfigFacts
    ):
        raise ControlGitInputError('ORIGINAL_METADATA_CONFIG_VALIDATION_REQUIRED')
    facts = parsed.local
    _hex(facts.output_sha256)
    if (
        directories.owner != config_export.owner
        or directories.scope != config_export.scope
        or parsed.scope == directories.scope
        or parsed.scope != replace(directories.scope, nonce=parsed.scope.nonce)
        or parsed.source_file != config_export.file
        or parsed.source_sha256 != config_export.sha256
        or type(parsed.io_nonce) is not str
        or re.fullmatch(
            '[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',
            parsed.io_nonce,
        )
        is None
        or type(facts.bare) is not bool
        or facts.bare != directories.expected_bare
        or type(facts.entry_count) is not int
        or not 0 <= facts.entry_count <= MAX_SAFE_INTEGER
        or type(facts.repository_format_version) is not int
        or facts.repository_format_version not in (0, 1)
        or facts.object_format not in ('sha1', 'sha256')
        or facts.object_format == 'sha256'
        and facts.repository_format_version != 1
    ):
        raise ControlGitInputError('ORIGINAL_METADATA_CONFIG_SCOPE_OR_FACTS_DIFFERS')


def repository_read_prepare_input(stdio, directories, config_export, parsed, metadata, *, kind):
    for command, registered in REPOSITORY_READ_COMMANDS.items():
        if kind == registered:
            return _repository_prepare_input(
                stdio, directories, config_export, parsed, metadata, command
            )
    raise ControlGitInputError('ORIGINAL_METADATA_COMMAND_REQUIRED')


def baseline_ref_prepare_input(stdio, directories, config_export, parsed, metadata, intent):
    if (
        type(intent) is not RefPrepareInput
        or intent.kind != 'BASELINE_CREATE'
        or intent.object_format != parsed.local.object_format
    ):
        raise ControlGitInputError('ORIGINAL_BASELINE_REF_INTENT_REQUIRED')
    value = _repository_prepare_input(
        stdio, directories, config_export, parsed, metadata, BASELINE_REF_COMMAND_REF
    )
    value['baseline'] = {'snapshot_id': intent.resource_id, 'commit_oid': intent.new_oid}
    return value


def delivery_object_prepare_input(stdio, directories, config_export, parsed, metadata, intent):
    if (
        type(intent) is not DeliveryObjectIntent
        or stdio.scope.step_no != 2
        or intent.object_format != parsed.local.object_format
    ):
        raise ControlGitInputError('ORIGINAL_DELIVERY_OBJECT_REQUIRED')
    value = _repository_prepare_input(
        stdio, directories, config_export, parsed, metadata, DELIVERY_OBJECT_COMMAND_REF
    )
    value['delivery_object'] = asdict(intent)
    return value


def delivery_ref_prepare_input(stdio, directories, config_export, parsed, metadata, intent, reflog):
    if (
        type(intent) is not RefPrepareInput
        or intent.kind != 'DELIVERY_UPDATE'
        or type(reflog) is not DeliveryReflogIdentity
        or stdio.scope.step_no != 4
        or intent.object_format != parsed.local.object_format
    ):
        raise ControlGitInputError('ORIGINAL_DELIVERY_REF_REQUIRED')
    value = _repository_prepare_input(
        stdio, directories, config_export, parsed, metadata, DELIVERY_REF_COMMAND_REF
    )
    value['delivery_ref'] = {
        'delivery_id': intent.resource_id,
        'target_ref': intent.full_ref,
        'planned_oid': intent.new_oid,
        'expected_oid': intent.expected_oid,
        'reflog': asdict(reflog),
    }
    return value


def delivery_target_prepare_input(stdio, directories, config_export, parsed, metadata, target):
    if stdio.scope.step_no not in (5, 7):
        raise ControlGitInputError('ORIGINAL_DELIVERY_TARGET_STEP_REQUIRED')
    value = _repository_prepare_input(
        stdio, directories, config_export, parsed, metadata, DELIVERY_TARGET_COMMAND_REF
    )
    value['target_ref'] = branch_ref(target)
    return value


def delivery_ancestry_prepare_input(stdio, directories, config_export, parsed, metadata, ancestry):
    if (
        stdio.scope.step_no != 7
        or type(ancestry) is not DeliveryAncestorQuery
        or ancestry.object_format != parsed.local.object_format
    ):
        raise ControlGitInputError('ORIGINAL_DELIVERY_ANCESTRY_REQUIRED')
    value = _repository_prepare_input(
        stdio, directories, config_export, parsed, metadata, DELIVERY_ANCESTOR_COMMAND_REF
    )
    value['ancestry'] = asdict(ancestry)
    return value


def decode_delivery_ancestry(value, format):
    if type(value) is not dict or set(value) != set(DeliveryAncestorQuery.__dataclass_fields__):
        raise ControlGitInputError('ORIGINAL_DELIVERY_ANCESTRY_REQUIRED')
    ancestry = DeliveryAncestorQuery(**value)
    if ancestry.object_format != format:
        raise ControlGitInputError('ORIGINAL_DELIVERY_ANCESTRY_FORMAT_DIFFERS')
    return ancestry


def decode_delivery_ref(value, format):
    if type(value) is not dict or set(value) != {
        'delivery_id',
        'target_ref',
        'planned_oid',
        'expected_oid',
        'reflog',
    }:
        raise ControlGitInputError('ORIGINAL_DELIVERY_REF_REQUIRED')
    reflog = value['reflog']
    if type(reflog) is not dict or set(reflog) != {'name', 'email', 'unix_seconds'}:
        raise ControlGitInputError('ORIGINAL_DELIVERY_REFLOG_REQUIRED')
    return (
        delivery_update(
            value['delivery_id'],
            value['target_ref'],
            value['planned_oid'],
            value['expected_oid'],
            format=format,
        ),
        DeliveryReflogIdentity(**reflog),
    )


def _repository_prepare_input(stdio, directories, config_export, parsed, metadata, command):
    if type(metadata) is not RepositoryMetadataLease:
        raise ControlGitInputError('ORIGINAL_METADATA_COMMAND_REQUIRED')
    value = config_prepare_input(stdio, config_export)
    snapshot = metadata.verify()
    _metadata_binding(directories, config_export, parsed, snapshot.fingerprint_sha256)
    original = metadata.location.verify()
    if (
        directories.location_sha256 != snapshot.location_sha256
        or directories.location_sha256 != original.fingerprint_sha256
        or tuple(getattr(directories, role).file for role in ROLES)
        != (original.root, original.git_directory, original.common_directory)
        or config_export.file != original.config
        or config_export.sha256 != original.config_sha256
        or parsed.local.object_format != snapshot.object_format
    ):
        raise ControlGitInputError('ORIGINAL_METADATA_SOURCE_DIFFERS')
    value['command_ref'] = command
    value['metadata'] = {
        'directories': {role: asdict(getattr(directories, role)) for role in ROLES},
        'expected_bare': directories.expected_bare,
        'linked': directories.linked,
        'location_sha256': directories.location_sha256,
        'metadata_sha256': snapshot.fingerprint_sha256,
        'config_nonce': parsed.scope.nonce,
        'config_io_nonce': parsed.io_nonce,
        'config_facts': asdict(parsed.local),
    }
    return value


def _decode_metadata(value, export, command):
    if (
        type(value) is not dict
        or set(value)
        != {
            'directories',
            'expected_bare',
            'linked',
            'location_sha256',
            'metadata_sha256',
            'config_nonce',
            'config_io_nonce',
            'config_facts',
        }
        or type(value['directories']) is not dict
        or set(value['directories']) != set(ROLES)
        or type(value['config_facts']) is not dict
        or set(value['config_facts']) != set(LocalConfigFacts.__dataclass_fields__)
    ):
        raise ControlGitInputError('ORIGINAL_METADATA_FIELDS_REQUIRED')
    directories = []
    for role in ROLES:
        item = value['directories'][role]
        if (
            type(item) is not dict
            or set(item) != {'file', 'handle'}
            or type(item['file']) is not dict
            or set(item['file']) != set(FileIdentity.__dataclass_fields__)
        ):
            raise ControlGitInputError('ORIGINAL_METADATA_DIRECTORY_FIELDS_REQUIRED')
        directories.append(DirectoryHandle(FileIdentity(**item['file']), item['handle']))
    bound = MetadataDirectoryExport(
        export.owner,
        export.scope,
        *directories,
        value['expected_bare'],
        value['linked'],
        value['location_sha256'],
    )
    parsed = ParsedRepositoryConfig(
        export.file,
        export.sha256,
        LocalConfigFacts(**value['config_facts']),
        replace(export.scope, nonce=value['config_nonce']),
        value['config_io_nonce'],
    )
    digest = value['metadata_sha256']
    _metadata_binding(bound, export, parsed, digest)
    return MetadataPrepare(REPOSITORY_COMMANDS[command], bound, parsed, digest)


def decode_control_git_action(request, binding, *, content_parent=None):
    if type(request) is not GuardRequestHeader or type(binding) is not GuardControllerBinding:
        raise TypeError('Original Guard header and controller binding required')
    if (
        request.scope.controller_ref != binding.controller_ref
        or request.owner_epoch != binding.owner_epoch
    ):
        raise ControlGitInputError('ORIGINAL_CONTROL_GIT_CALLER_DIFFERS')
    value = request.input
    if request.recovery is not None and (
        request.action not in ('OBSERVE', 'STOP', 'RELEASE')
        or value.pop('recovery', None) != asdict(request.recovery)
    ):
        raise ControlGitInputError('ORIGINAL_CONTROL_GIT_RECOVERY_DIFFERS')
    if request.action == 'PREPARE':
        command = value.get('command_ref')
        fields = {'run_kind', 'runtime_bundle_ref', 'command_ref', 'stdio'}
        if type(command) is not str:
            raise ControlGitInputError('REGISTERED_CONTROL_GIT_COMMAND_REQUIRED')
        if command == CONFIG_COMMAND_REF or command in REPOSITORY_COMMANDS:
            fields.add('config_export')
        if command in REPOSITORY_COMMANDS:
            fields.add('metadata')
        if command == BASELINE_REF_COMMAND_REF:
            fields.add('baseline')
        if command == CONTENT_COMMAND_REF:
            fields.add('content_source')
        if command == DELIVERY_OBJECT_COMMAND_REF:
            fields.add('delivery_object')
        if command == DELIVERY_REF_COMMAND_REF:
            fields.add('delivery_ref')
        if command == DELIVERY_TARGET_COMMAND_REF:
            fields.add('target_ref')
        if command == DELIVERY_ANCESTOR_COMMAND_REF:
            fields.add('ancestry')
        if (
            set(value) != fields
            or value['run_kind'] != 'CONTROL_GIT'
            or value['runtime_bundle_ref'] != GIT_RUNTIME_BUNDLE_REF
            or command
            not in (
                VERSION_COMMAND_REF,
                CONFIG_COMMAND_REF,
                CONTENT_COMMAND_REF,
                *REPOSITORY_COMMANDS,
            )
        ):
            raise ControlGitInputError('REGISTERED_CONTROL_GIT_COMMAND_REQUIRED')
        stdio = value['stdio']
        if type(stdio) is not dict or set(stdio) != STDIO_FIELDS:
            raise ControlGitInputError('ORIGINAL_CONTROL_GIT_STDIO_FIELDS_REQUIRED')
        descriptor = ChildStdioDescriptor(binding.controller, request.scope, **stdio)
        _descriptor(descriptor)
        if command == VERSION_COMMAND_REF:
            return PrepareControlGit(descriptor)
        if command == CONTENT_COMMAND_REF:
            if request.scope.step_no not in (2, 3):
                raise ControlGitInputError('ORIGINAL_PACKAGE_GIT_STEP_REQUIRED')
            return PrepareControlGit(
                descriptor,
                content=decode_content_git_source(
                    value['content_source'],
                    expected_parent=content_parent,
                ),
            )
        export = _decode_config_export(value['config_export'], binding, request.scope)
        metadata = (
            _decode_metadata(value['metadata'], export, command)
            if command in REPOSITORY_COMMANDS
            else None
        )
        if command == BASELINE_REF_COMMAND_REF:
            original = value['baseline']
            if type(original) is not dict or set(original) != {'snapshot_id', 'commit_oid'}:
                raise ControlGitInputError('ORIGINAL_BASELINE_REF_INTENT_REQUIRED')
            intent = baseline_create(
                original['snapshot_id'],
                original['commit_oid'],
                format=metadata.parsed.local.object_format,
            )
            metadata = replace(metadata, ref_intent=intent)
        if command == DELIVERY_OBJECT_COMMAND_REF:
            fields = value['delivery_object']
            if (
                request.scope.step_no != 2
                or type(fields) is not dict
                or set(fields) != set(DeliveryObjectIntent.__dataclass_fields__)
            ):
                raise ControlGitInputError('ORIGINAL_DELIVERY_OBJECT_REQUIRED')
            intent = DeliveryObjectIntent(**fields)
            if intent.object_format != metadata.parsed.local.object_format:
                raise ControlGitInputError('ORIGINAL_DELIVERY_OBJECT_FORMAT_DIFFERS')
            metadata = replace(metadata, object_intent=intent)
        if command == DELIVERY_REF_COMMAND_REF:
            if request.scope.step_no != 4:
                raise ControlGitInputError('ORIGINAL_DELIVERY_REF_STEP_REQUIRED')
            ref, reflog = decode_delivery_ref(
                value['delivery_ref'], metadata.parsed.local.object_format
            )
            metadata = replace(metadata, ref_intent=ref, reflog_identity=reflog)
        if command == DELIVERY_TARGET_COMMAND_REF:
            if request.scope.step_no not in (5, 7):
                raise ControlGitInputError('ORIGINAL_DELIVERY_TARGET_STEP_REQUIRED')
            metadata = replace(metadata, target_ref=branch_ref(value['target_ref']))
        if command == DELIVERY_ANCESTOR_COMMAND_REF:
            if request.scope.step_no != 7:
                raise ControlGitInputError('ORIGINAL_DELIVERY_ANCESTRY_STEP_REQUIRED')
            ancestry = decode_delivery_ancestry(
                value['ancestry'], metadata.parsed.local.object_format
            )
            metadata = replace(metadata, ancestry=ancestry)
        return PrepareControlGit(descriptor, export, metadata)
    if request.action == 'OBSERVE':
        if (
            set(value) != {'observed_action'}
            or type(value['observed_action']) is not str
            or value['observed_action'] not in MUTATIONS
        ):
            raise ControlGitInputError('ORIGINAL_CONTROL_GIT_OBSERVED_ACTION_REQUIRED')
        return ObserveControlGit(value['observed_action'])
    if request.action in MUTATIONS and not value:
        return None
    raise ControlGitInputError('REGISTERED_CONTROL_GIT_ACTION_INPUT_REQUIRED')
