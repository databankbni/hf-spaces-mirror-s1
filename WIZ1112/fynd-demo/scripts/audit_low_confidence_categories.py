# -*- coding: utf-8 -*-
"""
저confidence 안전장치 (수동 검토용 audit, DB는 건드리지 않는다)
- category_confidence가 극단적으로 낮은(기본: 전체 분포 p10=0.48 미만) 상품에 대해서만,
  DB category(SigLIP2, TAXONOMY 대분류)와 상품명 기반 extract_product_category()
  (CATEGORY_GROUPS 규칙) 결과를 병행 확인한다.
- 두 결과가 서로 다르면 로그로만 남긴다. 자동 수정은 하지 않는다.
"""

import os
import sys
import sqlite3
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.query_parsing import extract_product_category, OLD_TO_TAXONOMY_CATEGORY, categories_overlap

DB_PATH = "fashion_products.db"
P10_THRESHOLD = 0.48  # 전체 category_confidence 분포의 p10 (요청 시점 기준)


def run(db_path: str = DB_PATH, threshold: float = P10_THRESHOLD):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, category, category_confidence
        FROM products
        WHERE category_confidence IS NOT NULL AND category_confidence < ?
        ORDER BY category_confidence ASC
    """, (threshold,))
    rows = cur.fetchall()
    conn.close()

    print(f"📊 극단적으로 낮은 confidence(< {threshold}) 상품: {len(rows)}개")

    mismatches = []
    for product_id, name, db_category, confidence in rows:
        regex_category = extract_product_category(name)
        if regex_category is None:
            continue  # 정규식으로 아무것도 못 찾으면 비교 불가 -> 스킵

        # extract_product_category()는 구 CATEGORY_GROUPS 어휘를 반환하므로
        # OLD_TO_TAXONOMY_CATEGORY로 신 TAXONOMY 어휘(단일값 또는 Set)로 변환 후 비교한다.
        regex_major = OLD_TO_TAXONOMY_CATEGORY.get(regex_category, regex_category)
        if regex_major and not categories_overlap(regex_major, db_category):
            mismatches.append((product_id, name, db_category, regex_category, regex_major, confidence))

    print(f"⚠️  DB category와 이름 기반 추론이 불일치하는 상품: {len(mismatches)}개\n")
    for product_id, name, db_category, regex_category, regex_major, confidence in mismatches:
        print(
            f"   id={product_id:<6} conf={confidence:.4f}  "
            f"DB={db_category:<12} regex={regex_category}(→{regex_major})  name={name}"
        )

    return mismatches


def main():
    parser = argparse.ArgumentParser(description="저confidence 카테고리 안전장치 audit (읽기 전용)")
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument("--threshold", type=float, default=P10_THRESHOLD)
    args = parser.parse_args()

    run(args.db, args.threshold)


if __name__ == "__main__":
    main()
