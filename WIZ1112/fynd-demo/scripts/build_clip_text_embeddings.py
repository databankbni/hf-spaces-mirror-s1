# -*- coding: utf-8 -*-
"""
상품명(brand_name + name)을 FashionCLIP "텍스트" 인코더로 임베딩해서
embeddings/clip_text_names.pkl로 저장한다.
- cross_only/full_fusion 조건의 "쿼리 이미지 → 상품명" 교차항에 사용된다.
- 기존 Gemma 텍스트 임베딩(model1_gemma.pkl), CLIP 이미지 임베딩
  (model3_fashionclip.pkl)은 그대로 재사용하며 이 스크립트는 건드리지 않는다.
- 포맷은 다른 pkl과 동일하게 product_ids만 저장 (메타데이터는 로드 시 DB 조회)
"""

import os
import sys
import pickle

import numpy as np
import torch
from tqdm import tqdm
from transformers import CLIPProcessor, CLIPModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.recommend import FashionDB, ensure_embedding_dir

OUTPUT_PATH = os.path.join("embeddings", "clip_text_names.pkl")
BATCH_SIZE = 64
CLIP_MAX_LENGTH = 77  # CLIP 텍스트 인코더 최대 토큰 수 (fashion-clip 체크포인트에 미설정이라 명시)


def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def main():
    db = FashionDB()
    products = db.get_all_products(only_with_image=True)
    product_ids = [p['id'] for p in products]
    texts = [f"{p.get('brand_name', '')} {p.get('name', '')}".strip() for p in products]
    print(f"📊 대상 상품: {len(products)}개")

    device = get_device()
    print(f"📦 FashionCLIP 로딩 중... (device={device})")
    model = CLIPModel.from_pretrained("patrickjohncyh/fashion-clip").to(device)
    model.eval()
    processor = CLIPProcessor.from_pretrained("patrickjohncyh/fashion-clip")

    print("🔨 상품명 CLIP 텍스트 임베딩 생성 중...")
    embeddings = np.zeros((len(texts), 512), dtype=np.float32)
    for start in tqdm(range(0, len(texts), BATCH_SIZE)):
        batch = texts[start:start + BATCH_SIZE]
        inputs = processor(
            text=batch, return_tensors="pt",
            padding=True, truncation=True, max_length=CLIP_MAX_LENGTH,
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            features = model.get_text_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        embeddings[start:start + len(batch)] = features.cpu().numpy()

    ensure_embedding_dir()
    with open(OUTPUT_PATH, 'wb') as f:
        pickle.dump({
            'text_name_embeddings': embeddings,
            'product_ids': product_ids,
        }, f)

    size_mb = os.path.getsize(OUTPUT_PATH) / 1024 / 1024
    print(f"✅ 저장 완료: {OUTPUT_PATH} ({size_mb:.1f}MB, shape={embeddings.shape})")


if __name__ == "__main__":
    main()
