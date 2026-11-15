"""Bind trusted local model metadata to the existing immutable backend-only profile."""

import hashlib
from dataclasses import replace

from backend.app.infrastructure.deployment_manifest import LocalDeploymentError, digest
from backend.app.infrastructure.model_profile import ModelProfile
from backend.app.shared.json_canonical import canonical_input
from backend.app.shared.strict_objects import exact
from backend.app.shared.validation import strict_integer

from .coding_model_admission import CodingModelAdmission
from .coding_model_gateway import CodingModelDeployment
from .usage import UsageContract

_SEMANTICS = 'PER_DIMENSION_NONDECREASING'
_DIMENSIONS = frozenset(('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens'))


def _reference(value):
    if (
        type(value) is not str
        or not 1 <= len(value) <= 256
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_REFERENCE_REQUIRED')
    return value


def _names(values):
    if type(values) is not list or len(values) > 16:
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_FIELDS_REQUIRED')
    names = tuple(_reference(value) for value in values)
    if len(set(names)) != len(names):
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_FIELDS_DUPLICATED')
    return names


def _admission(value, profile):
    row = exact(
        value,
        (
            'evidence_ref',
            'model_snapshot_ref',
            'billing_scope_ref',
            'price_sha256',
            'model_profile_ref',
            'model_snapshot_sha256',
            'usage',
            'max_duration_seconds',
            'input_cap',
            'context_cap',
            'output_cap',
            'chunk_usage',
            'optional_fields',
        ),
    )
    if (
        row['model_profile_ref'] != profile.profile_id
        or digest(row['model_snapshot_sha256'])
        != hashlib.sha256(canonical_input(profile.snapshot).encode('utf-8')).hexdigest()
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_PROFILE_DIFFERS')
    usage = exact(
        row['usage'],
        (
            'version',
            'final_source',
            'required_dimensions',
            'cache_dimensions',
            'cumulative_semantics',
        ),
    )
    required = _names(usage['required_dimensions'])
    cache = _names(usage['cache_dimensions'])
    if (
        usage['cumulative_semantics'] != _SEMANTICS
        or set(required) - _DIMENSIONS
        or type(row['chunk_usage']) is not bool
    ):
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_USAGE_DIFFERS')
    return CodingModelAdmission(
        _reference(row['evidence_ref']),
        _reference(row['model_snapshot_ref']),
        _reference(row['billing_scope_ref']),
        digest(row['price_sha256']),
        profile,
        UsageContract(_reference(usage['version']), usage['final_source'], required, cache),
        strict_integer(row['max_duration_seconds'], 'max_duration_seconds', maximum=180),
        strict_integer(row['input_cap'], 'input_cap'),
        strict_integer(row['context_cap'], 'context_cap'),
        strict_integer(row['output_cap'], 'output_cap'),
        row['chunk_usage'],
        frozenset(_names(row['optional_fields'])),
    )


def decode_model_deployment(value, installation, *, environment):
    if installation.task_launch is None or installation.task_launch.coding is None:
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_TASK_REQUIRED')
    row = exact(value, ('admissions',))
    admissions = row['admissions']
    if type(admissions) is not list or not 1 <= len(admissions) <= 16:
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_ADMISSIONS_REQUIRED')
    if environment is None:
        raise LocalDeploymentError('CODE_DEPLOYMENT_MODEL_ENVIRONMENT_REQUIRED')
    # The one original credential source and immutable selected Profile are reused.
    # Parsing metadata never calls the provider, reads a user DB or publishes ready.
    profile = ModelProfile.from_environment(environment)
    deployed = CodingModelDeployment(tuple(_admission(item, profile) for item in admissions))
    return replace(installation, coding_models=deployed)
