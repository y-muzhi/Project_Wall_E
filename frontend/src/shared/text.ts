/** SHR-TEXT Unicode White_Space, exactly matching the native validator.
 * This is for ordinary form input, never Markdown or anchor fragments.
 */
const whitespace = '\u0009\u000a\u000b\u000c\u000d\u0020\u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000';
const leading = new RegExp('^[' + whitespace + ']+'), trailing = new RegExp('[' + whitespace + ']+$');
export function normalizeOrdinary(value: string): string {
  if (typeof value !== 'string') throw new TypeError('Text required');
  for (const character of value) if (character.length === 1 && character.charCodeAt(0) >= 0xd800 && character.charCodeAt(0) <= 0xdfff) throw new TypeError('Invalid Unicode');
  return value.replace(/\r\n?/g, '\n').replace(leading, '').replace(trailing, '');
}
export class FormFieldError extends Error { readonly field: string; constructor(field: string, message: string) { super(message); this.field = field; } }
export function ordinaryInput(value: string, field: string, minimum: number, maximum: number, multiline = true): string {
  let normalized: string;
  try { normalized = normalizeOrdinary(value); } catch { throw new FormFieldError(field, '请输入有效的 Unicode 文本'); }
  const length = [...normalized].length;
  if (length < minimum) throw new FormFieldError(field, '请填写此项');
  if (length > maximum) throw new FormFieldError(field, `最多允许 ${maximum} 个字符`);
  if (!multiline && normalized.includes('\n')) throw new FormFieldError(field, '此项不能包含换行');
  return normalized;
}
