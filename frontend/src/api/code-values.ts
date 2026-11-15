/** V2 amounts stay decimal strings on the wire; arithmetic uses micro-CNY. */
import { count, require, shape, text } from './decoding.ts';

export function money(value: unknown): string {
  const result = text(value);
  require(result === result.trim());
  require(/^(0|[1-9][0-9]*)(\.[0-9]{1,6})?$/.test(result));
  return result;
}

export function cnyBalance(value: unknown): string {
  const result = text(value);
  require(result === result.trim());
  require(/^-?(0|[1-9][0-9]*)\.[0-9]{6}$/.test(result) && result !== '-0.000000');
  return result;
}

function decimalMicro(value: string): bigint {
  const negative = value.startsWith('-');
  const [whole = '0', fraction = ''] = value.replace(/^-/, '').split('.');
  const magnitude = BigInt(whole) * 1000000n + BigInt(fraction.padEnd(6, '0'));
  return negative ? -magnitude : magnitude;
}

export function moneyMicro(value: unknown): bigint {
  return decimalMicro(money(value));
}

export function balanceMicro(value: unknown): bigint {
  return decimalMicro(cnyBalance(value));
}

export function formatCnyBalance(value: bigint): string {
  const magnitude = value < 0n ? -value : value;
  const whole = magnitude / 1000000n;
  const fraction = (magnitude % 1000000n).toString().padStart(6, '0');
  return `${value < 0n ? '-' : ''}${whole}.${fraction}`;
}

const budgetFields = shape({
  limit_cny: money,
  settled_cny: money,
  reserved_cny: money,
  available_cny: cnyBalance,
  unresolved_call_count: count,
});

/** Shared TaskView/TestingTaskView budget projection, one read snapshot. */
export function codeBudget(value: unknown): ReturnType<typeof budgetFields> {
  const result = budgetFields(value);
  require(
    balanceMicro(result.available_cny) ===
      moneyMicro(result.limit_cny) -
        moneyMicro(result.settled_cny) -
        moneyMicro(result.reserved_cny),
  );
  return result;
}
