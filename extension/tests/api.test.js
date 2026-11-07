import assert from "node:assert/strict";
import { test } from "node:test";

import { classifyBatch, classifyBatchDetailed, createBreaker } from "../api.js";

const apiUrl = "https://api.example";
const fast = { apiUrl, retryDelayMs: 0, retryTimeoutMs: 20, perHostMs: 0 }; // no real waiting in tests

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function scoringFetch(calls) {
  return async (url, init) => {
    const { hosts } = JSON.parse(init.body);
    calls.push({ url, hosts });
    return jsonResponse({
      threshold: 0.8,
      results: hosts.map((host) => ({
        host,
        p_phishing: host.startsWith("bad") ? 0.95 : 0.1,
        label: host.startsWith("bad") ? "Phishing" : "Legitimate",
        error: null,
      })),
    });
  };
}

test("splits into sequential chunks of 32 and keeps order", async () => {
  const calls = [];
  let active = 0;
  const inner = scoringFetch(calls);
  const fetchFn = async (url, init) => {
    active += 1;
    assert.equal(active, 1, "chunks must not overlap");
    try {
      return await inner(url, init);
    } finally {
      active -= 1;
    }
  };
  const hosts = Array.from({ length: 70 }, (_, i) => (i % 7 === 0 ? `bad${i}.xyz` : `ok${i}.com`));
  const results = await classifyBatch(hosts, { apiUrl, fetchFn });

  assert.deepEqual(calls.map((c) => c.hosts.length), [32, 32, 6]);
  assert.equal(calls[0].url, `${apiUrl}/v1/classify/batch`);
  assert.equal(results.length, 70);
  results.forEach((r, i) => {
    assert.equal(r.verdict, hosts[i].startsWith("bad") ? "phishing" : "legit");
  });
  assert.equal(results[0].p, 0.95);
});

test("an item error is unknown, the rest still count", async () => {
  const fetchFn = async () =>
    jsonResponse({
      threshold: 0.8,
      results: [
        { host: "x", error: "Invalid host" },
        { host: "bad.xyz", p_phishing: 0.9, label: "Phishing", error: null },
      ],
    });
  const results = await classifyBatch(["x", "bad.xyz"], { apiUrl, fetchFn });
  assert.deepEqual(results, [{ verdict: "unknown" }, { verdict: "phishing", p: 0.9 }]);
});

test("a 5xx, a network error or bad JSON gives unknown", async () => {
  // Only the retryable ones mark the API as unavailable (and so open the breaker)
  for (const [inner, unavailable] of [
    [async () => jsonResponse({ message: "Service Unavailable" }, 503), true],
    [
      async () => {
        throw new TypeError("network");
      },
      true,
    ],
    [async () => ({ ok: true, status: 200, json: async () => JSON.parse("{") }), false],
    [async () => jsonResponse({}), false],
  ]) {
    const fetchFn = async (...args) => inner(...args);
    const { results, failed } = await classifyBatchDetailed(["a.com", "b.com"], { ...fast, fetchFn });
    assert.deepEqual(results, [{ verdict: "unknown" }, { verdict: "unknown" }]);
    assert.equal(failed, unavailable);
  }
});

test("the timeout grows with the number of hosts", async () => {
  const seen = [];
  const fetchFn = (_url, { signal }) => {
    const start = Date.now();
    return new Promise((_, reject) =>
      signal.addEventListener("abort", () => {
        seen.push(Date.now() - start);
        reject(signal.reason);
      }),
    );
  };
  const opts = { ...fast, fetchFn, timeoutMs: 20, retryTimeoutMs: 20, perHostMs: 10 };
  await classifyBatch(["a.com"], opts);
  await classifyBatch(Array.from({ length: 30 }, (_, i) => `h${i}.com`), opts);
  // 1 host: 20 + 10 ms per attempt; 30 hosts: 20 + 300 ms per attempt
  assert.equal(seen.length, 4);
  assert.ok(seen[0] < 200 && seen[1] < 200, `1 host: ${seen}`);
  assert.ok(seen[2] >= 300 && seen[3] >= 300, `30 hosts: ${seen}`);
});

test("a slow response times out as unknown", async () => {
  const fetchFn = (_url, { signal }) =>
    new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  const start = Date.now();
  const results = await classifyBatch(["a.com"], { ...fast, fetchFn, timeoutMs: 20 });
  assert.deepEqual(results, [{ verdict: "unknown" }]);
  assert.ok(Date.now() - start < 1000);
});

function flaky(failures) {
  const calls = [];
  const ok = scoringFetch([]);
  const fetchFn = async (url, init) => {
    calls.push(init.body);
    const failure = failures[calls.length - 1];
    if (failure) return failure();
    return ok(url, init);
  };
  return { calls, fetchFn };
}

const status = (code) => async () => jsonResponse({ message: "x" }, code);
const networkError = async () => {
  throw new TypeError("network");
};
const hangUntilAbort = (_url, { signal }) =>
  new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason)));

test("retries once after a 5xx, 429, network error or timeout", async () => {
  for (const failure of [status(503), status(500), status(429), networkError]) {
    const { calls, fetchFn } = flaky([failure]);
    const { results, failed } = await classifyBatchDetailed(["bad.xyz"], { ...fast, fetchFn });
    assert.equal(calls.length, 2);
    assert.deepEqual(results, [{ verdict: "phishing", p: 0.95 }]);
    assert.equal(failed, false);
  }
  // Timeout on the first attempt, answer on the retry (which gets its own, longer timeout)
  let n = 0;
  const ok = scoringFetch([]);
  const fetchFn = (url, init) => (++n === 1 ? hangUntilAbort(url, init) : ok(url, init));
  const results = await classifyBatch(["ok.com"], { ...fast, fetchFn, timeoutMs: 20, retryTimeoutMs: 1000 });
  assert.equal(n, 2);
  assert.deepEqual(results, [{ verdict: "legit", p: 0.1 }]);
});

test("no retry on a 4xx other than 429, or on bad JSON", async () => {
  for (const failure of [status(400), status(413), status(422), async () => jsonResponse({})]) {
    const { calls, fetchFn } = flaky([failure]);
    const { results, failed } = await classifyBatchDetailed(["a.com"], { ...fast, fetchFn });
    assert.equal(calls.length, 1);
    assert.deepEqual(results, [{ verdict: "unknown" }]);
    assert.equal(failed, false); // specific to this request: the API is up, so no breaker
  }
});

test("two failures in a row: exactly 2 calls, unknown", async () => {
  const { calls, fetchFn } = flaky([status(503), status(503)]);
  const { results, failed } = await classifyBatchDetailed(["a.com", "b.com"], { ...fast, fetchFn });
  assert.equal(calls.length, 2);
  assert.deepEqual(results, [{ verdict: "unknown" }, { verdict: "unknown" }]);
  assert.equal(failed, true);
});

test("a failed chunk doesn't affect the other chunks", async () => {
  const { calls, fetchFn } = flaky([status(503), status(503)]);
  const hosts = Array.from({ length: 40 }, (_, i) => `bad${i}.xyz`);
  const { results, failed } = await classifyBatchDetailed(hosts, { ...fast, fetchFn });
  assert.equal(calls.length, 3); // chunk 1 twice, chunk 2 once
  assert.ok(results.slice(0, 32).every((r) => r.verdict === "unknown"));
  assert.ok(results.slice(32).every((r) => r.verdict === "phishing"));
  assert.equal(failed, true);
});

test("breaker: a failure opens it for the cooldown, a success closes it", () => {
  let t = 1000;
  const breaker = createBreaker({ cooldownMs: 30_000, now: () => t });
  assert.equal(breaker.isOpen(), false);
  breaker.failure();
  assert.equal(breaker.isOpen(), true);
  t += 29_999;
  assert.equal(breaker.isOpen(), true);
  t += 1;
  assert.equal(breaker.isOpen(), false);
  breaker.failure();
  breaker.success();
  assert.equal(breaker.isOpen(), false);
});
