from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_PATH = DATA_DIR / "PhiUSIIL_Phishing_URL_Dataset.csv"
WEIGHTS_PATH = PROJECT_ROOT / "model/phishing_classifier.pth"

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