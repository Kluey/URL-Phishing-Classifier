"""Time a cold start (import torch + load weights) and single-hostname latency on CPU.

Lambda gives about one vCPU per 1769 MB, so --threads 2 approximates a 3008 MB function.
"""
import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

t0 = time.perf_counter()
import torch  # noqa: E402

import_s = time.perf_counter() - t0

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import REAL_WORLD_PATH, WEIGHTS_PATH  # noqa: E402
from components.inference import get_tokenizer, load_classifier, phishing_probability  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=2, help="torch intra-op threads")
    parser.add_argument("--repeats", type=int, default=3, help="passes over the real-world URLs")
    args = parser.parse_args()

    if not WEIGHTS_PATH.exists():
        sys.exit(f"No trained model found at {WEIGHTS_PATH}. Run train.py first.")
    torch.set_num_threads(args.threads)

    t0 = time.perf_counter()
    tokenizer = get_tokenizer()
    model, device = load_classifier(device=torch.device("cpu"))
    load_s = time.perf_counter() - t0

    with open(REAL_WORLD_PATH, newline="") as f:
        urls = [row["URL"] for row in csv.DictReader(f)]

    t0 = time.perf_counter()
    phishing_probability(urls[0], model, tokenizer, device)
    first_ms = (time.perf_counter() - t0) * 1000

    times = []
    for _ in range(args.repeats):
        for url in urls:
            t0 = time.perf_counter()
            phishing_probability(url, model, tokenizer, device)
            times.append((time.perf_counter() - t0) * 1000)
    q = statistics.quantiles(times, n=100)

    print(f"threads:          {args.threads}")
    print(f"import torch:     {import_s:.2f} s")
    print(f"load model:       {load_s:.2f} s")
    print(f"first request:    {first_ms:.0f} ms")
    print(f"single request:   p50 {q[49]:.1f} ms, p95 {q[94]:.1f} ms, max {max(times):.1f} ms "
          f"({len(times)} requests)")


if __name__ == "__main__":
    main()
