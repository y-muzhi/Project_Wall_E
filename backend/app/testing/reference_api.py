"""Read the fixed, nonsecret Testing reference-set catalogue."""

from dataclasses import dataclass

from backend.app.code_tasks.authorization_api import authorization_query
from backend.app.code_tasks.configuration_identities import require_schema
from backend.app.infrastructure.check_runner_bundle import reference, valid_sha256
from backend.app.shared.http_projection import exact, page
from backend.app.shared.pagination import PAGE_SIZE, page_metadata, page_offset
from backend.app.shared.validation import decimal_integer, strict_integer

from .assets import _read
from .policy_api import PolicyRead
from .reference_resources import MAX_SAMPLES, registration_reason

FIELDS = (
    'reference_set_ref',
    'basis_fingerprint',
    'positive_count',
    'negative_count',
    'repeat_count',
    'ready',
    'reason_codes',
)


@dataclass(frozen=True)
class ReferenceListRequest:
    page: int

    @classmethod
    def parse(cls, request):
        query = authorization_query(request, singles=('page',))
        return cls(decimal_integer(query.get('page', '1'), 'page', 100000))


def project_reference(value):
    row = exact(value, FIELDS)
    reference(row['reference_set_ref'])
    positive = strict_integer(row['positive_count'], 'positive_count', 1, MAX_SAMPLES)
    negative = strict_integer(row['negative_count'], 'negative_count', 1, MAX_SAMPLES)
    strict_integer(row['repeat_count'], 'repeat_count', 2, 10)
    if (
        positive + negative > MAX_SAMPLES
        or not valid_sha256(row['basis_fingerprint'])
        or type(row['ready']) is not bool
        or row['reason_codes'] != ([] if row['ready'] else ['CONTENT_NOT_READY'])
    ):
        raise ValueError('Original reference set facts differ')
    return row


class ReferenceList(PolicyRead):
    @staticmethod
    def project(value, request):
        data, meta = page(value, project_reference, request.page)
        references = [row['reference_set_ref'] for row in data['items']]
        if references != sorted(set(references)):
            raise ValueError('Original reference-set catalogue order differs')
        return data, meta


def list_reference_sets(runtime, request):
    require_schema(runtime)
    installation = getattr(runtime.catalog, 'testing_assets', None)
    registrations = sorted(
        () if installation is None else installation.reference_sets,
        key=lambda entry: entry.reference.reference_set_ref,
    )
    first = page_offset(request.page)
    items = []
    for entry in registrations[first : first + PAGE_SIZE]:
        fixed = entry.reference
        reason = registration_reason(runtime.database, entry)
        items.append(
            {
                'reference_set_ref': fixed.reference_set_ref,
                'basis_fingerprint': fixed.basis_fingerprint,
                'positive_count': len(fixed.positive_snapshot_ids),
                'negative_count': len(fixed.negative_controls),
                'repeat_count': fixed.repeat_count,
                'ready': reason is None,
                'reason_codes': [] if reason is None else [reason],
            }
        )
    return _read({**page_metadata(request.page, len(registrations)), 'items': items})
