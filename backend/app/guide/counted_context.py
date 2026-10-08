"""D-011/D-015 exact-text compilation and versioned private audit replay.

No Chat I/O and no database transaction. Each changed candidate is counted
again as its actual serialized text. Private ORCH/audit integration is wired;
Legacy candidates retain their pending-proof identity. DeepSeek v3 uses the
separately approved empirical reserve, never a universal compatibility proof.
"""
from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from backend.app.infrastructure.audit_data import audit_json
from backend.app.infrastructure.model_profile import ModelProfile, MODEL_ID, DEFAULT_PROFILE
from backend.app.infrastructure.resources import ConfigInvalid, FrozenFunction
from backend.app.infrastructure.schema_transport import compact, function_schema
from backend.app.infrastructure.tokenization import TokenCounts, integer, restore_measurement, measurement_summary
from backend.app.infrastructure.idempotency import canonical_input
from backend.app.shared.validation import strict_json_object
from .context_builder import BuiltContext, ContextLimitExceeded, assemble_input

RELEASE_PATH = Path(__file__).resolve().parents[2] / 'resources/counting/v1/strategy.json'
RELEASE_SHA256 = 'fbfc01bf6411111f3012e5362218ca1ae76ce6676be5089370f3a3607980b908'
DEEPSEEK_RELEASE_PATH = RELEASE_PATH.parents[1] / 'v2/strategy.json'
DEEPSEEK_RELEASE_SHA256 = 'cdf8453b1e3a5e5ecb9a7919413a2385c45cd8c7ba22cd8b1e8a73e27b536b32'
PRACTICAL_RELEASE_PATH = RELEASE_PATH.parents[1] / 'v3/strategy.json'
PRACTICAL_RELEASE_SHA256 = '959f40c40ecff1b93bad62589a62bbd24c40fc215dce7cc6c44b863744e071ba'
PRACTICAL_MODE = 'exact_text_empirical_framing_v1'


def release_identity(profile=None, *, release_sha256=None):
    if profile is not None and type(profile) is not ModelProfile:
        raise ConfigInvalid('Counting release requires a frozen model profile')
    if profile is not None and profile.profile_id == DEFAULT_PROFILE:
        if release_sha256 in (None, PRACTICAL_RELEASE_SHA256):
            return PRACTICAL_RELEASE_PATH, PRACTICAL_RELEASE_SHA256
        if release_sha256 == DEEPSEEK_RELEASE_SHA256:
            return DEEPSEEK_RELEASE_PATH, DEEPSEEK_RELEASE_SHA256
        raise ConfigInvalid('Counting release does not belong to this profile')
    if release_sha256 not in (None, RELEASE_SHA256):
        raise ConfigInvalid('Counting release does not belong to this profile')
    return RELEASE_PATH, RELEASE_SHA256


def counting_release(profile=None, *, release_sha256=None):
    try:
        path, digest = release_identity(profile, release_sha256=release_sha256)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Counting release bytes changed')
        value = strict_json_object(raw.decode('utf-8'))
        if profile is not None and value['model'] != profile.model_name:
            raise ValueError('Counting release belongs to another model')
        return value
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

    Successful compilation proves only the configured budget calculation
    against returned text counts. The independent admission gates grant I/O.
    Public requests cannot select this compiler, counter or counting release.
    """
    if type(function) is not FrozenFunction or type(profile) is not ModelProfile:
        raise ConfigInvalid('Frozen Function and model are required')
    release = counting_release(profile)
    reserve = release['framing_reserve_candidate']
    if type(reserve) is not int or reserve < 0:
        raise ConfigInvalid('This model has no admitted Chat framing reserve')
    model = profile.model_name
    digest = release_identity(profile)[1]
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
        if type(result) is not TokenCounts or result.model != model or result.text_sha256 != hashes or len(result.counts) != len(texts):
            raise ConfigInvalid('Text counts do not belong to this exact candidate')
        try:
            counts = tuple(integer(count) for count in result.counts)
            # The request hash must bind the complete exact model/text batch.
            expected_request = hashlib.sha256(compact({'model': model, 'text': list(texts)}).encode('utf-8')).hexdigest()
            if result.request_sha256 != expected_request: raise ValueError('Count request mismatch')
        except (ValueError, TypeError) as error:
            raise ConfigInvalid('Text counts are invalid') from error
        attempts.append({'attempt_no': len(attempts)+1, 'removed_history_ids': list(removed_history),
                         'removed_neighbor_ids': list(removed_neighbors), 'measurement': result.evidence})
        input_tokens = counts[0] + counts[1] + release['framing_reserve_candidate']
        evidence = {'release_sha256': digest, 'strategy': release['strategy'],
                    'compatibility_proved': False, 'framing_reserve_candidate': release['framing_reserve_candidate'],
                    'schema': transport.evidence, 'counted_texts': release['counted_texts'],
                    'count_attempts': attempts, 'input_tokens_candidate': input_tokens}
        if digest == PRACTICAL_RELEASE_SHA256:
            evidence['admission_mode'] = PRACTICAL_MODE
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


def counting_snapshot(evidence):
    """Versioned private Chat snapshot; count raw responses stay in the journal."""
    return {**evidence, 'audit_format':'counts_summary_v1', 'count_attempts':[
        {**attempt,'measurement':measurement_summary(attempt['measurement'])} for attempt in evidence['count_attempts']]}


def verify_counting_evidence(actual, function, *, system, input_json, manifest_json, evidence, summary=False, profile=None):
    """Replay exact candidates from actual C03 without I/O or token guesses.

    Every retained/removed item, text hash, count ownership and each single cut
    must reproduce the final input. This gate grants no sending permission.
    """
    try:
        if type(evidence) is not dict:raise ValueError('Counting evidence required')
        digest=evidence.get('release_sha256')
        release=counting_release(profile,release_sha256=digest);policy=function.context_policy
        if digest!=release_identity(profile,release_sha256=digest)[1]:raise ValueError('Counting release missing')
        reserve=release['framing_reserve_candidate']
        model=MODEL_ID if profile is None else profile.model_name
        if type(reserve) is not int or reserve < 0:raise ValueError('Model-specific framing reserve is unavailable')
        if policy['budget']!=release['budget'] or policy['trim_order']!=release['trim_order']:raise ValueError('Counting policy')
        fields={'release_sha256','strategy','compatibility_proved','framing_reserve_candidate','schema','counted_texts','count_attempts','input_tokens_candidate'}
        if digest==PRACTICAL_RELEASE_SHA256:
            fields.add('admission_mode')
            if evidence.get('admission_mode')!=PRACTICAL_MODE:raise ValueError('Practical admission identity differs')
        if type(evidence) is not dict or set(evidence)!=fields | ({'audit_format'} if summary else set()):raise ValueError('Counting fields')
        transport=function_schema(function)
        if evidence['release_sha256']!=digest or evidence['strategy']!=release['strategy'] or evidence['compatibility_proved'] is not False or type(evidence['framing_reserve_candidate']) is not int or evidence['framing_reserve_candidate']!=reserve or canonical_input(evidence['schema'])!=canonical_input(transport.evidence) or evidence['counted_texts']!=release['counted_texts'] or summary and evidence['audit_format']!='counts_summary_v1':raise ValueError('Counting release identity')
        expected_system=function.prompt+'\n'+transport.schema_json
        if system!=expected_system:raise ValueError('Transport System differs')
        value=assemble_input(actual,function);budget=release['budget']
        required=set(actual['scope']['required_read_block_ids']) | {item['block_id'] for item in value['allowed_targets']} | set(value['template']['locked_heading_block_ids'])
        optional=[item['metadata']['block_id'] for item in value['current_document']['read_blocks'] if item['metadata']['block_id'] not in required]
        history_by_id={item['id']:item for item in actual['history']}
        removed_history,removed_neighbors=[],[]
        attempts=evidence['count_attempts']
        if type(attempts) is not list or not attempts or len(attempts)>1+len(value['history'])+len(optional):raise ValueError('Count attempts')
        for index,attempt in enumerate(attempts):
            if type(attempt) is not dict or set(attempt)!={'attempt_no','removed_history_ids','removed_neighbor_ids','measurement'} or type(attempt['attempt_no']) is not int or attempt['attempt_no']!=index+1 or compact(attempt['removed_history_ids'])!=compact(removed_history) or compact(attempt['removed_neighbor_ids'])!=compact(removed_neighbors):raise ValueError('Count cut sequence')
            encoded=compact({key:value[key] for key in policy['field_order']})
            texts=(system,encoded,*(compact(value[key]) for key in ('user_input','source','template','history')))
            counts=restore_measurement(attempt['measurement'],texts,raw_required=not summary,expected_model=model).counts
            if any(count>budget[limit] for count,limit in zip((counts[0],counts[2],counts[3],counts[4]),('prompt_tokens','current_user_tokens','source_tokens','template_tokens'))):raise ValueError('Required count overflow')
            total=counts[0]+counts[1]+reserve
            overflow=total>budget['input_tokens'] or total+budget['output_tokens']>budget['total_tokens']
            if value['history'] and (counts[5]>budget['history_tokens'] or overflow):
                removed_history.append(value['history'].pop(0)['id'])
            elif counts[5]>budget['history_tokens']:raise ValueError('History count overflow')
            elif overflow and optional:
                identity=optional.pop(0);removed_neighbors.append(identity)
                value['current_document']['read_blocks']=[item for item in value['current_document']['read_blocks'] if item['metadata']['block_id']!=identity]
            elif overflow:raise ValueError('Required input overflow')
            else:
                if index!=len(attempts)-1 or input_json!=encoded or compact(strict_json_object(manifest_json))!=compact(value['read_manifest']) or type(evidence['input_tokens_candidate']) is not int or evidence['input_tokens_candidate']!=total:raise ValueError('Counted final request')
                return value
            originals=[actual['user_input'],*(history_by_id[item['id']] for item in value['history'])]
            ids={item['id'] for item in originals};ids.update(item['reply_to_message_id'] for item in originals if item['message_type']=='CARD_RESPONSE')
            value['read_manifest']['message_ids']=[identity for identity in actual['read_manifest']['message_ids'] if identity in ids]
            value['read_manifest']['block_ids']=[item['metadata']['block_id'] for item in value['current_document']['read_blocks']]
        raise ValueError('No final counted candidate')
    except (ValueError,TypeError,KeyError,UnicodeError) as error:
        raise ConfigInvalid('Counted request does not reproduce its actual context') from error
