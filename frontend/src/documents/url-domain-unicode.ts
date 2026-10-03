import profile from '../../../shared/markdown/url-domain-unicode-v1.json' with {type: 'json'};

// The backend owns the shared Markdown semantics. Node's Unicode 17 classes
// must not silently accept a host rejected by the selected Python 15.1 profile.
// This immutable source table is generated once; all codepoints are verified
// against the actual backend, rather than trusting its version label alone.
export function isUrlDomainAlphanumeric(point: number): boolean {
  if (!Number.isInteger(point) || point < 0 || point > 0x10ffff) return false;
  let low = 0, high = profile.ranges.length;
  while (low < high) {
    const middle = (low + high) >>> 1, range = profile.ranges[middle]!;
    if (point < range[0]!) high = middle;
    else if (point > range[1]!) low = middle + 1;
    else return true;
  }
  return false;
}
