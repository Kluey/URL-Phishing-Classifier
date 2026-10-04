import torch

from components.metrics import calc_loss_batch, evaluate_loader


def build_optimizer(model, head_lr=1e-3, body_lr=5e-5, weight_decay=0.1):
    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    head_params = [p for n, p in trainable if n.startswith("out_head")]
    body_params = [p for n, p in trainable if not n.startswith("out_head")]
    use_fused = next(model.parameters()).device.type == "cuda"
    return torch.optim.AdamW(
        [
            {"params": head_params, "lr": head_lr},
            {"params": body_params, "lr": body_lr},
        ],
        weight_decay=weight_decay,
        fused=use_fused,
    )


def train_classifier(model, train_loader, val_loader, optimizer, device,
                     num_epochs, eval_freq, eval_iter):
    train_losses, val_losses, train_accs, val_accs = [], [], [], []
    examples_seen, global_step = 0, -1
    best_val_accuracy, best_state = -1.0, None

    for epoch in range(num_epochs):
        model.train()

        for input_batch, target_batch in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = calc_loss_batch(input_batch, target_batch, model, device)
            loss.backward()
            optimizer.step()
            examples_seen += input_batch.shape[0]
            global_step += 1

            if global_step % eval_freq == 0:
                train_loss, _ = evaluate_loader(train_loader, model, device, eval_iter)
                val_loss, _ = evaluate_loader(val_loader, model, device, eval_iter)
                model.train()
                train_losses.append(train_loss)
                val_losses.append(val_loss)
                print(f"Ep {epoch+1} (Step {global_step:06d}): "
                      f"Train loss {train_loss:.3f}, Val loss {val_loss:.3f}")

        _, train_acc = evaluate_loader(train_loader, model, device, eval_iter)
        _, val_acc = evaluate_loader(val_loader, model, device) 
        print(f"Training accuracy: {train_acc*100:.2f}% | ", end="")
        print(f"Validation accuracy: {val_acc*100:.2f}%")
        train_accs.append(train_acc)
        val_accs.append(val_acc)

        if val_acc > best_val_accuracy:
            best_val_accuracy = val_acc
            best_state = {
                n: p.detach().cpu().clone()
                for n, p in model.named_parameters() if p.requires_grad
            }

    if best_state is not None:
        model.load_state_dict(best_state, strict=False)
        print(f"Restored best checkpoint (val accuracy {best_val_accuracy*100:.2f}%)")

    return train_losses, val_losses, train_accs, val_accs, examples_seen