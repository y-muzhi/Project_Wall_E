"""HTTP boundaries for the original Testing report and human finding review."""

from dataclasses import dataclass

from fastapi import APIRouter, Request

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.command_registry import RegisteredCommand, registered_command
from backend.app.code_tasks.task_verification_reads import _admissions
from backend.app.shared.http_boundary import handle_http, idempotency_header, request_query
from backend.app.shared.http_projection import page
from backend.app.shared.pagination import MAX_PAGE
from backend.app.shared.validation import (
    decimal_integer,
    object_fields,
    ordinary_text,
    strict_enum,
    strict_integer,
)

from .findings import CLASSIFICATIONS, list_findings, project_finding, review_finding
from .policy_api import PolicyRead
from .reports import project_report, read_report

REPORT = '/test-reports/{id}'
TASK_REPORT = '/testing-tasks/{testing_task_id}/report'
FINDINGS = '/test-reports/{report_id}/findings'
REVIEW = '/testing-findings/{id}/review'
TEST_REPORT_ROUTER = APIRouter(redirect_slashes=False)


@dataclass(frozen=True)
class ReportRequest:
    identity: int
    by_task: bool
    admissions: tuple

    @classmethod
    def parse(cls, request):
        authorization_query(request)
        by_task = 'testing_task_id' in request.path_params
        field = 'testing_task_id' if by_task else 'id'
        return cls(
            decimal_integer(request.path_params[field], field),
            by_task,
            _admissions(request),
        )


@dataclass(frozen=True)
class FindingsRequest:
    identity: int
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(
            decimal_integer(request.path_params['report_id'], 'report_id'),
            decimal_integer(query.get('page', '1'), 'page', MAX_PAGE),
        )


@dataclass(frozen=True)
class ReviewRequest:
    identity: int
    expected: int
    classification: str
    reason: str
    command: RegisteredCommand
    body_fields = ('expected_state_version', 'classification', 'reason')

    @property
    def idempotency_key(self):
        return self.command.key

    def business_input(self):
        return {
            'expected_state_version': self.expected,
            'classification': self.classification,
            'reason': self.reason,
        }

    @classmethod
    def parse(cls, request, body):
        request_query(request)
        fields = object_fields(body, 'body', cls.body_fields, cls.body_fields)
        identity = decimal_integer(request.path_params['id'], 'id')
        return cls(
            identity,
            strict_integer(fields['expected_state_version'], 'expected_state_version'),
            strict_enum(fields['classification'], 'classification', CLASSIFICATIONS[1:]),
            ordinary_text(fields['reason'], 'reason', 1, 2000),
            registered_command(
                'POST',
                '/api/v1' + REVIEW.format(id=identity),
                idempotency_header(request, lowercase=True),
            ),
        )


class ReportRead(PolicyRead):
    @staticmethod
    def project(value, request):
        key = 'task_id' if request.by_task else 'report_id'
        return project_report(value, **{key: request.identity}), None


class FindingsRead(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(value, project_finding, request.page)
        ids = [row['id'] for row in data['items']]
        if ids != sorted(set(ids)) or any(
            row['test_report_id'] != request.identity for row in data['items']
        ):
            raise ValueError('Original Testing findings cross the requested report')
        return data, meta


class FindingReviewed(PolicyRead):
    success_code = 'UPDATED'
    errors = PolicyRead.errors | {
        'COMMAND_CLOSED',
        'OPERATION_CONFLICT',
        'VERSION_CONFLICT',
        'INVALID_STATE',
        'BASIS_REF_INVALID',
        'TEST_SOURCE_MISMATCH',
    }

    @staticmethod
    def project(value, request):
        row = project_review_receipt(request.command, value, 200)
        if (
            row['state_version'] != request.expected + 1
            or row['classification'] != request.classification
            or row['review_reason'] != request.reason
        ):
            raise ValueError('Original Testing review differs from the accepted input')
        return row, None


def project_review_receipt(command, value, status):
    row = project_finding(value)
    if (
        status != 200
        or row['id'] != command.route.match(command.path)['id']
        or row['review_operation_id'] is None
        or row['state_version'] < 2
    ):
        raise ValueError('Original Testing review receipt crosses scope')
    return row


@TEST_REPORT_ROUTER.get(REPORT)
@TEST_REPORT_ROUTER.get(TASK_REPORT)
async def report_http(request: Request):
    return await handle_http(request, ReportRequest, ReportRead, read_report)


@TEST_REPORT_ROUTER.get(FINDINGS)
async def findings_http(request: Request):
    return await handle_http(request, FindingsRequest, FindingsRead, list_findings)


@TEST_REPORT_ROUTER.post(REVIEW)
async def review_http(request: Request):
    return await handle_http(request, ReviewRequest, FindingReviewed, review_finding)
