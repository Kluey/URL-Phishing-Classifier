// Local rules that decide, without the API, whether a host needs checking.
// Pure functions, no chrome.* calls, so they run under `node --test`.

const MAX_HOST_LEN = 253;
const WWW = /^www\d*\./;
const LOCAL_SUFFIXES = [".local", ".internal", ".lan", ".home.arpa", ".test", ".localhost"];
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

// Same steps and order as components/preprocessing.normalize_url, applied to a bare hostname.
export function normalizeHost(raw) {
  let host = String(raw ?? "").trim().toLowerCase();
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  host = host.replace(WWW, "").replace(/\.+$/, "");
  return host.length > MAX_HOST_LEN ? "" : host;
}

function parseIpv4(host) {
  const m = IPV4.exec(host);
  if (!m) return null;
  const octets = m.slice(1).map(Number);
  return octets.every((o) => o <= 255) ? octets : null;
}

function isPrivateIpv4([a, b]) {
  return (
    a === 0 || a === 10 || a === 127 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127)
  );
}

export function isIpv6(host) {
  return host.includes(":");
}

function isPrivateIpv6(host) {
  if (host === "::1" || host === "::") return true;
  const first = parseInt(host.split(":")[0] || "0", 16);
  return (first & 0xfe00) === 0xfc00 || (first & 0xffc0) === 0xfe80;
}

function isSkipped(host) {
  if (!host || host === "localhost" || !host.includes(".") && !isIpv6(host)) return true;
  if (LOCAL_SUFFIXES.some((s) => host.endsWith(s))) return true;
  if (isIpv6(host)) return isPrivateIpv6(host);
  const ipv4 = parseIpv4(host);
  return ipv4 !== null && isPrivateIpv4(ipv4);
}

// a.b.google.com -> a.b.google.com, b.google.com, google.com, com. IP literals have no parents.
export function suffixes(host) {
  if (isIpv6(host) || parseIpv4(host)) return [host];
  const labels = host.split(".");
  return labels.map((_, i) => labels.slice(i).join("."));
}

// The host as sent to the API. The server parses "//" + host, so IPv6 needs its brackets back.
export function apiHost(host) {
  return isIpv6(host) ? `[${host}]` : host;
}

// Verdicts: skip (private, never sent), user (allowed in the popup), shared (anyone can
// publish there, neutral notice), allow (top site), check (ask the API).
export function createRules({ allowlist, shared }) {
  const allow = new Set(allowlist);
  const sharedSet = new Set(shared);
  return function verdictFor(rawHost, userAllow = new Set()) {
    const host = normalizeHost(rawHost);
    if (isSkipped(host)) return "skip";
    const parents = suffixes(host);
    if (parents.some((s) => userAllow.has(s))) return "user";
    // Before allow, so sites.google.com is shared while mail.google.com is allowed
    if (parents.some((s) => sharedSet.has(s))) return "shared";
    if (parents.some((s) => allow.has(s))) return "allow";
    return "check";
  };
}
