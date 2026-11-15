"""A trusted local quota exception never overrides retained or unknown effects."""

import pytest

from backend.app.code_tasks.task_capture_failure import local_capacity_failure
from backend.app.infrastructure.content_manifest import ContentManifestError
from backend.app.infrastructure.windows_config_source import ConfigReadError


@pytest.mark.parametrize(
    'case', ['manifest', 'file', 'mapped', 'spoof', 'retained', 'cycle', 'unavailable']
)
def test_quota_classification_requires_complete_trusted_exception_chain(case):
    if case in ('manifest', 'mapped'):
        original = ContentManifestError('CONTENT_MANIFEST_BYTES_EXCEEDED')
    else:
        original = ConfigReadError('CONFIG_READ_BYTES_EXCEEDED')
    if case == 'spoof':
        error = OSError('CONTENT_MANIFEST_BYTES_EXCEEDED')
    elif case == 'unavailable':
        error = ConfigReadError('CONFIG_READ_UNAVAILABLE')
    elif case in ('mapped', 'retained', 'cycle'):
        error = RuntimeError('SOURCE_UNSUPPORTED')
        error.__cause__ = original
        if case == 'retained':
            original.retained_owner = object()
        elif case == 'cycle':
            original.__cause__ = error
    else:
        error = original
    assert local_capacity_failure(error) is (case in ('manifest', 'file', 'mapped'))
