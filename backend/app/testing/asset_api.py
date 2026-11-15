"""Independent Testing asset HTTP boundary."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.command_registry import RegisteredCommand, registered_command
from backend.app.infrastructure.check_runner_bundle import CheckResourceError, reference
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import exact, page
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    ordinary_text,
    reject,
    strict_integer,
)

from .asset_operations import (
    SEAL_PATH,
    TEST_OPERATION,
    project_resource_fact,
    project_seal_operation,
    read_test_operation,
)
from .assets import create_pack, list_packs, project_pack, read_pack
from .pack_lifecycle import revoke_pack
from .pack_publication import publish_pack
from .pack_seal import seal_pack
from .pack_validation import (
    project_validation,
    project_validation_operation,
    read_validation,
    read_validation_operation,
    validate_pack,
)
from .policy_api import PolicyRead
from .reference_api import ReferenceList, ReferenceListRequest, list_reference_sets
from .task_operations import project_task_operation, read_task_operation

PACKS = '/test-plan-versions/{plan_version_id}/packs'
PACK = '/test-pack-versions/{id}'
REVOKE = PACK + '/revoke'
PUBLISH = PACK + '/publish'
VALIDATE = PACK + '/validations'
VALIDATION = '/test-pack-validations/{id}'
TEST_ASSET_ROUTER = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class CreatePackRequest:
    identity: int
    command: RegisteredCommand
    body_fields = ()

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        object_fields(body, 'body', (), ())
        identity = decimal_integer(request.path_params['plan_version_id'], 'plan_version_id')
        command = registered_command(
            'POST',
            '/api/v1' + PACKS.format(plan_version_id=identity),
            idempotency_header(request, lowercase=True),
        )
        return cls(identity, command)


@dataclass(frozen=True)
class SealPackRequest:
    identity: int
    expected: int
    command: RegisteredCommand
    body_fields = ('expected_state_version',)
    path = SEAL_PATH

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'expected_state_version': self.expected}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['id'], 'id')
        expected = strict_integer(fields['expected_state_version'], 'expected_state_version')
        command = registered_command(
            'POST',
            '/api/v1' + cls.path.format(id=identity),
            idempotency_header(request, lowercase=True),
        )
        return cls(identity, expected, command)


class PublishPackRequest(SealPackRequest):
    path = PUBLISH


@dataclass(frozen=True)
class ValidatePackRequest:
    identity: int
    expected: int
    profile: int
    reference: str
    authorization: int
    command: RegisteredCommand
    body_fields = (
        'expected_state_version',
        'profile_version_id',
        'reference_set_ref',
        'authorization_id',
    )

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'expected_state_version': self.expected,
            'profile_version_id': self.profile,
            'reference_set_ref': self.reference,
            'authorization_id': self.authorization,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        value = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['id'], 'id')
        try:
            original = reference(value['reference_set_ref'])
        except CheckResourceError:
            reject('reference_set_ref', 'INVALID_FORMAT', '必须选择已登记参考集')
        return cls(
            identity,
            strict_integer(value['expected_state_version'], 'expected_state_version'),
            strict_integer(value['profile_version_id'], 'profile_version_id'),
            original,
            strict_integer(value['authorization_id'], 'authorization_id'),
            registered_command(
                'POST',
                '/api/v1' + VALIDATE.format(id=identity),
                idempotency_header(request, lowercase=True),
            ),
        )


@dataclass(frozen=True)
class RevokePackRequest:
    identity: int
    expected: int
    reason: str
    command: RegisteredCommand
    body_fields = ('expected_state_version', 'reason')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {'expected_state_version': self.expected, 'reason': self.reason}

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['id'], 'id')
        return cls(
            identity,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            ordinary_text(fields['reason'], 'reason', 1, 2000),
            registered_command(
                'POST',
                '/api/v1' + REVOKE.format(id=identity),
                idempotency_header(request, lowercase=True),
            ),
        )


@dataclass(frozen=True)
class PackListRequest:
    identity: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['plan_version_id'], 'plan_version_id'),
            decimal_integer(query.get('page', '1'), 'page', 100000),
        )


@dataclass(frozen=True)
class PackReadRequest:
    identity: int

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        return cls(decimal_integer(request.path_params['id'], 'id'))


def project_created_pack(value):
    result = exact(value, ('test_pack_version_id',))
    strict_integer(result['test_pack_version_id'], 'test_pack_version_id')
    return result


class CreatedPack(PolicyRead):
    status = 201
    success_code = 'CREATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'INVALID_STATE',
        'BASIS_REF_INVALID',
        'TEST_ASSET_REVOKED',
    }

    @staticmethod
    def project(value, request):
        return project_created_pack(value), None


def project_seal_receipt(value, pack_id):
    result = exact(value, ('operation_id', 'test_pack_version_id', 'validation_id'))
    strict_integer(result['operation_id'], 'operation_id')
    if (
        strict_integer(result['test_pack_version_id'], 'test_pack_version_id') != pack_id
        or result['validation_id'] is not None
    ):
        raise ValueError('Original seal receipt crosses pack ownership')
    return result


class PackSealAccepted(PolicyRead):
    status = 202
    success_code = 'OPERATION_ACCEPTED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'OPERATION_IN_PROGRESS',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'CONFIG_NOT_READY',
        'CHECK_CONFIGURATION_INVALID',
        'CONTENT_NOT_READY',
        'TEST_ASSET_REVOKED',
    }

    @staticmethod
    def project(value, request):
        return project_seal_receipt(value, request.identity), None


class TestOperationRead(PolicyRead):
    @staticmethod
    def project(value, request):
        if value['resource_kind'] == 'TESTING_TASK':
            return project_task_operation(value, request.identity), None
        if value['operation_type'] == 'SEAL_PACK':
            return project_seal_operation(value, request.identity), None
        if value['operation_type'] == 'VALIDATE_PACK':
            return project_validation_operation(value, request.identity), None
        return project_resource_fact(value, request.identity), None


class PackRead(PolicyRead):
    @staticmethod
    def project(value, request):
        row = project_pack(value)
        if row['id'] != request.identity:
            raise ValueError('Original Testing pack identity differs')
        return row, None


class PackList(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(value, project_pack, request.page)
        ids = [row['id'] for row in data['items']]
        if ids != sorted(set(ids)) or any(
            row['plan_version_id'] != request.identity for row in data['items']
        ):
            raise ValueError('Original Testing pack list crosses plan scope')
        return data, meta


@TEST_ASSET_ROUTER.post(PACKS)
async def create_pack_http(request: Request):
    return await handle_http(request, CreatePackRequest, CreatedPack, create_pack)


@TEST_ASSET_ROUTER.get(PACKS)
async def list_packs_http(request: Request):
    return await handle_http(request, PackListRequest, PackList, list_packs)


@TEST_ASSET_ROUTER.get(PACK)
async def read_pack_http(request: Request):
    return await handle_http(request, PackReadRequest, PackRead, read_pack)


@TEST_ASSET_ROUTER.post(SEAL_PATH)
async def seal_pack_http(request: Request):
    return await handle_http(request, SealPackRequest, PackSealAccepted, seal_pack)


def _read_original_operation(runtime, request):
    result = read_test_operation(runtime, request)
    if result['code'] != 'NOT_FOUND':
        return result
    validation = read_validation_operation(runtime, request.identity)
    return (
        read_task_operation(runtime, request.identity)
        if validation['code'] == 'NOT_FOUND'
        else validation
    )


@TEST_ASSET_ROUTER.get(TEST_OPERATION)
async def read_testing_operation_http(request: Request):
    return await handle_http(request, PackReadRequest, TestOperationRead, _read_original_operation)


@TEST_ASSET_ROUTER.get('/testing-reference-sets')
async def list_reference_sets_http(request: Request):
    return await handle_http(request, ReferenceListRequest, ReferenceList, list_reference_sets)


class PackRevoked(PackRead):
    success_code = 'UPDATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'TEST_ASSET_REVOKED',
    }

    @staticmethod
    def project(value, request):
        row, _ = PackRead.project(value, request)
        if (
            row['status'] != 'REVOKED'
            or row['revocation_reason'] != request.reason
            or row['state_version'] != request.expected + 1
        ):
            raise ValueError('Original Testing pack revocation differs')
        return row, None


@TEST_ASSET_ROUTER.post(REVOKE)
async def revoke_pack_http(request: Request):
    return await handle_http(request, RevokePackRequest, PackRevoked, revoke_pack)


class PackValidationAccepted(PackSealAccepted):
    errors = PackSealAccepted.errors | {'AUTHORIZATION_NOT_APPLICABLE'}

    @staticmethod
    def project(value, request):
        result = exact(value, ('operation_id', 'test_pack_version_id', 'validation_id'))
        strict_integer(result['operation_id'], 'operation_id')
        strict_integer(result['validation_id'], 'validation_id')
        if result['test_pack_version_id'] != request.identity:
            raise ValueError('Original Testing validation crosses pack ownership')
        return result, None


class PackValidationRead(PolicyRead):
    @staticmethod
    def project(value, request):
        return project_validation(value, request.identity), None


@TEST_ASSET_ROUTER.post(VALIDATE)
async def validate_pack_http(request: Request):
    worker = getattr(request.app.state, 'walle_repository_registration', None)
    resources = getattr(worker, 'testing_cli_resources', None)
    response = await handle_http(
        request,
        ValidatePackRequest,
        PackValidationAccepted,
        lambda runtime, parsed: validate_pack(runtime, parsed, runtime_resources=resources),
    )
    if response.status_code == 202 and worker is not None:
        worker.wake()
    return response


@TEST_ASSET_ROUTER.get(VALIDATION)
async def read_validation_http(request: Request):
    return await handle_http(request, PackReadRequest, PackValidationRead, read_validation)


class PackPublished(PackRead):
    success_code = 'UPDATED'
    errors = PackRevoked.errors | {'CONFIG_NOT_READY', 'CHECK_CONFIGURATION_INVALID'}

    @staticmethod
    def project(value, request):
        row, _ = PackRead.project(value, request)
        if row['status'] != 'PUBLISHED' or row['state_version'] != request.expected + 1:
            raise ValueError('Original Testing pack publication differs')
        return row, None


@TEST_ASSET_ROUTER.post(PUBLISH)
async def publish_pack_http(request: Request):
    return await handle_http(request, PublishPackRequest, PackPublished, publish_pack)
