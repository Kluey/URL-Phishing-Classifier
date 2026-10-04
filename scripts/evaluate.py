import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import DATA_DIR, MAX_LEN, WEIGHTS_PATH
from components.data import PhishingDataset, make_eval_loader
from components.evaluation import compute_metrics
from components.inference import get_tokenizer, load_classifier
from components.metrics import predict_proba_loader


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate a trained phishing URL classifier")
    parser.add_argument("--split", choices=("validation", "test"), default="test")
    parser.add_argument("--weights", type=Path, default=WEIGHTS_PATH)
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="P(phishing) above this is classified as phishing")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--num-workers", type=int, default=0)
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.weights.exists():
        sys.exit(f"No trained model found at {args.weights}. Run train.py first.")
    csv_path = DATA_DIR / f"{args.split}.csv"
    if not csv_path.exists():
        sys.exit(f"Missing {csv_path}. Run train.py first to create the data splits.")

    tokenizer = get_tokenizer()
    model, device = load_classifier(args.weights)
    print(f"Device: {device}")

    dataset = PhishingDataset(csv_path, tokenizer, MAX_LEN)
    loader = make_eval_loader(dataset, batch_size=args.batch_size, num_workers=args.num_workers)
    p_phish, labels = predict_proba_loader(loader, model, device)
    metrics = compute_metrics(p_phish, labels, threshold=args.threshold)

    print(f"\n{args.split.capitalize()} metrics ({len(labels)} URLs, "
          f"phishing = positive class, threshold {args.threshold}):")
    for name, value in metrics.items():
        print(f"  {name:<24}{value:.4f}")

    metrics_path = args.weights.with_suffix(f".{args.split}_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(
            {
                "weights": str(args.weights),
                "split": args.split,
                "threshold": args.threshold,
                "num_examples": int(len(labels)),
                "metrics": metrics,
            },
            f, indent=2,
        )
    print(f"\nSaved metrics to {metrics_path}")


if __name__ == "__main__":
    main()