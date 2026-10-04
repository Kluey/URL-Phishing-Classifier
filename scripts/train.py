import argparse
import json
import sys
import time
from pathlib import Path
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import DATA_DIR, MAX_LEN, PROJECT_ROOT, RAW_DATA_PATH, SEED, WEIGHTS_PATH
from components.data import (
    balanced_subset,
    domain_overlap,
    load_urls,
    make_loaders,
    save_splits,
    split_dataset,
)
from components.inference import build_classifier, get_tokenizer, save_classifier
from components.training import build_optimizer, train_classifier

SPLIT_FILES = ("train.csv", "validation.csv", "test.csv")


def prepare_data(n_samples, seed, split_by):
    data = load_urls(RAW_DATA_PATH)
    subset = balanced_subset(data, n_samples, random_state=seed)
    train_df, val_df, test_df = split_dataset(
        subset, random_state=seed, group_by_domain=(split_by == "domain")
    )
    save_splits(train_df, val_df, test_df, DATA_DIR)
    print(f"Prepared {split_by}-level splits: "
          f"{len(train_df)} train / {len(val_df)} val / {len(test_df)} test")
    print(f"URLs whose domain also appears in train: "
          f"validation {domain_overlap(train_df, val_df):.1%}, "
          f"test {domain_overlap(train_df, test_df):.1%}")


def parse_args():
    parser = argparse.ArgumentParser(description="Fine-tune GPT-2 as a phishing URL classifier")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--head-lr", type=float, default=1e-3, help="LR for the new classification head")
    parser.add_argument("--body-lr", type=float, default=5e-5, help="LR for the unfrozen pretrained layers")
    parser.add_argument("--weight-decay", type=float, default=0.1)
    parser.add_argument("--eval-freq", type=int, default=100)
    parser.add_argument("--eval-iter", type=int, default=10)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--prepare-data", action="store_true",
                        help="rebuild train/validation/test CSVs from the raw dataset ")
    parser.add_argument("--n-samples", type=int, default=20_000,
                        help="balanced subset size used by --prepare-data")
    parser.add_argument("--split-by", choices=("domain", "url"), default="domain",
                        help="domain: no registered domain appears in more than one split; "
                             "url: random split (can leak domains across splits)")
    parser.add_argument("--pretrained-dir", default=str(PROJECT_ROOT / "model/gpt2"),
                        help="where the OpenAI GPT-2 weights are cached")
    parser.add_argument("--output", type=Path, default=WEIGHTS_PATH)
    return parser.parse_args()


def main():
    args = parse_args()

    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    missing = [f for f in SPLIT_FILES if not (DATA_DIR / f).exists()]
    if args.prepare_data or missing:
        if missing and not args.prepare_data:
            print(f"Missing splits ({', '.join(missing)}), preparing them from the raw dataset")
        prepare_data(args.n_samples, args.seed, args.split_by)

    tokenizer = get_tokenizer()
    train_loader, val_loader, _ = make_loaders(
        DATA_DIR, tokenizer, MAX_LEN,
        batch_size=args.batch_size, num_workers=args.num_workers,
    )

    model = build_classifier(pretrained=True, models_dir=args.pretrained_dir)
    model.to(device)  
    optimizer = build_optimizer(
        model, head_lr=args.head_lr, body_lr=args.body_lr, weight_decay=args.weight_decay
    )

    start = time.perf_counter()
    _, _, _, val_accs, _ = train_classifier(
        model, train_loader, val_loader, optimizer, device,
        num_epochs=args.epochs, eval_freq=args.eval_freq, eval_iter=args.eval_iter,
    )
    minutes = (time.perf_counter() - start) / 60
    print(f"Training completed in {minutes:.2f} minutes.")

    save_classifier(model, args.output)
    print(f"Saved model to {args.output}")

    run_path = args.output.with_suffix(".train.json")
    with open(run_path, "w") as f:
        json.dump(
            {"args": vars(args), "val_accuracy_per_epoch": val_accs, "minutes": minutes},
            f, indent=2, default=str,
        )
    print(f"Saved run info to {run_path}")


if __name__ == "__main__":
    main()