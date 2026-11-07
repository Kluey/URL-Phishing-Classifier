// Content script: checks the hosts a page links to and warns before a phishing link opens.
// Only hostnames leave the page (via the service worker). Classic script, so no imports.
(() => {
  const BATCH = 32;
  const PENDING_WAIT_MS = 300;
  const RESCAN_DELAY_MS = 500;
  const BACKDROP_GRACE_MS = 500;
  const UNKNOWN_TTL_MS = 30_000;

  const results = new Map(); // hostname -> {verdict, p?, until?}
  const lookups = new Map(); // hostname -> Promise<{verdict, p?}>
  const bypassed = new Set(); // hosts the user chose "Open anyway" for on this page
  let enabled = false;
  let observer = null;
  let rescanTimer = null;
  let hovered = null;
  let ui = null;
  let overlaySeq = 0; // a newer showOverlay call cancels an older one still waiting for CSS
  let generation = 0; // bumped when userAllow changes; answers from older lookups are dropped
  let replaying = null; // the link whose held click is being replayed with a.click()

  const alive = () => Boolean(chrome.runtime?.id); // false once the extension is reloaded

  function linkUrl(a) {
    // SVG links have an SVGAnimatedString href
    const href = typeof a.href === "string" ? a.href : a.href?.baseVal;
    try {
      const url = new URL(href, document.baseURI);
      return url.protocol === "http:" || url.protocol === "https:" ? url : null;
    } catch {
      return null;
    }
  }

  // Same-site links say nothing new, and leaving them alone keeps SPA routing untouched
  const isExternal = (host) => host && host !== location.hostname;

  async function ask(hosts) {
    try {
      if (alive()) return (await chrome.runtime.sendMessage({ type: "check", hosts })) ?? {};
    } catch {
      // Service worker unavailable: every host is unknown, nothing is blocked
    }
    return {};
  }

  // A known result, or undefined. "unknown" expires, so the page asks again later
  // (the service worker backs off on its own while the API is down).
  function known(host) {
    const result = results.get(host);
    if (result?.until && result.until < Date.now()) {
      results.delete(host);
      return undefined;
    }
    return result;
  }

  function sendChunk(hosts) {
    const gen = generation;
    const request = ask(hosts).then((answer) => {
      if (gen !== generation) return answer; // userAllow changed meanwhile; a fresh scan asks again
      for (const host of hosts) {
        const result = answer[host] ?? { verdict: "unknown" };
        lookups.delete(host);
        results.set(host, result.verdict === "unknown" ? { ...result, until: Date.now() + UNKNOWN_TTL_MS } : result);
        if (result.verdict === "phishing" || result.verdict === "shared") ensureUi();
      }
      return answer;
    });
    for (const host of hosts) {
      lookups.set(host, request.then((answer) => answer[host] ?? { verdict: "unknown" }));
    }
  }

  function request(hosts) {
    const fresh = [...new Set(hosts)].filter((h) => !known(h) && !lookups.has(h));
    for (let i = 0; i < fresh.length; i += BATCH) sendChunk(fresh.slice(i, i + BATCH));
  }

  function lookup(host) {
    const result = known(host);
    if (result) return Promise.resolve(result);
    if (!lookups.has(host)) request([host]);
    return lookups.get(host);
  }

  function scan() {
    if (!enabled || !alive()) return;
    const hosts = [];
    for (const a of document.querySelectorAll("a[href]")) {
      const url = linkUrl(a);
      if (url && isExternal(url.hostname)) hosts.push(url.hostname);
    }
    request(hosts);
  }

  // ---- UI: one host element with a closed shadow root, styled by warning.css ----

  function ensureUi() {
    if (ui) {
      if (!ui.host.isConnected) document.documentElement.append(ui.host);
      return ui;
    }
    const host = document.createElement("phishing-link-check");
    host.style.cssText = "all: initial; position: fixed; top: 0; left: 0; width: 0; height: 0; z-index: 2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = chrome.runtime.getURL("warning.css");
    const styled = new Promise((resolve) => {
      link.addEventListener("load", resolve, { once: true });
      link.addEventListener("error", resolve, { once: true });
      setTimeout(resolve, 1000);
    });
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.hidden = true;
    root.append(link, tip);
    document.documentElement.append(host);
    ui = { host, root, tip, styled, overlay: null };
    return ui;
  }

  const fmt = (p) => (typeof p === "number" ? ` (p=${p.toFixed(2)})` : "");

  function showTip(a, host, result) {
    const { tip } = ensureUi();
    if (result.verdict === "phishing") {
      tip.className = "tip danger";
      tip.textContent = `Likely phishing: ${host}${fmt(result.p)}`;
    } else if (result.verdict === "shared") {
      tip.className = "tip neutral";
      tip.textContent = `Shared platform: anyone can publish on ${host}`;
    } else {
      return hideTip();
    }
    tip.hidden = false;
    const rect = a.getBoundingClientRect();
    const width = tip.offsetWidth;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    const below = rect.bottom + 6;
    const top = below + tip.offsetHeight > window.innerHeight ? rect.top - tip.offsetHeight - 6 : below;
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(8, top)}px`;
  }

  function hideTip() {
    if (ui) ui.tip.hidden = true;
  }

  function closeOverlay() {
    if (!ui?.overlay) return;
    ui.overlay.remove();
    ui.overlay = null;
    window.removeEventListener("keydown", onOverlayKey, true);
  }

  function onOverlayKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      closeOverlay();
    }
  }

  async function showOverlay(a, url, host, result, newTab) {
    const seq = ++overlaySeq;
    const u = ensureUi();
    closeOverlay();
    hideTip();
    await u.styled;
    if (seq !== overlaySeq) return; // a second click got here first (fast double-click)

    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    const dialog = document.createElement("div");
    dialog.className = "dialog";
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "plc-title");

    const title = document.createElement("h2");
    title.id = "plc-title";
    title.textContent = "This link looks like phishing";
    const text = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = host;
    text.append("This link goes to ", strong, `, which looks like phishing${fmt(result.p)}.`);
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "Only the hostname was checked. If you didn't expect this link, go back.";

    const back = document.createElement("button");
    back.className = "back";
    back.textContent = "Go back";
    back.addEventListener("click", closeOverlay);
    const open = document.createElement("button");
    open.className = "open";
    open.textContent = "Open anyway";
    open.addEventListener("click", () => {
      bypassed.add(host);
      closeOverlay();
      navigate(a, url, newTab);
    });
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.append(back, open);

    dialog.append(title, text, note, actions);
    backdrop.append(dialog);
    const openedAt = performance.now();
    backdrop.addEventListener("click", (e) => {
      // The second click of a double-click lands here; it shouldn't dismiss the warning
      if (e.target === backdrop && performance.now() - openedAt > BACKDROP_GRACE_MS) closeOverlay();
    });
    u.root.append(backdrop);
    u.overlay = backdrop;
    window.addEventListener("keydown", onOverlayKey, true);
    back.focus();
  }

  // ---- Events ----

  function navigate(a, url, newTab) {
    if (newTab) {
      // Synthetic clicks drop modifier keys and middle clicks, so open the tab directly
      window.open(url.href, "_blank", "noopener");
    } else if (a.isConnected) {
      // Replaying the click keeps the page's handlers, download, rel and target
      replaying = a;
      try {
        a.click();
      } finally {
        replaying = null;
      }
    } else {
      location.assign(url.href);
    }
  }

  function opensNewTab(e, a) {
    const target = (a.getAttribute("target") || "").toLowerCase();
    const namedTarget = target && !["_self", "_top", "_parent"].includes(target);
    return e.button === 1 || e.ctrlKey || e.metaKey || e.shiftKey || namedTarget;
  }

  function onClick(e) {
    if (!enabled || !alive()) return;
    if (replaying && e.type === "click" && replaying.contains(e.target)) return;
    if (e.type === "click" ? e.button !== 0 : e.button !== 1) return;
    const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
    const url = a && linkUrl(a);
    if (!url || !isExternal(url.hostname) || bypassed.has(url.hostname)) return;
    const host = url.hostname;
    const newTab = opensNewTab(e, a);

    const result = known(host);
    if (result) {
      // Anything but phishing goes through untouched, "unknown" included: when the API is
      // down, clicks behave as if the extension weren't there
      if (result.verdict === "phishing") {
        e.preventDefault();
        e.stopImmediatePropagation();
        showOverlay(a, url, host, result, newTab);
      }
      return;
    }
    // Still pending: hold the click briefly, then warn or replay the navigation
    e.preventDefault();
    e.stopImmediatePropagation();
    const timeout = new Promise((resolve) => setTimeout(() => resolve(null), PENDING_WAIT_MS));
    Promise.race([lookup(host), timeout]).then((result) => {
      if (result?.verdict === "phishing") showOverlay(a, url, host, result, newTab);
      else navigate(a, url, newTab);
    });
  }

  function onOver(e) {
    if (!enabled) return;
    const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
    if (!a || a === hovered) return;
    hovered = a;
    const url = linkUrl(a);
    if (!url || !isExternal(url.hostname)) return hideTip();
    lookup(url.hostname).then((result) => {
      if (hovered === a) showTip(a, url.hostname, result);
    });
  }

  function onOut(e) {
    if (!hovered || (e.relatedTarget instanceof Node && hovered.contains(e.relatedTarget))) return;
    hovered = null;
    hideTip();
  }

  function badge(host) {
    try {
      if (alive()) chrome.runtime.sendMessage({ type: "page", host }).catch(() => {});
    } catch {
      // Extension reloaded
    }
  }

  function start() {
    if (enabled) return;
    enabled = true;
    scan();
    if (location.protocol === "http:" || location.protocol === "https:") badge(location.hostname);
    observer = new MutationObserver(() => {
      // Throttle, not debounce: a page that changes constantly still gets rescanned
      if (rescanTimer) return;
      rescanTimer = setTimeout(() => {
        rescanTimer = null;
        scan();
      }, RESCAN_DELAY_MS);
    });
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["href"] });
  }

  function stop() {
    enabled = false;
    observer?.disconnect();
    clearTimeout(rescanTimer);
    rescanTimer = null;
    hovered = null;
    hideTip();
    closeOverlay();
    badge(null);
  }

  window.addEventListener("click", onClick, true);
  window.addEventListener("auxclick", onClick, true);
  document.addEventListener("mouseover", onOver, true);
  document.addEventListener("mouseout", onOut, true);
  window.addEventListener("scroll", hideTip, { capture: true, passive: true });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !alive()) return;
    if (changes.userAllow) {
      // The service worker applies userAllow; forget page verdicts so it is asked again
      generation += 1;
      results.clear();
      lookups.clear();
      hideTip();
      scan();
      if (enabled && /^https?:$/.test(location.protocol)) badge(location.hostname);
    }
    if (changes.enabled) (changes.enabled.newValue === false ? stop : start)();
  });

  chrome.storage.local.get({ enabled: true }).then((stored) => {
    if (stored.enabled) start();
  });
})();
