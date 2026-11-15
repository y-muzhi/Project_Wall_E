"""Read the fixed LPAC policy resource already pinned by a CHECK20 runner manifest."""

from pathlib import Path

from backend.app.shared.validation import strict_json_object

from .check_runner_bundle import CheckResourceError
from .windows_config_source import LockedFileSource
from .windows_lpac_capabilities import LpacCapabilityError, validate_lpac_capability_names

POLICY_FILE = 'windows-lpac-policy.json'
MAX_POLICY_BYTES = 1024


def decode_browser_lpac_policy(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_POLICY_BYTES:
        raise CheckResourceError('BROWSER_LPAC_POLICY_INVALID')
    value = strict_json_object(raw)
    if (
        set(value) != {'schema_version', 'capability_names'}
        or type(value['schema_version']) is not int
        or value['schema_version'] != 1
        or type(value['capability_names']) is not list
    ):
        raise CheckResourceError('BROWSER_LPAC_POLICY_INVALID')
    try:
        return validate_lpac_capability_names(tuple(value['capability_names']))
    except LpacCapabilityError as error:
        raise CheckResourceError('BROWSER_LPAC_POLICY_INVALID') from error


def runner_lpac_capability_names(closure, checkpoint):
    files = {member.path: member for member in closure.manifest.file_entries}
    policy = files.get(POLICY_FILE)
    if policy is None:
        return ()
    if (
        'BROWSER' not in closure.manifest.capabilities
        or not 0 < policy.byte_count <= MAX_POLICY_BYTES
    ):
        raise CheckResourceError('BROWSER_LPAC_POLICY_INVALID')
    identities = dict(closure.members)
    with LockedFileSource(
        Path(closure.registration.directory.canonical_path) / POLICY_FILE,
        max_file_bytes=MAX_POLICY_BYTES,
        expected_file=identities[POLICY_FILE],
        checkpoint=checkpoint,
    ) as source:
        observed = source.snapshot
        if (observed.byte_count, observed.sha256) != (policy.byte_count, policy.sha256):
            raise CheckResourceError('BROWSER_LPAC_POLICY_SOURCE_DIFFERS')
        return decode_browser_lpac_policy(observed.raw)
