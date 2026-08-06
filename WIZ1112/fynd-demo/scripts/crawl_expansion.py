# -*- coding: utf-8 -*-
"""
DB 확장 크롤러 (2026-07, 16개 신규 브랜드)
- 기존 crawler.py의 사이트별 목록 셀렉터 방식 대신, 카페24 공통 상세페이지
  메타태그(og:title / product:sale_price:amount / og:image) 기반 공용 파서 사용.
- 상품 URL 수집: sitemap.xml 우선, 없으면 목록 페이지(cate_no 순회) 페이지네이션.
- 사전 확인(2026-07-05): 16곳 전부 robots.txt에서 상품 경로 허용.
  요청 간 딜레이로 서버 부하 최소화 (페이지 0.5s / 이미지 0.2s).
- 재실행 안전: DB에 이미 있는 product_url은 건너뜀.
- 신규 상품 category='ALL' → 이후 scripts/classify_categories_siglip2.py로 분류.
"""

import os
import re
import sys
import time
import hashlib
import sqlite3
import argparse
import urllib.parse

import requests

DB_PATH = "fashion_products.db"
PAGE_DELAY = 0.5
IMAGE_DELAY = 0.2
TIMEOUT = 15

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
}

# (브랜드명, base_url, 수집 방식, 이미지 저장 폴더 slug)
BRANDS = [
    ("SALT AND CHOCOLATE", "https://saltandchocolate.co.kr", "sitemap", "saltnchoco"),
    ("GLOWNY",             "https://glowny.co.kr",           "sitemap", "glowny"),
    ("LEATHERY",           "https://leathery.co.kr",         "sitemap", "leathery"),
    ("AAKAM",              "https://aakam.kr",               "sitemap", "aakam"),
    ("MIDNIGHT MOVE",      "https://midnight-move.com",      "sitemap", "midnightmove"),
    ("FANCYCLUB",          "https://nastyfancyclub.com",     "sitemap", "fancyclub"),
    ("PLEASENOFOLLOW",     "https://pleasenofollow.kr",      "sitemap", "pleasenofollow"),
    ("AS YOU ARE",         "https://asyouare.co.kr",         "sitemap", "asyouare"),
    ("FLAREUP",            "https://flareup.co.kr",          "sitemap", "flareup"),
    ("HUG YOUR SKIN",      "https://hugyourskin.kr",         "sitemap", "hugyourskin"),
    ("COIRIS",             "https://coiris.cafe24.com",      "sitemap", "coiris"),
    ("TRILLION",           "https://thetrillion.co.kr",      "list",    "trillion"),
    ("ASON",               "https://ason.kr",                "list",    "ason"),
    ("THE COLDEST MOMENT", "https://thecoldestmoment.com",   "list",    "coldestmoment"),
    ("ETRE AU SOMMET",     "https://etreausommet.co.kr",     "list",    "etreausommet"),
    ("SCHISM INDUCING",    "https://schisminducing.net",     "list",    "schisminducing"),
]

DETAIL_URL_RE = re.compile(r'/product/[^"\'?#]+/\d+/?$')
DETAIL_QS_RE = re.compile(r'/product/detail\.html\?product_no=\d+')


class ExpansionCrawler:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ---------- DB ----------
    def get_or_create_brand(self, name, base_url):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('SELECT id FROM brands WHERE name = ?', (name,))
        row = cur.fetchone()
        if row:
            brand_id = row[0]
        else:
            cur.execute('INSERT INTO brands (name, base_url) VALUES (?, ?)', (name, base_url))
            brand_id = cur.lastrowid
        conn.commit()
        conn.close()
        return brand_id

    def existing_urls(self, brand_id):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('SELECT product_url FROM products WHERE brand_id = ?', (brand_id,))
        urls = {r[0] for r in cur.fetchall() if r[0]}
        conn.close()
        return urls

    def save_product(self, brand_id, data):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            cur.execute('''
                INSERT OR IGNORE INTO products
                (brand_id, product_code, name, original_price, sale_price, image_url, product_url, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (brand_id, data['code'], data['name'], data['price'], data['price'],
                  data['image_url'], data['product_url'], 'ALL'))
            conn.commit()
            if cur.lastrowid and cur.rowcount > 0:
                return cur.lastrowid
            return None  # 이미 존재 (UNIQUE brand_id+product_code)
        finally:
            conn.close()

    def save_image_record(self, product_id, image_url, local_path):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute('''
            INSERT OR REPLACE INTO images (product_id, image_url, local_path, image_hash)
            VALUES (?, ?, ?, ?)
        ''', (product_id, image_url, local_path, hashlib.md5(image_url.encode()).hexdigest()))
        conn.commit()
        conn.close()

    # ---------- HTTP ----------
    def get(self, url, timeout=TIMEOUT):
        safe = urllib.parse.quote(url, safe=':/?&=%')
        for attempt in range(3):
            try:
                r = self.session.get(safe, timeout=timeout)
                if r.status_code == 200:
                    return r
                if r.status_code in (404, 410):
                    return None
            except requests.RequestException:
                pass
            time.sleep(1.5 * (attempt + 1))
        return None

    def download_image(self, image_url, save_dir):
        os.makedirs(save_dir, exist_ok=True)
        try:
            r = self.session.get(urllib.parse.quote(image_url, safe=':/?&=%'), timeout=TIMEOUT)
            r.raise_for_status()
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
            ext = image_url.split('.')[-1].split('?')[0].lower()
            if ext not in ('jpg', 'jpeg', 'png', 'webp', 'gif'):
                ext = 'jpg'
            path = os.path.join(save_dir, f"{url_hash}.{ext}")
            with open(path, 'wb') as f:
                f.write(r.content)
            return path
        except Exception:
            return None

    # ---------- 상품 URL 수집 ----------
    def urls_from_sitemap(self, base_url):
        r = self.get(f"{base_url}/sitemap.xml")
        if not r:
            return []
        locs = re.findall(r'<loc>([^<]+)</loc>', r.text)
        urls = []
        for u in locs:
            if '/product/' in u and '/category/' not in u:
                # sitemap이 다른 도메인(데모 등)을 가리키면 base로 교체
                parsed = urllib.parse.urlparse(u)
                urls.append(base_url + parsed.path)
        return sorted(set(urls))

    def urls_from_lists(self, base_url, max_cates=12, max_pages=30):
        """홈에서 cate_no 후보 수집 → 목록 페이지네이션 → 상세 링크 수집 (카페24 공통)"""
        home = self.get(base_url)
        if not home:
            return []
        cates = re.findall(r'cate_no=(\d+)', home.text)
        # SEO형 카테고리 링크도 수집 (/category/name/NN/)
        seo_cates = re.findall(r'href="(/category/[^"]+/\d+/)"', home.text)
        cate_counts = {}
        for c in cates:
            cate_counts[c] = cate_counts.get(c, 0) + 1
        cate_list = sorted(cate_counts, key=cate_counts.get, reverse=True)[:max_cates]

        product_urls = set()

        def collect_from(html):
            found = set()
            for m in re.finditer(r'href="([^"]+)"', html):
                href = m.group(1)
                if DETAIL_QS_RE.search(href) or DETAIL_URL_RE.search(href.split('?')[0]):
                    if href.startswith('/'):
                        href = base_url + href
                    if href.startswith(base_url):
                        u = href.split('#')[0]
                        # /product/이름/no/ 이후의 /category/../display/../ 꼬리를 제거해
                        # 같은 상품의 URL 변형이 중복 수집되는 것을 방지 (정규화)
                        u = re.sub(r'(/product/[^/]+/\d+)/.*$', r'\1/', u)
                        found.add(u)
            return found

        sources = [f"{base_url}/product/list.html?cate_no={c}" for c in cate_list]
        sources += [f"{base_url}{p}" for p in sorted(set(seo_cates))[:max_cates]]

        barren_streak = 0  # 새 URL을 전혀 못 더한 소스 연속 개수 (nav 중복 카테고리 조기 중단)
        for si, src in enumerate(sources):
            before_src = len(product_urls)
            prev_total = -1
            for page in range(1, max_pages + 1):
                sep = '&' if '?' in src else '?'
                r = self.get(f"{src}{sep}page={page}")
                time.sleep(PAGE_DELAY)
                if not r:
                    break
                new = collect_from(r.text)
                product_urls |= new
                if len(product_urls) == prev_total or not new:
                    break
                prev_total = len(product_urls)
            gained = len(product_urls) - before_src
            print(f"      [URL수집 {si+1}/{len(sources)}] +{gained} (누적 {len(product_urls)})", flush=True)
            barren_streak = barren_streak + 1 if gained == 0 else 0
            if barren_streak >= 4 and len(product_urls) > 0:
                print("      (연속 4개 소스에서 신규 없음 — 수집 조기 종료)", flush=True)
                break
        return sorted(product_urls)

    # ---------- 상세 파싱 (카페24 공통 메타) ----------
    @staticmethod
    def parse_detail(html, product_url):
        def meta(prop):
            m = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), html)
            return m.group(1).strip() if m else None

        name = meta('og:title')
        if not name:
            return None
        site_name = meta('og:site_name')
        if site_name and name.endswith(' - ' + site_name):
            name = name[: -len(' - ' + site_name)].strip()

        price = None
        for prop in ('product:sale_price:amount', 'product:price:amount'):
            v = meta(prop)
            if v:
                try:
                    price = int(float(v))
                    break
                except ValueError:
                    pass
        if price is None:
            price = 0

        # og:image가 여러 개인 스킨(첫 번째가 로고인 경우)이 있으므로,
        # 카페24 상품 이미지 경로(/web/product/)를 우선 선택한다
        og_images = re.findall(r'<meta property="og:image" content="([^"]*)"', html)
        image_url = None
        for cand in og_images:
            if '/web/product/' in cand:
                image_url = cand
                break
        if not image_url and og_images:
            image_url = og_images[0]
        if image_url and image_url.startswith('//'):
            image_url = 'https:' + image_url

        # SEO URL: /product/<이름>/<product_no>/ 뒤에 /category/42/display/1/ 이
        # 붙는 스킨이 있으므로, 반드시 이름 바로 다음의 숫자 세그먼트를 추출한다
        path = product_url.split('?')[0]
        m = re.search(r'/product/[^/]+/(\d+)', path)
        if m:
            code = m.group(1)
        else:
            m = re.search(r'product_no=(\d+)', product_url)
            code = m.group(1) if m else hashlib.md5(product_url.encode()).hexdigest()[:12]

        return {'name': name, 'price': price, 'image_url': image_url,
                'product_url': product_url, 'code': code}

    # ---------- 브랜드 단위 실행 ----------
    def crawl_brand(self, name, base_url, source, slug, limit=None):
        print(f"\n{'='*70}\n🔍 {name} ({base_url}) — 방식: {source}", flush=True)
        brand_id = self.get_or_create_brand(name, base_url)

        if source == "sitemap":
            urls = self.urls_from_sitemap(base_url)
        else:
            urls = self.urls_from_lists(base_url)
        print(f"   수집된 상품 URL: {len(urls)}개", flush=True)

        if limit:
            urls = urls[:limit]

        done_urls = self.existing_urls(brand_id)
        saved = skipped = failed = 0
        save_dir = os.path.join("images", slug)

        for i, url in enumerate(urls):
            if url in done_urls:
                skipped += 1
                continue
            r = self.get(url)
            time.sleep(PAGE_DELAY)
            if not r:
                failed += 1
                continue
            data = self.parse_detail(r.text, url)
            if not data or not data['image_url']:
                failed += 1
                continue
            product_id = self.save_product(brand_id, data)
            if not product_id:
                skipped += 1
                continue
            local = self.download_image(data['image_url'], save_dir)
            time.sleep(IMAGE_DELAY)
            if local:
                self.save_image_record(product_id, data['image_url'], local)
                saved += 1
            else:
                failed += 1
            if (saved + skipped + failed) % 50 == 0:
                print(f"   ... {i+1}/{len(urls)} (저장 {saved} / 스킵 {skipped} / 실패 {failed})", flush=True)

        print(f"✅ {name} 완료 — 저장 {saved} / 스킵 {skipped} / 실패 {failed}", flush=True)
        return saved


def main():
    parser = argparse.ArgumentParser(description="16개 신규 브랜드 확장 크롤러")
    parser.add_argument("--db", type=str, default=DB_PATH)
    parser.add_argument("--brand", type=str, default=None, help="특정 브랜드만 (이름 부분일치)")
    parser.add_argument("--limit", type=int, default=None, help="브랜드당 상품 수 제한 (테스트용)")
    args = parser.parse_args()

    crawler = ExpansionCrawler(args.db)
    total = 0
    for name, base_url, source, slug in BRANDS:
        if args.brand and args.brand.lower() not in name.lower():
            continue
        try:
            total += crawler.crawl_brand(name, base_url, source, slug, limit=args.limit)
        except Exception as e:
            print(f"❌ {name} 실패: {e}", flush=True)

    print(f"\n{'='*70}\n🏁 전체 완료 — 신규 저장 합계: {total}개", flush=True)


if __name__ == "__main__":
    main()
