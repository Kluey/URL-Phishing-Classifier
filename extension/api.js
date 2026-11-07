// Client for POST /v1/classify/batch. fetch is injected so tests can fake it.

export const MAX_BATCH = 32;
const PHISHING_LABEL = "Phishing"; // components.config.LABEL_NAMES[0]
const UNKNOWN = Object.freeze({ verdict: "unknown" });

async function classifyChunk(hosts, { apiUrl, fetchFn, timeoutMs }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchFn(`${apiUrl}/v1/classify/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hosts }),
      signal: controller.signal,
    });
    if (!res.ok) return hosts.map(() => UNKNOWN);
    const { results } = await res.json();
    // Results are matched by position; an item with an error echoes the raw input
    return hosts.map((_, i) => {
      const item = results?.[i];
      if (!item || item.error || typeof item.p_phishing !== "number") return UNKNOWN;
      return {
        verdict: item.label === PHISHING_LABEL ? "phishing" : "legit",
        p: item.p_phishing,
      };
    });
  } catch {
    // Timeout, network error or bad JSON: never block the page
    return hosts.map(() => UNKNOWN);
  } finally {
    clearTimeout(timer);
  }
}

// Returns one result per host, in order. Chunks run one after another to stay under the
// API's throttling (10 rps) and reserved concurrency.
export async function classifyBatch(hosts, { apiUrl, fetchFn = fetch, timeoutMs = 3000 }) {
  const out = [];
  for (let i = 0; i < hosts.length; i += MAX_BATCH) {
    out.push(...(await classifyChunk(hosts.slice(i, i + MAX_BATCH), { apiUrl, fetchFn, timeoutMs })));
  }
  return out;
}
