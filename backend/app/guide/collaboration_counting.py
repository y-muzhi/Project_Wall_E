"""V1.5 exact eight-text counting and bounded whole-material candidates."""

from dataclasses import dataclass
import json

from backend.app.infrastructure.collaboration_resources import sha256
from backend.app.infrastructure.resources import ConfigInvalid
from backend.app.infrastructure.schema_transport import compact
from backend.app.infrastructure.tokenization import (
    TokenCounts,
    restore_measurement,
    ExactCountUnavailable,
)
from backend.app.infrastructure.idempotency import canonical_input
from .collaboration_context import CollaborationContext, compile_context
from .context_builder import ContextLimitExceeded


@dataclass(frozen=True)
class CountedCollaborationContext(CollaborationContext):
    counting_json: str

    @property
    def counting_evidence(self):
        return json.loads(self.counting_json)


def restore_candidate_measurement(value, texts, profile, catalog):
    """Summary-only evidence can prove rejection, never an accepted request."""
    raw = type(value) is dict and 'response' in value
    measurement = restore_measurement(
        value, texts, raw_required=raw, expected_model=profile.model_name
    )
    counts = measurement.counts
    if len(counts) != 8 or counts[0] <= 0 or counts[1] <= 0:
        raise ConfigInvalid('Eight actual diagnostic counts required')
    release = catalog.collaboration.counting
    predicted = counts[0] + counts[1] + release['framing_reserve']
    accepted = (
        predicted <= release['input_limit']
        and predicted + release['output_limit'] <= release['total_limit']
    )
    if not raw and accepted:
        raise ExactCountUnavailable('AUDIT_CAPACITY')
    return measurement


async def compile_counted(canonical, catalog, profile, *, counter, admission_guard=None):
    resources = catalog.collaboration

    async def admitted():
        if admission_guard is None:
            resources.require_live(profile.snapshot)
        else:
            await admission_guard()

    await admitted()
    release = resources.counting
    if (release['model'], release['model_version']) != (profile.model_name, profile.model_version):
        raise ConfigInvalid('Counting release and exact model differ')
    attempts, seen = [], set()
    for history, background in ((False, False), (True, False), (True, True)):
        context = compile_context(
            canonical, catalog, omit_history=history, omit_background=background
        )
        digest = sha256(context.input_json)
        if digest in seen:
            continue
        seen.add(digest)
        await admitted()
        receipt = await counter.count(profile, context.texts)
        if type(receipt) is not TokenCounts:
            raise ConfigInvalid('Exact immutable count receipt required')
        measurement = restore_candidate_measurement(
            receipt.evidence, context.texts, profile, catalog
        )
        counts = measurement.counts
        if len(counts) != 8 or counts[0] <= 0 or counts[1] <= 0:
            raise ConfigInvalid('Eight actual diagnostic counts required')
        predicted = counts[0] + counts[1] + release['framing_reserve']
        accepted = (
            predicted <= release['input_limit']
            and predicted + release['output_limit'] <= release['total_limit']
        )
        attempts.append(
            {
                'candidate_sha256': digest,
                'system_sha256': sha256(context.system),
                'omit_history': history,
                'omit_background': background,
                'selected': context.basis['selected'],
                'omitted': context.basis['omitted'],
                'measurement': receipt.evidence,
                'within_budget': accepted,
            }
        )
        if accepted:
            evidence = {
                'schema_version': 1,
                'layout': 'collaboration_context_v1',
                'release_sha256': resources.release_sha256,
                'model_profile_sha256': sha256(compact(profile.snapshot)),
                'counting_resource': resources.release['counting'],
                'admission_mode': release['admission_mode'],
                'compatibility_proved': False,
                'input_tokens_candidate': predicted,
                'output_tokens_limit': release['output_limit'],
                'soft_input_target': release['soft_input_target'],
                'soft_target_exceeded': predicted > release['soft_input_target'],
                'count_attempts': attempts,
            }
            return CountedCollaborationContext(
                context.system,
                context.input_json,
                context.basis_json,
                context.manifest_json,
                compact(evidence),
            )
    raise ContextLimitExceeded('Necessary materials exceed the collaboration budget')


def verify_counted(context, catalog, profile, *, expected_canonical=None):
    """Recompile every persisted candidate; hashes alone cannot grant a trim."""
    if type(context) is not CountedCollaborationContext:
        raise ConfigInvalid('Counted collaboration context required')
    resources = catalog.collaboration
    evidence = context.counting_evidence
    if (
        evidence.get('layout'),
        evidence.get('release_sha256'),
        evidence.get('model_profile_sha256'),
        evidence.get('counting_resource'),
    ) != (
        'collaboration_context_v1',
        resources.release_sha256,
        sha256(compact(profile.snapshot)),
        resources.release['counting'],
    ):
        raise ConfigInvalid('Collaboration count identity differs')
    if (
        evidence.get('admission_mode') != resources.counting['admission_mode']
        or evidence.get('compatibility_proved') is not False
    ):
        raise ConfigInvalid('Empirical framing must remain explicit')
    canonical = context.canonical if expected_canonical is None else expected_canonical
    attempts = evidence.get('count_attempts')
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
        raise ConfigInvalid('Bounded actual candidate count required')
    candidates = []
    seen = set()
    for history, background in ((False, False), (True, False), (True, True)):
        candidate = compile_context(
            canonical, catalog, omit_history=history, omit_background=background
        )
        digest = sha256(candidate.input_json)
        if digest not in seen:
            candidates.append((history, background, digest, candidate))
            seen.add(digest)
    last = None
    for index, attempt in enumerate(attempts):
        history, background, digest, candidate = candidates[index]
        if (
            attempt.get('omit_history'),
            attempt.get('omit_background'),
            attempt.get('candidate_sha256'),
            attempt.get('system_sha256'),
        ) != (history, background, digest, sha256(candidate.system)):
            raise ConfigInvalid('Candidate sequence or actual bytes differ')
        if (
            attempt.get('selected') != candidate.basis['selected']
            or attempt.get('omitted') != candidate.basis['omitted']
        ):
            raise ConfigInvalid('Candidate selection differs from its snapshot')
        counts = restore_candidate_measurement(
            attempt['measurement'], candidate.texts, profile, catalog
        ).counts
        if len(counts) != 8 or counts[0] <= 0 or counts[1] <= 0:
            raise ConfigInvalid('Count dimensions or empty diagnostics differ')
        predicted = counts[0] + counts[1] + resources.counting['framing_reserve']
        accepted = (
            predicted <= resources.counting['input_limit']
            and predicted + resources.counting['output_limit'] <= resources.counting['total_limit']
        )
        if attempt.get('within_budget') is not accepted or accepted != (index == len(attempts) - 1):
            raise ConfigInvalid('Counting stopped at a different budget decision')
        last = candidate
    if (last.system, last.input_json, last.basis_json, last.manifest_json) != (
        context.system,
        context.input_json,
        context.basis_json,
        context.manifest_json,
    ):
        raise ConfigInvalid('Final count belongs to another request or basis')
    if (
        evidence.get('input_tokens_candidate') != predicted
        or evidence.get('output_tokens_limit') != resources.counting['output_limit']
        or evidence.get('soft_input_target') != resources.counting['soft_input_target']
        or evidence.get('soft_target_exceeded')
        is not (predicted > resources.counting['soft_input_target'])
    ):
        raise ConfigInvalid('Count summary differs')
    return evidence


def restore_counted(snapshot, catalog, profile):
    resources = catalog.collaboration
    if snapshot['profile'] != profile.snapshot or snapshot['protocol'][
        'release'
    ] != resources.reference('collaboration.release'):
        raise ConfigInvalid('Persisted request release/profile differs')
    basis = resources.validate('ContextBasis', snapshot['context_basis'])
    request = snapshot['request']
    if len(request['messages']) != 2 or [message['role'] for message in request['messages']] != [
        'system',
        'user',
    ]:
        raise ConfigInvalid('Collaboration requires its two-message request')
    context = CountedCollaborationContext(
        request['messages'][0]['content'],
        request['messages'][1]['content'],
        resources.serialize('ContextBasis', basis),
        canonical_input({'selected': basis['selected'], 'omitted': basis['omitted']}),
        compact(snapshot['counting']),
    )
    if profile.request(context) != request:
        raise ConfigInvalid('Persisted model parameters differ')
    verify_counted(context, catalog, profile)
    return context
