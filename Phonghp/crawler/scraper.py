import asyncio
import json
import html
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import cloakbrowser

load_dotenv()

# Biến toàn cục để tái sử dụng tài nguyên trong suốt 1 job crawl
_context = None
_browser_lock = asyncio.Lock()
PAGE_CLOSE_DELAY_SECONDS = 0
STV_CHAPTER_PAGE_CLOSE_DELAY_SECONDS = 10
STV_PROFILE_DIR = Path(__file__).resolve().parent / "browser_profiles" / "stv"


def is_stv_persistent_profile_enabled() -> bool:
    value = os.getenv("STV_PERSISTENT_BROWSER_ENABLED", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


async def get_browser(use_persistent: bool = False, user_data_dir: Optional[str] = None):
    global _context
    async with _browser_lock:
        prev_ctx_id = id(_context) if _context is not None else None
        logger = logging.getLogger(__name__)
        logger.info(f"[BROWSER] get_browser called. prev_ctx_id={prev_ctx_id}, use_persistent={use_persistent}")
        if use_persistent:
            profile_dir = user_data_dir or str(STV_PROFILE_DIR)
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            try:
                if _context is not None and not getattr(_context, "_is_persistent_profile", False):
                    logger.warning(f"[BROWSER] replacing non-persistent context before persistent launch. old_ctx_id={id(_context)}")
                    await _context.close()
                    _context = None

                if _context is None:
                    logger.info("\n[SYSTEM] Khởi chạy CloakBrowser bằng phương thức launch_persistent_context_async...")
                    _context = await cloakbrowser.launch_persistent_context_async(
                        profile_dir,
                        headless=True,
                        viewport={'width': 1280, 'height': 720},
                        locale="vi-VN",
                        timezone="Asia/Ho_Chi_Minh",
                        humanize=True,
                        geoip=False,
                    )
                    setattr(_context, "_is_persistent_profile", True)
                    logger.info(f"✅ Khởi chạy CloakBrowser persistent profile thành công! new_ctx_id={id(_context)}")
                else:
                    logger.info(f"[BROWSER] reuse existing persistent context. ctx_id={id(_context)}")
                return _context
            except Exception as e:
                logger.warning(f"⚠️ Persistent profile launch failed, falling back to legacy browser context: {e}")
                if _context is not None:
                    try:
                        await _context.close()
                    except Exception:
                        pass
                    _context = None

        if _context is None:
            try:
                import backend.logging_config as _lc
            except Exception:
                pass
            logger.info("\n[SYSTEM] Khởi chạy CloakBrowser bằng phương thức launch_context_async...")
            try:
                _context = await cloakbrowser.launch_context_async(
                    headless=True,
                    viewport={'width': 1280, 'height': 720},
                    locale="vi-VN",
                    timezone="Asia/Ho_Chi_Minh"
                )
                setattr(_context, "_is_persistent_profile", False)
                logger.info(f"✅ Khởi chạy CloakBrowser (Stealth Chromium) thành công! new_ctx_id={id(_context)}")
            except Exception as e:
                logger.exception(f"❌ Lỗi cấu hình cloakbrowser: {e}")
                raise e
        else:
            logger.info(f"[BROWSER] reuse existing legacy context. ctx_id={id(_context)}")
        return _context

async def close_browser():
    global _context
    logger = logging.getLogger(__name__)
    if _context is not None:
        ctx_id = id(_context)
        logger.warning(f"[BROWSER] close_browser called. ctx_id={ctx_id}")
        try:
            await _context.close()
        except Exception as e:
            logger.exception(f"⚠️ Lỗi khi đóng CloakBrowser context: {e}")
        finally:
            _context = None
            logger.warning("[BROWSER] context set to None after close")
    else:
        logger.warning("[BROWSER] close_browser called but _context is None")

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
        logging.getLogger(__name__).exception(f"❌ Lỗi Playwright Info: {e}")
        return None
    finally:
        await asyncio.sleep(PAGE_CLOSE_DELAY_SECONDS)
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

        logging.getLogger(__name__).info(f"✅ Đã tìm thấy: {len(unique_chapters)} chương")
        return unique_chapters
    except Exception as e:
        logging.getLogger(__name__).exception(f"❌ Lỗi Scrape Chapters: {e}")
        return []
    finally:
        await asyncio.sleep(PAGE_CLOSE_DELAY_SECONDS)
        await page.close()

async def scrape_chapter_content(url: str):
    url = urllib.parse.unquote(url).strip()
    context = await get_browser()
    logger = logging.getLogger(__name__)
    logger.info(f"[PAGE] New page for scrape_stv_chapter_content. ctx_id={id(context)}")
    page = await context.new_page()
    logger.info(f"[PAGE] open page success. ctx_id={id(context)}, page_count={len(context.pages)}")

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
        logging.getLogger(__name__).exception(f"❌ Lỗi Scrape Content: {str(e)}")
        return None
    finally:
        await asyncio.sleep(2)
        await page.close()

async def scrape_stv_basic_info(url: str):
    url = urllib.parse.unquote(url).strip()
    context = await get_browser()
    page = await context.new_page()
    try:
        # STV metadata có thể có sẵn trong meta tags nên chỉ cần DOMContentLoaded là đủ.
        await page.goto(url, wait_until="domcontentloaded", timeout=120000)
        await asyncio.sleep(2)

        data = await page.evaluate('''() => {
            const getMeta = (selector) => document.querySelector(selector)?.content?.trim() || "";
            const title = getMeta('meta[property="og:novel:book_name"]') || getMeta('meta[property="og:title"]') || document.title || "";
            const author = getMeta('meta[property="og:novel:author"]') || "";
            const description = getMeta('meta[property="og:description"]') || getMeta('meta[name="description"]') || "";
            const cover = getMeta('meta[property="og:image"]') || getMeta('meta[itemprop="image"]') || "";
            return { title_vi: title, author_vi: author, description_vi: description, cover_url: cover };
        }''')

        if data and not data.get("title_vi"):
            return await page.evaluate('''() => {
                return {
                    title_vi: document.querySelector('#book_name2')?.innerText?.trim() || "",
                    author_vi: document.querySelector('h2')?.innerText?.trim() || "",
                    description_vi: document.querySelector('.textzoom')?.innerText?.trim() || "",
                    cover_url: document.querySelector('#thumb-prop')?.src || ""
                };
            }''')

        return data
    except Exception as e:
        logging.getLogger(__name__).exception(f"❌ Lỗi STV Info: {e}")
        return None
    finally:
        await asyncio.sleep(PAGE_CLOSE_DELAY_SECONDS)
        await page.close()

async def scrape_stv_chapters(url: str):
    url = urllib.parse.unquote(url).strip()
    logging.getLogger(__name__).info(f"🔍 Đang lấy danh sách chương từ STV: {url}")
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
            logging.getLogger(__name__).info("✅ Đã bắt được ID chương từ API!")
            return parse_stv_data(api_raw_data, url)
    
        await page.wait_for_selector(".listchapitem", timeout=15000)
        
        return await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a.listchapitem'));
            return links.map(a => ({
                title_vi: a.innerText.trim(),
                url: a.href,
                access: "regular"
            })).filter(c => c.title_vi !== "");
        }''')
    except Exception as e:
        screenshot_path = f"debug_logs/stv_chapters_error_{int(time.time())}.png"
        html_path = f"debug_logs/stv_chapters_error_{int(time.time())}.html"
        try:
            await page.screenshot(path=screenshot_path, timeout=120000, full_page=False)
            logging.getLogger(__name__).warning(f"❌ Đã chụp screenshot lỗi STV Chapters: {screenshot_path}")
        except Exception as screenshot_exc:
            logging.getLogger(__name__).warning(f"⚠️ Không chụp được screenshot lỗi STV Chapters: {screenshot_exc}")
            try:
                html_content = await page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                logging.getLogger(__name__).warning(f"📄 Đã lưu HTML lỗi STV Chapters: {html_path}")
            except Exception as html_exc:
                logging.getLogger(__name__).exception(f"⚠️ Không lưu được HTML lỗi STV Chapters: {html_exc}")
        logging.getLogger(__name__).exception(f"❌ Lỗi STV Chapters: {e}")
        return []
    finally:
        await asyncio.sleep(PAGE_CLOSE_DELAY_SECONDS)
        await page.close()
        
def parse_stv_data(raw_str, url):
    chapters = []
    items = [item.strip() for item in raw_str.strip().split("-//-") if item.strip()]
    for index, item in enumerate(items):
        text = item
        access = "regular"

        if text.lower().endswith("-/-vip"):
            access = "vip"
            text = text[: -len("-/-vip")].strip()
        elif text.lower().endswith("-/-unvip"):
            access = "unvip"
            text = text[: -len("-/-unvip")].strip()

        parts = re.split(r"-\\?/-", text, maxsplit=2)
        if len(parts) < 3:
            continue

        _, c_id, title = parts
        title = title.strip()
        if not c_id or not title:
            continue

        chapters.append({
            "chapter_no": index + 1,
            "title_vi": title,
            "real_id": c_id.strip(),
            "access": access,
            "url": f"{url}{c_id.strip()}/"
        })
    return chapters


async def get_stv_browser():
    """Use persistent profile for STV only when the config flag is enabled; otherwise keep the legacy browser flow."""
    if is_stv_persistent_profile_enabled():
        try:
            return await get_browser(use_persistent=True, user_data_dir=str(STV_PROFILE_DIR))
        except Exception:
            logging.getLogger(__name__).warning("⚠️ STV persistent browser failed; falling back to legacy browser context.")
    return await get_browser()


async def scrape_stv_chapter_content(url: str):
    # 1. Trích xuất ID để đối chiếu (Chống lấy nhầm chương cũ)
    logging.getLogger(__name__).info(f"🚀 [START] Đang xử lý chương: {url}")
    url = urllib.parse.unquote(url).strip()
    path_parts = [p for p in url.split("/") if p]
    try:
        target_chap_id = path_parts[-1]
        source_type = path_parts[3]
    except Exception as exc:
        logging.getLogger(__name__).exception(f"❌ [ERROR] Không thể trích xuất Chapter ID từ URL: {url} | error={exc}")
        return None

    logging.getLogger(__name__).info(f"🚀 [START] Chapter ID={target_chap_id}, source_type={source_type}")

    # Giữ nguyên logic scrape cũ, chỉ thử persistent profile ở STV và fallback về legacy nếu cần.
    context = await get_stv_browser()
    page = await context.new_page()

    captured_data = {"raw": None, "responses": []}

    # 3. Lắng nghe API sajax - Có lọc ID chương
    async def handle_response(response):
        res_url = response.url
        if "sajax=readchapter" in res_url:
            captured_data["responses"].append(res_url)
            logging.getLogger(__name__).debug(f"🔔 [RESPONSE] readchapter URL: {res_url}")
            try:
                text_res = await response.text()
            except Exception as exc:
                logging.getLogger(__name__).exception(f"⚠️ [API ERROR] Không đọc được response text cho {res_url}: {exc}")
                return

            if target_chap_id in res_url:
                start_idx = text_res.find('{"')
                if start_idx == -1:
                    logging.getLogger(__name__).warning(f"⚠️ [API PARSE] Không tìm thấy JSON bắt đầu trong response cho {res_url}")
                    logging.getLogger(__name__).debug(f"[API PARSE] Response snippet: {text_res[:200]!r}")
                    return

                try:
                    data_json = json.loads(text_res[start_idx:])
                except Exception as exc:
                    logging.getLogger(__name__).exception(f"⚠️ [API ERROR] JSON decode failed cho {res_url}: {exc}")
                    logging.getLogger(__name__).debug(f"[API ERROR] Response snippet: {text_res[:200]!r}")
                    return

                if data_json.get("code") == "0" and data_json.get("data"):
                    captured_data["raw"] = data_json["data"]
                    logging.getLogger(__name__).info(
                        f"✅ [SUCCESS] Đã bắt đúng API chương {target_chap_id} | length={len(data_json['data'])} | url={res_url}"
                    )
                else:
                    logging.getLogger(__name__).warning(
                        f"⚠️ [API DATA] API trả về code={data_json.get('code')} hoặc không có data | url={res_url}"
                    )
                    logging.getLogger(__name__).debug(f"[API DATA] JSON payload: {data_json}")
            else:
                logging.getLogger(__name__).debug(f"⏭️ [SKIP] Bỏ qua API không khớp ID: {res_url}")

    page.on("response", handle_response)

    try:
        logging.getLogger(__name__).debug(f"Step 1: Điều hướng tới {url}")
        await page.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf,eot,ico}", lambda route: route.abort())
        await page.route(
            lambda request_url: any(
                blocked in request_url
                for blocked in ["analytics", "hm.baidu.com", "google-analytics", "googletagmanager", "doubleclick", "adservice", "ads", "tracking"]
            ),
            lambda route: route.abort(),
        )
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        logging.getLogger(__name__).debug(f"Step 1: Page loaded at {page.url}")

        logging.getLogger(__name__).debug("Step 2: Đợi nạp script và kích hoạt API")
        await asyncio.sleep(1.5)

        logging.getLogger(__name__).debug("Step 3: Thử kích hoạt API bằng Click/Scroll...")
        try:
            await page.click("#content-container", timeout=2000)
            logging.getLogger(__name__).debug("Step 3: Click vào #content-container thành công")
        except Exception as exc:
            logging.getLogger(__name__).debug(f"Step 3: Click thất bại ({exc}), sẽ thử cuộn chuột")
            await page.mouse.wheel(0, 500)

        found = False
        for i in range(40):
            if captured_data["raw"]:
                found = True
                logging.getLogger(__name__).debug(f"Step 4: Captured raw data sau {i+1} vòng lặp")
                break
            if i % 10 == 0:
                logging.getLogger(__name__).debug(f"⏳ [WAITING] Đang đợi dữ liệu... ({i*0.3}s)")
            await asyncio.sleep(0.3)

        if not found:
            logging.getLogger(__name__).debug("Step 5: Dự phòng click nút nếu chưa thấy dữ liệu")
            try:
                btn = page.get_by_text("Nhấp vào để tải chương")
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    logging.getLogger(__name__).debug("Step 5: Click nút tải chương thành công")
                    for _ in range(20):
                        if captured_data["raw"]:
                            found = True
                            logging.getLogger(__name__).debug("Step 5: Captured raw data sau click nút tải chương")
                            break
                        await asyncio.sleep(0.3)
                else:
                    logging.getLogger(__name__).debug("Step 5: Nút tải chương không hiển thị")
            except Exception as exc:
                logging.getLogger(__name__).debug(f"Step 5: Không tìm thấy hoặc click nút tải chương được ({exc})")

        if not found:
            logging.getLogger(__name__).warning(f"❌ [TIMEOUT] Không bắt được dữ liệu cho chương {target_chap_id}")
            screenshot_path = f"debug_logs/debug_{target_chap_id}_2_timeout.png"
            await page.screenshot(path=screenshot_path)
            logging.getLogger(__name__).warning(f"❌ [TIMEOUT] Đã chụp screenshot: {screenshot_path}")
            return None

        logging.getLogger(__name__).debug(f"Step 6: Bóc tách nội dung (Nguồn: {source_type})...")
        raw_data = captured_data["raw"]
        logging.getLogger(__name__).debug(f"Step 6: raw_data length={len(raw_data)} | snippet={raw_data[:200]!r}")

        text = normalize_stv_chapter_data(raw_data)
        paragraphs = [line.strip() for line in text.split('\n') if line.strip()]
        logging.getLogger(__name__).info(f"✅ [RESULT] Trích xuất xong {len(paragraphs)} đoạn từ chương {target_chap_id}")
        return "\n".join(paragraphs)

    except Exception as e:
        logging.getLogger(__name__).exception(f"🔥 [CRASH] Lỗi Scraper: {str(e)}")
        screenshot_path = f"debug_logs/debug_{target_chap_id}_crash_{int(time.time())}.png"
        html_path = f"debug_logs/debug_{target_chap_id}_crash_{int(time.time())}.html"
        try:
            await page.screenshot(path=screenshot_path, timeout=120000, full_page=False)
            logging.getLogger(__name__).warning(f"🔥 [CRASH] Đã chụp screenshot: {screenshot_path}")
        except Exception as screenshot_exc:
            logging.getLogger(__name__).warning(f"⚠️ Không chụp được screenshot crash: {screenshot_exc}")
            try:
                html_content = await page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                logging.getLogger(__name__).warning(f"📄 Đã lưu HTML crash: {html_path}")
            except Exception as html_exc:
                logging.getLogger(__name__).exception(f"⚠️ Không lưu được HTML crash: {html_exc}")
        return None
    finally:
        logger = logging.getLogger(__name__)
        page.remove_listener("response", handle_response)
        logger.info(f"[PAGE] closing page for STV chapter. ctx_id={id(context)}, page_count_before_close={len(context.pages)}")
        await asyncio.sleep(STV_CHAPTER_PAGE_CLOSE_DELAY_SECONDS)
        await page.close()
        logger.info(f"[PAGE] page closed for STV chapter. ctx_id={id(context)}, page_count_after_close={len(context.pages)}")
        logging.getLogger(__name__).info(f"🏁 [FINISHED] Giải phóng tài nguyên chương {target_chap_id}")
    
import datetime


def normalize_stv_chapter_data(raw_data: Optional[str]) -> str:
    """Normalize STV chapter payloads that can contain either plain HTML or inline XML/HTML wrappers.

    Both variants start with a string that includes nested <i> tags and sometimes literal XML declaration
    fragments. We need to convert them to readable text without leaving behind HTML tags, escaped XML,
    or the saved-notice banner.
    """
    if not raw_data:
        return ""

    text = str(raw_data)
    text = html.unescape(text)

    text = re.sub(r'@?Bạn đang đọc bản lưu trong hệ thống', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*<\?xml[^>]*>\s*', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*<html[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*</html\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*<head[^>]*>.*?</head\s*>', '\n', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\s*<body[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*</body\s*>', '\n', text, flags=re.IGNORECASE)

    text = re.sub(r'<i\b[^>]*>(.*?)</i>', lambda m: m.group(1), text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'</?p\b[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?span\b[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)

    text = text.replace("\r", "\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)


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

    logging.getLogger(__name__).debug(f"\n[DEBUG] 1. Khởi tạo tài nguyên an toàn cho URL mục tiêu: {url}")
    
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
        logging.getLogger(__name__).debug("[DEBUG] 2. Đang tải trang hỏa tốc (wait_until='commit')...")
        await page_ctx.goto(url, wait_until="commit", timeout=25000)
        
        logging.getLogger(__name__).debug("[DEBUG] 3. Đang chờ Javascript dựng danh sách truyện (Tối đa 15s, xong sớm đi sớm)...")
        
        # SỬA Ở ĐÂY: Nhắm thẳng vào danh sách thẻ 'li' cụ thể bên trong ul để chắc chắn dữ liệu đã render xong
        # Đồng thời nâng timeout lên 15 giây để bù đắp cho những lần mạng lag, tránh bị fail oan.
        target_selector = '#book-img-text ul li, .rank-view-list ul li, .rank-body ul li'
        try:
            await page_ctx.wait_for_selector(target_selector, timeout=15000)
            logging.getLogger(__name__).debug(" -> [OK] Cấu trúc truyện đã được render hoàn tất!")
        except Exception:
            logging.getLogger(__name__).warning(" -> [FAIL] Quá thời gian chờ. JS không render được danh sách truyện hoặc bị Cloudflare chặn.")
            return []

        logging.getLogger(__name__).debug("[DEBUG] 4. Bắt đầu chạy JavaScript thực thi bóc tách dữ liệu...")
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
        
        logging.getLogger(__name__).debug(f"[DEBUG] 5. Kết thúc xử lý. Trích xuất thành công {len(ranking_data)} truyện thô từ Qidian.")
        return ranking_data
        
    except Exception as e:
        logging.getLogger(__name__).exception(f"❌ [CRITICAL] Lỗi phát sinh trong quá trình cào: {e}")
        return []
        
    finally:
        logging.getLogger(__name__).debug("[DEBUG] 6. Đóng tab cô lập.")
        await page_ctx.close()