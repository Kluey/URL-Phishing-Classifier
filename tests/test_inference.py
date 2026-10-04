import pytest
import torch

from components.config import LABEL_NAMES, NUM_CLASSES
from components.inference import (
    build_classifier, classify_url, classify_url_name, get_tokenizer,
    load_classifier, save_classifier,
)


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(0)
    m = build_classifier(pretrained=False)
    m.eval()
    return m


def test_build_classifier_freezes_all_but_last_block(model):
    assert model.out_head.out_features == NUM_CLASSES
    assert all(p.requires_grad for p in model.out_head.parameters())
    assert all(p.requires_grad for p in model.trf_blocks[-1].parameters())
    assert all(p.requires_grad for p in model.final_norm.parameters())
    assert not any(p.requires_grad for p in model.trf_blocks[0].parameters())
    assert not model.tok_emb.weight.requires_grad


def test_classify_url_returns_valid_label_and_confidence(model):
    label, conf = classify_url("http://example.com/login", model, get_tokenizer(), "cpu")
    assert label in LABEL_NAMES
    assert 0.5 <= conf <= 1.0


def test_classify_url_name_maps_label(model):
    name, _ = classify_url_name("https://example.com", model, get_tokenizer(), "cpu")
    assert name in LABEL_NAMES.values()


def test_classify_url_empty_raises(model):
    with pytest.raises(ValueError):
        classify_url("", model, get_tokenizer(), "cpu")


def test_classify_url_truncates_long_input(model):
    url = "http://example.com/" + "a" * 5000
    label, _ = classify_url(url, model, get_tokenizer(), "cpu")
    assert label in LABEL_NAMES


def test_save_and_load_roundtrip(model, tmp_path):
    path = tmp_path / "ckpt" / "model.pth"
    save_classifier(model, path)
    loaded, device = load_classifier(path, device=torch.device("cpu"))
    assert not loaded.training
    tok = get_tokenizer()
    url = "http://paypa1-secure.example.com/verify"
    assert classify_url(url, model, tok, "cpu") == classify_url(url, loaded, tok, device)
