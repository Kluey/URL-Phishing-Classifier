import numpy as np
import pandas as pd
import pytest

from components.data import balanced_subset, domain_overlap, registered_domain, split_dataset


@pytest.fixture
def urls_df():
    rng = np.random.default_rng(0)
    rows = []
    for d in range(400): 
        host = f"site{d}.{'com' if d % 3 else 'co.uk'}"
        for k in range(int(rng.integers(1, 9))):
            sub = rng.choice(["", "www.", "a.", "login."])
            rows.append((f"http://{sub}{host}/p{k}", d % 2))
    return pd.DataFrame(rows, columns=["URL", "label"])


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://a.b.example.co.uk/x", "example.co.uk"),
        ("https://foo.weebly.com/login", "weebly.com"),
        ("https://www.google.com/search?q=1", "google.com"),
        ("http://192.168.1.1/login", "192.168.1.1"),
    ],
)
def test_registered_domain(url, expected):
    assert registered_domain(url) == expected


def test_domain_split_never_shares_a_domain(urls_df):
    train, val, test = split_dataset(urls_df, group_by_domain=True)
    assert domain_overlap(train, val) == 0
    assert domain_overlap(train, test) == 0
    assert domain_overlap(val, test) == 0


def test_domain_split_uses_every_row_exactly_once(urls_df):
    train, val, test = split_dataset(urls_df, group_by_domain=True)
    all_idx = list(train.index) + list(val.index) + list(test.index)
    assert len(all_idx) == len(set(all_idx)) == len(urls_df)


def test_domain_split_sizes_and_label_balance(urls_df):
    train, val, test = split_dataset(urls_df, train_frac=0.7, validation_frac=0.1)
    n = len(urls_df)
    for part, share in ((train, 0.7), (val, 0.1), (test, 0.2)):
        assert abs(len(part) / n - share) < 0.05
        assert abs(part["label"].mean() - urls_df["label"].mean()) < 0.05


def test_random_url_split_leaks_domains(urls_df):
    train, _, test = split_dataset(urls_df, group_by_domain=False)
    assert domain_overlap(train, test) > 0.5


def test_balanced_subset_has_equal_classes(urls_df):
    subset = balanced_subset(urls_df, 200)
    assert subset["label"].value_counts().tolist() == [100, 100]