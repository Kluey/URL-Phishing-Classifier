import assert from "node:assert/strict";
import { test } from "node:test";

import { apiHost, createRules, normalizeHost, suffixes } from "../rules.js";

const verdictFor = createRules({
  allowlist: ["google.com", "paypal.com", "example.com", "web.app"],
  shared: ["sites.google.com", "web.app", "github.io"],
});

test("normalizeHost matches normalize_url", () => {
  assert.equal(normalizeHost("WWW.Example.COM."), "example.com");
  assert.equal(normalizeHost("www2.paypal.com"), "paypal.com");
  assert.equal(normalizeHost("  [::1] "), "::1");
  assert.equal(normalizeHost("wwwx.com"), "wwwx.com");
  assert.equal(normalizeHost("a".repeat(254)), "");
});

test("suffixes walks labels, not IP literals", () => {
  assert.deepEqual(suffixes("a.b.google.com"), ["a.b.google.com", "b.google.com", "google.com", "com"]);
  assert.deepEqual(suffixes("8.8.8.8"), ["8.8.8.8"]);
});

test("allowlisted registered domains cover their subdomains", () => {
  assert.equal(verdictFor("mail.google.com"), "allow");
  assert.equal(verdictFor("www2.paypal.com"), "allow");
});

test("shared platforms win over the allowlist", () => {
  assert.equal(verdictFor("foo.web.app"), "shared");
  assert.equal(verdictFor("sites.google.com"), "shared");
  assert.equal(verdictFor("user.github.io"), "shared");
});

test("user allow wins over shared", () => {
  assert.equal(verdictFor("foo.web.app", new Set(["foo.web.app"])), "user");
  assert.equal(verdictFor("a.unknown-site.xyz", new Set(["unknown-site.xyz"])), "user");
});

test("private and local hosts are skipped", () => {
  for (const host of [
    "10.1.2.3", "127.0.0.1", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.1.1",
    "100.64.0.1", "0.0.0.0", "[::1]", "[::]", "[fe80::1]", "[fd00::1]", "[fc00::1]",
    // IPv4-mapped, as the browser writes them and in dotted form
    "[::ffff:c0a8:101]", "[::ffff:7f00:1]", "[::ffff:a00:1]", "[::ffff:192.168.1.1]",
    "[0:0:0:0:0:ffff:7f00:1]", "[not:an:ip]",
    "localhost", "intranet", "printer.local", "nas.lan", "router.home.arpa", "app.test",
    "db.internal", "", "   ",
  ]) {
    assert.equal(verdictFor(host), "skip", host);
  }
});

test("public addresses and unknown names are checked", () => {
  for (const host of [
    "8.8.8.8", "172.32.0.1", "100.128.0.1", "[2001:db8::1]", "[2001:db8:0:0:1::1]", "[::ffff:808:808]",
    "[::ffff:8.8.8.8]", "paypal-login-verify.xyz", "999.1.1.1",
  ]) {
    assert.equal(verdictFor(host), "check", host);
  }
});

test("apiHost brackets IPv6 only", () => {
  assert.equal(apiHost("2001:db8::1"), "[2001:db8::1]");
  assert.equal(apiHost("example.com"), "example.com");
  assert.equal(apiHost("8.8.8.8"), "8.8.8.8");
});
