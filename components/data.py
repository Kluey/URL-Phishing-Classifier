import numpy as np
import pandas as pd
import tldextract
import torch
from sklearn.model_selection import StratifiedGroupKFold, train_test_split
from torch.utils.data import DataLoader, Dataset, Subset

from components.config import MAX_LEN, PAD_ID, SEED
from components.preprocessing import normalize_url


def load_urls(csv_path):
    df = pd.read_csv(csv_path)
    return df[["URL", "label"]].drop_duplicates(subset="URL")


def balanced_subset(df, n_total, label_col="label", random_state=SEED):
    per_class = min(n_total // 2, df[label_col].value_counts().min())
    parts = [
        df[df[label_col] == label].sample(n=per_class, random_state=random_state)
        for label in (0, 1)
    ]
    return (
        pd.concat(parts)
        .sample(frac=1, random_state=random_state)
        .reset_index(drop=True)
    )

_extract_domain = tldextract.TLDExtract(suffix_list_urls=())


def registered_domain(url):
    ext = _extract_domain(url)
    domain = f"{ext.domain}.{ext.suffix}" if ext.suffix else ext.domain
    return domain or url


def domain_overlap(train_df, other_df):
    train_domains = set(train_df["URL"].map(registered_domain))
    return other_df["URL"].map(registered_domain).isin(train_domains).mean()


def _split_by_domain(df, train_frac, validation_frac, random_state, n_folds=10):
    groups = df["URL"].map(registered_domain).to_numpy()
    folds = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=random_state)
    fold_indices = [idx for _, idx in folds.split(df, df["label"], groups)]

    n_val = max(1, round(validation_frac * n_folds))
    n_test = max(1, round((1 - train_frac - validation_frac) * n_folds))
    if n_val + n_test >= n_folds:
        raise ValueError("train_frac is too small to split by domain")

    test_idx = np.concatenate(fold_indices[:n_test])
    val_idx = np.concatenate(fold_indices[n_test:n_test + n_val])
    train_idx = np.concatenate(fold_indices[n_test + n_val:])
    return df.iloc[train_idx], df.iloc[val_idx], df.iloc[test_idx]


def split_dataset(df, train_frac=0.7, validation_frac=0.1, random_state=SEED,
                  group_by_domain=True):
    if group_by_domain:
        return _split_by_domain(df, train_frac, validation_frac, random_state)

    train_df, rest_df = train_test_split(
        df, train_size=train_frac, stratify=df["label"], random_state=random_state
    )
    val_share = validation_frac / (1 - train_frac)
    validation_df, test_df = train_test_split(
        rest_df, train_size=val_share, stratify=rest_df["label"], random_state=random_state
    )
    return train_df, validation_df, test_df


def save_splits(train_df, validation_df, test_df, data_dir):
    train_df.to_csv(data_dir / "train.csv", index=False)
    validation_df.to_csv(data_dir / "validation.csv", index=False)
    test_df.to_csv(data_dir / "test.csv", index=False)


class PhishingDataset(Dataset):
    """Yields (token_id_list, label). Use collate_pad as the DataLoader collate_fn."""

    def __init__(self, csv_file, tokenizer, max_length=MAX_LEN):
        self.data = pd.read_csv(csv_file)
        self.max_length = max_length

        self.encoded_texts = [
            tokenizer.encode(normalize_url(url), disallowed_special=())[:max_length]
            for url in self.data["URL"]
        ]
        self.labels = self.data["label"].tolist()

    def __getitem__(self, idx):
        return self.encoded_texts[idx], self.labels[idx]

    def __len__(self):
        return len(self.labels)


def collate_pad(batch, pad_token_id=PAD_ID):
    encoded_texts, labels = zip(*batch)
    longest = max(len(e) for e in encoded_texts)
    input_ids = torch.full((len(encoded_texts), longest), pad_token_id, dtype=torch.long)
    for i, encoded in enumerate(encoded_texts):
        input_ids[i, :len(encoded)] = torch.tensor(encoded, dtype=torch.long)
    return input_ids, torch.tensor(labels, dtype=torch.long)


def make_loaders(data_dir, tokenizer, max_length=MAX_LEN, batch_size=32, num_workers=0):
    def build(csv_name, shuffle, drop_last):
        return DataLoader(
            PhishingDataset(data_dir / csv_name, tokenizer, max_length),
            batch_size=batch_size,
            shuffle=shuffle,
            drop_last=drop_last,
            num_workers=num_workers,
            collate_fn=collate_pad,
            pin_memory=torch.cuda.is_available(),
        )

    train_loader = build("train.csv", shuffle=True, drop_last=True)
    val_loader = build("validation.csv", shuffle=False, drop_last=False)
    test_loader = build("test.csv", shuffle=False, drop_last=False)
    return train_loader, val_loader, test_loader


def make_eval_loader(dataset, batch_size=256, num_workers=0):
    order = sorted(range(len(dataset)), key=lambda i: len(dataset.encoded_texts[i]))
    return DataLoader(
        Subset(dataset, order),
        batch_size=batch_size,
        collate_fn=collate_pad,
        num_workers=num_workers,
        pin_memory=torch.cuda.is_available(),
    )