from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_PATH = DATA_DIR / "PhiUSIIL_Phishing_URL_Dataset.csv"
WEIGHTS_PATH = PROJECT_ROOT / "model/phishing_classifier.pth"
# Small tracked list of everyday URLs (with paths) to catch shortcut learning
REAL_WORLD_PATH = PROJECT_ROOT / "eval/real_world_urls.csv"
# Tranco top-sites list including subdomains, pinned so the training data can be rebuilt exactly
TRANCO_LIST_ID = "V355N"
TRANCO_URL = f"https://tranco-list.eu/download/{TRANCO_LIST_ID}/1000000"
TRANCO_PATH = DATA_DIR / f"tranco_{TRANCO_LIST_ID}.csv"

MODEL = "gpt2-small (124M)"
MODEL_CONFIG = {
    "vocab_size": 50257,
    "context_length": 1024,
    "drop_rate": 0.0,
    "qkv_bias": True,
    "emb_dim": 768,
    "n_layers": 12,
    "n_heads": 12,
}

SEED = 123
PAD_ID = 50256
MAX_LEN = 128 
NUM_CLASSES = 2

LABEL_NAMES = {0: "Phishing", 1: "Legitimate"}