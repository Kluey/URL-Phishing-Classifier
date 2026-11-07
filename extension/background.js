// Service worker: answers {type: "check", hosts} with a verdict per host.
// Order: local rules, then the session cache, then the API. Hostnames are never logged.

import { classifyBatch } from "./api.js";
import { API_URL } from "./config.js";
import { apiHost, createRules, normalizeHost } from "./rules.js";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHED_VERDICTS = new Set(["phishing", "legit"]); // never cache "unknown"

async function loadList(name) {
  const res = await fetch(chrome.runtime.getURL(`data/${name}.json`));
  return (await res.json()).domains;
}

const rulesReady = Promise.all([loadList("allowlist"), loadList("shared_platforms")]).then(
  ([allowlist, shared]) => createRules({ allowlist, shared }),
);

// Shared across tabs, so two pages linking the same host make one request
const inFlight = new Map();

async function readCache(hosts) {
  const now = Date.now();
  const stored = await chrome.storage.session.get(hosts.map((h) => `v:${h}`));
  const hits = new Map();
  for (const host of hosts) {
    const entry = stored[`v:${host}`];
    if (entry && now - entry.ts < CACHE_TTL_MS) hits.set(host, { verdict: entry.verdict, p: entry.p });
  }
  return hits;
}

async function fetchVerdicts(hosts) {
  const results = await classifyBatch(hosts.map(apiHost), { apiUrl: API_URL });
  const toCache = {};
  const ts = Date.now();
  hosts.forEach((host, i) => {
    if (CACHED_VERDICTS.has(results[i].verdict)) toCache[`v:${host}`] = { ...results[i], ts };
  });
  try {
    await chrome.storage.session.set(toCache);
  } catch {
    // Quota or a closing worker: the verdicts are still good for this answer
  }
  return new Map(hosts.map((host, i) => [host, results[i]]));
}

// Returns {rawHost: {verdict, p?}}, keyed by the caller's input so content.js
// can look results up by a.hostname without normalizing.
async function checkHosts(rawHosts) {
  const verdictFor = await rulesReady;
  const { userAllow = [] } = await chrome.storage.local.get("userAllow");
  const allowed = new Set(userAllow);

  const byRaw = new Map();
  for (const raw of new Set(rawHosts)) {
    if (typeof raw === "string") byRaw.set(raw, normalizeHost(raw));
  }

  const resolved = new Map();
  const toCheck = new Set();
  for (const host of new Set(byRaw.values())) {
    const verdict = verdictFor(host, allowed);
    if (verdict === "check") toCheck.add(host);
    else resolved.set(host, { verdict });
  }

  const pending = [...toCheck];
  for (const [host, result] of await readCache(pending)) {
    resolved.set(host, result);
    toCheck.delete(host);
  }

  const waits = [];
  const missing = [];
  for (const host of toCheck) {
    if (inFlight.has(host)) waits.push(inFlight.get(host).then((r) => resolved.set(host, r.get(host))));
    else missing.push(host);
  }
  if (missing.length) {
    const request = fetchVerdicts(missing);
    for (const host of missing) inFlight.set(host, request);
    waits.push(
      request
        .then((r) => r.forEach((result, host) => resolved.set(host, result)))
        .finally(() => missing.forEach((host) => inFlight.delete(host))),
    );
  }
  await Promise.all(waits);

  const out = {};
  for (const [raw, host] of byRaw) out[raw] = resolved.get(host) ?? { verdict: "unknown" };
  return out;
}

// For manual checks from the service worker's DevTools console
self.checkHosts = checkHosts;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id || message?.type !== "check" || !Array.isArray(message.hosts)) {
    return false;
  }
  checkHosts(message.hosts).then(sendResponse, () => sendResponse({}));
  return true; // respond asynchronously
});
