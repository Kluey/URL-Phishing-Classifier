"""Build the extension's allowlist and shared-platform list from Tranco and PhiUSIIL.

Writes extension/data/allowlist.json and extension/data/shared_platforms.json. Both are
committed, so the extension builds without data/. Needs the raw PhiUSIIL CSV and the
pinned Tranco list (downloaded on first run).
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import PROJECT_ROOT, RAW_DATA_PATH, TRANCO_LIST_ID
from components.data import (
    download_tranco,
    drop_popular_phishing_hosts,
    registered_domain,
    shared_hosting_domains,
)
from components.preprocessing import normalize_url

OUT_DIR = PROJECT_ROOT / "extension/data"

# Anyone can publish under these, so the hostname says little about who runs the site
HOSTING_PLATFORMS = {
    "sites.google.com", "github.io", "web.app", "firebaseapp.com", "pages.dev", "workers.dev",
    "netlify.app", "vercel.app", "blogspot.com", "weebly.com", "wixsite.com", "herokuapp.com",
    "azurewebsites.net", "amazonaws.com", "cloudfront.net", "r2.dev", "glitch.me", "repl.co",
    "ngrok-free.app",
}
# The hostname of a short link says nothing about where it goes
URL_SHORTENERS = {"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "rebrand.ly"}
# Reviewed by hand: PhiUSIIL labels the company's own subdomains (ftp., labs., kr.) as phishing,
# which is label noise, not a platform where anyone can publish
NOT_SHARED = {"binance.com"}


def top_registered_domains(tranco_csv, n):
    hosts = pd.read_csv(tranco_csv, header=None, names=["rank", "host"])["host"]
    seen, domains = set(), []
    for host in hosts:
        domain = registered_domain(normalize_url(host))
        if not domain or domain.endswith(".arpa") or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        if len(domains) == n:
            break
    return domains


def write_list(path, domains):
    payload = {"tranco_list": TRANCO_LIST_ID, "count": len(domains), "domains": sorted(domains)}
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top", type=int, default=10_000, help="registered domains to allowlist")
    args = parser.parse_args()

    tranco_csv = download_tranco()
    raw = pd.read_csv(RAW_DATA_PATH, usecols=["URL", "label"])
    # Same order as train.py: phishing forms on docs.google.com must not make google.com "shared"
    from_phiusiil = shared_hosting_domains(drop_popular_phishing_hosts(raw, tranco_csv)) - NOT_SHARED
    shared = from_phiusiil | HOSTING_PLATFORMS | URL_SHORTENERS

    top = top_registered_domains(tranco_csv, args.top)
    allowlist = [d for d in top if d not in shared]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_list(OUT_DIR / "allowlist.json", allowlist)
    write_list(OUT_DIR / "shared_platforms.json", shared)

    print(f"Allowlist: {len(allowlist)} of the top {len(top)} registered domains "
          f"(Tranco {TRANCO_LIST_ID}), {len(top) - len(allowlist)} removed as shared")
    print(f"Shared platforms: {len(shared)} ({len(from_phiusiil)} from PhiUSIIL, "
          f"{len(HOSTING_PLATFORMS | URL_SHORTENERS)} by hand)")
    overlap = sorted(set(top) & from_phiusiil)
    print(f"PhiUSIIL shared domains in the Tranco top {args.top} (review these): {len(overlap)}")
    for domain in overlap:
        print(f"  {domain}")


if __name__ == "__main__":
    main()
