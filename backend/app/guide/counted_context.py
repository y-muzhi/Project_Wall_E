"""D-011 exact-text compiler candidate, NOT a production compatibility proof.

No Chat I/O and no database transaction. Each changed candidate is counted
again as its actual serialized text. Existing production ORCH remains closed
until real same-model framing proof and audited integration are available.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID
from backend.app.infrastructure.resources import ConfigInvalid, FrozenFunction
from backend.app.infrastructure.schema_transport import compact, function_schema
from backend.app.infrastructure.tokenization import TokenCounts, integer
from backend.app.shared.validation import strict_json_object
from .context_builder import BuiltContext, ContextLimitExceeded, assemble_input

RELEASE_PATH = Path(__file__).resolve().parents[2] / 'resources/counting/v1/strategy.json'
RELEASE_SHA256 = 'fbfc01bf6411111f3012e5362218ca1ae76ce6676be5089370f3a3607980b908'


def counting_release():
    try:
        raw = RELEASE_PATH.read_bytes()
        if hashlib.sha256(raw).hexdigest() != RELEASE_SHA256:
            raise ValueError('Counting release bytes changed')
        return strict_json_object(raw.decode('utf-8'))
    except (OSError, ValueError, UnicodeError) as error:
        raise ConfigInvalid('Frozen counting candidate is unavailable') from error


@dataclass(frozen=True)
class CountedContext(BuiltContext):
    input_tokens: int
    counting_json: str = field(repr=False)

    @property
    def counting_evidence(self):
        return strict_json_object(self.counting_json)


async def compile_counted_candidate(context, function: FrozenFunction, profile: ModelProfile, *, counter):
    """Private candidate boundary: injected counter never grants Chat permission.

    The 256-token reserve is explicitly pending proof. Successful compilation
    proves only the candidate budget calculation against returned text counts.
    Public requests cannot select this compiler, counter or counting release.
    """
    if type(function) is not FrozenFunction or type(profile) is not ModelProfile:
        raise ConfigInvalid('Frozen Function and model are required')
    release = counting_release()
    policy = function.context_policy
    if policy['budget'] != release['budget'] or policy['trim_order'] != release['trim_order']:
        raise ConfigInvalid('Counting cannot override the approved context budgets')
    value = assemble_input(context, function)
    transport = function_schema(function)
    system = function.prompt + '\n' + transport.schema_json
    required = set(context['scope']['required_read_block_ids']) | {item['block_id'] for item in value['allowed_targets']}
    required.update(value['template']['locked_heading_block_ids'])
    optional = [item['metadata']['block_id'] for item in value['current_document']['read_blocks'] if item['metadata']['block_id'] not in required]
    history_by_id = {item['id']: item for item in context['history']}
    removed_history, removed_neighbors, attempts = [], [], []
    budget = release['budget']

    def update_manifest():
        originals = [context['user_input'], *(history_by_id[item['id']] for item in value['history'])]
        ids = {item['id'] for item in originals}
        ids.update(item['reply_to_message_id'] for item in originals if item['message_type'] == 'CARD_RESPONSE')
        value['read_manifest']['message_ids'] = [identity for identity in context['read_manifest']['message_ids'] if identity in ids]
        value['read_manifest']['block_ids'] = [item['metadata']['block_id'] for item in value['current_document']['read_blocks']]

    while True:
        # Validation and exact ordering are repeated after every whole-item cut.
        function.validate_input(value)
        encoded = compact({key: value[key] for key in policy['field_order']})
        texts = (system, encoded, *(compact(value[key]) for key in ('user_input', 'source', 'template', 'history')))
        result = await counter.count(profile, texts)
        hashes = tuple(hashlib.sha256(text.encode('utf-8')).hexdigest() for text in texts)
        if type(result) is not TokenCounts or result.model != MODEL_ID or result.text_sha256 != hashes or len(result.counts) != len(texts):
            raise ConfigInvalid('Text counts do not belong to this exact candidate')
        try:
            counts = tuple(integer(count) for count in result.counts)
            # The request hash must bind the complete exact model/text batch.
            expected_request = hashlib.sha256(compact({'model': MODEL_ID, 'text': list(texts)}).encode('utf-8')).hexdigest()
            if result.request_sha256 != expected_request: raise ValueError('Count request mismatch')
        except (ValueError, TypeError) as error:
            raise ConfigInvalid('Text counts are invalid') from error
        attempts.append({'attempt_no': len(attempts)+1, 'removed_history_ids': list(removed_history),
                         'removed_neighbor_ids': list(removed_neighbors), 'measurement': result.evidence})
        input_tokens = counts[0] + counts[1] + release['framing_reserve_candidate']
        evidence = {'release_sha256': RELEASE_SHA256, 'strategy': release['strategy'],
                    'compatibility_proved': False, 'framing_reserve_candidate': release['framing_reserve_candidate'],
                    'schema': transport.evidence, 'counted_texts': release['counted_texts'],
                    'count_attempts': attempts, 'input_tokens_candidate': input_tokens}
        # Count calls have separate identities; audit overflow cannot silently
        # discard their history or authorize Chat. Credentials remain private.
        evidence_json = audit_json(evidence, credentials=(profile.api_key,))
        for count, limit in zip((counts[0], counts[2], counts[3], counts[4]),
                               (budget['prompt_tokens'], budget['current_user_tokens'], budget['source_tokens'], budget['template_tokens'])):
            if count > limit:
                raise ContextLimitExceeded('Required context exceeds its approved token budget')
        exceeds_input = input_tokens > budget['input_tokens'] or input_tokens + budget['output_tokens'] > budget['total_tokens']
        if value['history'] and (counts[5] > budget['history_tokens'] or exceeds_input):
            removed_history.append(value['history'].pop(0)['id']); update_manifest(); continue
        if counts[5] > budget['history_tokens']:
            raise ContextLimitExceeded('Empty history exceeds its approved token budget')
        if exceeds_input and optional:
            identity = optional.pop(0)
            value['current_document']['read_blocks'] = [item for item in value['current_document']['read_blocks'] if item['metadata']['block_id'] != identity]
            removed_neighbors.append(identity); update_manifest(); continue
        if exceeds_input:
            raise ContextLimitExceeded('Required context exceeds its approved token budget')
        return CountedContext(system, encoded, compact(value['read_manifest']),
                              len(system.encode('utf-8'))+len(encoded.encode('utf-8')),
                              tuple(removed_history), tuple(removed_neighbors), input_tokens, evidence_json)
