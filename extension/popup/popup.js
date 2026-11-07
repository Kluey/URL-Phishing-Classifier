import { normalizeHost, suffixes } from "../rules.js";

const $ = (id) => document.getElementById(id);

const VERDICTS = {
  phishing: ["danger", "Looks like phishing"],
  legit: ["ok", "Looks fine"],
  allow: ["ok", "Popular site"],
  user: ["ok", "You allowed this site"],
  shared: ["neutral", "Shared platform: anyone can publish here"],
  skip: ["muted", "Private or local address, not checked"],
  unknown: ["muted", "Couldn't check right now. The service may be warming up; try again shortly."],
};

async function currentHost() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const url = new URL(tab?.url ?? "");
    return url.protocol === "http:" || url.protocol === "https:" ? url.hostname : null;
  } catch {
    return null;
  }
}

async function getUserAllow() {
  const { userAllow = [] } = await chrome.storage.local.get("userAllow");
  return userAllow;
}

async function render(host) {
  const allowBtn = $("allow");
  const unallowBtn = $("unallow");
  allowBtn.hidden = unallowBtn.hidden = true;

  if (!host) {
    $("host").textContent = "This page";
    $("verdict").className = "verdict muted";
    $("verdict").textContent = "Not checked: only http and https pages are checked";
    return;
  }
  $("host").textContent = host;
  $("verdict").className = "verdict muted";
  $("verdict").textContent = "Checking…";

  let result = { verdict: "unknown" };
  try {
    const answer = await chrome.runtime.sendMessage({ type: "check", hosts: [host] });
    result = answer?.[host] ?? result;
  } catch {
    // Service worker unavailable: show unknown
  }
  const [tone, text] = VERDICTS[result.verdict] ?? VERDICTS.unknown;
  $("verdict").className = `verdict ${tone}`;
  $("verdict").textContent = text;
  $("detail").textContent =
    typeof result.p === "number" ? `Model score p(phishing) = ${result.p.toFixed(2)}` : "";

  if (result.verdict === "user") unallowBtn.hidden = false;
  else if (result.verdict !== "skip") allowBtn.hidden = false;
}

async function main() {
  const { enabled = true } = await chrome.storage.local.get("enabled");
  $("enabled").checked = enabled;
  $("enabled").addEventListener("change", (e) => chrome.storage.local.set({ enabled: e.target.checked }));

  const host = await currentHost();
  const normalized = host && normalizeHost(host);

  $("allow").addEventListener("click", async () => {
    const userAllow = new Set(await getUserAllow());
    userAllow.add(normalized);
    await chrome.storage.local.set({ userAllow: [...userAllow] });
    render(host);
  });
  $("unallow").addEventListener("click", async () => {
    // Remove whichever entry covers this host (it may have been added on a parent domain)
    const covering = new Set(suffixes(normalized));
    const userAllow = (await getUserAllow()).filter((d) => !covering.has(d));
    await chrome.storage.local.set({ userAllow });
    render(host);
  });

  render(host);
}

main();
