/** Exact public projections; never normalize a stored fact on read. */
import { exact, positiveInteger } from './client.ts';

export type Decoder<T> = (value: unknown) => T;
export const id = positiveInteger;
export function require(condition: boolean): asserts condition { if (!condition) throw new TypeError('API projection is inconsistent'); }
export const count: Decoder<number> = value => { require(typeof value === 'number' && Number.isSafeInteger(value) && value >= 0); return value; };
export const bool: Decoder<boolean> = value => { require(typeof value === 'boolean'); return value; };
export const text: Decoder<string> = value => {
  require(typeof value === 'string');
  for (const char of value) require(char.length !== 1 || char.charCodeAt(0) < 0xd800 || char.charCodeAt(0) > 0xdfff);
  return value;
};
export const nonempty: Decoder<string> = value => { const result = text(value); require(result.length > 0); return result; };
export const time: Decoder<string> = value => {
  const result = text(value); require(/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$/.test(result) && !result.startsWith('0000-'));
  const date = new Date(result); require(Number.isFinite(date.getTime()) && date.toISOString() === result); return result;
};
export function nullable<T>(decode: Decoder<T>): Decoder<T | null> { return value => value === null ? null : decode(value); }
export function choices<const T extends readonly (string | number)[]>(values: T): Decoder<T[number]> {
  return value => { require(values.includes(value as T[number])); return value as T[number]; };
}
export function array<T>(decode: Decoder<T>, maximum: number, minimum = 0): Decoder<readonly T[]> {
  return value => { require(Array.isArray(value) && value.length >= minimum && value.length <= maximum); return Object.freeze(value.map(decode)); };
}
export function shape<T extends Record<string, Decoder<unknown>>>(fields: T): Decoder<Readonly<{ [K in keyof T]: ReturnType<T[K]> }>> {
  return value => {
    const row = exact(value, Object.keys(fields));
    return Object.freeze(Object.fromEntries(Object.entries(fields).map(([key, decode]) => [key, decode(row[key])]))) as Readonly<{ [K in keyof T]: ReturnType<T[K]> }>;
  };
}
export function checked<T>(decode: Decoder<T>, check: (result: T) => void): Decoder<T> {
  return value => { const result = decode(value); check(result); return result; };
}
export function interval(row: { created_at: string; updated_at: string }, events: readonly (string | null)[] = []): void {
  require(row.created_at <= row.updated_at);
  for (const event of events) if (event !== null) require(row.created_at <= event && event <= row.updated_at);
}
export function distinct(values: readonly unknown[]): void { require(new Set(values).size === values.length); }
export type Model<D extends Decoder<unknown>> = ReturnType<D>;
