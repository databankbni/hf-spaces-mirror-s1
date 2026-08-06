"""Train PIRD: a paraphrase-invariant, multi-signal detector.

Objective (the contribution):
  - detection loss (human vs AI)
  - augmentation: paraphrased AI is included, still labelled AI
  - invariance: consistency loss pulling P(AI|x) ~ P(AI|paraphrase(x))
Full PIRD additionally fuses Stream A (statistical) + Stream C (stylometric) features onto the
encoder embedding, and fits a calibration temperature on a held-out val split (contribution C3).
Set use_features=False for the encoder-only "PIRD-lite" ablation.
"""
from __future__ import annotations
import json
import os
import random
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from transformers import AutoTokenizer

from .model import PIRDModel
from .attacks import Paraphraser
from .features import CombinedFeatures, standardize


class _PairDataset(Dataset):
    def __init__(self, items, tok, max_len=256, use_features=False):
        self.items = items; self.tok = tok; self.max_len = max_len; self.use_features = use_features

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def collate(self, batch):
        def enc(texts):
            e = self.tok(texts, return_tensors="pt", truncation=True,
                         max_length=self.max_len, padding=True)
            return e["input_ids"], e["attention_mask"]
        ids, mask = enc([b["text"] for b in batch])
        out = {"ids": ids, "mask": mask,
               "labels": torch.tensor([b["label"] for b in batch], dtype=torch.float)}
        if self.use_features:
            out["extra"] = torch.tensor(np.stack([b["extra"] for b in batch]), dtype=torch.float)
        has_para = [b for b in batch if b.get("para")]
        if has_para:
            p_ids, p_mask = enc([b["para"] for b in has_para])
            out.update({"p_ids": p_ids, "p_mask": p_mask,
                        "p_labels": torch.tensor([b["label"] for b in has_para], dtype=torch.float)})
            if self.use_features:
                out["p_extra"] = torch.tensor(np.stack([b["p_extra"] for b in has_para]),
                                              dtype=torch.float)
        return out


def build_items(human, ai, recursive_rounds=0, seed=42, paraphraser=None):
    para = paraphraser or Paraphraser()
    print(f"paraphrasing {len(ai)} AI texts (rounds={max(1, recursive_rounds)}) ...")
    ai_para = para.paraphrase_many(ai, rounds=max(1, recursive_rounds))
    items = [{"text": h, "label": 0.0, "para": None} for h in human]
    items += [{"text": a, "label": 1.0, "para": ap} for a, ap in zip(ai, ai_para)]
    random.Random(seed).shuffle(items)
    return items


def _attach_features(items, extractor, mean, std):
    X = standardize(extractor.matrix([it["text"] for it in items]), mean, std)
    for it, x in zip(items, X):
        it["extra"] = x.astype("float32")
    pidx = [i for i, it in enumerate(items) if it.get("para")]
    if pidx:
        P = standardize(extractor.matrix([items[i]["para"] for i in pidx]), mean, std)
        for j, i in enumerate(pidx):
            items[i]["p_extra"] = P[j].astype("float32")


def _fit_temperature(model, items, tok, max_len, device, use_features):
    model.eval()
    zs, ys = [], []
    with torch.no_grad():
        for i in range(0, len(items), 16):
            chunk = items[i:i + 16]
            e = tok([c["text"] for c in chunk], return_tensors="pt", truncation=True,
                    max_length=max_len, padding=True)
            extra = (torch.tensor(np.stack([c["extra"] for c in chunk]), dtype=torch.float).to(device)
                     if use_features else None)
            z = model(e["input_ids"].to(device), e["attention_mask"].to(device), extra)
            zs.append(np.atleast_1d(z.cpu().numpy())); ys.append([c["label"] for c in chunk])
    model.train()
    z = np.concatenate(zs); y = np.concatenate(ys)
    best_T, best = 1.0, 1e9
    for T in np.linspace(0.5, 5.0, 91):
        p = np.clip(1.0 / (1.0 + np.exp(-z / T)), 1e-6, 1 - 1e-6)
        bce = -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
        if bce < best:
            best, best_T = bce, float(T)
    return best_T


def train_pird(items, out_dir="pird_ckpt", encoder="roberta-base", epochs=3, batch_size=8,
               lr=2e-5, max_len=256, lam_inv=1.0, lam_aug=1.0, seed=42, device=None,
               use_features=True, stat_model="gpt2", val_frac=0.15):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(seed); np.random.seed(seed); random.seed(seed)

    random.Random(seed).shuffle(items)
    n_val = max(40, int(len(items) * val_frac))
    val_items, train_items = items[:n_val], items[n_val:]

    n_extra, mean, std = 0, None, None
    if use_features:
        extractor = CombinedFeatures(stat_model, device=device)
        Xo = extractor.matrix([it["text"] for it in train_items])
        mean, std = Xo.mean(0), Xo.std(0); std[std < 1e-6] = 1.0
        n_extra = Xo.shape[1]
        print(f"[pird] fusing {n_extra} A+C features (standardized)")
        _attach_features(train_items, extractor, mean, std)
        _attach_features(val_items, extractor, mean, std)

    tok = AutoTokenizer.from_pretrained(encoder)
    model = PIRDModel(encoder, n_extra=n_extra).to(device)
    ds = _PairDataset(train_items, tok, max_len, use_features)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True, collate_fn=ds.collate)
    opt = torch.optim.AdamW(model.parameters(), lr=lr)
    bce = nn.BCEWithLogitsLoss()

    model.train()
    for epoch in range(epochs):
        run = {"det": 0.0, "aug": 0.0, "inv": 0.0}
        for step, b in enumerate(dl):
            extra = b.get("extra").to(device) if "extra" in b else None
            logits = model(b["ids"].to(device), b["mask"].to(device), extra)
            labels = b["labels"].to(device)
            loss = bce(logits, labels)
            run["det"] += loss.item()
            if "p_ids" in b:
                p_extra = b.get("p_extra").to(device) if "p_extra" in b else None
                p_logits = model(b["p_ids"].to(device), b["p_mask"].to(device), p_extra)
                p_labels = b["p_labels"].to(device)
                aug = bce(p_logits, p_labels)
                ai_logits = logits[labels == 1.0]
                m = min(len(ai_logits), len(p_logits))
                inv = ((torch.sigmoid(ai_logits[:m]) - torch.sigmoid(p_logits[:m])) ** 2).mean()
                loss = loss + lam_aug * aug + lam_inv * inv
                run["aug"] += aug.item(); run["inv"] += inv.item()
            if not torch.isfinite(loss):
                print(f"  WARN non-finite loss at step {step}, skipping"); opt.zero_grad(); continue
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        n = len(dl)
        print(f"epoch {epoch+1}/{epochs}  det={run['det']/n:.4f}  aug={run['aug']/n:.4f}  "
              f"inv={run['inv']/n:.4f}")

    temperature = _fit_temperature(model, val_items, tok, max_len, device, use_features)
    print(f"[pird] calibration temperature T={temperature:.2f}")

    os.makedirs(out_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(out_dir, "pird.pt"))
    cfg = {"encoder": encoder, "n_extra": n_extra, "max_len": max_len,
           "use_features": use_features, "stat_model": stat_model, "temperature": temperature,
           "feat_mean": (mean.tolist() if mean is not None else None),
           "feat_std": (std.tolist() if std is not None else None)}
    with open(os.path.join(out_dir, "config.json"), "w") as f:
        json.dump(cfg, f)
    print(f"saved PIRD checkpoint -> {out_dir}")
    return out_dir
