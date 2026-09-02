import json
import re
import time
import hashlib
import logging
from typing import Optional, Dict, Any, List, Tuple

from modules.blogger.ai_manager import AIClient, AIKeyManager, AllProvidersExhausted as AllKeysExhausted
from modules.blogger.prompts import (
    SYSTEM_REWRITE,
    SYSTEM_EXTRACT,
    SYSTEM_SEO,
    SYSTEM_HASHTAGS,
    SYSTEM_ALT_IMAGE,
    SYSTEM_SUMMARY,
    SYSTEM_NOTES,
    SYSTEM_KEYWORDS,
    SYSTEM_METADATA,
    make_rewrite_prompt,
    make_extract_prompt,
    make_seo_prompt,
    make_hashtag_prompt,
    make_summary_prompt,
    make_notes_prompt,
    make_keywords_prompt,
    make_metadata_prompt,
)
from modules.blogger.database import BloggerDatabase
from core.content_pipeline import ContentGate
from modules.blogger.prompts import SYSTEM_ARTICLE_PACKAGE, make_article_package_prompt

logger = logging.getLogger(__name__)

SECTION_ICONS = {
    "نبذة": "ℹ️", "تفاصيل": "📋", "بيئة": "🏢", "المهام": "📌",
    "مؤهلات": "🎓", "شروط": "📄", "تقديم": "📝", "مميزات": "⭐",
    "أسئلة": "❓", "خلاصة": "✅", "تعليمات": "📋", "ملاحظات": "⚠️",
    "طريقة": "📝", "شواغر": "👥", "راتب": "💰", "دوام": "🕐",
}


class ArticleProcessor:
    def __init__(self, db: BloggerDatabase, ai_client: AIClient, config=None, runtime=None, section: str = "blogger"):
        self.db = db
        self.gemini = ai_client
        self.config = config
        self.gate = ContentGate(db)
        self.runtime = runtime
        self.section = section

    MAX_PENDING_ATTEMPTS = 5

    async def process_raw_post(self, raw_text: str, source_url: str = "", media: List[Dict] = None, channel_id: str = "") -> Optional[Dict]:
        """Immediate/manual processing path (e.g. UI 'preview now' button).
        Attempts Gemini processing right away. NOT used by the automatic channel
        polling flow — that flow uses enqueue_raw_post() instead so that message
        ingestion never depends on Gemini availability."""
        raw_text = raw_text.strip()
        if not raw_text:
            return None

        gate = self.gate.preflight(raw_text, source_url, channel_id)
        if not gate.allowed:
            logger.info("Article rejected before AI: reason=%s matched=%s", gate.reason, gate.matched)
            return None
        return await self._process_fresh(raw_text, source_url, media, gate.fingerprint, channel_id)

    def enqueue_raw_post(self, raw_text: str, source_url: str = "", media: List[Dict] = None,
                          channel_id: str = "", section: str = "") -> Optional[str]:
        """Save an incoming raw post straight to the Gemini pending queue, WITHOUT ever
        calling Gemini. This is the entry point used by the automatic channel-polling
        scheduler, so that ingesting new posts never fails or blocks because of a
        Gemini cooldown/quota issue. Returns the fingerprint if newly queued,
        None if it's a duplicate or already being handled."""
        raw_text = raw_text.strip()
        if not raw_text:
            return None

        if self.runtime is not None:
            result = self.runtime.ingest(
                self.section or section or "blogger", raw_text,
                article_id=f"{channel_id}:{source_url or hashlib.md5(raw_text.encode('utf-8', errors='replace')).hexdigest()}",
                source="telegram" if channel_id else "legacy", source_url=source_url,
                channel_id=channel_id, target=self.section or section or "blogger",
                metadata={"media": media or [], "legacy_section": section},
            )
            if result.status != "queued":
                logger.info("Article rejected by RuntimeIntegration: reason=%s", result.reason)
                return None
            return result.fingerprint
        gate = self.gate.preflight(raw_text, source_url, channel_id)
        if not gate.allowed:
            logger.info("Article rejected at ingestion before AI: reason=%s matched=%s", gate.reason, gate.matched)
            return None
        fingerprint = gate.fingerprint
        self._save_to_pending(raw_text, source_url, media, fingerprint, channel_id, section)
        return fingerprint

    def _save_to_pending(self, raw_text: str, source_url: str, media: List[Dict], fingerprint: str,
                          channel_id: str = "", section: str = ""):
        article = {
            "fingerprint": fingerprint,
            "source_text": raw_text,
            "source_url": source_url,
            "media": media or [],
            "channel_id": channel_id,
            "status": "gemini_pending",
            "created_at": int(time.time()),
        }
        self._save_article(article)
        self.db.add_to_gemini_pending(raw_text, source_url, media, fingerprint, channel_id, section)

    def _handle_processing_failure(self, fingerprint: str, raw_text: str, source_url: str,
                                    media: List[Dict], channel_id: str, error: Exception,
                                    article: Dict, section: str = ""):
        """Called whenever an unexpected error occurs while processing an article
        (fresh or from the pending queue). Keeps the article retry-able in the
        pending queue instead of losing it, up to MAX_PENDING_ATTEMPTS."""
        attempts = self.db.increment_pending_attempts(fingerprint)
        if attempts == -1:
            # Wasn't in the pending queue yet (e.g. failed during the "fresh" path) — add it.
            self.db.add_to_gemini_pending(raw_text, source_url, media, fingerprint, channel_id, section)
            attempts = self.db.increment_pending_attempts(fingerprint)
            if attempts == -1:
                attempts = 1
        if attempts >= self.MAX_PENDING_ATTEMPTS:
            logger.error(
                f"Article {fingerprint[:16]} failed {attempts} times, giving up permanently: {error}"
            )
            article["status"] = "failed_permanent"
            article["error"] = str(error)
            self._save_article(article)
            self.db.remove_pending_by_fingerprint(fingerprint)
        else:
            eta = self.db.set_pending_retry_after(fingerprint, attempts)
            logger.warning(
                f"Article {fingerprint[:16]} processing failed (attempt {attempts}/{self.MAX_PENDING_ATTEMPTS}), "
                f"kept in pending queue, retry in {eta}s: {error}"
            )
            article["status"] = "gemini_pending"
            article["error"] = str(error)
            self._save_article(article)

    async def _process_fresh(self, raw_text: str, source_url: str, media: List[Dict], fingerprint: str, channel_id: str = "", section: str = "") -> Optional[Dict]:
        article = {
            "fingerprint": fingerprint,
            "source_text": raw_text,
            "source_url": source_url,
            "media": media or [],
            "channel_id": channel_id,
            "status": "processing",
            "created_at": int(time.time()),
        }
        try:
            session_ok = await self.gemini.acquire_session()
            if not session_ok:
                logger.warning(f"Gemini session failed for {fingerprint[:16]}, saving to pending")
                article["status"] = "gemini_pending"
                self._save_article(article)
                self.db.add_to_gemini_pending(raw_text, source_url, media, fingerprint, channel_id, section)
                return None

            result = await self._run_pipeline(article, raw_text, source_url, media)
            return result
        except AllKeysExhausted:
            logger.warning(f"All Gemini keys exhausted processing {fingerprint[:16]}, saving to pending")
            article["status"] = "gemini_pending"
            self._save_article(article)
            self.db.add_to_gemini_pending(raw_text, source_url, media, fingerprint, channel_id, section)
            return None
        except Exception as e:
            logger.exception(f"Article processing failed: {e}")
            self._handle_processing_failure(fingerprint, raw_text, source_url, media, channel_id, e, article, section)
            return None
        finally:
            self.gemini.release_session()

    async def _process_next_pending(self) -> Optional[Dict]:
        """Try to process the next retry-ready item in the Gemini pending queue (FIFO).
        Items still in exponential backoff are skipped so one blocked article does
        not stall the rest of the queue. Returns the processed article if successful,
        None otherwise."""
        pending = self.db.get_gemini_pending_queue()
        if not pending:
            return None
        now = time.time()
        first = None
        first_idx = 0
        for idx, item in enumerate(pending):
            retry_after = item.get("retry_after", 0)
            if retry_after and now < retry_after:
                continue
            first = item
            first_idx = idx
            break
        if first is None:
            logger.info("Gemini pending queue: all items in backoff, deferring")
            return None
        raw_text = first.get("raw_text", "").strip()
        fingerprint = first.get("fingerprint", "")
        if not raw_text:
            if fingerprint:
                self.db.remove_pending_by_fingerprint(fingerprint)
            else:
                self.db.remove_from_gemini_pending(first_idx)
            return None
        source_url = first.get("source_url", "")
        media = first.get("media", [])
        channel_id = first.get("channel_id", "")
        pending_section = first.get("section", "")
        if not fingerprint:
            fingerprint = self._fingerprint(raw_text, source_url)

        if self.db.is_published(fingerprint):
            self.db.remove_pending_by_fingerprint(fingerprint)
            return None

        article = {
            "fingerprint": fingerprint,
            "source_text": raw_text,
            "source_url": source_url,
            "media": media,
            "channel_id": channel_id,
            "status": "processing",
            "created_at": int(time.time()),
        }
        try:
            session_ok = await self.gemini.acquire_session()
            if not session_ok:
                self._handle_processing_failure(
                    fingerprint, raw_text, source_url, media, channel_id,
                    AllKeysExhausted("No AI provider available"), article
                )
                return None

            result = await self._run_pipeline(article, raw_text, source_url, media)
            if result:
                result["channel_id"] = channel_id
                if pending_section and not result.get("section"):
                    result["section"] = pending_section
                self.db.remove_pending_by_fingerprint(fingerprint)
                logger.info(f"Gemini pending queue: recovered article {fingerprint[:16]}")
            return result
        except AllKeysExhausted as e:
            self._handle_processing_failure(
                fingerprint, raw_text, source_url, media, channel_id, e, article
            )
            return None
        except Exception as e:
            logger.exception(f"Pending recovery failed for {fingerprint[:16]}: {e}")
            # Keep the item in pending (up to MAX_PENDING_ATTEMPTS) instead of losing it.
            self._handle_processing_failure(fingerprint, raw_text, source_url, media, channel_id, e, article)
            return None
        finally:
            self.gemini.release_session()

    async def _run_pipeline(self, article: Dict, raw_text: str, source_url: str = "", media: List[Dict] = None) -> Optional[Dict]:
        """Execute the full Gemini pipeline on raw_text and populate article dict."""
        clean_text = self._clean_source_footer(raw_text)
        # One AI request for the whole article package.
        package = await self.gemini.generate_json(
            make_article_package_prompt(clean_text, bool(media)),
            SYSTEM_ARTICLE_PACKAGE,
        )
        if not package or "raw" in package:
            raise RuntimeError("AI returned invalid article package JSON")
        article.update({k: v for k, v in package.items() if v is not None})
        article["labels"] = (package.get("seo") or {}).get("labels", [])
        article["reading_time"] = self._reading_time(article.get("body", clean_text))
        # Never let AI rewrite bypass the same content safety gates.
        post = self.gate.postflight(article, article.get("channel_id", ""))
        if not post.allowed:
            article["status"] = "discarded"
            article["discard_reason"] = post.reason
            article["matched_blocked_words"] = list(post.matched)
            self._save_article(article)
            logger.warning("AI output discarded by postflight: %s %s", post.reason, post.matched)
            return None
        article["status"] = "processed"
        article["processed_at"] = int(time.time())
        self._save_article(article)
        return article

    @staticmethod
    def _clean_source_footer(text: str) -> str:
        """Remove source-channel footer/signature lines before contact extraction."""
        if not text:
            return ""
        kept = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            low = line.lower()
            if re.search(r'(?:t\.me/|telegram\.me/|tlgrm\.me/)', low):
                continue
            if re.match(r'^@[\w.]+$', line):
                continue
            if re.search(r'castlejob|castle\s*job|قلعة الوظائف', low):
                continue
            if re.search(r'telegram|تلغرام|تيليجرام|تلجرام', low):
                continue
            if re.search(r'تابعونا|تتابعنا|متابعتنا|متابعة القناة|المزيد من الوظائف|للمزيد من الوظائف|للمزيد من الفرص|اشترك بالقناة|انضم للقناة|قناتنا|قناة الوظائف|follow us|join telegram|subscribe', low):
                continue
            kept.append(raw)
        return "\n".join(kept).strip()

    def _fingerprint(self, text: str, url: str = "") -> str:
        raw = f"{url}|{text[:300]}"
        return hashlib.md5(raw.encode("utf-8", errors="replace")).hexdigest()

    def _save_article(self, article: Dict):
        aid = article.get("fingerprint", str(int(time.time())))
        self.db.save_article(aid, article)

    async def _rewrite(self, text: str) -> Optional[Dict]:
        prompt = make_rewrite_prompt(text)
        result = await self.gemini.generate_json(prompt, SYSTEM_REWRITE)
        if not result:
            logger.warning("Gemini _rewrite returned no result")
            return None
        logger.info("Gemini _rewrite succeeded")
        return {
            "title": result.get("title", text[:80]),
            "body": result.get("body", f"<p>{text}</p>"),
            "introduction": result.get("introduction", ""),
            "faq": result.get("faq", []),
            "conclusion": result.get("conclusion", ""),
            "gemini_used": True,
        }

    async def _extract(self, text: str) -> Optional[Dict]:
        prompt = make_extract_prompt(text)
        return await self.gemini.generate_json(prompt, SYSTEM_EXTRACT)

    async def _seo(self, title: str, body: str) -> Optional[Dict]:
        prompt = make_seo_prompt(title, body)
        return await self.gemini.generate_json(prompt, SYSTEM_SEO)

    async def _hashtags(self, extracted: Dict, title: str, body: str) -> Optional[List[str]]:
        prompt = make_hashtag_prompt(extracted, title, body)
        result = await self.gemini.generate_json(prompt, SYSTEM_HASHTAGS)
        if result and isinstance(result, dict):
            tags = result.get("hashtags", [])
            if isinstance(tags, list):
                logger.info(f"Hashtags Generated: {tags}")
                return tags
            logger.warning(f"Hashtags Generated but 'hashtags' key is not list: {type(tags)}")
        else:
            logger.warning(f"Hashtags Generated: AI returned invalid data: {result}")
        return []

    async def _alt_text(self, title: str, body: str) -> Optional[Dict]:
        prompt = f"""أنشئ وصف ALT وتعليق للصورة بناءً على:
العنوان: {title}
المحتوى: {body[:500]}
الرد JSON فقط: {{"alt": "...", "caption": "..."}}"""
        return await self.gemini.generate_json(prompt, SYSTEM_ALT_IMAGE)

    # Legacy — labels now come from section settings in scheduler
    def _make_labels(self, extracted: Dict, seo: Dict) -> List[str]:
        labels = set()
        if extracted.get("type"):
            labels.add(extracted["type"])
        if extracted.get("ministry"):
            labels.add(extracted["ministry"])
        if extracted.get("province"):
            labels.add(extracted["province"])
        if extracted.get("city"):
            labels.add(extracted["city"])
        if extracted.get("company"):
            labels.add(extracted["company"])
        seo_labels = seo.get("labels", [])
        if isinstance(seo_labels, list):
            for lbl in seo_labels:
                if lbl:
                    labels.add(str(lbl))
        return list(labels)[:10]

    async def _summary(self, text: str) -> Optional[str]:
        prompt = make_summary_prompt(text)
        result = await self.gemini.generate_json(prompt, SYSTEM_SUMMARY)
        if result and isinstance(result, dict):
            return result.get("summary", "")
        return None

    async def _notes(self, extracted: Dict, title: str, body: str) -> Optional[List[str]]:
        prompt = make_notes_prompt(extracted, title, body)
        result = await self.gemini.generate_json(prompt, SYSTEM_NOTES)
        if result and isinstance(result, dict):
            notes = result.get("notes", [])
            if isinstance(notes, list) and notes:
                return notes
        return None

    async def _keywords(self, title: str, body: str, extracted: Dict) -> Optional[str]:
        prompt = make_keywords_prompt(title, body, extracted)
        result = await self.gemini.generate_json(prompt, SYSTEM_KEYWORDS)
        if result and isinstance(result, dict):
            kw = result.get("keywords", "")
            if kw and isinstance(kw, str):
                return kw
        return None

    async def _metadata(self, extracted: Dict, title: str, body: str) -> Optional[Dict]:
        prompt = make_metadata_prompt(extracted, title, body)
        result = await self.gemini.generate_json(prompt, SYSTEM_METADATA)
        if result and isinstance(result, dict):
            return result
        return None

    @staticmethod
    def _reading_time(body_html: str) -> int:
        text = re.sub(r'<[^>]+>', '', body_html)
        word_count = len(text.split())
        minutes = max(1, round(word_count / 150))
        return minutes

    def _add_inline_hashtags(self, body: str, extracted: Dict) -> str:
        entities = []
        if extracted.get("city"):
            entities.append(extracted["city"])
        if extracted.get("province"):
            entities.append(extracted["province"])
        if extracted.get("ministry"):
            entities.append(extracted["ministry"])
        if extracted.get("company"):
            entities.append(extracted["company"])
        if extracted.get("university"):
            entities.append(extracted["university"])
        if extracted.get("organization"):
            entities.append(extracted["organization"])
        if extracted.get("job_type"):
            entities.append(extracted["job_type"])
        if extracted.get("district"):
            entities.append(extracted["district"])
        result = body
        for entity in entities:
            if entity and len(entity) > 2:
                tag = entity.replace(" ", "_")
                replacement = f'<a href="https://www.blogger.com/search?q={tag}" style="text-decoration:none;color:#1a73e8;">#{tag}</a>'
                result = result.replace(entity, replacement, 1)
        return result

    def _article_css(self) -> str:
        return """<style>
html{scroll-behavior:smooth;}
.blog-article{font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:#2b3440;font-size:16px;line-height:1.9;direction:rtl;text-align:right;}
.blog-article h2,.blog-article h3,.blog-article h4{font-weight:bold!important;clear:both;color:#1a1a2e;line-height:1.6;}
.blog-article h2{font-size:19px;}
.blog-article h3{font-size:17px;}
.blog-article p{line-height:1.9;color:#374151;margin:8px 0;font-size:15px;}
.blog-article a{color:#1a73e8;text-decoration:none;}
.blog-article a:hover{text-decoration:underline;}
.blog-article img{max-width:100%;height:auto;}
table,.job-table{width:100%;border-collapse:separate;border-spacing:0;margin:16px 0;font-size:14px;direction:rtl;text-align:right;font-family:'Segoe UI',Tahoma,Arial,sans-serif;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(30,60,120,.06);}
table th,.job-table th{background:#1f3a5f;color:#fff;padding:11px 14px;border:1px solid #1f3a5f;text-align:right;font-weight:bold;font-size:14px;}
table td,.job-table td{padding:11px 14px;border:1px solid #e7ebf1;color:#2c3e50;vertical-align:top;line-height:1.7;font-size:14px;text-align:right;}
table tr:nth-child(even) td,.job-table tr:nth-child(even) td{background:#f6f8fb;}
table tr:hover td,.job-table tr:hover td{background:#eef4fb;}
.sec-card{background:#ffffff;border:1px solid #e6ebf2;border-radius:14px;padding:18px 20px;margin:16px 0;box-shadow:0 2px 8px rgba(30,60,120,.05);}
.sec-title{background:linear-gradient(135deg,#eef4ff,#fafcff)!important;color:#1a4f9e!important;border-right:4px solid #2f7cf6;padding:10px 14px;border-radius:10px;margin:0 0 12px 0!important;}
.summary-box{background:linear-gradient(135deg,#fffdf6,#fff6d6);border:1px solid #f3dca2;border-right:4px solid #f5b301;border-radius:12px;padding:14px 18px;margin:16px 0;}
.summary-box p{color:#6b5300!important;margin:8px 0 0 0;}
.notes-box{background:linear-gradient(135deg,#fff7f7,#ffecec);border:1px solid #f3cccc;border-right:4px solid #e74c4c;border-radius:12px;padding:14px 18px;margin:16px 0;}
.notes-box ul{color:#7f1d1d!important;margin:8px 0 0 0;padding-right:20px;}
.hashtag-box,.keywords-box{margin:16px 0;padding:14px 18px;background:#ffffff;border:1px solid #e6ebf2;border-radius:14px;box-shadow:0 1px 4px rgba(30,60,120,.05);}
.ht-wrap,.kw-wrap{text-align:center;margin-top:8px;}
.ht-chip{display:inline-block;background:linear-gradient(135deg,#e3f2fd,#d6ebff);color:#0d47a1;border:1px solid #90caf9;padding:4px 14px;margin:4px;border-radius:20px;font-size:13px;font-weight:bold;line-height:1.5;}
.kw-chip{display:inline-block;background:linear-gradient(135deg,#f4ecfd,#efe4ff);color:#6a1b9a;border:1px solid #d3b5f2;padding:4px 14px;margin:4px;border-radius:20px;font-size:13px;line-height:1.5;}
.tag{display:inline-block;background:#e3f2fd;color:#1565c0;padding:4px 12px;margin:3px 4px;border-radius:16px;font-size:13px;border:1px solid #90caf9;}
.sec-head{font-size:15px;font-weight:bold;margin-bottom:8px;display:block;}
.has-head{color:#0d47a1;}
.kw-head{color:#6a1b9a;}
.sum-head{color:#8a6d1a;}
.notes-head{color:#7f1d1d;}
.faq-card{background:#f8fbff;border:1px solid #d3e4fa;border-radius:14px;padding:16px 20px;margin:16px 0;}
.faq-h{color:#1a4f9e;margin:0 0 12px 0;}
.faq-q{font-size:16px;margin-top:15px;color:#1a1a2e;}
.faq-a p{color:#374151;}
.article-end{background:linear-gradient(135deg,#e8f4fd,#dff0ff);border:1px solid #b9dcf7;border-right:4px solid #1a73e8;border-radius:14px;padding:18px 22px;margin:22px 0;text-align:center;box-shadow:0 2px 8px rgba(26,80,232,.08);}
.article-end p{margin:0;font-size:16px;color:#0b3d66;line-height:1.9;}
.tg-card{background:linear-gradient(135deg,#e7f3ff,#dbefff);border:1px solid #a9d4f7;border-radius:16px;padding:18px;margin:20px 0;text-align:center;box-shadow:0 2px 10px rgba(26,112,232,.10);}
.tg-card-h{font-size:17px;font-weight:bold;color:#0b5fa5;margin-bottom:8px;}
.tg-card-p{font-size:14px;color:#2e4a70;margin:0 0 14px 0;line-height:1.9;}
.tg-card-btn{display:inline-block;background:linear-gradient(135deg,#1e8ff0,#1a73e8);color:#ffffff!important;padding:11px 26px;border-radius:26px;font-size:15px;font-weight:bold;text-decoration:none!important;box-shadow:0 2px 8px rgba(26,115,232,.35);}
.tg-card-btn:hover{opacity:.92;text-decoration:none!important;}
.apply-section{margin:18px 0;text-align:center;direction:rtl;}
.apply-box{display:block;margin:14px auto;max-width:520px;background:linear-gradient(135deg,#fffdf3,#fff6d6);border:1px solid #f2d47c;border-radius:14px;padding:18px 22px;text-align:right;box-shadow:0 3px 10px rgba(120,90,0,.10);}
.apply-box-title{font-size:17px;font-weight:bold;color:#7a5c00;margin-bottom:12px;text-align:center;border-bottom:1px dashed #f0d48a;padding-bottom:8px;}
.apply-row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:9px 0;border-bottom:1px solid #faf0ce;}
.apply-row:last-child{border-bottom:0;}
.apply-row-label{font-weight:bold;font-size:14px;color:#7a5c00;}
.apply-box-phone .apply-row-label{color:#6b5300;}
.apply-box-phone{color:#6b5300;}
.apply-box-value{font-size:18px;font-weight:bold;color:#8a5a00;direction:ltr;display:inline-block;word-break:break-all;text-decoration:none!important;background:#fffce8;border:1px solid #f0d48a;border-radius:8px;padding:5px 12px;}
.apply-box-value:hover{text-decoration:underline!important;}
.apply-box-phone .apply-box-value{color:#5a4400;font-size:22px;}
.apply-box-actions{margin-top:14px;text-align:center;}
.apply-btn{display:inline-block;padding:10px 28px;border-radius:24px;font-weight:bold;font-size:15px;margin:4px;text-decoration:none!important;color:#fff!important;box-shadow:0 2px 6px rgba(0,0,0,.14);transition:transform .12s,opacity .15s;}
.apply-btn:hover{opacity:.92;text-decoration:none!important;transform:translateY(-1px);}
.apply-btn-call{background:linear-gradient(135deg,#1a73e8,#1557b0);}
.apply-btn-whatsapp{background:linear-gradient(135deg,#25d366,#1da851);}
.apply-btn-cv{background:linear-gradient(135deg,#8e24aa,#6a1b9a);}
.apply-btn-now{background:linear-gradient(135deg,#ffb300,#f57c00);}
.article-title{font-size:26px;font-weight:bold!important;color:#1a1a2e;line-height:1.5;margin:6px 0 4px 0;}
@media (max-width:768px){
.blog-article{font-size:15px;}
.sec-card{padding:14px 14px;margin:12px 0;}
.apply-btn{padding:9px 20px;}
}
@media (max-width:600px){
.blog-article{font-size:14px;}
table,.job-table{font-size:13px;}
table th,table td,.job-table th,.job-table td{padding:8px 10px;}
.apply-box{width:92%;padding:14px 14px;}
.apply-box-value{font-size:17px;}
.apply-box-phone .apply-box-value{font-size:22px;}
.apply-btn{display:block;margin:6px auto;width:70%;}
.tg-card-btn{display:block;width:80%;margin:0 auto;}
}
</style>"""

    def make_article_html(self, article: Dict) -> str:
        parts = []
        parts.append(self._article_css())

        # ── 0. Article Title ──
        title = article.get("title", "").strip()
        if title:
            parts.append(f'<h1 class="article-title">{title}</h1>')

        # ── 1. Featured Image ──
        parts.append(self._make_featured_image(article))

        # ── 2. Summary Box ──
        summary = article.get("summary", "")
        if summary:
            parts.append(self._make_summary_box(summary))

        # ── 3. Introduction ──
        intro = article.get("introduction", "")
        if intro:
            parts.append(f'<div class="sec-card"><h2 id="intro">المقدمة</h2><p>{intro}</p></div>')

        # ── 4. Full Article Body (no TOC; sections rendered as cards) ──
        body_to_process = article.get("body", "")
        body_to_process = self._enhance_body_tables(body_to_process)
        body_to_process = self._inject_apply_into_body(article, body_to_process)
        body_to_process = self._wrap_sections(body_to_process)
        if body_to_process:
            parts.append(body_to_process)

        # ── 5.5 Contact box (current article's extracted data only, no fallback) ──
        extracted = article.get("extracted", {}) or {}
        emails = self._contact_values(extracted.get("email"))
        phones = self._contact_values(extracted.get("phone"))
        apply_url = str(extracted.get("apply_url") or "").strip()
        if apply_url and re.search(r'^https?://(?:t\.me|telegram\.me|tlgrm\.me)/|^@', apply_url, re.IGNORECASE):
            apply_url = ""
        if not re.match(r'^https?://', apply_url):
            apply_url = ""
        if emails or phones or apply_url:
            parts.append(self._make_apply_section_html(emails, phones, apply_url))

        # ── 6. Important Notes ──
        notes = article.get("notes", [])
        if notes:
            parts.append(self._make_notes_box(notes))

        # ── 7. FAQ ──
        faq = article.get("faq", [])
        if faq:
            parts.append(self._make_faq(faq))

        # ── 8. Conclusion (professional end card) ──
        conclusion = article.get("conclusion", "")
        if conclusion:
            parts.append(self._make_conclusion_box(conclusion))

        # ── 8.5 Telegram channel CTA (right before hashtags) ──
        parts.append(self._make_telegram_section())

        # ── 9. Hashtags ──
        hashtags = article.get("hashtags", [])
        logger.info(f"Hashtags Before HTML: {hashtags}")
        if hashtags:
            parts.append(self._make_hashtags_section(hashtags))

        # ── 10. Keywords ──
        keywords = article.get("keywords", "")
        if keywords:
            parts.append(self._make_keywords_section(keywords))

        # ── 12. Schema JSON-LD ──
        schema = self._make_schema(article)
        if schema:
            parts.append(schema)

        return '<div class="blog-article">\n' + "\n".join(parts) + '\n</div>'

    def _enhance_body_tables(self, body: str) -> str:
        if not body:
            return body
        def _replace(m):
            tag = m.group(0)
            if "class=" not in tag:
                return '<table class="job-table">'
            return tag
        return re.sub(r'<table[^>]*>', _replace, body)

    def _wrap_sections(self, body: str) -> str:
        """Wrap each h2 section of the body into a styled card (presentation only)."""
        if not body or "<h2" not in body:
            return body
        pieces = re.split(r'(?=<h2[^>]*>)', body)
        head = pieces[0]
        cards = []
        for piece in pieces[1:]:
            m = re.match(r'<h2([^>]*)>(.*?)</h2>(.*)$', piece, re.DOTALL)
            if not m:
                cards.append(piece)
                continue
            attrs, text, rest = m.group(1), m.group(2), m.group(3)
            icon = SECTION_ICONS.get(next((k for k in SECTION_ICONS if k in text), ""), "📌")
            if 'class="' in attrs:
                attrs = re.sub(r'class="([^"]*)"', r'class="sec-title \1"', attrs, count=1)
            else:
                attrs += ' class="sec-title"'
            cards.append(f'<div class="sec-card"><h2{attrs}>{icon} {text}</h2>{rest}</div>')
        return head + "".join(cards)

    def _make_conclusion_box(self, conclusion: str) -> str:
        return f'<div class="article-end"><p>📢 {conclusion}</p></div>'

    def _make_featured_image(self, article: Dict) -> str:
        alt_text = article.get("media_alt", {}).get("alt", "")
        caption = article.get("media_alt", {}).get("caption", "")
        img_src = None
        if self.config:
            img_src = self.config.get("default_jobs_image", "")
        if not img_src:
            return ""
        alt = alt_text or "صورة المقال"
        title = article.get("title", "")[:60]
        img = f'<p style="text-align:center;"><img src="{img_src}" alt="{alt}" title="{title}" loading="lazy" style="width:100%;max-width:100%;height:auto;border-radius:8px;" /></p>'
        if caption:
            img += f'<p style="text-align:center;font-size:13px;color:#666;margin-top:-10px;">{caption}</p>'
        return img

    def _make_summary_box(self, summary: str) -> str:
        return f'<div class="summary-box"><div class="sec-head sum-head">📌 ملخص المقال</div><p>{summary}</p></div>'

    @staticmethod
    def _is_iraqi_phone(clean_phone: str) -> bool:
        digits = re.sub(r'[^\d]', '', clean_phone)
        return digits.startswith("07") or digits.startswith("9647")

    @staticmethod
    def _to_whatsapp(clean_phone: str) -> str:
        digits = re.sub(r'[^\d]', '', clean_phone)
        if digits.startswith("964"):
            return digits
        if digits.startswith("0"):
            return "964" + digits[1:]
        return "964" + digits

    def _make_apply_section_html(self, emails: List[str], phones: List[str], apply_url: str) -> str:
        logger.info("Apply Builder Called")
        rows = ""
        actions = ""
        whatsapp_done = False
        for raw_phone in phones:
            clean_phone = self._valid_phone(raw_phone)
            if not clean_phone:
                continue
            rows += (f'<div class="apply-row"><span class="apply-row-label">📞 رقم الهاتف</span>'
                     f'<a class="apply-box-value" href="tel:{clean_phone}">{raw_phone}</a></div>')
            actions += f'<a class="apply-btn apply-btn-call" href="tel:{clean_phone}">📞 اتصال</a>'
            if not whatsapp_done and self._is_iraqi_phone(clean_phone):
                wa = self._to_whatsapp(clean_phone)
                actions += f'<a class="apply-btn apply-btn-whatsapp" href="https://wa.me/{wa}" target="_blank" rel="noopener">💬 واتساب</a>'
                whatsapp_done = True
        for raw_email in emails:
            email = self._valid_email(raw_email)
            if not email:
                continue
            rows += (f'<div class="apply-row"><span class="apply-row-label">✉️ البريد الإلكتروني</span>'
                     f'<a class="apply-box-value" href="mailto:{email}">{email}</a></div>')
            actions += f'<a class="apply-btn apply-btn-cv" href="mailto:{email}">📧 إرسال CV</a>'
        if apply_url:
            rows += (f'<div class="apply-row"><span class="apply-row-label">🌐 رابط التقديم</span>'
                     f'<a class="apply-box-value" href="{apply_url}" target="_blank" rel="noopener">{apply_url}</a></div>')
            actions += f'<a class="apply-btn apply-btn-now" href="{apply_url}" target="_blank" rel="noopener">التقديم</a>'
        if not rows:
            return ""
        return (f'<div class="apply-section">'
                f'<div class="apply-box">'
                f'<div class="apply-box-title">📞 معلومات التواصل</div>'
                f'{rows}'
                f'<div class="apply-box-actions">{actions}</div>'
                f'</div>'
                f'</div>')

    @staticmethod
    def _contact_values(value) -> List[str]:
        """Split a contact field (str or list) into distinct values.
        Values come ONLY from the current article's extracted data."""
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            items = [str(v) for v in value]
        else:
            items = re.split(r'[،,;/\n]+', str(value))
        out = []
        for item in items:
            item = re.sub(r'^[\s.\-()"\']+|[\s.\-()"\']+$', '', item)
            if item and item not in out:
                out.append(item)
        return out

    @staticmethod
    def _valid_phone(value: str) -> Optional[str]:
        digits = re.sub(r'[^\d+]', '', value)
        if not re.fullmatch(r'\+?\d{7,15}', digits):
            return None
        return digits

    @staticmethod
    def _valid_email(value: str) -> Optional[str]:
        value = re.sub(r'^[\s.\-()"\']+|[\s.\-()"\']+$', '', str(value).strip())
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', value):
            return None
        return value

    def _inject_apply_into_body(self, article: Dict, body: str) -> str:
        """Remove any AI-authored apply section from the body so the contact
        details appear only once, inside the dedicated contact box."""
        if not body:
            return body
        extracted = article.get("extracted", {}) or {}
        emails = self._contact_values(extracted.get("email"))
        phones = self._contact_values(extracted.get("phone"))
        apply_url = str(extracted.get("apply_url") or "").strip()
        if apply_url and re.search(r'^https?://(?:t\.me|telegram\.me|tlgrm\.me)/|^@', apply_url, re.IGNORECASE):
            apply_url = ""
        if not (emails or phones or apply_url):
            return body

        patterns = [
            r'<h[23][^>]*>(?:آلية التقديم والتواصل|طريقة التقديم والتواصل|طريقة التقديم على الوظيفة|طريقة التقديم|كيفية التقديم|التقديم على الوظيفة|شروط التقديم|التقديم)</h[23]>',
        ]
        for pattern in patterns:
            matches = list(re.finditer(
                pattern + r'.*?(?=<h[23][^>]*>|$)',
                body, flags=re.DOTALL | re.IGNORECASE
            ))
            if len(matches) <= 1:
                continue
            first = matches[0]
            kept = [body[:first.start()], first.group(0)]
            pos = first.end()
            for m in matches[1:]:
                kept.append(body[pos:m.start()])
                pos = m.end()
            kept.append(body[pos:])
            body = "".join(kept)
        return body

    def _make_notes_box(self, notes: list) -> str:
        lis = "".join(f"<li>{n}</li>" for n in notes)
        return f'<div class="notes-box"><div class="sec-head notes-head">⚠️ ملاحظات مهمة</div><ul class="notes-list">{lis}</ul></div>'

    def _make_faq(self, faq: list) -> str:
        items = ""
        for item in faq:
            q = item.get("question", "")
            a = item.get("answer", "")
            if q and a:
                items += f'<h3 itemscope itemprop="mainEntity" itemtype="https://schema.org/Question" class="faq-q">{q}</h3><div itemprop="acceptedAnswer" itemscope itemtype="https://schema.org/Answer" class="faq-a"><p itemprop="text">{a}</p></div>'
        if not items:
            return ""
        return f'<div class="faq-card"><h2 class="faq-h">الأسئلة الشائعة</h2><div itemscope itemtype="https://schema.org/FAQPage">{items}</div></div>'

    def _make_telegram_section(self) -> str:
        return (f'<div class="tg-card">'
                f'<div class="tg-card-h">📢 للمزيد من الوظائف</div>'
                f'<p class="tg-card-p">للمزيد من الوظائف وفرص العمل، تابع قناة الوظائف على تيليجرام.</p>'
                f'<a class="tg-card-btn" href="https://t.me/CastleJobiq" target="_blank" rel="noopener">🔵 اشترك في قناة الوظائف على تيليجرام</a>'
                f'</div>')

    def _make_keywords_section(self, keywords: str) -> str:
        parts = re.split(r'[،,\n]+', keywords)
        tags = []
        for p in parts:
            t = p.strip()
            if t:
                tags.append(f'<span class="kw-chip">{t}</span>')
        if not tags:
            return ""
        return f'<div class="keywords-box"><div class="sec-head kw-head">🏷️ الكلمات الدلالية</div><div class="kw-wrap">{"".join(tags)}</div></div>'

    def _make_hashtags_section(self, hashtags: List[str]) -> str:
        tags_items = []
        for tag in hashtags:
            t = tag.strip()
            if t and not t.startswith("#"):
                t = "#" + t
            if t:
                tags_items.append(f'<span class="ht-chip">{t}</span>')
        items = "".join(tags_items)
        return f'<div class="hashtag-box"><div class="sec-head has-head">🏷️ الهاشتاكات</div><div class="ht-wrap">{items}</div></div>'

    def _make_schema(self, article: Dict) -> str:
        title = article.get("title", "")
        intro = article.get("introduction", "")
        body = article.get("body", "")
        apply_pattern = r'<h[23][^>]*>(?:آلية التقديم والتواصل|طريقة التقديم والتواصل|طريقة التقديم على الوظيفة|طريقة التقديم|كيفية التقديم|التقديم على الوظيفة)</h[23]>.*?(?=<h[23]|$)'
        body = re.sub(apply_pattern, '', body, flags=re.DOTALL | re.IGNORECASE)
        nav_pattern = r'<h[23][^>]*>[^<]*(?:التنقل|navigation)[^<]*</h[23]>.*?(?=<h[23]|$)'
        body = re.sub(nav_pattern, '', body, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', f"{intro} {body}")[:300]
        section = article.get("section", "")
        is_news = section not in ("jobs", "وظائف")
        schema = {
            "@context": "https://schema.org",
            "@type": "NewsArticle" if is_news else "Article",
            "headline": title,
            "description": text[:160],
            "articleBody": text,
            "inLanguage": "ar",
            "author": {"@type": "Organization", "name": "المدونة"},
            "publisher": {"@type": "Organization", "name": "المدونة"},
            "datePublished": article.get("created_at", ""),
            "dateModified": article.get("processed_at", ""),
        }
        schema_str = json.dumps(schema, ensure_ascii=False)
        return f'<script type="application/ld+json">{schema_str}</script>'

    def make_preview_data(self, article: Dict) -> Tuple[Optional[str], str]:
        html = self.make_article_html(article)
        image = None
        media = article.get("media", [])
        for m in media:
            if m.get("type") == "photo":
                image = m.get("file_id")
                break
        if not image and self.config:
            section = article.get("section", "")
            if section in ("jobs", "وظائف", "general"):
                image = self.config.get("default_jobs_image", "")
        telegram_text = self.html_to_telegram(html)
        title = article.get("title", "")
        if title:
            telegram_text = f"<b>{title}</b>\n\n{telegram_text}"
        reading_time = article.get("reading_time", 0)
        if reading_time:
            telegram_text += f"\n⏱️ مدة القراءة: {reading_time} دقيقة"
        labels = article.get("labels", [])
        if labels:
            telegram_text += f"\n🏷 {', '.join(labels)}"
        return image, telegram_text

    @staticmethod
    def html_to_telegram(html: str) -> str:
        html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)

        def _replace_table(m):
            rows = re.findall(r'<tr>(.*?)</tr>', m.group(1), re.DOTALL)
            lines = []
            for row in rows:
                cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', row, re.DOTALL)
                if cells:
                    lines.append(' | '.join(cells))
            return '\n'.join(lines) + '\n'
        html = re.sub(r'<table[^>]*>(.*?)</table>', _replace_table, html, flags=re.DOTALL)
        html = re.sub(r'<img[^>]*>', '', html)
        html = re.sub(r'<h([23])[^>]*>(.*?)</h\1>', r'<b>\2</b>', html, flags=re.DOTALL)
        html = re.sub(r'<li>(.*?)</li>', r'• \1', html, flags=re.DOTALL)
        html = re.sub(r'</?u?[ol][^>]*>', '', html)
        html = re.sub(r'<details[^>]*>', '', html)
        html = re.sub(r'</details>', '', html)
        html = re.sub(r'<summary[^>]*>(.*?)</summary>', r'<b>\1</b>\n', html, flags=re.DOTALL)
        html = re.sub(r'</?div[^>]*>', '', html)
        html = re.sub(r'</?span[^>]*>', '', html)
        html = re.sub(r'<p>(.*?)</p>', r'\1\n', html, flags=re.DOTALL)
        html = re.sub(r'<br\s*/?>', '\n', html)
        html = re.sub(r'<strong>(.*?)</strong>', r'<b>\1</b>', html)
        html = re.sub(r'<em>(.*?)</em>', r'<i>\1</i>', html)
        html = re.sub(r'</?t[rdh][^>]*>', '', html)

        def _clean_allowed_attrs(m):
            tag = m.group(1).lower()
            if tag == 'a':
                href = re.search(r'href="([^"]+)"', m.group(0))
                return f'<a href="{href.group(1)}">' if href else '<a>'
            return f'<{tag}>'
        html = re.sub(r'<(a|b|i|u|s|em|strong|code|pre)\b[^>]*>', _clean_allowed_attrs, html, flags=re.IGNORECASE)
        allowed = {'b', 'i', 'u', 's', 'a', 'code', 'pre', 'em', 'strong'}
        html = re.sub(r'<(?!/?(' + '|'.join(allowed) + r')(?:\s[^>]*)?>)[a-z]+[^>]*>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'</(?!(' + '|'.join(allowed) + r')\b)[a-z]+>', '', html, flags=re.IGNORECASE)
        html = re.sub(r'\n{3,}', '\n\n', html)
        return html.strip()
