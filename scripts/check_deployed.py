"""Checks against the deployed API.

    real-world  score eval/real_world_urls.csv on the API and locally, compare p and the confusion
    burst       send N concurrent requests and tally the status codes (expect 429s, no 5xx)

Only the standard library talks to the API. `real-world` also needs torch and the local weights.
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import LABEL_NAMES, REAL_WORLD_PATH, WEIGHTS_PATH
from components.preprocessing import normalize_url

BATCH = 32  # API limit
PHISHING = 0  # LABEL_NAMES: 0 = Phishing, 1 = Legitimate


def post(api_url, path, body, timeout=30):
    """Returns (status, parsed JSON or None)."""
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "check-deployed"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError):
        return None, None


def post_batch_with_retry(api_url, hosts, deadline_s=90):
    """Cold instances can answer 5xx or time out for the first ~minute after idle."""
    start = time.monotonic()
    while True:
        status, body = post(api_url, "/v1/classify/batch", {"hosts": hosts})
        if status == 200:
            return body
        if time.monotonic() - start > deadline_s:
            sys.exit(f"API still failing after {deadline_s} s (last status {status})")
        print(f"  status {status}, retrying…", file=sys.stderr)
        time.sleep(5)


def confusion(ps, labels, threshold):
    tp = sum(p >= threshold and y == PHISHING for p, y in zip(ps, labels))
    fp = sum(p >= threshold and y != PHISHING for p, y in zip(ps, labels))
    n_phish = sum(y == PHISHING for y in labels)
    return tp, n_phish, fp, len(labels) - n_phish


def real_world(args):
    with open(REAL_WORLD_PATH, newline="", encoding="utf-8") as f:
        rows = [(r["URL"], int(r["label"])) for r in csv.DictReader(f)]
    hosts = [normalize_url(url) for url, _ in rows]
    labels = [label for _, label in rows]

    remote = []
    for i in range(0, len(hosts), BATCH):
        body = post_batch_with_retry(args.api_url, hosts[i:i + BATCH])
        threshold = body["threshold"]
        for host, item in zip(hosts[i:i + BATCH], body["results"]):
            if item.get("error"):
                sys.exit(f"API rejected {host!r}: {item['error']}")
            if item["host"] != host:
                sys.exit(f"API normalized {host!r} to {item['host']!r}")
            remote.append(item["p_phishing"])

    # Imported here so `burst` doesn't need torch
    from components.inference import get_tokenizer, load_classifier, phishing_probability

    model, device = load_classifier(args.weights)
    tokenizer = get_tokenizer()
    local = [phishing_probability(h, model, tokenizer, device) for h in hosts]

    deltas = [abs(r - l) for r, l in zip(remote, local)]
    print(f"{len(hosts)} hosts, API threshold {threshold}")
    print(f"max |p_api - p_local| = {max(deltas):.2e} (mean {sum(deltas) / len(deltas):.2e})")
    for name, ps in (("api", remote), ("local", local)):
        tp, n_phish, fp, n_legit = confusion(ps, labels, threshold)
        print(f"{name:>5}: phishing caught {tp}/{n_phish}, false positives {fp}/{n_legit}")

    print(f"\nWithin {args.margin} of the threshold, or misclassified:")
    shown = 0
    for host, y, p in sorted(zip(hosts, labels, remote), key=lambda t: t[2]):
        wrong = (p >= threshold) != (y == PHISHING)
        if wrong or abs(p - threshold) < args.margin:
            flag = "WRONG" if wrong else "close"
            print(f"  {flag:5}  p={p:.3f}  {LABEL_NAMES[y]:10}  {host}")
            shown += 1
    if not shown:
        print("  none")

    tp, n_phish, fp, _ = confusion(remote, labels, threshold)
    ok = max(deltas) < 1e-4 and tp == n_phish and fp == 0
    return 0 if ok else 1


def burst(args):
    # Synthetic, clearly fake hostnames, so they're easy to look for in CloudWatch
    hosts = [f"burst-check-{i}-{args.tag}.example" for i in range(args.n)]

    def one(host):
        t = time.monotonic()
        status, _ = post(args.api_url, "/v1/classify", {"host": host}, timeout=35)
        return status, time.monotonic() - t

    with ThreadPoolExecutor(max_workers=args.n) as pool:
        out = list(pool.map(one, hosts))

    counts = Counter(status for status, _ in out)
    print(f"{args.n} concurrent requests: " + ", ".join(f"{s}: {c}" for s, c in sorted(counts.items(), key=str)))
    ok_times = sorted(t for s, t in out if s == 200)
    if ok_times:
        print(f"200 latency: min {ok_times[0]:.2f} s, max {ok_times[-1]:.2f} s")
    print(f"CloudWatch search term: burst-check  (tag {args.tag})")
    server_errors = sum(c for s, c in counts.items() if s is None or s >= 500)
    return 1 if server_errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    rw = sub.add_parser("real-world", help="compare the API with the local model on the real-world list")
    rw.add_argument("--weights", type=Path, default=WEIGHTS_PATH)
    rw.add_argument("--margin", type=float, default=0.1, help="list hosts this close to the threshold")
    rw.set_defaults(func=real_world)

    b = sub.add_parser("burst", help="concurrent requests, to check throttling")
    b.add_argument("--n", type=int, default=50)
    b.add_argument("--tag", default=time.strftime("%H%M%S"))
    b.set_defaults(func=burst)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
