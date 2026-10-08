"""Default service AI dependencies, bound to immutable approved releases.

Wiring a real counter grants no network permission. Legacy v1/v2 stay closed;
v3 needs its separately pinned admission after the approved bounded checks.
Observations never change these resources or open a gate automatically.
"""
import hashlib

from backend.app.guide.counted_context import (
    CountedContext, counting_release, release_identity,
    PRACTICAL_RELEASE_SHA256, PRACTICAL_MODE, PRACTICAL_RELEASE_PATH)
from backend.app.shared.validation import strict_json_object
from .idempotency import canonical_input
from .model_profile import ModelProfile
from .resources import ConfigInvalid, FrozenFunction
from .tokenization import TokenizationGateway

ADOPTION_SHA256 = '0a46525e989905ebca4725a07ed5e4b4b89a070b478929c875b7ae891554a1de'
OBSERVATION_PLAN_SHA256 = '13c5657288a54ffad593a6e66d6097d5273af3e0771d7f429eecc8eec41a4e7a'
ADMISSION_PATH = PRACTICAL_RELEASE_PATH.with_name('admission.json')
# Set only after the approved bounded checks actually succeed. No environment
# flag, report auto-discovery, or loose "latest" selector grants production I/O.
ADMISSION_SHA256 = 'ae136a0472f9a1ddb27c40564198deb6364d7bde6fe538e82351a41c5f3b4957'


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


def before_count(profile, function, release):
    if type(profile) is not ModelProfile or type(function) is not FrozenFunction:
        raise ConfigInvalid('Production AI requires frozen identities')
    frozen = counting_release(profile)
    if canonical_input(release) != canonical_input(frozen):
        raise ConfigInvalid('Production counting release differs')
    return (release_identity(profile)[1] == PRACTICAL_RELEASE_SHA256
            and frozen.get('admission_mode') == PRACTICAL_MODE
            and frozen.get('provider_compatibility_proved') is False
            and function.version == 'v2'
            and function.manifest_sha256 == 'b30923bccfa873fce9fa7e45c74bae399e0051d6ca873b21346677f4cd36d905'
            and admitted())


def before_send(profile, context, function):
    release = counting_release(profile)
    if not before_count(profile, function, release) or type(context) is not CountedContext:
        return False
    evidence = context.counting_evidence
    return (evidence.get('release_sha256') == release_identity(profile)[1]
            and evidence.get('admission_mode') == PRACTICAL_MODE
            and evidence.get('compatibility_proved') is False
            and evidence.get('framing_reserve_candidate') == 1024)


def production_options():
    """No credential read or network I/O during construction/startup."""
    return {'counting_counter': TokenizationGateway(),
            'counting_compatibility_check': before_count,
            'compatibility_check': before_send}
