// Checks the committed lists (built by scripts/build_extension_lists.py) and the manifest.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { API_URL } from "../config.js";
import { createRules } from "../rules.js";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const allowlist = JSON.parse(read("../data/allowlist.json")).domains;
const shared = JSON.parse(read("../data/shared_platforms.json")).domains;
const manifest = JSON.parse(read("../manifest.json"));
const verdictFor = createRules({ allowlist, shared });

test("allowlist and shared platforms don't overlap", () => {
  const sharedSet = new Set(shared);
  assert.deepEqual(allowlist.filter((d) => sharedSet.has(d)), []);
  assert.ok(allowlist.length > 9000, `allowlist has ${allowlist.length} domains`);
});

test("no public suffix is allowlisted or shared", () => {
  // A suffix entry would cover every site under it, e.g. "co.uk" allowing paypal-verify.co.uk
  const suffixes = ["co.uk", "com.au", "com.br", "co.za", "co.jp", "com.cn", "gov.uk", "ac.uk", "my.id", "ne.jp", "co.in", "com"];
  for (const list of [allowlist, shared]) {
    assert.deepEqual(list.filter((d) => suffixes.includes(d)), []);
  }
  for (const host of ["paypal-verify.co.uk", "login.com.br", "evil.my.id"]) {
    assert.equal(verdictFor(host), "check", host);
  }
});

test("everyday sites are allowed and hosting platforms are shared", () => {
  for (const host of ["google.com", "mail.google.com", "wikipedia.org", "en.wikipedia.org", "github.com"]) {
    assert.equal(verdictFor(host), "allow", host);
  }
  for (const host of [
    "sites.google.com", "foo.web.app", "someone.github.io", "bit.ly", "storage.googleapis.com",
    "x-y-z.trycloudflare.com", "someone.gitlab.io", "blog.wordpress.com", "cutt.ly", "forms.gle",
  ]) {
    assert.equal(verdictFor(host), "shared", host);
  }
});

test("no synthetic phishing host from the real-world check is allowlisted", () => {
  const rows = read("../../eval/real_world_urls.csv").trim().split(/\r?\n/).slice(1);
  const phishing = rows
    .map((line) => line.split(","))
    .filter(([, label]) => label === "0")
    .map(([url]) => new URL(url).hostname);
  assert.equal(phishing.length, 20);
  const allowed = phishing.filter((host) => ["allow", "skip"].includes(verdictFor(host)));
  assert.deepEqual(allowed, []);
});

test("host_permissions covers exactly the configured API", () => {
  assert.deepEqual(manifest.host_permissions, [`${API_URL}/*`]);
  assert.equal(manifest.background.type, "module");
});
