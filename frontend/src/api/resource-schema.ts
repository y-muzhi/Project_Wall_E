/** Evaluate only the keyword set of the frozen public resource definitions.
 * v1/v2 public schemas have identical approved bytes. No Prompt or input is
 * fetched here; this is shape validation, never model-output repair/adoption.
 */
import resource from '../../../backend/resources/v2/schemas/ASK_OUTPUT.v1.json' with { type: 'json' };
import { object } from './client.ts';
import { require, text } from './decoding.ts';

const definitions: Readonly<Record<string, unknown>> = resource.$defs;
const supported = new Set(['$ref', 'type', 'const', 'enum', 'allOf', 'anyOf', 'oneOf', 'if', 'then', 'else',
  'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'uniqueItems',
  'minimum', 'maximum', 'minLength', 'maxLength', 'pattern', 'format']);

function valid(value: unknown, schema: unknown): boolean {
  try { validate(value, schema); return true; } catch (error) { if (error instanceof TypeError) return false; throw error; }
}
function validate(value: unknown, schema: unknown): void {
  const rule = object(schema);
  if (Object.keys(rule).some(key => !supported.has(key))) throw new Error('Unsupported frozen schema keyword');
  if (rule.$ref !== undefined) {
    if (typeof rule.$ref !== 'string' || !/^#\/\$defs\/[a-z_]+$/.test(rule.$ref)) throw new Error('Unsupported resource reference');
    const referenced = definitions[rule.$ref.slice(8)]; if (referenced === undefined) throw new Error('Missing frozen definition');
    validate(value, referenced);
  }
  if (Object.hasOwn(rule, 'const')) require(JSON.stringify(value) === JSON.stringify(rule.const));
  if (rule.enum !== undefined) require((rule.enum as readonly unknown[]).includes(value));
  if (rule.type !== undefined) {
    const types: Record<string, boolean> = { null: value === null, object: value !== null && typeof value === 'object' && !Array.isArray(value),
      array: Array.isArray(value), string: typeof value === 'string', boolean: typeof value === 'boolean',
      integer: typeof value === 'number' && Number.isSafeInteger(value), number: typeof value === 'number' && Number.isFinite(value) };
    require(typeof rule.type === 'string' && types[rule.type] === true);
  }
  if (rule.allOf !== undefined) for (const child of rule.allOf as readonly unknown[]) validate(value, child);
  for (const key of ['anyOf', 'oneOf']) if (rule[key] !== undefined) {
    const matches = (rule[key] as readonly unknown[]).filter(child => valid(value, child)).length;
    require(key === 'oneOf' ? matches === 1 : matches > 0);
  }
  if (rule.if !== undefined) { const branch = valid(value, rule.if) ? rule.then : rule.else; if (branch !== undefined) validate(value, branch); }
  if (typeof value === 'string') {
    text(value); const length = [...value].length;
    if (rule.minLength !== undefined) require(length >= (rule.minLength as number));
    if (rule.maxLength !== undefined) require(length <= (rule.maxLength as number));
    if (rule.pattern !== undefined) require(new RegExp(rule.pattern as string, 'u').test(value));
    if (rule.format !== undefined) { if (rule.format !== 'date-time') throw new Error('Unsupported format'); require(Number.isFinite(Date.parse(value))); }
  }
  if (typeof value === 'number') {
    if (rule.minimum !== undefined) require(value >= (rule.minimum as number));
    if (rule.maximum !== undefined) require(value <= (rule.maximum as number));
  }
  if (Array.isArray(value)) {
    if (rule.minItems !== undefined) require(value.length >= (rule.minItems as number));
    if (rule.maxItems !== undefined) require(value.length <= (rule.maxItems as number));
    if (rule.uniqueItems === true) require(new Set(value.map(item => JSON.stringify(item))).size === value.length);
    if (rule.items !== undefined) for (const item of value) validate(item, rule.items);
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const row = object(value), properties = rule.properties === undefined ? {} : object(rule.properties);
    if (rule.required !== undefined) for (const key of rule.required as readonly string[]) require(Object.hasOwn(row, key));
    if (rule.additionalProperties === false) require(Object.keys(row).every(key => Object.hasOwn(properties, key)));
    for (const [key, child] of Object.entries(properties)) if (Object.hasOwn(row, key)) validate(row[key], child);
  }
}
export function validateDefinition(name: string, value: unknown): void {
  const schema = definitions[name]; if (schema === undefined) throw new Error('Unregistered frozen definition'); validate(value, schema);
}
