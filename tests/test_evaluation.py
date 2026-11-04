import numpy as np
import pandas as pd
import torch

from components.data import PhishingDataset, make_eval_loader
from components.inference import get_tokenizer
from components.metrics import predict_proba_loader


class LengthModel(torch.nn.Module):
    """Logits that depend only on the token at each position, so outputs are traceable."""

    def forward(self, input_ids):
        x = input_ids.float()
        return torch.stack([x, torch.zeros_like(x)], dim=-1)


def test_predict_proba_loader_returns_dataset_order(tmp_path):
    csv = tmp_path / "split.csv"
    urls = ["a.com/" + "x" * n for n in (30, 1, 12, 5)]
    pd.DataFrame({"URL": urls, "label": [0, 1, 0, 1]}).to_csv(csv, index=False)
    dataset = PhishingDataset(csv, get_tokenizer())

    p_sorted, labels = predict_proba_loader(make_eval_loader(dataset, batch_size=2), LengthModel(), "cpu")
    p_plain = []
    for ids, _ in (dataset[i] for i in range(len(dataset))):
        p_plain.append(torch.sigmoid(torch.tensor(float(ids[-1]))).item())

    np.testing.assert_allclose(p_sorted, p_plain, rtol=1e-5)
    assert labels.tolist() == [0, 1, 0, 1]
