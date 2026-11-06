import pytest
import torch

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.app import MAX_BATCH, MAX_BODY_BYTES, create_app  # noqa: E402
from components.config import LABEL_NAMES  # noqa: E402
from components.inference import build_classifier, get_tokenizer, phishing_probability  # noqa: E402


@pytest.fixture(scope="module")
def model():
    torch.manual_seed(0)
    m = build_classifier(pretrained=False)
    m.eval()
    return m


@pytest.fixture(scope="module")
def client(model):
    return TestClient(create_app(model, get_tokenizer(), "cpu", threshold=0.8))


def test_health(client):
    assert client.get("/v1/health").json() == {"status": "ok", "threshold": 0.8}


def test_classify_returns_normalized_host_and_score(client, model):
    body = client.post("/v1/classify", json={"host": "https://WWW.Example.com/login?x=1"}).json()
    assert body["host"] == "example.com"
    assert body["threshold"] == 0.8
    assert body["p_phishing"] == pytest.approx(
        phishing_probability("example.com", model, get_tokenizer(), "cpu"))
    assert body["label"] == (LABEL_NAMES[0] if body["p_phishing"] >= 0.8 else LABEL_NAMES[1])


@pytest.mark.parametrize("threshold", [0.01, 0.99])
def test_threshold_decides_label(model, threshold):
    client = TestClient(create_app(model, get_tokenizer(), "cpu", threshold=threshold))
    body = client.post("/v1/classify", json={"host": "example.com"}).json()
    assert body["threshold"] == threshold
    assert body["label"] == (LABEL_NAMES[0] if body["p_phishing"] >= threshold else LABEL_NAMES[1])


@pytest.mark.parametrize("payload", [{}, {"host": ""}, {"host": "a" * 254}, {"host": 5}])
def test_classify_rejects_invalid_input(client, payload):
    assert client.post("/v1/classify", json=payload).status_code == 422


def test_classify_without_hostname_is_422(client):
    assert client.post("/v1/classify", json={"host": "https://"}).status_code == 422


def test_batch_keeps_order_and_reports_bad_items(client):
    hosts = ["example.com", "https://", "paypa1-secure.example.com"]
    body = client.post("/v1/classify/batch", json={"hosts": hosts}).json()
    results = body["results"]
    assert [r["host"] for r in results] == ["example.com", "https://", "paypa1-secure.example.com"]
    assert results[1]["error"] and results[1]["p_phishing"] is None
    assert all(0.0 <= r["p_phishing"] <= 1.0 for r in (results[0], results[2]))


def test_batch_limit(client):
    hosts = ["example.com"] * (MAX_BATCH + 1)
    assert client.post("/v1/classify/batch", json={"hosts": hosts}).status_code == 422


def test_body_too_large_is_413(client):
    big = '{"host": "' + "a" * MAX_BODY_BYTES + '"}'
    response = client.post("/v1/classify", content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413
