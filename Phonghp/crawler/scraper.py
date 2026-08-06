import asyncio
import json
import re
import urllib.parse
import cloakbrowser

# Biến toàn cục để tái sử dụng tài nguyên
_context = None

async def get_browser():
    global _context
    if _context is None:
        print("\n[SYSTEM] Khởi chạy CloakBrowser bằng phương thức launch_context_async...")
        try:
            _context = await cloakbrowser.launch_context_async(
                headless=True,
                viewport={'width': 1280, 'height': 720},
                locale="vi-VN",
                timezone_id="Asia/Ho_Chi_Minh"
            )
            print("✅ Khởi chạy CloakBrowser (Stealth Chromium) thành công!")
        except Exception as e:
            print(f"❌ Lỗi cấu hình cloakbrowser: {e}")
            raise e
    return _context

async def close_browser():
    global _context
    if _context is not None:
        try:
            await _context.close()
        except Exception as e:
            print(f"⚠️ Lỗi khi đóng CloakBrowser context: {e}")
        finally:
            _context = None

async def scrape_basic_info(url: str):
    url = urllib.parse.unquote(url) # Fix lỗi link mã hóa gây 400
    context = await get_browser()
    page = await context.new_page()
    await page.route("**/*.{png,jpg,jpeg,gif,css,woff,woff2,svg}", lambda route: route.abort())

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        
        data = await page.evaluate('''() => {
            const title = document.querySelector('.booknav2 h1 a')?.innerText || "";
            const author = document.querySelector('.booknav2 p a')?.innerText || "";
            const desc = document.querySelector('.navtxt')?.innerText || "";
            const cover = document.querySelector('.bookimg2 img')?.src || "";
            return { title_cn: title, author_cn: author, description_cn: desc, cover_url: cover };
        }''')
        return data
    except Exception as e:
        print(f"❌ Lỗi Playwright Info: {e}")
        return None
    finally:
        await page.close()

async def scrape_chapters(url: str):
    url = urllib.parse.unquote(url)
    context = await get_browser()
    page = await context.new_page()
    await page.route("**/*.{png,jpg,jpeg,gif,css,woff,woff2,svg}", lambda route: route.abort())

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1000)

        chapters = await page.evaluate('''() => {
            const selectors = '.catalog ul li a, .quanshu ul li a, .content ul li a';
            const items = Array.from(document.querySelectorAll(selectors));
            return items.map(item => ({ title_cn: item.innerText.trim(), url: item.href }));
        }''')
        
        # Nhận diện cả link /txt/ và /book/
        filtered = [c for c in chapters if ("/txt/" in c['url'] or "/book/" in c['url']) and c['title_cn']]
        
        unique_chapters = []
        seen_urls = set()
        for ch in filtered:
            if ch['url'] not in seen_urls:
                unique_chapters.append(ch)
                seen_urls.add(ch['url'])

        print(f"✅ Đã tìm thấy: {len(unique_chapters)} chương")
        return unique_chapters
    except Exception as e:
        print(f"❌ Lỗi Scrape Chapters: {e}")
        return []
    finally:
        await page.close()

async def scrape_chapter_content(url: str):
    url = urllib.parse.unquote(url).strip()
    context = await get_browser()
    page = await context.new_page()

    try:
        # Giả lập Referer để tránh bị 69shuba nghi ngờ bot cào
        await page.set_extra_http_headers({"Referer": "https://69shuba.cx"})
        
        # 1. Vào trang và đợi cho đến khi bắt đầu load (commit)
        await page.goto(url, wait_until="commit", timeout=30000)
        
        # 2. Quan trọng: Nghỉ 5 giây để Cloudflare nhả cho qua
        await asyncio.sleep(5) 
        
        # 3. Cuộn chuột nhẹ để giả lập người thật
        await page.mouse.wheel(0, 500)
        await asyncio.sleep(1) 
        
        # 4. Chờ đúng thẻ chứa nội dung truyện hiện ra
        await page.wait_for_selector(".txtnav", timeout=20000)

        content = await page.evaluate('''() => {
            const el = document.querySelector('.txtnav');
            if (!el) return null;
            // Xóa sạch quảng cáo, rác
            const targets = 'h1, .head, .bottom-ad, script, style, a, .top_ad, .p_ad';
            el.querySelectorAll(targets).forEach(item => item.remove());
            return el.innerText;
        }''')
        
        return content.strip() if content else None
    except Exception as e:
        # Chụp ảnh lỗi để soi xem nó hiện thông báo gì (Captcha hay Cloudflare)
        await page.screenshot(path="debug_logs/error_debug.png")
        print(f"❌ Lỗi Scrape Content: {str(e)}")
        return None
    finally:
        await page.close()
        
async def scrape_stv_basic_info(url: str):
    url = urllib.parse.unquote(url).strip()
    context = await get_browser()
    page = await context.new_page()
    try:
        # STV cần thời gian để render bản dịch JS
        await page.goto(url, wait_until="commit", timeout=60000)
        await page.wait_for_selector("#book_name2", timeout=20000)
        await asyncio.sleep(2) 

        return await page.evaluate('''() => {
            return { 
                title_vi: document.querySelector('#book_name2')?.innerText?.trim() || "", 
                author_vi: document.querySelector('h2')?.innerText?.trim() || "", 
                description_vi: document.querySelector('.textzoom')?.innerText?.trim() || "", 
                cover_url: document.querySelector('#thumb-prop')?.src || "" 
            };
        }''')
    except Exception as e:
        print(f"❌ Lỗi STV Info: {e}")
        return None
    finally:
        await page.close()

async def scrape_stv_chapters(url: str):
    url = urllib.parse.unquote(url).strip()
    print(f"🔍 Đang lấy danh sách chương từ STV: {url}")
    context = await get_browser()
    page = await context.new_page()
    
    # --- BƯỚC A: TẠO BIẾN ĐỂ HỨNG DỮ LIỆU ---
    api_raw_data = None
    
    async def handle_response(response):
        nonlocal api_raw_data
        # Nếu thấy gói tin có chứa 'getchapterlist' thì hốt luôn
        if "sajax=getchapterlist" in response.url:
            try:
                res_json = await response.json()
                api_raw_data = res_json.get("data")
            except:
                pass
            # Đăng ký lắng nghe sự kiện TRƯỚC KHI goto
    page.on("response", handle_response)

    try:
        await page.goto(url, wait_until="networkidle", timeout=60000)
        
        # Đợi một chút để API kịp trả về
        await asyncio.sleep(2)

        # --- BƯỚC B: ƯU TIÊN DÙNG DỮ LIỆU TỪ API ---
        if api_raw_data:
            print("✅ Đã bắt được ID chương từ API!")
            return parse_stv_data(api_raw_data, url)
    
        await page.wait_for_selector(".listchapitem", timeout=15000)
        
        return await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a.listchapitem'));
            return links.map(a => ({
                title_vi: a.innerText.trim(), 
                url: a.href
            })).filter(c => c.title_vi !== "");
        }''')
    except Exception as e:
        print(f"❌ Lỗi STV Chapters: {e}")
        return []
    finally:
        await page.close()
        
def parse_stv_data(raw_str, url):
    chapters = []
    items = raw_str.strip().split("-//-")
    for index, item in enumerate(items):
        if not item.strip(): continue
        parts = item.split("-/-")
        if len(parts) >= 3:
            c_id = parts[1].strip()
            title = parts[2].strip()
            chapters.append({
                "chapter_no": index + 1,
                "title_vi": title,
                "real_id": c_id,
                "url": f"{url}{c_id}/"
            })
    return chapters


async def scrape_stv_chapter_content(url: str):
    # 1. Trích xuất ID để đối chiếu (Chống lấy nhầm chương cũ)
    print(f"🚀 [START] Đang xử lý chương: {url}")
    url = urllib.parse.unquote(url).strip()
    path_parts = [p for p in url.split("/") if p]
    try:
        target_chap_id = path_parts[-1]
        source_type = path_parts[3]
    except:
        print(f"❌ [ERROR] Không thể trích xuất Chapter ID từ URL: {url}")
        return None

    print(f"🚀 [START] Đang xử lý chương: {target_chap_id}")
    
    # Lấy global context đang chạy thay vì khởi tạo một browser object cồng kềnh mới
    context = await get_browser()
    page = await context.new_page()

    captured_data = {"raw": None}

    # 3. Lắng nghe API sajax - Có lọc ID chương
    async def handle_response(response):
        res_url = response.url
        if "sajax=readchapter" in res_url:
            if target_chap_id in res_url:
                try:
                    text_res = await response.text()
                    start_idx = text_res.find('{"')
                    if start_idx != -1:
                        data_json = json.loads(text_res[start_idx:])
                        if data_json.get("code") == "0" and data_json.get("data"):
                            captured_data["raw"] = data_json["data"]
                            print(f"✅ [SUCCESS] Đã bắt đúng API chương {target_chap_id} ({len(data_json['data'])} ký tự)")
                except Exception as e:
                    print(f"⚠️ [API ERROR] Lỗi xử lý response: {e}")
            else:
                print(f"⏭️ [SKIP] Bỏ qua API không khớp ID: {res_url[-30:]}")

    page.on("response", handle_response)

    try:
        # Bước 1: Điều hướng
        print(f"Step 1: Điều hướng tới {url}")
        await page.goto(url, wait_until="commit", timeout=60000)
        
        
        # Bước 2: Đợi nạp script và kích hoạt API
        await asyncio.sleep(1.5)
        
        # Thử kích hoạt nạp bằng cách click hoặc cuộn chuột
        print("Step 2: Kích hoạt API bằng Click/Scroll...")
        try:
            await page.click("#content-container", timeout=2000)
        except:
            await page.mouse.wheel(0, 500)

        # Bước 3: Chờ dữ liệu đổ về (Tối đa 12 giây)
        found = False
        for i in range(40):
            if captured_data["raw"]:
                found = True
                break
            if i % 10 == 0:
                print(f"⏳ [WAITING] Đang đợi dữ liệu... ({i*0.3}s)")
            await asyncio.sleep(0.3)

        # Dự phòng: Click nút nạp nếu vẫn chưa thấy
        if not found:
            print("Step 3 (Dự phòng): Thử click nút nạp thủ công...")
            try:
                btn = page.get_by_text("Nhấp vào để tải chương")
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    for _ in range(20):
                        if captured_data["raw"]: 
                            found = True
                            break
                        await asyncio.sleep(0.3)
            except:
                pass

        if not found:
            print(f"❌ [TIMEOUT] Không bắt được dữ liệu cho chương {target_chap_id}")
            await page.screenshot(path=f"debug_logs/debug_{target_chap_id}_2_timeout.png")
            return None

        
        # Bước 4: Bóc tách nội dung
        print(f"Step 4: Đang trích xuất nội dung (Nguồn: {source_type})...")
        raw_data = captured_data["raw"]
        paragraphs = []

        if source_type == "sangtac":
            paragraphs = [line.strip() for line in raw_data.split('\n') if line.strip()]
        else:
            for section in raw_data.split('<p>'):
                words = re.findall(r'>([^<]+)</i>', section)
                if words:
                    line = " ".join(words).strip()
                    if line:
                        paragraphs.append(line)

        return "\n\n".join(paragraphs)

    except Exception as e:
        print(f"🔥 [CRASH] Lỗi Scraper: {str(e)}")
        await page.screenshot(path=f"debug_logs/debug_{target_chap_id}_crash.png")
        return None
    finally:
        page.remove_listener("response", handle_response)
        await page.close()
        print(f"🏁 [FINISHED] Giải phóng tài nguyên chương {target_chap_id}")
    
import datetime

async def scrape_qidian_ranking(
    category_id: str = "yuepiao", 
    chn_id: int = -1, 
    page: int = 1,
    year: str = None,
    month: str = None
):
    """
    Hàm cào dữ liệu xếp hạng Qidian - Sửa lỗi không tải được ở các lượt đầu.
    """
    now = datetime.datetime.now()
    final_year = year if year else now.strftime("%Y")
    final_month = month if month else now.strftime("%m")
    
    if len(final_month) == 1:
        final_month = f"0{final_month}"

    page_str = f"year{final_year}-month{final_month}-page{page}"

    if chn_id == -1:
        if category_id in ["signnewbook", "pubnewbook", "newauthor"]:
            url = f"https://www.qidian.com/rank/{category_id}/page/{page}/"
        else:
            url = f"https://www.qidian.com/rank/{category_id}/{page_str}/"
    else:
        if category_id in ["signnewbook", "pubnewbook", "newauthor"]:
            url = f"https://www.qidian.com/rank/{category_id}/page/{page}/chn{chn_id}/"
        else:
            url = f"https://www.qidian.com/rank/{category_id}/{page_str}/chn{chn_id}/"

    print(f"\n[DEBUG] 1. Khởi tạo tài nguyên an toàn cho URL mục tiêu: {url}")
    
    context = await get_browser()
    page_ctx = await context.new_page()
    
    # Giữ nguyên phần chặn tài nguyên rác để tối ưu băng thông
    await page_ctx.route(
        "**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf,eot,ico}", 
        lambda route: route.abort()
    )
    await page_ctx.route(
        lambda url: "analytics" in url or "hm.baidu.com" in url, 
        lambda route: route.abort()
    )

    try:
        print("[DEBUG] 2. Đang tải trang hỏa tốc (wait_until='commit')...")
        await page_ctx.goto(url, wait_until="commit", timeout=25000)
        
        print("[DEBUG] 3. Đang chờ Javascript dựng danh sách truyện (Tối đa 15s, xong sớm đi sớm)...")
        
        # SỬA Ở ĐÂY: Nhắm thẳng vào danh sách thẻ 'li' cụ thể bên trong ul để chắc chắn dữ liệu đã render xong
        # Đồng thời nâng timeout lên 15 giây để bù đắp cho những lần mạng lag, tránh bị fail oan.
        target_selector = '#book-img-text ul li, .rank-view-list ul li, .rank-body ul li'
        try:
            await page_ctx.wait_for_selector(target_selector, timeout=15000)
            print(" -> [OK] Cấu trúc truyện đã được render hoàn tất!")
        except Exception:
            print(" -> [FAIL] Quá thời gian chờ. JS không render được danh sách truyện hoặc bị Cloudflare chặn.")
            return []

        print("[DEBUG] 4. Bắt đầu chạy JavaScript thực thi bóc tách dữ liệu...")
        ranking_data = await page_ctx.evaluate('''() => {
            const listContainer = document.querySelector('#book-img-text ul') || document.querySelector('.rank-view-list ul');
            if (!listContainer) return [];

            const items = Array.from(listContainer.querySelectorAll('li'));
            
            return items.map((item, index) => {
                const info = item.querySelector('.book-mid-info');
                if (!info) return null;

                const titleAnchor = info.querySelector('h2 a');
                const authorLinks = Array.from(info.querySelectorAll('.author a'));
                
                const rawCoverUrl = item.querySelector('.book-img-box img')?.getAttribute('src') || "";
                const cover_url = rawCoverUrl.startsWith('//') ? `https:${rawCoverUrl}` : rawCoverUrl;

                return {
                    rank: index + 1,
                    title_cn: titleAnchor?.innerText?.trim() || "",
                    author_cn: info.querySelector('.author a.name')?.innerText?.trim() || "",
                    category_cn: authorLinks.length > 1 ? authorLinks[1]?.innerText?.trim() : "",
                    desc_cn: info.querySelector('.intro')?.innerText?.trim() || "",
                    source_url: titleAnchor?.href || "",
                    cover_url: cover_url
                };
            }).filter(book => book !== null && book.title_cn !== "");
        }''')
        
        print(f"[DEBUG] 5. Kết thúc xử lý. Trích xuất thành công {len(ranking_data)} truyện thô từ Qidian.")
        return ranking_data
        
    except Exception as e:
        print(f"❌ [CRITICAL] Lỗi phát sinh trong quá trình cào: {e}")
        return []
        
    finally:
        print("[DEBUG] 6. Đóng tab cô lập.")
        await page_ctx.close()