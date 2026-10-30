"""D-015 actual-usage gate, independently repeated before trusting output.

Text counts plus reserve are a preflight estimate, never a universal bound.
This gate cannot undo a paid request. It rejects adoption and further retries.
"""

from backend.app.guide.counted_context import PRACTICAL_RELEASES, PRACTICAL_MODE, counting_release
from backend.app.shared.validation import MAX_SAFE_INTEGER
from .resources import ConfigInvalid


def _integer(value):
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ValueError('Actual token count required')
    return value


def validate_practical_usage(raw, *, profile, counting, input_tokens, output_tokens):
    """Each practical release enforces its own frozen actual-usage limits."""
    if type(counting) is not dict or counting.get('release_sha256') not in PRACTICAL_RELEASES:
        return
    try:
        release = counting_release(profile, release_sha256=counting['release_sha256'])
        if (
            counting.get('admission_mode') != PRACTICAL_MODE
            or counting.get('compatibility_proved') is not False
        ):
            raise ValueError('Practical admission identity differs')
        if (
            type(raw) is not dict
            or raw.get('model') != profile.model_name
            or raw.get('object') != 'chat.completion'
        ):
            raise ValueError('Actual model/envelope differs')
        usage = raw['usage']
        if type(usage) is not dict:
            raise ValueError('Actual usage required')
        prompt = _integer(usage['prompt_tokens'])
        completion = _integer(usage['completion_tokens'])
        total = _integer(usage['total_tokens'])
        if (
            prompt != _integer(input_tokens)
            or completion != _integer(output_tokens)
            or total != prompt + completion
        ):
            raise ValueError('Actual usage differs')
        budget = release['budget']
        if (
            prompt > budget['input_tokens']
            or completion > budget['output_tokens']
            or total > budget['total_tokens']
        ):
            raise ValueError('Actual usage exceeds approved budgets')
        attempts = counting['count_attempts']
        if type(attempts) is not list or not attempts:
            raise ValueError('Exact count receipt required')
        counts = attempts[-1]['measurement']['counts']
        if type(counts) is not list or len(counts) != 6:
            raise ValueError('Exact count receipt differs')
        text_tokens = _integer(counts[0]) + _integer(counts[1])
        reserve = release['framing_reserve_candidate']
        if (
            _integer(counting['input_tokens_candidate']) != text_tokens + reserve
            or not 0 <= prompt - text_tokens <= reserve
        ):
            raise ValueError('Observed framing exceeds admitted reserve')
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise ConfigInvalid('Actual AI usage failed the approved practical budget gate') from error


def validate_collaboration_measurements(
    raw, *, model, release, counts, input_tokens, output_tokens
):
    """Shared small recorded values; no context reconstruction or provider IO."""
    try:
        if (
            type(raw) is not dict
            or raw.get('model') != model
            or raw.get('object') != 'chat.completion'
        ):
            raise ValueError('Actual model/envelope differs')
        usage = raw['usage']
        prompt = _integer(usage['prompt_tokens'])
        completion = _integer(usage['completion_tokens'])
        total = _integer(usage['total_tokens'])
        if (
            prompt != _integer(input_tokens)
            or completion != _integer(output_tokens)
            or total != prompt + completion
        ):
            raise ValueError('Actual usage differs')
        if (
            prompt > release['input_limit']
            or completion > release['output_limit']
            or total > release['total_limit']
        ):
            raise ValueError('Actual usage exceeds collaboration limits')
        details = usage.get('prompt_tokens_details')
        if details is not None:
            if type(details) is not dict:
                raise ValueError('Cache usage details are invalid')
            if (
                details.get('cached_tokens') is not None
                and _integer(details['cached_tokens']) > prompt
            ):
                raise ValueError('Cached input exceeds the actual input')
        if (
            type(counts) is not list
            or len(counts) != 8
            or not 0
            <= prompt - _integer(counts[0]) - _integer(counts[1])
            <= release['framing_reserve']
        ):
            raise ValueError('Observed framing exceeds the admitted reserve')
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise ConfigInvalid('Actual collaboration usage failed its release gate') from error


def validate_collaboration_usage(raw, *, profile, context, catalog, input_tokens, output_tokens):
    """Repeat exact candidate proof before trusting any business result."""
    from backend.app.guide.collaboration_counting import verify_counted

    evidence = verify_counted(context, catalog, profile)
    validate_collaboration_measurements(
        raw,
        model=profile.model_name,
        release=catalog.collaboration.counting,
        counts=evidence['count_attempts'][-1]['measurement']['counts'],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
