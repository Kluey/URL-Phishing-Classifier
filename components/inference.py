import tiktoken
import torch

from components.config import (
    LABEL_NAMES, MAX_LEN, MODEL, MODEL_CONFIG, NUM_CLASSES, WEIGHTS_PATH,
)
from components.metrics import last_real_token_logits
from components.gpt.model import GPTModel
from components.preprocessing import normalize_url


def build_classifier(pretrained=False, models_dir="gpt2", trainable_blocks=1):
    """GPT-2 with a 2-class head; only the head, final norm and last trainable_blocks blocks train."""
    model = GPTModel(MODEL_CONFIG)
    if pretrained:
        from components.gpt.load_gpt2 import download_and_load_gpt2, load_weights_into_gpt

        size = MODEL.split(" ")[-1].lstrip("(").rstrip(")")
        _, params = download_and_load_gpt2(model_size=size, models_dir=models_dir)
        load_weights_into_gpt(model, params)

    for p in model.parameters():
        p.requires_grad = False
    model.out_head = torch.nn.Linear(MODEL_CONFIG["emb_dim"], NUM_CLASSES)
    for p in model.trf_blocks[-trainable_blocks:].parameters():
        p.requires_grad = True
    for p in model.final_norm.parameters():
        p.requires_grad = True
    return model


def save_classifier(model, path=WEIGHTS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), path)


def load_classifier(path=WEIGHTS_PATH, device=None):
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_classifier(pretrained=False)
    model.load_state_dict(torch.load(path, map_location=device, weights_only=True))
    model.to(device)
    model.eval()
    return model, device


def get_tokenizer():
    return tiktoken.get_encoding("gpt2")


@torch.inference_mode()
def _class_probs(url, model, tokenizer, device, max_length):
    model.eval()
    supported = model.pos_emb.weight.shape[0]
    ids = tokenizer.encode(normalize_url(url), disallowed_special=())[:min(max_length, supported)]
    if not ids:
        raise ValueError("Cannot classify an empty URL")
    input_tensor = torch.tensor(ids, device=device).unsqueeze(0)
    return torch.softmax(last_real_token_logits(model, input_tensor), dim=-1)[0]


def classify_url(url, model, tokenizer, device, max_length=MAX_LEN):
    probs = _class_probs(url, model, tokenizer, device, max_length)
    label = int(probs.argmax())
    return label, probs[label].item()


def phishing_probability(url, model, tokenizer, device, max_length=MAX_LEN):
    """P(phishing) for the URL's hostname; label 0 is phishing, so this is the class-0 probability."""
    return _class_probs(url, model, tokenizer, device, max_length)[0].item()


def classify_url_name(url, model, tokenizer, device, max_length=MAX_LEN):
    label, confidence = classify_url(url, model, tokenizer, device, max_length)
    return LABEL_NAMES[label], confidence