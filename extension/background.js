// Service worker: answers {type: "check", hosts} with a verdict per host.
// Order: local rules, then the session cache, then the API. Hostnames are never logged.

import { UNKNOWN, classifyBatchDetailed, createBreaker } from "./api.js";
import { API_URL } from "./config.js";
import { apiHost, createRules, normalizeHost } from "./rules.js";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const CACHED_VERDICTS = new Set(["phishing", "legit"]); // never cache "unknown"

// Opens after a request that failed even on retry; while open, the API isn't called.
// Lives in the worker's memory, so a restarted worker tries again straight away.
const breaker = createBreaker({ cooldownMs: 30_000 });

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

// One API request at a time across all tabs and messages. content.js sends a busy page as
// many 32-host messages, and sending them at once would trip the stage throttle (5 rps).
let apiQueue = Promise.resolve();
function serialized(fn) {
  const run = apiQueue.then(fn, fn);
  apiQueue = run.catch(() => {});
  return run;
}

async function fetchVerdicts(hosts) {
  const { results, failed } = await serialized(async () => {
    // Checked inside the queue, so requests queued behind a failure don't each retry
    if (breaker.isOpen()) return { results: hosts.map(() => UNKNOWN), failed: false };
    const out = await classifyBatchDetailed(hosts.map(apiHost), { apiUrl: API_URL });
    if (out.failed) breaker.failure();
    else breaker.success();
    return out;
  });
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
  for (const [raw, host] of byRaw) out[raw] = resolved.get(host) ?? UNKNOWN;
  return out;
}

// For manual checks from the service worker's DevTools console
self.checkHosts = checkHosts;

// The page host each tab last reported. The check can wait behind the queue or a cold-start
// retry, and a tab that moved on meanwhile must not get the old page's badge.
const pageHosts = new Map();
chrome.tabs?.onRemoved?.addListener((tabId) => pageHosts.delete(tabId));

// Toolbar badge for the tab's own host. Per-tab badges reset when the tab navigates.
// Privacy: unlike link checks, this sends the host of the page being visited (unless it is
// allowlisted, private, user-allowed or cached), so the API sees those page visits.
async function setPageBadge(tabId, host) {
  pageHosts.set(tabId, host);
  let phishing = false;
  if (typeof host === "string" && host) {
    phishing = (await checkHosts([host]))[host]?.verdict === "phishing";
  }
  if (pageHosts.get(tabId) !== host) return; // a newer page in this tab owns the badge
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#c62828" });
    await chrome.action.setBadgeText({ tabId, text: phishing ? "!" : "" });
    await chrome.action.setTitle({
      tabId,
      title: phishing ? "Phishing Link Check: this site looks like phishing" : "Phishing Link Check",
    });
  } catch {
    // The tab closed meanwhile
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return false;
  if (message?.type === "check" && Array.isArray(message.hosts)) {
    checkHosts(message.hosts).then(sendResponse, () => sendResponse({}));
    return true; // respond asynchronously
  }
  // Only from a content script in a top frame, so sender.tab is the page's tab
  if (message?.type === "page" && sender.tab?.id != null && sender.frameId === 0) {
    setPageBadge(sender.tab.id, message.host).catch(() => {});
  }
  return false;
});
