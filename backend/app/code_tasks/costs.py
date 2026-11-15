"""SHR-CODE-MONEY/BALANCE/COST: exact CNY arithmetic, without provider I/O.

Inputs are applicable, admitted prices and proven token bounds/final usage.
This module calculates amounts only: it cannot admit a price, settle a database
reservation, release funds, or infer missing usage.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import re

from backend.app.shared.validation import reject, strict_integer, text_value

from .usage import UsageState

MICRO_PER_CNY = 1_000_000
TOKENS_PER_PRICE_UNIT = 1_000_000


def parse_money(value: object, field: str = 'amount') -> int:
    text = text_value(value, field)
    if re.fullmatch(r'(0|[1-9][0-9]*)(\.[0-9]{1,6})?', text) is None:
        reject(field, 'INVALID_FORMAT', '必须是非负十进制金额，最多六位小数')
    whole, _, fraction = text.partition('.')
    return int(whole) * MICRO_PER_CNY + int(fraction.ljust(6, '0'))


def parse_balance(value: object, field: str = 'available_cny') -> int:
    text = text_value(value, field)
    if re.fullmatch(r'-?(0|[1-9][0-9]*)\.[0-9]{6}', text) is None or text == '-0.000000':
        reject(field, 'INVALID_FORMAT', '余额必须是规范的六位小数金额')
    magnitude = parse_money(text.removeprefix('-'), field)
    return -magnitude if text.startswith('-') else magnitude


def format_balance(micro: int) -> str:
    if type(micro) is not int:
        raise TypeError('Micro-CNY must be an integer')
    whole, fraction = divmod(abs(micro), MICRO_PER_CNY)
    sign = '-' if micro < 0 else ''
    return f'{sign}{whole}.{fraction:06d}'


def format_money(micro: int) -> str:
    _nonnegative_micro(micro)
    return format_balance(micro)


def _nonnegative_micro(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError('Money must be nonnegative integer micro-CNY')


def available_balance(limit: int, settled: int, reserved: int) -> int:
    for value in (limit, settled, reserved):
        _nonnegative_micro(value)
    return limit - settled - reserved


def reserve_cost(
    input_cap: int, output_cap: int, max_input_price: int, max_output_price: int
) -> int:
    """Ceil once, using highest admitted prices across all applicable tiers."""
    strict_integer(input_cap, 'input_cap', minimum=0)
    strict_integer(output_cap, 'output_cap', minimum=0)
    _nonnegative_micro(max_input_price)
    _nonnegative_micro(max_output_price)
    numerator = input_cap * max_input_price + output_cap * max_output_price
    return (numerator + TOKENS_PER_PRICE_UNIT - 1) // TOKENS_PER_PRICE_UNIT


@dataclass(frozen=True)
class CachePrice:
    dimension: str
    price_micro: int

    def __post_init__(self) -> None:
        if type(self.dimension) is not str or not self.dimension:
            raise ValueError('Cache dimension is required')
        _nonnegative_micro(self.price_micro)


@dataclass(frozen=True)
class ApplicablePrices:
    """Already selected price tier; cache categories must be proven disjoint."""

    input_micro: int
    output_micro: int
    cache: tuple[CachePrice, ...] = ()

    def __post_init__(self) -> None:
        _nonnegative_micro(self.input_micro)
        _nonnegative_micro(self.output_micro)
        if type(self.cache) is not tuple or any(
            type(item) is not CachePrice for item in self.cache
        ):
            raise TypeError('Cache prices must be an immutable tuple')
        if len({item.dimension for item in self.cache}) != len(self.cache):
            raise ValueError('Duplicate cache dimensions')


class IncompleteUsage(ValueError):
    """Keep the original reservation; missing usage is not zero."""


def settle_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    prices: ApplicablePrices,
    cache_counts: Mapping[str, int] | None = None,
) -> int:
    """Calculate VERIFIED_USAGE only after the caller proves final usage.

    Reasoning tokens are already included in output_tokens. Do not add them.
    No rounding occurs until the entire request numerator has been calculated.
    """
    if input_tokens is None or output_tokens is None:
        raise IncompleteUsage('Final input/output usage is required')
    strict_integer(input_tokens, 'input_tokens', minimum=0)
    strict_integer(output_tokens, 'output_tokens', minimum=0)
    cache_prices = {item.dimension: item.price_micro for item in prices.cache}
    counts = {} if cache_counts is None else dict(cache_counts)
    if counts.keys() - cache_prices.keys():
        raise ValueError('Unpriced cache dimension')
    for dimension, count in counts.items():
        strict_integer(count, dimension, minimum=0)
    cached_tokens = sum(counts.values())
    if cached_tokens > input_tokens:
        raise ValueError('Cache categories exceed total input tokens')
    missing = cache_prices.keys() - counts.keys()
    same_input_prices = all(price == prices.input_micro for price in cache_prices.values())
    if missing and not same_input_prices:
        raise IncompleteUsage('All price-relevant cache dimensions are required')
    numerator = input_tokens * prices.input_micro + output_tokens * prices.output_micro
    if not missing:
        numerator -= cached_tokens * prices.input_micro
        numerator += sum(counts[name] * cache_prices[name] for name in counts)
    return (numerator + TOKENS_PER_PRICE_UNIT // 2) // TOKENS_PER_PRICE_UNIT


def final_usage_cost(state: UsageState, prices: ApplicablePrices) -> int:
    """Calculate only a frozen undisputed final vector; never release a reserve."""
    usage = state.settlement_usage
    if usage is None:
        raise IncompleteUsage('Reliable final usage is required')
    cache_counts = {
        item.dimension: usage[item.dimension] for item in prices.cache if item.dimension in usage
    }
    return settle_cost(usage['input_tokens'], usage['output_tokens'], prices, cache_counts)
