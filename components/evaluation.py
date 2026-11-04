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

    num_legit = max(int((is_phish == 0).sum()), 1)
    metrics = {
        "accuracy": float((pred_phish == is_phish).mean()),
        "precision_phishing": float(precision_score(is_phish, pred_phish, zero_division=0)),
        "recall_phishing": float(recall_score(is_phish, pred_phish, zero_division=0)),
        "false_positive_rate": float(((pred_phish == 1) & (is_phish == 0)).sum() / num_legit),
        "mcc": float(matthews_corrcoef(is_phish, pred_phish)),
        "brier": float(brier_score_loss(is_phish, p_phish, pos_label=1)),
    }
    fpr_targets = (0.01, 0.001)
    if len(np.unique(is_phish)) < 2:
        # Ranking metrics are undefined when the labels contain only one class
        metrics.update(dict.fromkeys(
            ["roc_auc", "pr_auc", *(f"recall_at_{t:.1%}_fpr" for t in fpr_targets)]
        ))
        return metrics

    fpr, tpr, _ = roc_curve(is_phish, p_phish)
    metrics["roc_auc"] = float(roc_auc_score(is_phish, p_phish))
    metrics["pr_auc"] = float(average_precision_score(is_phish, p_phish))
    for target in fpr_targets:
        metrics[f"recall_at_{target:.1%}_fpr"] = float(tpr[fpr <= target].max())
    return metrics

