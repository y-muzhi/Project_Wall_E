/** D-004/GFM literal spans in the original source. Markdown context is owned
 * by the inline tokenizer, not by this candidate index. No fuzzy domains. */
import { isUrlDomainAlphanumeric } from './url-domain-unicode.ts';
export interface LiteralLink { readonly start: number; readonly end: number; readonly text: string; readonly href: string; }
const atext = /[A-Za-z0-9.+_-]/;
const domainChar = /[A-Za-z0-9._-]/;
const resource = /[A-Za-z0-9.@]/;
const alphanumeric = /[A-Za-z0-9]/;
const space = /[ \t\r\n\v\f]/;
const prefixes = /https?:\/\/|www\.|mailto:|xmpp:/gi;
const punctuation = new Set('?!.,:*_~');

function emailEnd(source: string, at: number): number | undefined {
  let end = at + 1, dot = false, segment = false;
  while (end < source.length) {
    const char = source[end]!;
    if (domainChar.test(char) && char !== '.') { segment = true; end++; }
    else if (char === '.' && segment && end + 1 < source.length && domainChar.test(source[end + 1]!) && source[end + 1] !== '.') {
      dot = true; segment = false; end++;
    } else break;
  }
  return dot && segment && !'-_'.includes(source[end - 1]!) ? end : undefined;
}

export class AutolinkIndex {
  readonly source: string;
  readonly starts: ReadonlySet<number>;
  private readonly emails = new Map<number, number>();
  constructor(source: string) {
    this.source = source;
    const starts = new Set([...source.matchAll(prefixes)].map(match => match.index));
    for (const match of source.matchAll(/@/g)) {
      const at = match.index;
      let start = at;
      while (start && atext.test(source[start - 1]!)) start--;
      if (start === at) continue;
      const end = emailEnd(source, at);
      if (end !== undefined) { this.emails.set(start, end); starts.add(start); }
    }
    this.starts = starts;
  }
  match(start: number, maximum: number, previous: string | null): LiteralLink | undefined {
    const source = this.source;
    const found = /^(https?:\/\/|www\.|mailto:|xmpp:)/i.exec(source.slice(start, start + 8));
    if (found) {
      const prefix = found[0];
      const protocol = prefix.toLowerCase();
      if (protocol.startsWith('http') || protocol === 'www.') {
        if (previous !== null && !space.test(previous) && !'*_~('.includes(previous)) return;
        const domainStart = protocol === 'www.' ? start : start + prefix.length;
        let domainEnd = domainStart;
        while (domainEnd < maximum) {
          const point = source.codePointAt(domainEnd)!;
          const char = String.fromCodePoint(point);
          if (!'._-'.includes(char) && !isUrlDomainAlphanumeric(point)) break;
          domainEnd += char.length;
        }
        const domain = source.slice(domainStart, domainEnd).replace(/\.+$/, '');
        const labels = domain.split('.');
        if (labels.length < 2 || labels.some(label => !label) || labels.slice(-2).some(label => label.includes('_'))) return;
        let end = domainEnd;
        while (end < maximum && !space.test(source[end]!) && source[end] !== '<') end++;
        let excess = 0;
        for (let index = start; index < end; index++) { if (source[index] === ')') excess++; else if (source[index] === '(') excess--; }
        while (end > domainStart) {
          const char = source[end - 1]!;
          if (punctuation.has(char)) end--;
          else if (char === ')' && excess > 0) { end--; excess--; }
          else if (char === ';') {
            let amp = end - 1;
            while (amp > start && alphanumeric.test(source[amp - 1]!)) amp--;
            if (amp < end - 1 && amp > start && source[amp - 1] === '&') end = amp - 1;
            else break;
          } else break;
        }
        if (end < domainStart + domain.length) return;
        const text = source.slice(start, end).replace(/\0/g, '\ufffd');
        return {start, end, text, href: (protocol === 'www.' ? 'http://' : '') + text};
      }
      if (previous !== null && (atext.test(previous) || previous === '/')) return;
      let end = this.emails.get(start + prefix.length);
      if (end === undefined || end > maximum) return;
      if (protocol === 'xmpp:' && end < maximum && source[end] === '/') {
        let resourceEnd = end + 1;
        while (resourceEnd < maximum && resource.test(source[resourceEnd]!)) resourceEnd++;
        if (resourceEnd > end + 1) end = resourceEnd;
      }
      const text = source.slice(start, end);
      return {start, end, text, href: text};
    }
    const end = this.emails.get(start);
    if (end === undefined || end > maximum || previous !== null && (atext.test(previous) || previous === '/')) return;
    const text = source.slice(start, end);
    return {start, end, text, href: 'mailto:' + text};
  }
}
