# -*- coding: utf-8 -*-
"""
상품 이미지 일괄 리사이즈 (배포 용량 관리)
- HF Space 저장소 1GB 제한 대응: 크롤링 원본(og:image 풀사이즈, ~400KB/장)을
  최대 변 max-side(px)로 축소해 JPEG로 저장한다.
- CLIP 입력이 224px라 500px 축소는 검색 품질에 영향 없음. 웹 썸네일 용도로도 충분.
- PNG 등 다른 포맷은 .jpg로 변환하고 DB(images.local_path, 상품과 무관)를 갱신한다.
- 이미 충분히 작은 파일(기본 120KB 미만)은 건너뜀 → 재실행 안전.
"""

import os
import sys
import sqlite3
import argparse

from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True

DB_PATH = "fashion_products.db"

# 신규 크롤링 브랜드 폴더 (기존 브랜드는 이미 썸네일 크기)
DEFAULT_DIRS = [
    "saltnchoco", "glowny", "leathery", "aakam", "midnightmove", "fancyclub",
    "pleasenofollow", "asyouare", "flareup", "hugyourskin", "coiris",
    "trillion", "ason", "coldestmoment", "etreausommet", "schisminducing",
]


def resize_file(path, max_side, quality):
    """리사이즈 + JPEG 변환. 반환: (새 경로, 변환 여부)"""
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        base, ext = os.path.splitext(path)
        new_path = base + ".jpg"
        img.save(new_path, "JPEG", quality=quality, optimize=True)

    if new_path != path:
        os.remove(path)
        return new_path, True
    return new_path, False


def main():
    parser = argparse.ArgumentParser(description="상품 이미지 일괄 리사이즈")
    parser.add_argument("--dirs", nargs="*", default=DEFAULT_DIRS, help="images/ 하위 대상 폴더")
    parser.add_argument("--max-side", type=int, default=500)
    parser.add_argument("--quality", type=int, default=85)
    parser.add_argument("--skip-under-kb", type=int, default=120, help="이 크기 미만 파일은 건너뜀")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    resized = skipped = failed = renamed = 0
    for d in args.dirs:
        folder = os.path.join("images", d)
        if not os.path.isdir(folder):
            continue
        for fname in sorted(os.listdir(folder)):
            path = os.path.join(folder, fname)
            if not os.path.isfile(path):
                continue
            if os.path.getsize(path) < args.skip_under_kb * 1024 and path.endswith(".jpg"):
                skipped += 1
                continue
            try:
                new_path, changed = resize_file(path, args.max_side, args.quality)
                resized += 1
                if changed:
                    cur.execute("UPDATE images SET local_path=? WHERE local_path=?", (new_path, path))
                    renamed += cur.rowcount
            except Exception as e:
                print(f"   ⚠️ 실패: {path} ({e})")
                failed += 1
        conn.commit()
        print(f"✅ {folder} 처리 완료", flush=True)

    conn.commit()
    conn.close()
    print(f"\n리사이즈 {resized} / 스킵(이미 작음) {skipped} / 실패 {failed} / 확장자변경 DB갱신 {renamed}")


if __name__ == "__main__":
    main()
