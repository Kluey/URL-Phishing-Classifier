import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from components.config import MAX_LEN, WEIGHTS_PATH
from components.inference import classify_url_name, get_tokenizer, load_classifier
from components.preprocessing import normalize_url


def predict(url, model, tokenizer, device):
    label, confidence = classify_url_name(url, model, tokenizer, device)
    note = ""
    if len(tokenizer.encode(normalize_url(url), disallowed_special=())) > MAX_LEN:
        note = f" [only the first {MAX_LEN} tokens were used]"
    return f"{label} ({confidence:.1%} confidence){note}"


def main():
    if not WEIGHTS_PATH.exists():
        sys.exit(f"No trained model found at {WEIGHTS_PATH}. Run train.py first.")

    tokenizer = get_tokenizer()
    model, device = load_classifier()

    urls = sys.argv[1:]
    if urls:
        for url in urls:
            print(f"{url}\n  -> {predict(url, model, tokenizer, device)}")
        return

    print("URL Phishing Classifier")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            url = input("Enter URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if url.lower() in {"quit", "exit"}:
            break
        if not url:
            continue
        print(f"Prediction: {predict(url, model, tokenizer, device)}\n")


if __name__ == "__main__":
    main()