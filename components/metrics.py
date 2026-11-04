import torch

from components.config import PAD_ID


def last_real_token_logits(model, input_batch, pad_id=PAD_ID):
    with torch.autocast(
        device_type=input_batch.device.type,
        dtype=torch.bfloat16,
        enabled=input_batch.is_cuda,
    ):
        logits = model(input_batch)
    last_idx = (input_batch != pad_id).sum(dim=1).clamp(min=1) - 1
    return logits[torch.arange(logits.shape[0], device=logits.device), last_idx].float()


def calc_loss_batch(input_batch, target_batch, model, device):
    input_batch = input_batch.to(device, non_blocking=True)
    target_batch = target_batch.to(device, non_blocking=True)
    logits = last_real_token_logits(model, input_batch)
    return torch.nn.functional.cross_entropy(logits, target_batch)


@torch.inference_mode()
def evaluate_loader(data_loader, model, device, num_batches=None):
    model.eval()
    num_batches = len(data_loader) if num_batches is None else min(num_batches, len(data_loader))
    total_loss = torch.zeros((), device=device)
    correct = torch.zeros((), device=device)
    num_examples = 0

    for i, (input_batch, target_batch) in enumerate(data_loader):
        if i >= num_batches:
            break
        input_batch = input_batch.to(device, non_blocking=True)
        target_batch = target_batch.to(device, non_blocking=True)
        logits = last_real_token_logits(model, input_batch)
        total_loss += torch.nn.functional.cross_entropy(logits, target_batch, reduction="sum")
        correct += (logits.argmax(dim=-1) == target_batch).sum()
        num_examples += target_batch.shape[0]

    num_examples = max(num_examples, 1)
    return total_loss.item() / num_examples, correct.item() / num_examples


@torch.inference_mode()
def predict_proba_loader(data_loader, model, device):
    model.eval()
    probs, labels = [], []
    for input_batch, target_batch in data_loader:
        logits = last_real_token_logits(model, input_batch.to(device, non_blocking=True))
        probs.append(torch.softmax(logits, dim=-1)[:, 0])
        labels.append(target_batch)
    return torch.cat(probs).cpu().numpy(), torch.cat(labels).numpy()