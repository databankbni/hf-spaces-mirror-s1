# -*- coding: utf-8 -*-
"""
embeddings/ 핵심 pkl 재생성 (products 메타데이터 대신 product_ids만 저장)
- model1_gemma.pkl : Gemma("{brand} {name}") 상품명 텍스트 임베딩
- model3_fashionclip.pkl : FashionCLIP 상품 사진 임베딩 (배치 처리)
- CLIP 상품명 임베딩(clip_text_names.pkl)은 scripts/build_clip_text_embeddings.py 담당
"""

import os
import sys
import pickle

import numpy as np
import torch
from PIL import Image, ImageFile
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from transformers import CLIPProcessor, CLIPModel

ImageFile.LOAD_TRUNCATED_IMAGES = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.recommend import FashionDB, EMBEDDING_PATHS, ensure_embedding_dir


def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def build_text_embeddings(products):
    print("📦 Gemma 로딩 중...")
    model = SentenceTransformer("google/embeddinggemma-300m")
    print("🔨 [1/2] 텍스트 임베딩 생성 중 (Gemma, 전 모델 공통)...")
    texts = [f"{p.get('brand_name', '')} {p.get('name', '')}".strip() for p in products]
    return model.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)


def build_image_embeddings(products, batch_size=32):
    device = get_device()
    print(f"📦 FashionCLIP 로딩 중... (device={device})")
    clip_model = CLIPModel.from_pretrained("patrickjohncyh/fashion-clip").to(device)
    clip_model.eval()
    clip_processor = CLIPProcessor.from_pretrained("patrickjohncyh/fashion-clip")

    print("🔨 [2/2] 이미지 임베딩 생성 중 (FashionCLIP, 전 모델 공통)...")
    embeddings = np.zeros((len(products), 512), dtype=np.float32)

    for start in tqdm(range(0, len(products), batch_size)):
        batch = products[start:start + batch_size]
        images = []
        valid_positions = []
        for pos, p in enumerate(batch):
            try:
                images.append(Image.open(p['local_image_path']).convert("RGB"))
                valid_positions.append(pos)
            except Exception as e:
                print(f"   ⚠️  이미지 로드 실패 (0벡터로 대체): {p.get('local_image_path')} ({e})")

        if not images:
            continue

        inputs = clip_processor(images=images, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            features = clip_model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        features = features.cpu().numpy()

        for local_i, pos in enumerate(valid_positions):
            embeddings[start + pos] = features[local_i]

    return embeddings


def main():
    db = FashionDB()
    products = db.get_all_products(only_with_image=True)
    product_ids = [p['id'] for p in products]
    print(f"📊 대상 상품: {len(products)}개")

    text_embeddings = build_text_embeddings(products)
    image_embeddings = build_image_embeddings(products)

    ensure_embedding_dir()

    outputs = {
        EMBEDDING_PATHS["model1"]: {
            'embeddings': text_embeddings,
            'product_ids': product_ids,
        },
        EMBEDDING_PATHS["model3"]: {
            'image_embeddings': image_embeddings,
            'product_ids': product_ids,
        },
    }

    print("\n💾 pkl 저장 중...")
    for path, data in outputs.items():
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        size_mb = os.path.getsize(path) / 1024 / 1024
        shapes = {k: v.shape for k, v in data.items() if hasattr(v, 'shape')}
        print(f"   ✅ {path}: {size_mb:.1f}MB | 상품 {len(data['product_ids'])}개 | {shapes}")

    print("\n✅ 전체 재생성 완료")


if __name__ == "__main__":
    main()
