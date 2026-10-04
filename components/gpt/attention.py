import torch.nn as nn

class MHAPyTorchScaledDotProduct(nn.Module):
    def __init__(
        self,
        d_in,
        d_out,
        num_heads,
        context_length,
        dropout=0.0,
        qkv_bias=False,
    ):
        super().__init__()
        assert d_out % num_heads == 0, "d_out must be divisible by num_heads"
        self.num_heads = num_heads
        self.context_length = context_length
        self.head_dim = d_out // num_heads
        self.d_out = d_out
        self.qkv = nn.Linear(d_in, 3 * d_out, bias=qkv_bias)
        self.proj = nn.Linear(d_out, d_out)
        self.dropout = dropout

    def forward(self, x):
        batch_size, num_tokens, _ = x.shape
        qkv = self.qkv(x).view(batch_size, num_tokens, 3, self.num_heads, self.head_dim)
        queries, keys, values = qkv.permute(2, 0, 3, 1, 4)
        dropout_p = 0.0 if not self.training else self.dropout
        context = nn.functional.scaled_dot_product_attention(
            queries,
            keys,
            values,
            attn_mask=None,
            dropout_p=dropout_p,
            is_causal=True,
        )
        context = context.transpose(1, 2).contiguous().view(batch_size, num_tokens, self.d_out)
        return self.proj(context)