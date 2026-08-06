# -*- coding: utf-8 -*-
"""
SigLIP2 분류 후처리: skirts/dresses로 오분류된 탱크탑/홀터탑/튜브탑류 보정
- category가 skirts 또는 dresses인 상품 중 상품명에 TOP_OVERRIDE_KEYWORDS가
  포함된 경우 category를 tops로 강제 재배정한다.
- 단, 상품명에 DRESS_GUARD_KEYWORDS(dress/one-piece/원피스)가 함께 있으면
  실제로는 원피스일 가능성이 높으므로 오버라이드를 적용하지 않는다
  (예: "Shirring shirts long one piece"는 "shirt"가 매칭되지만 "one piece"가
  있으므로 원피스로 그대로 둔다).
- category_confidence는 유지하고, category_source="keyword_override"로 표시한다.
  (기존에 SigLIP2로 분류된 나머지 상품은 category_source="siglip2"로 채운다.)
- subcategory/subcategory_confidence/subcategory_source는 건드리지 않는다
  (재배정 후에는 더 이상 정확한 값이 아니므로 참고용으로만 남는다).
"""

import os
import sys
import sqlite3
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.query_parsing import TOP_OVERRIDE_KEYWORDS

DB_PATH = "fashion_products.db"
TARGET_CATEGORIES = ("skirts", "dresses")

# TOP_OVERRIDE_KEYWORDS가 매칭돼도 이 키워드가 함께 있으면 오버라이드하지 않는다
# (실제로는 원피스/one-piece인데 "shirt"/"top" 등이 스타일 묘사로 들어간 경우 방지)
DRESS_GUARD_KEYWORDS = ["dress", "one-piece", "one piece", "원피스"]


def ensure_category_source_column(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(products)")
    columns = [row[1] for row in cur.fetchall()]
    if "category_source" not in columns:
        cur.execute("ALTER TABLE products ADD COLUMN category_source TEXT")
        conn.commit()
        print("   🛠️  products.category_source 컬럼 추가됨")


def matches_top_override(name: str) -> bool:
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in TOP_OVERRIDE_KEYWORDS)


def matches_dress_guard(name: str) -> bool:
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in DRESS_GUARD_KEYWORDS)


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    ensure_category_source_column(conn)
    cur = conn.cursor()

    # 기존 SigLIP2 분류 결과에는 기본값으로 category_source='siglip2'를 채워둔다
    cur.execute("""
        UPDATE products SET category_source = 'siglip2'
        WHERE category IS NOT NULL AND category_source IS NULL
    """)
    conn.commit()

    placeholders = ",".join("?" for _ in TARGET_CATEGORIES)
    cur.execute(f"""
        SELECT id, name FROM products
        WHERE category IN ({placeholders})
    """, TARGET_CATEGORIES)
    candidates = cur.fetchall()

    guarded = [
        (pid, name) for pid, name in candidates
        if matches_top_override(name) and matches_dress_guard(name)
    ]
    overridden = [
        (pid, name) for pid, name in candidates
        if matches_top_override(name) and not matches_dress_guard(name)
    ]

    print(f"📊 검토 대상 (category IN {TARGET_CATEGORIES}): {len(candidates)}개")
    print(f"🛡️  가드로 제외된 상품 (dress/one-piece/원피스 포함): {len(guarded)}개")
    print(f"🔁 tops로 재배정된 상품: {len(overridden)}개")

    for product_id, _ in overridden:
        cur.execute("""
            UPDATE products SET category = 'tops', category_source = 'keyword_override'
            WHERE id = ?
        """, (product_id,))
    conn.commit()
    conn.close()

    return overridden, guarded


def revert_false_positive_overrides(db_path: str, backup_db_path: str):
    """
    가드 추가 전에 이미 category_source='keyword_override'로 재배정됐지만
    DRESS_GUARD_KEYWORDS에 걸리는(false positive) 상품을 backup DB의 원래
    category로 되돌린다. backup_db_path는 오버라이드 적용 이전 시점의 DB 백업이어야 한다.
    """
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM products WHERE category_source = 'keyword_override'")
    overridden_rows = cur.fetchall()

    false_positives = [(pid, name) for pid, name in overridden_rows if matches_dress_guard(name)]

    if not false_positives:
        conn.close()
        return []

    backup_conn = sqlite3.connect(backup_db_path)
    backup_cur = backup_conn.cursor()

    reverted = []
    for product_id, name in false_positives:
        backup_cur.execute("SELECT category FROM products WHERE id = ?", (product_id,))
        row = backup_cur.fetchone()
        if row is None or row[0] is None:
            print(f"   ⚠️  id={product_id} backup에 원래 category가 없어 건너뜀: {name}")
            continue
        original_category = row[0]
        cur.execute(
            "UPDATE products SET category = ?, category_source = 'siglip2' WHERE id = ?",
            (original_category, product_id)
        )
        reverted.append((product_id, name, original_category))

    backup_conn.close()
    conn.commit()
    conn.close()
    return reverted


def main():
    parser = argparse.ArgumentParser(description="상의 오분류 키워드 오버라이드 (dress/one-piece 가드 포함)")
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument(
        "--revert-backup", type=str, default=None,
        help="오버라이드 적용 이전 시점 백업 DB 경로. 지정하면 가드에 걸리는 기존 "
             "keyword_override 상품을 이 백업의 원래 category로 되돌리고 종료한다."
    )
    args = parser.parse_args()

    if args.revert_backup:
        reverted = revert_false_positive_overrides(args.db, args.revert_backup)
        print(f"↩️  되돌린 상품: {len(reverted)}개")
        for product_id, name, original_category in reverted:
            print(f"   id={product_id:<6} category→{original_category:<8} {name}")
        return

    overridden, guarded = run(args.db)
    print()
    for product_id, name in overridden:
        print(f"   id={product_id:<6} {name}")
    if guarded:
        print("\n🛡️  가드로 제외된 상품 목록:")
        for product_id, name in guarded:
            print(f"   id={product_id:<6} {name}")


if __name__ == "__main__":
    main()
