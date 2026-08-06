"""
한국 패션 브랜드 크롤러
- ASURA 등 한국 패션 브랜드 상품 데이터 수집
- SQLite 데이터베이스에 저장
"""

import requests
from bs4 import BeautifulSoup
import sqlite3
import json
import os
import time
import re
from datetime import datetime
from urllib.parse import urljoin
import hashlib


class FashionCrawler:
    def __init__(self, db_path="fashion_products.db"):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        self._init_db()
    
    def _init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 브랜드 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS brands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                base_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 상품 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_id INTEGER,
                product_code TEXT,
                name TEXT NOT NULL,
                original_price INTEGER,
                sale_price INTEGER,
                image_url TEXT,
                product_url TEXT,
                category TEXT,
                crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brand_id) REFERENCES brands(id),
                UNIQUE(brand_id, product_code)
            )
        ''')
        
        # 이미지 테이블 (로컬 저장용)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                image_url TEXT,
                local_path TEXT,
                image_hash TEXT,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        ''')
        
        conn.commit()
        conn.close()
        print(f"✅ 데이터베이스 초기화 완료: {self.db_path}")
    
    def get_or_create_brand(self, name, base_url=None):
        """브랜드 조회 또는 생성"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM brands WHERE name = ?', (name,))
        result = cursor.fetchone()
        
        if result:
            brand_id = result[0]
        else:
            cursor.execute(
                'INSERT INTO brands (name, base_url) VALUES (?, ?)',
                (name, base_url)
            )
            brand_id = cursor.lastrowid
            print(f"✅ 새 브랜드 등록: {name}")
        
        conn.commit()
        conn.close()
        return brand_id
    
    def save_product(self, brand_id, product_data):
        """상품 저장"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO products 
                (brand_id, product_code, name, original_price, sale_price, image_url, product_url, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                brand_id,
                product_data.get('code'),
                product_data.get('name'),
                product_data.get('original_price'),
                product_data.get('price'),
                product_data.get('image_url'),
                product_data.get('product_url'),
                product_data.get('category')
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"❌ 상품 저장 실패: {e}")
            return None
        finally:
            conn.close()
    
    def download_image(self, image_url, save_dir="images"):
        """이미지 다운로드"""
        os.makedirs(save_dir, exist_ok=True)
        
        try:
            response = self.session.get(image_url, timeout=10)
            response.raise_for_status()
            
            # 파일명 생성 (URL 해시)
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
            ext = image_url.split('.')[-1].split('?')[0]
            if ext not in ['jpg', 'jpeg', 'png', 'webp', 'gif']:
                ext = 'jpg'
            
            filename = f"{url_hash}.{ext}"
            filepath = os.path.join(save_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return filepath
        except Exception as e:
            print(f"   ⚠️ 이미지 다운로드 실패: {image_url[:50]}...")
            return None
    
    def save_image_record(self, product_id, image_url, local_path):
        """이미지 레코드 저장"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            image_hash = hashlib.md5(image_url.encode()).hexdigest()
            cursor.execute('''
                INSERT OR REPLACE INTO images 
                (product_id, image_url, local_path, image_hash)
                VALUES (?, ?, ?, ?)
            ''', (product_id, image_url, local_path, image_hash))
            conn.commit()
        except Exception as e:
            print(f"   ⚠️ 이미지 레코드 저장 실패: {e}")
        finally:
            conn.close()
    
    def crawl_asura(self, base_url="https://s2asuras2.com", category_path="/1857907220", max_pages=10):
        """
        ASURA 브랜드 크롤링
        
        Args:
            base_url: 사이트 기본 URL
            category_path: 카테고리 경로 (ALL 카테고리)
            max_pages: 최대 페이지 수
        """
        brand_id = self.get_or_create_brand("ASURA", base_url)
        products_crawled = 0
        
        print(f"\n🔍 ASURA 크롤링 시작...")
        print(f"   URL: {base_url}{category_path}")
        
        page = 1
        while page <= max_pages:
            # 페이지 URL 구성 (imweb 플랫폼 특성)
            if page == 1:
                url = f"{base_url}{category_path}"
            else:
                url = f"{base_url}{category_path}?page={page}"
            
            print(f"\n📄 페이지 {page} 크롤링 중... ({url})")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 상품 아이템 찾기
                items = soup.find_all('div', class_='shop-item')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                for item in items:
                    # data-product-properties에서 JSON 추출
                    props_str = item.get('data-product-properties')
                    if not props_str:
                        continue
                    
                    try:
                        props = json.loads(props_str)
                        
                        # 상품 상세 URL 구성
                        product_url = f"{base_url}{category_path}/?idx={props.get('idx')}"
                        
                        product_data = {
                            'code': props.get('code'),
                            'name': props.get('name'),
                            'original_price': props.get('original_price'),
                            'price': props.get('price'),
                            'image_url': props.get('image_url'),
                            'product_url': product_url,
                            'category': 'ALL'  # 나중에 카테고리별 크롤링 시 변경
                        }
                        
                        self.save_product(brand_id, product_data)
                        products_crawled += 1
                        print(f"   ✅ {product_data['name'][:30]}... - {product_data['price']:,}원")
                        
                    except json.JSONDecodeError as e:
                        print(f"   ❌ JSON 파싱 실패: {e}")
                        continue
                
                # 다음 페이지 확인
                # imweb 플랫폼은 보통 페이지네이션이 있거나 무한스크롤
                next_btn = soup.find('a', class_='next') or soup.find('li', class_='next')
                if not next_btn and page > 1:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)  # 서버 부하 방지
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ ASURA 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled
    
    def crawl_with_scroll(self, url, brand_name, scroll_pause=2, max_scrolls=20, download_images=True):
        """
        무한 스크롤 페이지용 크롤링 (Selenium 필요)
        imweb 기반 사이트들은 무한스크롤을 사용하는 경우가 많음
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            print("❌ Selenium이 설치되지 않았습니다.")
            print("   pip install selenium 실행 후 다시 시도해주세요.")
            return 0
        
        brand_id = self.get_or_create_brand(brand_name, url)
        
        # 이미지 저장 폴더명 (브랜드명 기반)
        image_folder = f"images/{brand_name.lower().replace(' ', '_')}"
        
        # Chrome 옵션 설정
        options = Options()
        options.add_argument('--headless')  # 헤드리스 모드
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        
        driver = webdriver.Chrome(options=options)
        products_crawled = 0
        
        try:
            print(f"\n🔍 {brand_name} 크롤링 시작 (Selenium)...")
            if download_images:
                print(f"   📷 이미지 다운로드: ON")
            driver.get(url)
            time.sleep(3)
            
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0
            
            while scroll_count < max_scrolls:
                # 스크롤 다운
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_pause)
                
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    print(f"   📄 더 이상 로드할 상품이 없습니다.")
                    break
                
                last_height = new_height
                scroll_count += 1
                print(f"   📜 스크롤 {scroll_count}/{max_scrolls}")
            
            # 페이지 파싱
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items = soup.find_all('div', class_='shop-item')
            
            print(f"   📦 총 {len(items)}개 상품 발견")
            
            for item in items:
                props_str = item.get('data-product-properties')
                if not props_str:
                    continue
                
                try:
                    props = json.loads(props_str)
                    product_data = {
                        'code': props.get('code'),
                        'name': props.get('name'),
                        'original_price': props.get('original_price'),
                        'price': props.get('price'),
                        'image_url': props.get('image_url'),
                        'product_url': url + f"?idx={props.get('idx')}",
                        'category': 'ALL'
                    }
                    
                    product_id = self.save_product(brand_id, product_data)
                    products_crawled += 1
                    print(f"   ✅ {product_data['name'][:35]}... - {product_data['price']:,}원")
                    
                    # 이미지 다운로드
                    if download_images and product_data['image_url'] and product_id:
                        local_path = self.download_image(product_data['image_url'], save_dir=image_folder)
                        if local_path:
                            self.save_image_record(product_id, product_data['image_url'], local_path)
                    
                except json.JSONDecodeError:
                    continue
            
        finally:
            driver.quit()
        
        print(f"\n✅ {brand_name} 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled
    
    def crawl_michiko(self, base_url="https://michiko-london.kr", cate_no=44, max_pages=50, download_images=True):
        """
        미치코런던 크롤링 (카페24 기반)
        
        Args:
            base_url: 사이트 기본 URL
            cate_no: 카테고리 번호 (44 = 전체)
            max_pages: 최대 페이지 수
            download_images: 이미지 다운로드 여부
        """
        brand_id = self.get_or_create_brand("MICHIKO LONDON", base_url)
        products_crawled = 0
        
        print(f"\n🔍 MICHIKO LONDON 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중... ({url})")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 상품 박스 찾기
                items = soup.find_all('div', class_='box')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('div', class_='name')
                        if not name_elem:
                            continue
                        # 모든 span 찾아서 '상품명'이 아닌 실제 상품명 추출
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:14px' in x)
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        price_elem = item.find('ul', class_='spec')
                        if price_elem:
                            price_text = price_elem.get_text()
                            # 숫자만 추출 (예: "KRW 62,000" 또는 "62,000원")
                            numbers = re.findall(r'[\d,]+', price_text)
                            for num in numbers:
                                try:
                                    parsed = int(num.replace(',', ''))
                                    if parsed > 1000:  # 가격으로 보이는 값만
                                        price = parsed
                                        break
                                except:
                                    continue
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='thumb')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=True)
                        if link_elem:
                            product_url = base_url + link_elem['href']
                            # product_no 추출해서 코드로 사용
                            match = re.search(r'product_no=(\d+)', link_elem['href'])
                            product_code = match.group(1) if match else name[:20]
                        else:
                            product_url = ''
                            product_code = name[:20]
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        # 이미지 다운로드
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/michiko")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                # 상품이 없으면 마지막 페이지
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)  # 서버 부하 방지
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ MICHIKO LONDON 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_miseki(self, base_url="https://misekiseoul.kr", cate_no=29, max_pages=50, download_images=True):
        """
        미세키 서울 크롤링 (카페24 기반)
        
        Args:
            base_url: 사이트 기본 URL
            cate_no: 카테고리 번호 (29 = 전체)
            max_pages: 최대 페이지 수
            download_images: 이미지 다운로드 여부
        """
        brand_id = self.get_or_create_brand("MISEKI SEOUL", base_url)
        products_crawled = 0
        
        print(f"\n🔍 MISEKI SEOUL 크롤링 시작...")
        print(f"   URL: {base_url}/category/all/{cate_no}/")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/category/all/{cate_no}/?page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중... ({url})")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 상품 아이템 찾기
                items = soup.find_all('li', class_='prdList_item')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        # 모든 span 찾아서 '상품명'이 아닌 실제 상품명 추출
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:14px' in x)
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출 (할인가 우선)
                        price = 0
                        original_price = 0
                        
                        # 할인판매가 먼저 확인
                        sale_price_elem = item.find('p', class_='x_prd_price_sale')
                        if sale_price_elem:
                            price_text = sale_price_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                price = int(numbers[0].replace(',', ''))
                        
                        # 원가 확인
                        original_price_elem = item.find('p', class_='x_product_price')
                        if original_price_elem:
                            price_text = original_price_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                original_price = int(numbers[0].replace(',', ''))
                        
                        # 할인가가 없으면 spec에서 찾기
                        if price == 0:
                            spec_elem = item.find('ul', class_='spec')
                            if spec_elem:
                                price_text = spec_elem.get_text()
                                numbers = re.findall(r'[\d,]+', price_text)
                                for num in numbers:
                                    try:
                                        parsed = int(num.replace(',', ''))
                                        if parsed > 1000:
                                            if original_price == 0:
                                                original_price = parsed
                                            else:
                                                price = parsed
                                    except:
                                        continue
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='thumber_1')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 URL 및 코드 추출
                        link_elem = item.find('a', href=True)
                        if link_elem:
                            product_url = base_url + link_elem['href']
                            # anchorBoxId에서 product_no 추출
                            item_id = item.get('id', '')
                            match = re.search(r'anchorBoxId_(\d+)', item_id)
                            product_code = match.group(1) if match else name[:20]
                        else:
                            product_url = ''
                            product_code = name[:20]
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        # 이미지 다운로드
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/miseki")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                # 상품이 없으면 마지막 페이지
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)  # 서버 부하 방지
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ MISEKI SEOUL 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_bohemseoul(self, base_url="https://bohemseo.com", cate_no=64, max_pages=50, download_images=True):
        """
        보헤미안서울 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("BOHEMIAN SEOUL", base_url)
        products_crawled = 0
        
        print(f"\n🔍 BOHEMIAN SEOUL 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        # a 태그 안의 텍스트에서 상품명 추출 (title span 제외)
                        name_link = name_elem.find('a')
                        if name_link:
                            # title span 제거하고 텍스트 추출
                            title_span = name_link.find('span', class_='title')
                            if title_span:
                                title_span.decompose()
                            name = name_link.get_text(strip=True)
                        else:
                            name = name_elem.get_text(strip=True)
                        # 혹시 남아있는 '상품명 :' 제거
                        name = name.replace('상품명 :', '').replace('상품명:', '').strip()
                        if not name:
                            continue
                        
                        # 가격 추출 (ec-data-price 속성 활용)
                        price = 0
                        text_box = item.find('div', class_='text-box')
                        if text_box and text_box.get('ec-data-price'):
                            price = int(text_box.get('ec-data-price'))
                        else:
                            spec_elem = item.find('ul', class_='spec')
                            if spec_elem:
                                price_text = spec_elem.get_text()
                                numbers = re.findall(r'[\d,]+', price_text)
                                for num in numbers:
                                    parsed = int(num.replace(',', ''))
                                    if parsed > 1000:
                                        price = parsed
                                        break
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='before') or item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/bohemseoul")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ BOHEMIAN SEOUL 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_oheshio(self, base_url="https://oheshio.com", cate_no=29, max_pages=50, download_images=True):
        """
        오헤시오 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("OHESHIO", base_url)
        products_crawled = 0
        
        print(f"\n🔍 OHESHIO 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        # 모든 span 찾아서 '상품명'이 아닌 실제 상품명 추출
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:12px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            name = name_elem.get_text(strip=True).replace('상품명 :', '').replace('상품명:', '').strip()
                        if not name or name == '상품명':
                            continue
                        
                        # 가격 추출
                        price = 0
                        spec_elem = item.find('ul', class_='spec')
                        if spec_elem:
                            price_text = spec_elem.get_text()
                            # "KRW 198,000" 형태
                            numbers = re.findall(r'[\d,]+', price_text)
                            for num in numbers:
                                parsed = int(num.replace(',', ''))
                                if parsed > 1000:
                                    price = parsed
                                    break
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/oheshio")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ OHESHIO 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_coyseio(self, base_url="https://coyseio.com", cate_no=54, max_pages=50, download_images=True):
        """
        코이세이오 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("COYSEIO", base_url)
        products_crawled = 0
        
        print(f"\n🔍 COYSEIO 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        name_span = name_elem.find('span', style=lambda x: x and 'font-size:12px' in str(x))
                        if name_span:
                            name = name_span.get_text(strip=True)
                        else:
                            name = name_elem.get_text(strip=True)
                        
                        # 가격 추출
                        price = 0
                        spec_elem = item.find('ul', class_='spec')
                        if spec_elem:
                            price_text = spec_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            for num in numbers:
                                parsed = int(num.replace(',', ''))
                                if parsed > 1000:
                                    price = parsed
                                    break
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='thumb_Img') or item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        if link_elem:
                            href = link_elem['href']
                            if href.startswith('/'):
                                product_url = base_url + href
                            else:
                                product_url = href
                        else:
                            product_url = ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/coyseio")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ COYSEIO 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_siyazu(self, base_url="https://m.siyazu.co.kr", cate_no=43, max_pages=50, download_images=True):
        """
        시아쥬 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("SIYAZU", base_url)
        products_crawled = 0
        
        print(f"\n🔍 SIYAZU 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('div', class_='mun-prd-list-cover')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('div', class_='name')
                        if not name_elem:
                            continue
                        name_link = name_elem.find('a')
                        name = name_link.get_text(strip=True) if name_link else name_elem.get_text(strip=True)
                        if not name:
                            continue
                        
                        # 가격 추출 (할인가 우선)
                        price = 0
                        original_price = 0
                        
                        # 할인가
                        sale_elem = item.find('li', class_='sale')
                        if sale_elem:
                            price_text = sale_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                price = int(numbers[0].replace(',', ''))
                        
                        # 원가
                        strike_elem = item.find('li', class_='strike')
                        if strike_elem:
                            price_text = strike_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                original_price = int(numbers[0].replace(',', ''))
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 및 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        if link_elem:
                            href = link_elem['href']
                            product_url = base_url + href if href.startswith('/') else href
                            match = re.search(r'/(\d+)/', href)
                            product_code = match.group(1) if match else name[:20]
                        else:
                            product_url = ''
                            product_code = name[:20]
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/siyazu")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ SIYAZU 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_raive(self, base_url="https://raivestudio.com", cate_no=210, max_pages=50, download_images=True):
        """
        레이브 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("RAIVE", base_url)
        products_crawled = 0
        
        print(f"\n🔍 RAIVE 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('p', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:13px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        spec_elem = item.find('ul', class_='spec')
                        if spec_elem:
                            li_elems = spec_elem.find_all('li')
                            for li in li_elems:
                                price_text = li.get_text()
                                numbers = re.findall(r'[\d,]+', price_text)
                                for num in numbers:
                                    parsed = int(num.replace(',', ''))
                                    if parsed > 1000:
                                        if original_price == 0:
                                            original_price = parsed
                                        else:
                                            price = parsed
                                        break
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='front') or item.find('img', class_='back')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/raive")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ RAIVE 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_sunburn(self, base_url="https://sunburnproject.com", cate_no=23, max_pages=50, download_images=True):
        """
        썬번프로젝트 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("SUNBURN PROJECT", base_url)
        products_crawled = 0
        
        print(f"\n🔍 SUNBURN PROJECT 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('div', class_='name')
                        if not name_elem:
                            continue
                        name_span = name_elem.find('span', style=lambda x: x and 'font-size:12px' in str(x))
                        name = name_span.get_text(strip=True) if name_span else name_elem.get_text(strip=True)
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        
                        # 할인가 (prd_price_sale)
                        sale_elem = item.find('li', class_='prd_price_sale')
                        if sale_elem:
                            price_text = sale_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                price = int(numbers[0].replace(',', ''))
                        
                        # 원가 (product_price)
                        orig_elem = item.find('li', class_='product_price')
                        if orig_elem:
                            price_text = orig_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                original_price = int(numbers[0].replace(',', ''))
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='thumb')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/sunburn")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ SUNBURN PROJECT 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_sculptor(self, base_url="https://sculptorpage.com", cate_no=779, max_pages=50, download_images=True):
        """
        스컬프터 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("SCULPTOR", base_url)
        products_crawled = 0
        
        print(f"\n🔍 SCULPTOR 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('a', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:11px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        spec_elem = item.find('ul', class_='xans-product-listitem')
                        if spec_elem:
                            li_elems = spec_elem.find_all('li')
                            for li in li_elems:
                                price_text = li.get_text()
                                numbers = re.findall(r'[\d,]+', price_text)
                                for num in numbers:
                                    parsed = int(num.replace(',', ''))
                                    if parsed > 1000:
                                        if original_price == 0:
                                            original_price = parsed
                                        else:
                                            price = parsed
                                        break
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', id=lambda x: x and 'eListPrdImage' in str(x)) or item.find('img', class_='big')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/sculptor")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ SCULPTOR 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_insilence(self, base_url="https://insilence.co.kr", cate_no=348, max_pages=50, download_images=True):
        """
        인사일런스 우먼 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("INSILENCE WOMEN", base_url)
        products_crawled = 0
        
        print(f"\n🔍 INSILENCE WOMEN 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', class_='item')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('a', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:12px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        
                        # 판매가 (original_price 클래스)
                        orig_elem = item.find('li', class_='original_price')
                        if orig_elem:
                            price_text = orig_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                price = int(numbers[0].replace(',', ''))
                        
                        # 소비자가 (sale_price 클래스)
                        sale_elem = item.find('li', class_='sale_price')
                        if sale_elem:
                            price_text = sale_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                original_price = int(numbers[0].replace(',', ''))
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='big')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 및 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        if link_elem:
                            href = link_elem['href']
                            product_url = base_url + href if href.startswith('/') else href
                            match = re.search(r'product_no=(\d+)', href)
                            product_code = match.group(1) if match else name[:20]
                        else:
                            product_url = ''
                            product_code = name[:20]
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/insilence")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ INSILENCE WOMEN 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_treemingbird(self, base_url="https://treemingbird.com", cate_no=214, max_pages=50, download_images=True):
        """
        트리밍버드 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("TREEMINGBIRD", base_url)
        products_crawled = 0
        
        print(f"\n🔍 TREEMINGBIRD 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', class_='mun-prd-list')
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('div', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:13px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        info_area = item.find('ul', class_='xans-product-listitem')
                        if info_area:
                            price_text = info_area.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            for num in numbers:
                                parsed = int(num.replace(',', ''))
                                if parsed > 1000:
                                    price = parsed
                                    break
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', class_='medium') or item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 및 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        if link_elem:
                            href = link_elem['href']
                            product_url = base_url + href if href.startswith('/') else href
                            match = re.search(r'product_no=(\d+)', href)
                            product_code = match.group(1) if match else name[:20]
                        else:
                            product_url = ''
                            product_code = name[:20]
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/treemingbird")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ TREEMINGBIRD 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_illigo(self, base_url="https://illigo.co.kr", cate_no=111, max_pages=50, download_images=True):
        """
        일리고 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("ILLIGO", base_url)
        products_crawled = 0
        
        print(f"\n🔍 ILLIGO 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:12px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        
                        # 판매가 (product_price)
                        price_elem = item.find('li', class_='product_price')
                        if price_elem:
                            price_text = price_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                price = int(numbers[0].replace(',', ''))
                        
                        # 소비자가 (product_custom)
                        orig_elem = item.find('li', class_='product_custom')
                        if orig_elem:
                            price_text = orig_elem.get_text()
                            numbers = re.findall(r'[\d,]+', price_text)
                            if numbers:
                                original_price = int(numbers[0].replace(',', ''))
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', id=lambda x: x and 'eListPrdImage' in str(x)) or item.find('img', class_='thumber_1')
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/illigo")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ ILLIGO 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def crawl_ason(self, base_url="https://ason.co.kr", cate_no=67, max_pages=50, download_images=True):
        """
        애즈온 크롤링 (카페24 기반)
        """
        brand_id = self.get_or_create_brand("ASON", base_url)
        products_crawled = 0
        
        print(f"\n🔍 ASON 크롤링 시작...")
        print(f"   URL: {base_url}/product/list.html?cate_no={cate_no}")
        if download_images:
            print(f"   📷 이미지 다운로드: ON")
        
        page = 1
        while page <= max_pages:
            url = f"{base_url}/product/list.html?cate_no={cate_no}&page={page}"
            print(f"\n📄 페이지 {page} 크롤링 중...")
            
            try:
                response = self.session.get(url, timeout=15)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                
                items = soup.find_all('li', id=lambda x: x and x.startswith('anchorBoxId_'))
                
                if not items:
                    print(f"   ⚠️ 상품을 찾을 수 없습니다. 크롤링 종료.")
                    break
                
                print(f"   📦 {len(items)}개 상품 발견")
                
                found_products = 0
                for item in items:
                    try:
                        # 상품명 추출
                        name_elem = item.find('strong', class_='name')
                        if not name_elem:
                            continue
                        all_spans = name_elem.find_all('span', style=lambda x: x and 'font-size:16px' in str(x))
                        name = None
                        for span in all_spans:
                            text = span.get_text(strip=True)
                            if text and text != '상품명':
                                name = text
                                break
                        if not name:
                            continue
                        
                        # 가격 추출
                        price = 0
                        original_price = 0
                        spec_elem = item.find('ul', class_='spec')
                        if spec_elem:
                            li_elems = spec_elem.find_all('li')
                            for li in li_elems:
                                price_text = li.get_text()
                                numbers = re.findall(r'[\d,]+', price_text)
                                for num in numbers:
                                    parsed = int(num.replace(',', ''))
                                    if parsed > 1000:
                                        if original_price == 0:
                                            original_price = parsed
                                        else:
                                            price = parsed
                                        break
                        
                        if price == 0:
                            price = original_price
                        if original_price == 0:
                            original_price = price
                        
                        # 이미지 URL 추출
                        img_elem = item.find('img', id=lambda x: x and 'eListPrdImage' in str(x))
                        if img_elem:
                            image_url = img_elem.get('src', '')
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                        else:
                            image_url = ''
                        
                        # 상품 코드 추출
                        item_id = item.get('id', '')
                        match = re.search(r'anchorBoxId_(\d+)', item_id)
                        product_code = match.group(1) if match else name[:20]
                        
                        # 상품 URL 추출
                        link_elem = item.find('a', href=lambda x: x and '/product/' in str(x))
                        product_url = base_url + link_elem['href'] if link_elem else ''
                        
                        product_data = {
                            'code': product_code,
                            'name': name,
                            'original_price': original_price,
                            'price': price,
                            'image_url': image_url,
                            'product_url': product_url,
                            'category': 'ALL'
                        }
                        
                        product_id = self.save_product(brand_id, product_data)
                        products_crawled += 1
                        found_products += 1
                        print(f"   ✅ {name[:35]}... - {price:,}원")
                        
                        if download_images and image_url and product_id:
                            local_path = self.download_image(image_url, save_dir="images/ason")
                            if local_path:
                                self.save_image_record(product_id, image_url, local_path)
                        
                    except Exception as e:
                        print(f"   ❌ 상품 파싱 실패: {e}")
                        continue
                
                if found_products == 0:
                    print(f"\n   📄 마지막 페이지 도달")
                    break
                
                page += 1
                time.sleep(1)
                
            except requests.RequestException as e:
                print(f"   ❌ 요청 실패: {e}")
                break
        
        print(f"\n✅ ASON 크롤링 완료! 총 {products_crawled}개 상품 수집")
        return products_crawled

    def get_stats(self):
        """데이터베이스 통계"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM brands')
        brand_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM products')
        product_count = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT b.name, COUNT(p.id) as cnt 
            FROM brands b 
            LEFT JOIN products p ON b.id = p.brand_id 
            GROUP BY b.id
        ''')
        brand_stats = cursor.fetchall()
        
        conn.close()
        
        print("\n📊 데이터베이스 통계")
        print(f"   브랜드 수: {brand_count}")
        print(f"   총 상품 수: {product_count}")
        print("\n   브랜드별 상품 수:")
        for name, cnt in brand_stats:
            print(f"   - {name}: {cnt}개")
    
    def export_for_embedding(self, output_path="products_for_embedding.json"):
        """임베딩용 데이터 내보내기"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                p.id, p.product_code, p.name, p.original_price, p.sale_price,
                p.image_url, p.product_url, p.category, b.name as brand_name
            FROM products p
            JOIN brands b ON p.brand_id = b.id
        ''')
        
        products = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 임베딩용 데이터 내보내기 완료: {output_path}")
        return products


def main():
    """메인 실행"""
    crawler = FashionCrawler(db_path="fashion_products.db")
    
    # ASURA 크롤링 (무한스크롤 - Selenium 필요)
    '''
    crawler.crawl_with_scroll(
        url="https://s2asuras2.com/1857907220",
        brand_name="ASURA",
        scroll_pause=2,
        max_scrolls=30,
        download_images=True
    )
    
    # MICHIKO LONDON 크롤링
    crawler.crawl_michiko(
        base_url="https://michiko-london.kr",
        cate_no=44,
        max_pages=50,
        download_images=True
    )
    
    # MISEKI SEOUL 크롤링
    crawler.crawl_miseki(
        base_url="https://misekiseoul.kr",
        cate_no=29,
        max_pages=50,
        download_images=True
    )
    
    # BOHEMIAN SEOUL 크롤링
    crawler.crawl_bohemseoul(
        base_url="https://bohemseo.com",
        cate_no=64,
        max_pages=50,
        download_images=True
    )
    
    # OHESHIO 크롤링
    crawler.crawl_oheshio(
        base_url="https://oheshio.com",
        cate_no=29,
        max_pages=50,
        download_images=True
    )
    
    # COYSEIO 크롤링
    crawler.crawl_coyseio(
        base_url="https://coyseio.com",
        cate_no=54,
        max_pages=50,
        download_images=True
    )
    
    # SIYAZU 크롤링
    crawler.crawl_siyazu(
        base_url="https://m.siyazu.co.kr",
        cate_no=43,
        max_pages=50,
        download_images=True
    )
    
    # RAIVE 크롤링
    crawler.crawl_raive(
        base_url="https://raivestudio.com",
        cate_no=210,
        max_pages=50,
        download_images=True
    )
    
    # SUNBURN PROJECT 크롤링
    crawler.crawl_sunburn(
        base_url="https://sunburnproject.com",
        cate_no=23,
        max_pages=50,
        download_images=True
    )
    
    # SCULPTOR 크롤링
    crawler.crawl_sculptor(
        base_url="https://sculptorpage.com",
        cate_no=779,
        max_pages=50,
        download_images=True
    )
    
    # INSILENCE WOMEN 크롤링
    crawler.crawl_insilence(
        base_url="https://insilence.co.kr",
        cate_no=348,
        max_pages=50,
        download_images=True
    )
    
    # TREEMINGBIRD 크롤링
    crawler.crawl_treemingbird(
        base_url="https://treemingbird.com",
        cate_no=214,
        max_pages=50,
        download_images=True
    )
    
    # ILLIGO 크롤링
    crawler.crawl_illigo(
        base_url="https://illigo.co.kr",
        cate_no=111,
        max_pages=50,
        download_images=True
    )
    
    # ASON 크롤링
    crawler.crawl_ason(
        base_url="https://ason.co.kr",
        cate_no=67,
        max_pages=50,
        download_images=True
    )
    '''
    # 통계 출력
    crawler.get_stats()
    
    # 임베딩용 데이터 내보내기
    crawler.export_for_embedding()


if __name__ == "__main__":
    main()