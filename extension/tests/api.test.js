import assert from "node:assert/strict";
import { test } from "node:test";

import { classifyBatch } from "../api.js";

const apiUrl = "https://api.example";

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
  for (const fetchFn of [
    async () => jsonResponse({ message: "Service Unavailable" }, 503),
    async () => {
      throw new TypeError("network");
    },
    async () => ({ ok: true, status: 200, json: async () => JSON.parse("{") }),
    async () => jsonResponse({}),
  ]) {
    assert.deepEqual(await classifyBatch(["a.com", "b.com"], { apiUrl, fetchFn }), [
      { verdict: "unknown" },
      { verdict: "unknown" },
    ]);
  }
});

test("a slow response times out as unknown", async () => {
  const fetchFn = (_url, { signal }) =>
    new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  const start = Date.now();
  const results = await classifyBatch(["a.com"], { apiUrl, fetchFn, timeoutMs: 20 });
  assert.deepEqual(results, [{ verdict: "unknown" }]);
  assert.ok(Date.now() - start < 1000);
});
