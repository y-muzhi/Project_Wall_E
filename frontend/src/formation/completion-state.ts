export type RemainingDisposition = Readonly<{
  ref: string;
  disposition: 'TRANSFER' | 'DEFERRED' | 'DROPPED';
  to_step_ref: string | null;
  reason: string | null;
}>;
export type RemainingChoices = Readonly<Record<string, RemainingDisposition>>;
export function remainingProblem(values: RemainingChoices): string | null {
  const rows = Object.values(values);
  if (rows.length > 20) return '每类最多明确处置20项，其余保持开放';
  for (const row of rows) {
    if (row.disposition === 'TRANSFER') {
      if (row.to_step_ref === null) return '请为转交事项选择目标步骤';
    } else if (row.reason === null || row.reason.trim() === '' || [...row.reason].length > 1000)
      return '请填写暂缓或放弃的原因，最多1000字符';
  }
  return null;
}
export function changeRemaining(
  values: RemainingChoices,
  ref: string,
  disposition: RemainingDisposition['disposition'] | 'KEEP_OPEN',
): RemainingChoices {
  const next = { ...values };
  if (disposition === 'KEEP_OPEN') delete next[ref];
  else if (values[ref]?.disposition !== disposition)
    next[ref] = {
      ref,
      disposition,
      to_step_ref: null,
      reason: disposition === 'TRANSFER' ? null : '',
    };
  return Object.freeze(next);
}
