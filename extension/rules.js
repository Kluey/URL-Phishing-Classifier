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

// "::ffff:192.168.1.1" -> [0, 0, 0, 0, 0, 0xffff, 0xc0a8, 0x101]; null if malformed
function parseIpv6(host) {
  let groups = host.split(":");
  const last = groups[groups.length - 1];
  if (last.includes(".")) {
    const v4 = parseIpv4(last);
    if (!v4) return null;
    groups = [...groups.slice(0, -1), ((v4[0] << 8) | v4[1]).toString(16), ((v4[2] << 8) | v4[3]).toString(16)];
  }
  const gap = groups.indexOf("");
  if (gap !== -1) {
    // "::" splits into empty strings at the gap (two at either end)
    const head = groups.slice(0, gap);
    const tail = groups.slice(groups.lastIndexOf("") + 1);
    if (head.length + tail.length > 7) return null;
    groups = [...head, ...Array(8 - head.length - tail.length).fill("0"), ...tail];
  }
  if (groups.length !== 8 || !groups.every((g) => /^[0-9a-f]{1,4}$/.test(g))) return null;
  return groups.map((g) => parseInt(g, 16));
}

function isPrivateIpv6(host) {
  const h = parseIpv6(host);
  if (!h) return true; // not a real address: never send it
  const zerosUpTo = (n) => h.slice(0, n).every((x) => x === 0);
  if (zerosUpTo(7) && h[7] <= 1) return true; // :: and ::1
  // IPv4-mapped ::ffff:a.b.c.d: private if the IPv4 address is
  if (zerosUpTo(5) && h[5] === 0xffff) {
    return isPrivateIpv4([h[6] >> 8, h[6] & 0xff, h[7] >> 8, h[7] & 0xff]);
  }
  return (h[0] & 0xfe00) === 0xfc00 || (h[0] & 0xffc0) === 0xfe80;
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
