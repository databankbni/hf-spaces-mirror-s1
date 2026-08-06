# -*- coding: utf-8 -*-
"""
SigLIP2 계층적(2단계) 제로샷 이미지 분류로 products.category/subcategory 채우기
- 1단계: src.query_parsing.TAXONOMY의 대분류(8개) 중 하나를 소프트맥스로 결정
- 2단계: 1단계에서 결정된 대분류에 속한 중분류 후보만 놓고 다시 소프트맥스로 결정
  단, dresses/skirts는 상품명에서 LENGTH_KEYWORDS(미니/미디/롱) 키워드가
  매칭되면 그 결과(텍스트 기반)를 우선 사용한다. 이때 subcategory_confidence는
  1단계 대분류 확신도(category_confidence)를 넘지 않도록 제한한다.
  (DETAIL_KEYWORDS_EXPANDED의 "crop"은 "크롭핏"을 가리키는 별개 키워드라
  "CROP TOP"처럼 실제 상의 상품명에도 매칭되므로 기장 판정에는 쓰지 않는다.)
- TAXONOMY 라벨은 영어를 사용한다: SigLIP2가 한국어 프롬프트에서 신뢰도 높은
  오분류를 체계적으로 일으키는 것을 확인했기 때문 (예: 스웨트셔츠를 0.88
  신뢰도로 "원피스"로 분류). 영어 프롬프트가 훨씬 안정적으로 동작한다.
"""

import os
import sys
import math
import sqlite3
import argparse
from typing import Dict, List, Optional, Tuple

import torch
from PIL import Image, ImageFile
from tqdm import tqdm
from transformers import AutoModel, AutoProcessor

ImageFile.LOAD_TRUNCATED_IMAGES = True

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.query_parsing import TAXONOMY

MODEL_NAME = "google/siglip2-base-patch16-224"
DB_PATH = "fashion_products.db"

MAJOR_LABELS = list(TAXONOMY.keys())

# dresses/skirts 기장(길이) 판정 전용 키워드셋.
# DETAIL_KEYWORDS_EXPANDED의 "crop"은 상의/아우터의 "크롭핏"을 가리키는 키워드라
# "CROP TOP"처럼 실제로는 상의인 상품명에도 매칭돼버리므로, 여기서는 재사용하지
# 않고 기장 판정 전용으로 별도 정의한다. crop 키워드 자체는 DETAIL_KEYWORDS_EXPANDED에
# 그대로 남아있고 상의/아우터 핏 판정에는 계속 쓰인다.
LENGTH_KEYWORDS = {
    "미니": ["미니", "mini"],
    "미디": ["미디", "midi"],
    "롱": ["맥시", "long", "롱", "maxi"],
}
LENGTH_TO_SUBCATEGORY = {
    "dresses": {"미니": "mini dresses", "미디": "midi dresses", "롱": "maxi dresses"},
    "skirts": {"미니": "mini skirts", "미디": "midi skirts", "롱": "long skirts"},
}


def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def ensure_columns(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(products)")
    columns = [row[1] for row in cur.fetchall()]

    needed = {
        "category": "TEXT",
        "category_confidence": "REAL",
        "subcategory": "TEXT",
        "subcategory_confidence": "REAL",
        "subcategory_source": "TEXT",
    }
    for name, col_type in needed.items():
        if name not in columns:
            cur.execute(f"ALTER TABLE products ADD COLUMN {name} {col_type}")
            conn.commit()
            print(f"   🛠️  products.{name} 컬럼 추가됨")


def fetch_targets(conn: sqlite3.Connection, force: bool, limit: int = None):
    cur = conn.cursor()
    query = """
        SELECT p.id, p.name, i.local_path
        FROM products p
        JOIN images i ON p.id = i.product_id
        WHERE i.local_path IS NOT NULL
    """
    if not force:
        query += " AND p.subcategory_confidence IS NULL"
    query += " ORDER BY p.id"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query)
    return cur.fetchall()


def load_model(device: str):
    print(f"📦 SigLIP2 로딩 중... ({MODEL_NAME}, device={device})")
    processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model = AutoModel.from_pretrained(MODEL_NAME)
    model = model.to(device)
    model.eval()
    print("   ✅ 로딩 완료!")
    return model, processor


def encode_texts(prompts: List[str], model, processor, device: str) -> torch.Tensor:
    inputs = processor(text=prompts, padding="max_length", return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        text_embeds = model.get_text_features(**inputs)
    text_embeds = text_embeds / text_embeds.norm(p=2, dim=-1, keepdim=True)
    return text_embeds


def build_taxonomy_text_embeddings(model, processor, device: str):
    """대분류(8개) + 대분류별 중분류 텍스트 임베딩(정규화됨)을 미리 계산한다."""
    major_prompts = [f"This is a photo of {label}." for label in MAJOR_LABELS]
    major_embeds = encode_texts(major_prompts, model, processor, device)

    sub_embeds_by_major: Dict[str, torch.Tensor] = {}
    for major, subs in TAXONOMY.items():
        sub_prompts = [f"This is a photo of {sub}." for sub in subs]
        sub_embeds_by_major[major] = encode_texts(sub_prompts, model, processor, device)

    return major_embeds, sub_embeds_by_major


def detect_length_subcategory(major: str, name: str) -> Optional[str]:
    """원피스/스커트 상품명에서 LENGTH_KEYWORDS(미니/미디/롱)를 찾아 중분류로 변환"""
    if major not in LENGTH_TO_SUBCATEGORY:
        return None

    name_lower = name.lower()
    matched = []
    for length_key, keywords in LENGTH_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in name_lower:
                matched.append((len(kw), length_key))

    if not matched:
        return None

    matched.sort(reverse=True)
    length_key = matched[0][1]
    return LENGTH_TO_SUBCATEGORY[major][length_key]


def load_images(image_paths: List[str]) -> Tuple[List[Image.Image], List[int]]:
    images = []
    valid_positions = []
    for pos, path in enumerate(image_paths):
        try:
            images.append(Image.open(path).convert("RGB"))
            valid_positions.append(pos)
        except Exception as e:
            print(f"   ⚠️  이미지 로드 실패: {path} ({e})")
    return images, valid_positions


def classify_batch(
    image_paths: List[str],
    names: List[str],
    model, processor, device: str,
    major_embeds: torch.Tensor,
    sub_embeds_by_major: Dict[str, torch.Tensor],
):
    """
    이미지 배치를 계층적으로 분류한다.
    반환: (category, category_confidence, subcategory, subcategory_confidence, subcategory_source)
          튜플 리스트. 이미지 로드 실패 시 해당 위치는 None.
    """
    images, valid_positions = load_images(image_paths)

    results = [None] * len(image_paths)
    if not images:
        return results

    inputs = processor(images=images, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        image_embeds = model.get_image_features(**inputs)
    image_embeds = image_embeds / image_embeds.norm(p=2, dim=-1, keepdim=True)

    scale = model.logit_scale.exp()

    # === 1단계: 대분류 (8개 로짓끼리 소프트맥스) ===
    major_logits = image_embeds @ major_embeds.t() * scale
    major_probs = torch.softmax(major_logits, dim=1)
    major_scores, major_indices = major_probs.max(dim=1)

    for local_i, pos in enumerate(valid_positions):
        major = MAJOR_LABELS[major_indices[local_i].item()]
        major_confidence = float(major_scores[local_i].item())
        name = names[pos]

        # === 원피스/스커트: 상품명 기반 기장 판정 우선 ===
        # 텍스트 키워드가 매칭돼도 1단계 대분류 확신도(major_confidence)를
        # 넘지 않도록 제한한다 (1단계가 불확실했던 상품은 낮은 confidence 유지)
        text_subcategory = detect_length_subcategory(major, name)
        if text_subcategory is not None:
            text_confidence = min(1.0, major_confidence)
            results[pos] = (major, major_confidence, text_subcategory, text_confidence, "text")
            continue

        # === 2단계: 중분류 (대분류 내 후보끼리 소프트맥스) ===
        sub_labels = TAXONOMY[major]
        sub_embeds = sub_embeds_by_major[major]
        image_embed = image_embeds[local_i:local_i + 1]

        sub_logits = image_embed @ sub_embeds.t() * scale
        sub_probs = torch.softmax(sub_logits, dim=1)[0]
        sub_score, sub_index = sub_probs.max(dim=0)

        subcategory = sub_labels[sub_index.item()]
        results[pos] = (major, major_confidence, subcategory, float(sub_score.item()), "siglip2")

    return results


def run(db_path: str, batch_size: int, force: bool, limit: int):
    conn = sqlite3.connect(db_path)
    ensure_columns(conn)

    targets = fetch_targets(conn, force=force, limit=limit)
    if not targets:
        print("✅ 분류할 상품이 없습니다 (이미 전부 분류됨, --force로 재분류 가능)")
        conn.close()
        return

    print(f"📊 분류 대상: {len(targets)}개 상품")

    device = get_device()
    model, processor = load_model(device)
    major_embeds, sub_embeds_by_major = build_taxonomy_text_embeddings(model, processor, device)

    cur = conn.cursor()
    updated = 0

    for i in tqdm(range(0, len(targets), batch_size), desc="분류 진행"):
        batch = targets[i:i + batch_size]
        image_paths = [row[2] for row in batch]
        names = [row[1] for row in batch]
        batch_results = classify_batch(
            image_paths, names, model, processor, device, major_embeds, sub_embeds_by_major
        )

        for row, result in zip(batch, batch_results):
            if result is None:
                continue
            category, category_confidence, subcategory, subcategory_confidence, subcategory_source = result
            cur.execute(
                """UPDATE products
                   SET category = ?, category_confidence = ?,
                       subcategory = ?, subcategory_confidence = ?, subcategory_source = ?
                   WHERE id = ?""",
                (category, category_confidence, subcategory, subcategory_confidence, subcategory_source, row[0])
            )
            updated += 1

        conn.commit()

    print(f"\n✅ {updated}개 상품 분류 완료")
    print_distribution(cur)
    conn.close()


def print_distribution(cur: sqlite3.Cursor):
    # 대분류별 분포
    cur.execute("""
        SELECT category, COUNT(*) FROM products
        WHERE category IS NOT NULL
        GROUP BY category ORDER BY COUNT(*) DESC
    """)
    major_rows = cur.fetchall()
    total = sum(count for _, count in major_rows)

    print("\n📊 대분류별 분포:")
    print(f"   {'대분류':<10} {'개수':>8}")
    print(f"   {'-' * 10} {'-' * 8}")
    for category, count in major_rows:
        print(f"   {category:<10} {count:>8}개")
    print(f"   {'-' * 10} {'-' * 8}")
    print(f"   {'합계':<10} {total:>8}개")

    # 중분류별 분포 (대분류 순서 기준으로 정렬)
    cur.execute("""
        SELECT category, subcategory, COUNT(*) FROM products
        WHERE subcategory IS NOT NULL
        GROUP BY category, subcategory
    """)
    sub_counts: Dict[Tuple[str, str], int] = {
        (category, subcategory): count for category, subcategory, count in cur.fetchall()
    }

    print("\n📊 중분류별 분포:")
    print(f"   {'대분류':<10} {'중분류':<12} {'개수':>8}")
    print(f"   {'-' * 10} {'-' * 12} {'-' * 8}")
    low_count_subcategories = []
    for major, subs in TAXONOMY.items():
        for sub in subs:
            count = sub_counts.get((major, sub), 0)
            print(f"   {major:<10} {sub:<12} {count:>8}개")
            if count < 10:
                low_count_subcategories.append((major, sub, count))

    if low_count_subcategories:
        print(f"\n⚠️  상품이 10개 미만인 중분류 ({len(low_count_subcategories)}개) — taxonomy 조정 검토 필요:")
        for major, sub, count in low_count_subcategories:
            print(f"   [{major} > {sub}] {count}개")
    else:
        print("\n✅ 모든 중분류가 10개 이상의 상품을 보유하고 있습니다.")


def main():
    parser = argparse.ArgumentParser(description="SigLIP2 계층적(2단계) 제로샷 카테고리 분류")
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true", help="이미 분류된 상품도 재분류")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 샘플 개수 제한")
    args = parser.parse_args()

    run(args.db, args.batch_size, args.force, args.limit)


if __name__ == "__main__":
    main()
