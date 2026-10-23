"""Default service AI dependencies, bound to immutable approved releases.

Wiring a real counter grants no network permission. Counting v1/v2 stay closed;
v3 retains its checked admission; later releases chain explicit user approvals.
Observations never change these resources or open a gate automatically.
"""
import hashlib

from backend.app.guide.counted_context import (
    CountedContext, counting_release_for_function, counting_digest_for_function,
    PRACTICAL_RELEASE_SHA256, PRACTICAL_MODE, PRACTICAL_RELEASE_PATH,
    EXPANDED_RELEASE_SHA256, EXPANDED_RELEASE_PATH,
    LAYOUT_RELEASE_PATH, LAYOUT_RELEASE_SHA256, FULL_LAYOUT_RELEASE_PATH, FULL_LAYOUT_RELEASE_SHA256,
    PROGRESSION_RELEASE_PATH, PROGRESSION_RELEASE_SHA256, FULL_PROGRESSION_RELEASE_PATH, FULL_PROGRESSION_RELEASE_SHA256,
    PROJECTION_RELEASE_PATH, PROJECTION_RELEASE_SHA256, FULL_PROJECTION_RELEASE_PATH, FULL_PROJECTION_RELEASE_SHA256)
from backend.app.shared.validation import strict_json_object
from .idempotency import canonical_input
from .model_profile import ModelProfile
from .resources import ConfigInvalid, FrozenFunction, V2_MANIFEST_SHA256, V3_MANIFEST_SHA256, V4_MANIFEST_SHA256, V5_MANIFEST_SHA256, V8_MANIFEST_SHA256
from .tokenization import TokenizationGateway

ADOPTION_SHA256 = '0a46525e989905ebca4725a07ed5e4b4b89a070b478929c875b7ae891554a1de'
OBSERVATION_PLAN_SHA256 = '13c5657288a54ffad593a6e66d6097d5273af3e0771d7f429eecc8eec41a4e7a'
ADMISSION_PATH = PRACTICAL_RELEASE_PATH.with_name('admission.json')
# Set only after the approved bounded checks actually succeed. No environment
# flag, report auto-discovery, or loose "latest" selector grants production I/O.
ADMISSION_SHA256 = 'ae136a0472f9a1ddb27c40564198deb6364d7bde6fe538e82351a41c5f3b4957'
EXPANDED_ADMISSION_PATH = EXPANDED_RELEASE_PATH.with_name('admission.json')
EXPANDED_ADMISSION_SHA256 = 'f22f99842e68f82d416a9ad0888cf654ba5751c931b84c01b8a42163792da504'
LAYOUT_ADMISSIONS = {
    'v4': (LAYOUT_RELEASE_PATH.with_name('admission.json'),
           '42c894b46677f366813f696a95e4e9793329e74a6d9ed33fed46aedbefe1279a',
           LAYOUT_RELEASE_SHA256, ADMISSION_SHA256),
    'v5': (FULL_LAYOUT_RELEASE_PATH.with_name('admission.json'),
           '688d0cc8941f84e0bcfa2e33cac07ca7a29f3da2b6946f960ffb911c86b7741e',
           FULL_LAYOUT_RELEASE_SHA256, EXPANDED_ADMISSION_SHA256)}
PROGRESSION_ADMISSIONS = {
    'v6': (PROGRESSION_RELEASE_PATH.with_name('admission.json'),
           '282302677ea6773e34309abe1d3e84fad12fc872efb3d3ea39016a97e33b4652', PROGRESSION_RELEASE_SHA256, 'v4'),
    'v7': (FULL_PROGRESSION_RELEASE_PATH.with_name('admission.json'),
           'c3b0abd94dbc3b34068b41aea799b9a364bd8a1eb9910389ba93e34ec5b24df1', FULL_PROGRESSION_RELEASE_SHA256, 'v5')}
PROJECTION_ADMISSIONS = {
    'v8': (PROJECTION_RELEASE_PATH.with_name('admission.json'),
           'a7ea78950b018e10b015c2af6d048130b6308320d130c1f471aef87e7f70a687', PROJECTION_RELEASE_SHA256, 'v4'),
    'v9': (FULL_PROJECTION_RELEASE_PATH.with_name('admission.json'),
           'f6c261d994d36e581f3a340145db9129d5b3cd63e239902f886907c7f46f94e2', FULL_PROJECTION_RELEASE_SHA256, 'v5')}


def admitted():
    if ADMISSION_SHA256 is None:
        return False
    try:
        raw = ADMISSION_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ADMISSION_SHA256:
            return False
        value = strict_json_object(raw)
        return (value.get('status') == 'ENABLED_AFTER_APPROVED_CHECKS'
                and value.get('decision') == 'D-015'
                and value.get('adoption_sha256') == ADOPTION_SHA256
                and value.get('plan_sha256') == OBSERVATION_PLAN_SHA256
                and value.get('release_sha256') == PRACTICAL_RELEASE_SHA256
                and value.get('admission_mode') == PRACTICAL_MODE
                and value.get('model') == 'deepseek-v4-1-flash-260910'
                and value.get('provider_compatibility_proved') is False)
    except (OSError, ValueError, UnicodeError):
        return False


def expanded_admitted():
    """Explicit budget approval retains the original practical admission gate."""
    if not admitted():
        return False
    try:
        raw = EXPANDED_ADMISSION_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXPANDED_ADMISSION_SHA256:
            return False
        value = strict_json_object(raw)
        return (value.get('status') == 'ENABLED_BY_USER_BUDGET_APPROVAL'
                and value.get('decision') == 'TPL-001'
                and value.get('base_admission_sha256') == ADMISSION_SHA256
                and value.get('release_sha256') == EXPANDED_RELEASE_SHA256
                and value.get('function_manifest_sha256') == V3_MANIFEST_SHA256
                and value.get('admission_mode') == PRACTICAL_MODE
                and value.get('model') == 'deepseek-v4-1-flash-260910'
                and value.get('provider_compatibility_proved') is False)
    except (OSError, ValueError, UnicodeError):
        return False


def layout_admitted(function):
    if function.manifest_sha256 != V4_MANIFEST_SHA256:
        return False
    return _layout_version_admitted(function.version)


def _layout_version_admitted(version):
    binding = LAYOUT_ADMISSIONS.get(version)
    if binding is None:
        return False
    if not (expanded_admitted() if version == 'v5' else admitted()):
        return False
    path, digest, release_digest, base_digest = binding
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            return False
        value = strict_json_object(raw)
        return (value.get('status') == 'ENABLED_BY_USER_CONTEXT_APPROVAL'
                and value.get('decision') == 'CTX-001'
                and value.get('base_admission_sha256') == base_digest
                and value.get('release_sha256') == release_digest
                and value.get('function_manifest_sha256') == V4_MANIFEST_SHA256
                and value.get('function_version') == version
                and value.get('admission_mode') == PRACTICAL_MODE
                and value.get('model') == 'deepseek-v4-1-flash-260910'
                and value.get('provider_compatibility_proved') is False)
    except (OSError, ValueError, UnicodeError):
        return False


def progression_admitted(function):
    binding = PROGRESSION_ADMISSIONS.get(function.version)
    if binding is None or function.action_type != 'INITIALIZE' or function.manifest_sha256 != V5_MANIFEST_SHA256:
        return False
    path, digest, release_digest, base_version = binding
    if not _layout_version_admitted(base_version):
        return False
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            return False
        value = strict_json_object(raw)
        return (value.get('status') == 'ENABLED_BY_USER_FLOW_APPROVAL'
                and value.get('decision') == 'FLOW-002'
                and value.get('base_admission_sha256') == LAYOUT_ADMISSIONS[base_version][1]
                and value.get('release_sha256') == release_digest
                and value.get('function_manifest_sha256') == V5_MANIFEST_SHA256
                and value.get('function_version') == function.version
                and value.get('admission_mode') == PRACTICAL_MODE
                and value.get('model') == 'deepseek-v4-1-flash-260910'
                and value.get('provider_compatibility_proved') is False)
    except (OSError, ValueError, UnicodeError):
        return False


def projection_admitted(function):
    binding = PROJECTION_ADMISSIONS.get(function.version)
    if binding is None or function.manifest_sha256 != V8_MANIFEST_SHA256:
        return False
    path, digest, release_digest, base_version = binding
    if not _layout_version_admitted(base_version):
        return False
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            return False
        value = strict_json_object(raw)
        return (value.get('status') == 'ENABLED_BY_USER_PHASE_A_APPROVAL'
                and value.get('decision') == 'CTX-002-A'
                and value.get('base_admission_sha256') == LAYOUT_ADMISSIONS[base_version][1]
                and value.get('release_sha256') == release_digest
                and value.get('function_manifest_sha256') == V8_MANIFEST_SHA256
                and value.get('function_version') == function.version
                and value.get('admission_mode') == PRACTICAL_MODE
                and value.get('model') == 'deepseek-v4-1-flash-260910'
                and value.get('provider_compatibility_proved') is False)
    except (OSError, ValueError, UnicodeError):
        return False


def before_count(profile, function, release):
    if type(profile) is not ModelProfile or type(function) is not FrozenFunction:
        raise ConfigInvalid('Production AI requires frozen identities')
    frozen = counting_release_for_function(profile, function)
    if canonical_input(release) != canonical_input(frozen):
        raise ConfigInvalid('Production counting release differs')
    release_admitted = (function.version == 'v2' and function.manifest_sha256 == V2_MANIFEST_SHA256 and admitted())
    if function.version == 'v3':
        release_admitted = (function.manifest_sha256 == V3_MANIFEST_SHA256
                            and frozen.get('function_manifest_sha256') == V3_MANIFEST_SHA256
                            and expanded_admitted())
    if function.version in LAYOUT_ADMISSIONS:
        release_admitted = (layout_admitted(function)
                            and frozen.get('function_manifest_sha256') == V4_MANIFEST_SHA256
                            and frozen.get('function_version') == function.version)
    if function.version in PROGRESSION_ADMISSIONS:
        release_admitted = (progression_admitted(function)
                            and frozen.get('function_manifest_sha256') == V5_MANIFEST_SHA256
                            and frozen.get('function_version') == function.version)
    if function.version in PROJECTION_ADMISSIONS:
        release_admitted = (projection_admitted(function)
                            and frozen.get('function_manifest_sha256') == V8_MANIFEST_SHA256
                            and frozen.get('function_version') == function.version)
    return (frozen.get('admission_mode') == PRACTICAL_MODE
            and frozen.get('provider_compatibility_proved') is False
            and release_admitted)


def before_send(profile, context, function):
    release = counting_release_for_function(profile, function)
    if not before_count(profile, function, release) or type(context) is not CountedContext:
        return False
    evidence = context.counting_evidence
    if function.version in PROJECTION_ADMISSIONS:
        try:
            from backend.app.guide.context_builder import restore_transport_input
            if context.basis_json is None: return False
            restore_transport_input(context.input, function, basis=strict_json_object(context.basis_json))
        except (ValueError, TypeError, KeyError):
            return False
    digest = counting_digest_for_function(profile, function)
    return (evidence.get('release_sha256') == digest
            and evidence.get('admission_mode') == PRACTICAL_MODE
            and evidence.get('compatibility_proved') is False
            and evidence.get('framing_reserve_candidate') == 1024)


def production_options():
    """No credential read or network I/O during construction/startup."""
    # V1.5 gates exact release/profile in collaboration_execution, before
    # counting and Chat. Historical Function admissions cannot authorize it.
    return {'counting_counter': TokenizationGateway()}
