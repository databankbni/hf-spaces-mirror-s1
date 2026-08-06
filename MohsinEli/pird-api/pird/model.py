"""PIRD model. Stream B = a transformer encoder (DeBERTa-v3-small by default) with mean pooling and
an MLP head. Designed to also accept concatenated Stream A/C feature vectors (`extra`) for the later
fusion version; in PIRD-lite `n_extra=0` and only the encoder is used."""
from __future__ import annotations
import torch
import torch.nn as nn
from transformers import AutoModel


class PIRDModel(nn.Module):
    def __init__(self, encoder_name: str = "roberta-base",
                 n_extra: int = 0, hidden: int = 256, dropout: float = 0.2):
        super().__init__()
        self.encoder_name = encoder_name
        self.n_extra = n_extra
        self.encoder = AutoModel.from_pretrained(encoder_name)
        enc_dim = self.encoder.config.hidden_size
        self.head = nn.Sequential(
            nn.Linear(enc_dim + n_extra, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, 1),
        )

    def encode(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        h = out.last_hidden_state                      # [B, T, H]
        mask = attention_mask.unsqueeze(-1).float()
        return (h * mask).sum(1) / mask.sum(1).clamp_min(1e-6)   # mean pooling

    def forward(self, input_ids, attention_mask, extra=None):
        pooled = self.encode(input_ids, attention_mask)
        if self.n_extra and extra is not None:
            pooled = torch.cat([pooled, extra], dim=-1)
        return self.head(pooled).squeeze(-1)           # raw logit; higher = more AI
