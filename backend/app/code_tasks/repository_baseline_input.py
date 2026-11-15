"""Original C05 input rules shared by acceptance and later Git execution."""

from backend.app.infrastructure.database import StorageUnavailable
from backend.app.infrastructure.git_ref_protocol import (
    RefProtocolError,
    _nonzero_oid,
    baseline_create,
)
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.shared.command_execution import ConfigurationNotReady
from backend.app.shared.http_boundary import HTTP_REQUEST_BYTES
from backend.app.shared.validation import (
    object_fields,
    reject,
    strict_integer,
    strict_json_object,
)

from .execution_profile_content import capture, git_profile

BASELINE_INPUT_FIELDS = ('repository_id', 'commit_oid', 'execution_profile_version_id')


def check_baseline_input(original, format):
    fields = object_fields(original, 'body', BASELINE_INPUT_FIELDS, BASELINE_INPUT_FIELDS)
    for key in ('repository_id', 'execution_profile_version_id'):
        strict_integer(fields[key], key)
    try:
        _nonzero_oid(fields['commit_oid'], format)
    except RefProtocolError:
        reject('commit_oid', 'INVALID_FORMAT', '必须提供符合原仓库对象格式的完整提交编号')


def baseline_profile(connection, catalog, profile_version_id):
    row = connection.execute(
        'SELECT git,capture_rules FROM code_execution_profile_versions WHERE id=?',
        (profile_version_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        stored_git = strict_json_object(row['git'])
        stored_content = strict_json_object(row['capture_rules'])
        git = git_profile(stored_git, HTTP_REQUEST_BYTES)
        content = capture(stored_content, HTTP_REQUEST_BYTES)
        if git != stored_git or content != stored_content:
            raise ValueError('Stored baseline configuration must not be normalized')
    except (ValueError, TypeError, KeyError) as error:
        raise StorageUnavailable('Stored baseline configuration differs') from error

    policy = {key: content[key] for key in ('content_policy_version', 'secret_policy_ref')}
    try:
        for kind, expected, capability in (
            ('GIT', git, 'Q20-GIT'),
            ('CONTENT_POLICY', policy, 'Q20-CONTENT'),
        ):
            matches = [
                row for row in catalog.code_configuration_options(kind) if row['value'] == expected
            ]
            if len(matches) != 1:
                raise ConfigurationNotReady(capability)
    except ConfigInvalid as error:
        raise ConfigurationNotReady('Q20-CONFIG') from error
    return git, content


def baseline_fixed_input(original, snapshot_id, format):
    ref = baseline_create(snapshot_id, original['commit_oid'], format=format)
    return {**original, 'snapshot_id': snapshot_id, 'retention_ref': ref.full_ref}
