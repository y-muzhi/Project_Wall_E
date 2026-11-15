"""Private exact UTF-8 source files and the original no-replace basis seal."""

import hashlib
import re
from dataclasses import asdict

from backend.app.infrastructure.idempotency import canonical_input
from backend.app.infrastructure.windows_config_source import LockedFileSource
from backend.app.infrastructure.windows_local_paths import FileIdentity
from backend.app.infrastructure.windows_private_record import (
    PrivateRecordAppend,
    PrivateRecordReference,
)
from backend.app.infrastructure.windows_task_basis import (
    BackendBasisWriter,
    BasisCopySpec,
    bind_basis_offer,
)
from backend.app.infrastructure.windows_task_basis_group import BasisCopyPlan
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import strict_integer, strict_json_object

from .task_basis import TaskBasisUnavailable


def basis_source(originals):
    return [
        {
            'document_id': original.document_id,
            'revision_id': original.revision_id,
            'byte_count': len(original.utf8),
            'sha256': hashlib.sha256(original.utf8).hexdigest(),
        }
        for original in originals
    ]


def basis_digest(source):
    return hashlib.sha256(canonical_input({'source': source}).encode('utf-8')).hexdigest()


def _basis_name(nonce, number):
    return f'{nonce}.b{number}.md'


def _seal_name(nonce):
    return nonce + '.basis-seal.json'


def _reference(value, filename, limit):
    if type(value) is not dict or set(value) != {'filename', 'sha256', 'byte_count', 'file'}:
        raise TaskBasisUnavailable('Original basis file reference differs')
    if (
        value['filename'] != filename
        or type(value['sha256']) is not str
        or re.fullmatch('[0-9a-f]{64}', value['sha256']) is None
        or type(value['byte_count']) is not int
        or not 0 <= value['byte_count'] <= limit
    ):
        raise TaskBasisUnavailable('Original basis file metadata differs')
    return PrivateRecordReference(
        filename, value['sha256'], value['byte_count'], FileIdentity(**value['file'])
    )


def _read_reference(parent, reference):
    file = parent.verify_member(reference.filename, directory=False)
    if file != reference.file:
        raise TaskBasisUnavailable('Original basis file identity differs')
    with LockedFileSource(
        parent.path / reference.filename,
        max_file_bytes=max(1, reference.byte_count),
        expected_file=file,
    ) as lease:
        data = lease.snapshot
        if data.sha256 != reference.sha256 or data.byte_count != reference.byte_count:
            raise TaskBasisUnavailable('Original basis file bytes differ')
        return data.raw


def publish_basis_package(parent, binding, originals, check_active):
    files = []
    nonce = binding['nonce']
    for number, original in enumerate(originals, 1):
        check_active()
        name = _basis_name(nonce, number)
        with PrivateRecordAppend(
            parent, name, original.utf8, max_record_bytes=max(1, len(original.utf8))
        ) as record:
            check_active()
            files.append(asdict(record.publish()))
    seal = canonical_input(
        {'binding': binding, 'source': basis_source(originals), 'files': files}
    ).encode('utf-8')
    check_active()
    with PrivateRecordAppend(
        parent, _seal_name(nonce), seal, max_record_bytes=HTTP_REQUEST_BYTES
    ) as record:
        check_active()
        return asdict(record.publish())


def observe_basis_seal(parent, binding):
    name = _seal_name(binding['nonce'])
    file = parent.verify_member(name, directory=False)
    with LockedFileSource(
        parent.path / name, max_file_bytes=HTTP_REQUEST_BYTES, expected_file=file
    ) as lease:
        fact = lease.snapshot
        return asdict(PrivateRecordReference(name, fact.sha256, fact.byte_count, fact.file))


def _basis_references(parent, binding, seal, check_active):
    check_active()
    reference = _reference(seal, _seal_name(binding['nonce']), HTTP_REQUEST_BYTES)
    manifest = strict_json_object(_read_reference(parent, reference))
    if (
        type(manifest) is not dict
        or set(manifest) != {'binding', 'source', 'files'}
        or manifest['binding'] != binding
    ):
        raise TaskBasisUnavailable('Original basis seal differs from its binding')
    source, files = manifest['source'], manifest['files']
    if (
        type(source) is not list
        or type(files) is not list
        or len(source) != binding['document_count']
        or len(files) != len(source)
        or basis_digest(source) != binding['source_sha256']
    ):
        raise TaskBasisUnavailable('Original basis seal source differs')
    for number, (item, entry) in enumerate(zip(source, files), 1):
        if type(item) is not dict or set(item) != {
            'document_id',
            'revision_id',
            'byte_count',
            'sha256',
        }:
            raise TaskBasisUnavailable('Original basis source fields differ')
        strict_integer(item['document_id'], 'document_id')
        strict_integer(item['revision_id'], 'revision_id')
        length = strict_integer(item['byte_count'], 'byte_count', minimum=0)
        file = _reference(entry, _basis_name(binding['nonce'], number), length)
        if file.sha256 != item['sha256'] or file.byte_count != length:
            raise TaskBasisUnavailable('Original basis file metadata differs')
        check_active()
        yield item, file


def read_basis_package(parent, binding, seal, check_active, *, document_id=None):
    result = []
    for item, file in _basis_references(parent, binding, seal, check_active):
        if document_id is None or document_id == item['document_id']:
            raw = _read_reference(parent, file)
            if document_id is not None:
                result.append(raw)
    check_active()
    if document_id is not None:
        if len(result) != 1:
            raise TaskBasisUnavailable('Original basis document is unavailable')
        return result[0]
    return None


def _runtime_basis_reference(parent, binding, seal, number, check_active):
    strict_integer(number, 'number')
    reference = None
    for ordinal, (_, file) in enumerate(_basis_references(parent, binding, seal, check_active), 1):
        if number == ordinal:
            reference = file
    if reference is None:
        raise TaskBasisUnavailable('Original basis copy member is unavailable')
    return reference


def runtime_basis_plan(parent, binding, seal, check_active):
    members = tuple(
        BasisCopySpec(number, file.byte_count, file.sha256, binding['source_sha256'])
        for number, (_, file) in enumerate(
            _basis_references(parent, binding, seal, check_active), 1
        )
    )
    check_active()
    return BasisCopyPlan(
        binding['operation_id'],
        binding['task_id'],
        binding['workspace_id'],
        binding['generation'],
        binding['source_sha256'],
        members,
    )


def write_runtime_basis(parent, binding, seal, offer, scope, binding_ref, check_active):
    with BackendBasisWriter(offer, scope, binding_ref) as writer:
        check_active()
        spec = offer.expected.spec
        if binding['operation_id'] != scope.operation_id or scope.step_no != 4:
            raise TaskBasisUnavailable('Original basis START_INSTANCE scope differs')
        source = _runtime_basis_reference(parent, binding, seal, spec.number, check_active)
        if spec != BasisCopySpec(
            spec.number, source.byte_count, source.sha256, binding['source_sha256']
        ):
            raise TaskBasisUnavailable('Original basis copy source differs')
        writer.write(_read_reference(parent, source), check_active)


def verify_runtime_basis_copy(offer, scope, binding_ref, check_active):
    expected, path = bind_basis_offer(offer, scope, binding_ref)
    check_active()
    with LockedFileSource(
        path, max_file_bytes=max(1, expected.spec.byte_count), expected_file=expected.file
    ) as source:
        actual = source.snapshot
        if actual.byte_count != expected.spec.byte_count or actual.sha256 != expected.spec.sha256:
            raise TaskBasisUnavailable('Original basis runtime copy bytes differ')
        check_active()
    return expected
