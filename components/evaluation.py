import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    matthews_corrcoef,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


def compute_metrics(p_phish, labels, threshold=0.5):
    is_phish = (labels == 0).astype(int)
    pred_phish = (p_phish > threshold).astype(int)

    fpr, tpr, _ = roc_curve(is_phish, p_phish)
    num_legit = max(int((is_phish == 0).sum()), 1)
    metrics = {
        "accuracy": float((pred_phish == is_phish).mean()),
        "precision_phishing": float(precision_score(is_phish, pred_phish, zero_division=0)),
        "recall_phishing": float(recall_score(is_phish, pred_phish, zero_division=0)),
        "false_positive_rate": float(((pred_phish == 1) & (is_phish == 0)).sum() / num_legit),
        "mcc": float(matthews_corrcoef(is_phish, pred_phish)),
        "roc_auc": float(roc_auc_score(is_phish, p_phish)),
        "pr_auc": float(average_precision_score(is_phish, p_phish)),
        "brier": float(brier_score_loss(is_phish, p_phish)),
    }
    for target in (0.01, 0.001):
        metrics[f"recall_at_{target:.1%}_fpr"] = float(tpr[fpr <= target].max())
    return metrics


def misclassified(df, p_phish, threshold=0.5):
    pred = np.where(p_phish > threshold, 0, 1)
    out = df.assign(p_phish=p_phish, pred=pred)
    return out[out["pred"] != out["label"]]