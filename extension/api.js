// Client for POST /v1/classify/batch. fetch is injected so tests can fake it.

export const MAX_BATCH = 32;
const PHISHING_LABEL = "Phishing"; // components.config.LABEL_NAMES[0]
const UNKNOWN = Object.freeze({ verdict: "unknown" });

// A cold Lambda takes ~10–15 s to start. The first request usually times out but still starts
// an instance, so one retry with a longer timeout tends to land on it.
const DEFAULTS = { timeoutMs: 3000, retryDelayMs: 1500, retryTimeoutMs: 8000 };

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// One attempt. Returns the results, or {retry: bool} when there are none.
async function attempt(hosts, { apiUrl, fetchFn, timeoutMs }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchFn(`${apiUrl}/v1/classify/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hosts }),
      signal: controller.signal,
    });
    // 5xx (cold init failure) and 429 (throttled) can pass on a retry; other 4xx won't
    if (!res.ok) return { retry: res.status >= 500 || res.status === 429 };
    const { results } = await res.json();
    if (!Array.isArray(results)) return { retry: false };
    // Results are matched by position; an item with an error echoes the raw input
    return {
      results: hosts.map((_, i) => {
        const item = results[i];
        if (!item || item.error || typeof item.p_phishing !== "number") return UNKNOWN;
        return {
          verdict: item.label === PHISHING_LABEL ? "phishing" : "legit",
          p: item.p_phishing,
        };
      }),
    };
  } catch (err) {
    // Timeout or network error can pass on a retry; bad JSON won't
    return { retry: !(err instanceof SyntaxError) };
  } finally {
    clearTimeout(timer);
  }
}

async function classifyChunk(hosts, opts) {
  let out = await attempt(hosts, { ...opts, timeoutMs: opts.timeoutMs });
  if (!out.results && out.retry) {
    await sleep(opts.retryDelayMs);
    out = await attempt(hosts, { ...opts, timeoutMs: opts.retryTimeoutMs });
  }
  // Never block the page: no answer means unknown
  return { results: out.results ?? hosts.map(() => UNKNOWN), failed: !out.results };
}

// Returns one result per host, in order, plus whether any chunk got no answer at all.
// Chunks run one after another to stay under the API's throttling (10 rps) and reserved concurrency.
export async function classifyBatchDetailed(hosts, { apiUrl, fetchFn = fetch, ...rest }) {
  const opts = { ...DEFAULTS, ...rest, apiUrl, fetchFn };
  const results = [];
  let failed = false;
  for (let i = 0; i < hosts.length; i += MAX_BATCH) {
    const chunk = await classifyChunk(hosts.slice(i, i + MAX_BATCH), opts);
    results.push(...chunk.results);
    failed ||= chunk.failed;
  }
  return { results, failed };
}

export async function classifyBatch(hosts, options) {
  return (await classifyBatchDetailed(hosts, options)).results;
}

// After a request that got no answer even on retry, don't call the API again for a while:
// a page that keeps asking would otherwise retry every host on every hover and scan.
export function createBreaker({ cooldownMs = 30_000, now = Date.now } = {}) {
  let openUntil = 0;
  return {
    isOpen: () => now() < openUntil,
    failure: () => {
      openUntil = now() + cooldownMs;
    },
    success: () => {
      openUntil = 0;
    },
  };
}
