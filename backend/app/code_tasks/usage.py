"""Pure SHR-CODE-USAGE transitions for one original response.

The gateway must audit each raw frame before using this reducer. This is not
a settlement ledger: database uniqueness must enforce one original settlement.
Final source/completion evidence comes from the admitted protocol adapter.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from backend.app.shared.validation import MAX_SAFE_INTEGER

UsageStatus = Literal['NOT_REPORTED', 'PARTIAL', 'FINAL', 'DISPUTED']
FinalSource = Literal['USAGE_TRAILER', 'FINAL_FINISH_FRAME', 'COMPLETE_BODY']


@dataclass(frozen=True)
class UsageContract:
    version: str
    final_source: FinalSource
    required_dimensions: tuple[str, ...]
    cache_dimensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.final_source not in ('USAGE_TRAILER', 'FINAL_FINISH_FRAME', 'COMPLETE_BODY'):
            raise ValueError('Unadmitted final source')
        for dimensions in (self.required_dimensions, self.cache_dimensions):
            if (
                type(dimensions) is not tuple
                or any(type(name) is not str or not name for name in dimensions)
                or len(set(dimensions)) != len(dimensions)
            ):
                raise ValueError('Usage dimensions must be unique immutable names')
        if not {'input_tokens', 'output_tokens'} <= set(self.required_dimensions):
            raise ValueError('Final input/output dimensions are required')
        if not set(self.cache_dimensions) <= set(self.required_dimensions):
            raise ValueError('Price-relevant cache dimensions must be required')
        if set(self.cache_dimensions) & {'input_tokens', 'output_tokens', 'reasoning_tokens'}:
            raise ValueError('Cache dimensions must describe disjoint input subsets')
        if type(self.version) is not str or not self.version:
            raise ValueError('Fixed parser version is required')


@dataclass(frozen=True)
class UsageState:
    response_ref: str
    status: UsageStatus = 'NOT_REPORTED'
    latest: tuple[tuple[str, int], ...] = ()
    frozen_final: tuple[tuple[str, int], ...] | None = None
    dispute_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.response_ref) is not str or not self.response_ref:
            raise ValueError('Original response identity is required')

    @property
    def settlement_usage(self) -> dict[str, int] | None:
        if self.status != 'FINAL' or self.frozen_final is None:
            return None
        return dict(self.frozen_final)


def _dispute(state: UsageState, reason: str) -> UsageState:
    return replace(state, status='DISPUTED', dispute_reason=reason)


def observe_usage(
    state: UsageState,
    values: Mapping[str, object],
    *,
    response_ref: str,
    contract: UsageContract,
) -> UsageState:
    """Compare cumulative values, never add frames or fill missing with zero.

    Subsets compare only values present together, never stale cross-frame values.
    """
    if state.status == 'DISPUTED':
        return state
    if response_ref != state.response_ref:
        return _dispute(state, 'RESPONSE_MISMATCH')
    observed: dict[str, int] = {}
    for name, value in values.items():
        if type(name) is not str or not name:
            return _dispute(state, 'INVALID_DIMENSION')
        if value is None:
            continue
        if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
            return _dispute(state, 'INVALID_USAGE')
        observed[name] = value
    if 'input_tokens' in observed:
        cached = sum(observed.get(name, 0) for name in contract.cache_dimensions)
        if cached > observed['input_tokens']:
            return _dispute(state, 'CACHE_EXCEEDS_INPUT')
    if (
        'reasoning_tokens' in observed
        and 'output_tokens' in observed
        and observed['reasoning_tokens'] > observed['output_tokens']
    ):
        return _dispute(state, 'REASONING_EXCEEDS_OUTPUT')
    latest = dict(state.latest)
    if state.frozen_final is not None:
        final = dict(state.frozen_final)
        if any(name not in final or final[name] != value for name, value in observed.items()):
            return _dispute(state, 'FROZEN_USAGE_CHANGED')
        return state
    if any(name in latest and value < latest[name] for name, value in observed.items()):
        return _dispute(state, 'USAGE_REGRESSED')
    latest.update(observed)
    return replace(
        state,
        status='PARTIAL' if latest else 'NOT_REPORTED',
        latest=tuple(sorted(latest.items())),
    )


def confirm_final_usage(
    state: UsageState,
    values: Mapping[str, object],
    *,
    response_ref: str,
    contract: UsageContract,
    source: FinalSource,
    complete: bool,
    audit_complete: bool,
) -> UsageState:
    """Freeze only the actual final candidate, never a guessed frame.

    For trailers call at real DONE with the last complete vector after finish.
    For finish frames prove the vector stayed unchanged through real DONE.
    For complete bodies prove reliable end of the non-streaming response.
    """
    observed = observe_usage(state, values, response_ref=response_ref, contract=contract)
    if observed.status == 'DISPUTED':
        return observed
    if source != contract.final_source:
        return _dispute(observed, 'FINAL_SOURCE_MISMATCH')
    if complete is not True or audit_complete is not True:
        return observed
    if any(name not in values or values[name] is None for name in contract.required_dimensions):
        return observed
    final = tuple(sorted((name, value) for name, value in values.items() if value is not None))
    if state.frozen_final is not None:
        if final != state.frozen_final:
            return _dispute(observed, 'FINAL_VECTOR_CHANGED')
        return observed
    return replace(observed, status='FINAL', frozen_final=final)
