"""
Gọi DeepSeek để làm giàu metadata tài liệu lúc index:
  - Tóm tắt nội dung (3-5 câu)
  - Phân loại chủ đề
  - Đối tượng đọc

Chỉ chạy 1 lần/tài liệu lúc index → chi phí nhỏ, đổi lại thủ thư trả lời meta tốt hơn nhiều.
"""

from __future__ import annotations

import json
import logging
import time

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

_ENRICH_PROMPT = """Bạn là thủ thư phân loại tài liệu. Đọc đoạn mở đầu + mục lục dưới đây và trả về JSON đúng định dạng:
{
  "title": "Tiêu đề ngắn gọn, rõ ràng (≤120 ký tự)",
  "category": "MỘT trong: Sách | Giáo trình / Bài giảng | Báo cáo / Nghiên cứu | Luận văn / Luận án | Hướng dẫn / Kỹ thuật | Quy định / Pháp lý | Tài liệu khác",
  "summary": "Tóm tắt 3-5 câu về nội dung chính, chủ đề, đối tượng đọc, giá trị cốt lõi (tiếng Việt)",
  "topics": ["3-6 từ khóa chủ đề chính, tiếng Việt"]
}
Chỉ trả về JSON thuần, KHÔNG có text khác, KHÔNG markdown code fence."""


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def enrich_document(
    source_name: str,
    fallback_title: str,
    intro_text: str,
    toc: list[dict],
) -> dict:
    """
    Trả về dict {title, category, summary, topics}.
    Khi LLM lỗi/thiếu API key → fallback giá trị từ rule-based.
    """
    fallback = {
        "title": fallback_title,
        "category": "Tài liệu khác",
        "summary": "",
        "topics": [],
    }
    if not LLM_API_KEY:
        return fallback

    toc_lines = "\n".join(f"- {t['heading']} (tr.{t['page']})" for t in toc[:30]) or "(không phát hiện)"
    user_msg = (
        f"Tên file: {source_name}\n"
        f"Tiêu đề tạm: {fallback_title}\n\n"
        f"Mục lục:\n{toc_lines}\n\n"
        f"Đoạn mở đầu (trích):\n{intro_text[:2000]}"
    )

    t0 = time.perf_counter()
    try:
        resp = _get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _ENRICH_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=600,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content.strip()
        data = json.loads(raw)
        elapsed = time.perf_counter() - t0
        usage = resp.usage
        logger.info(
            "[DEEPSEEK enrich] %s | %.2fs | in=%d out=%d",
            source_name, elapsed,
            usage.prompt_tokens if usage else -1,
            usage.completion_tokens if usage else -1,
        )
        return {
            "title": (data.get("title") or fallback_title).strip()[:200],
            "category": (data.get("category") or "Tài liệu khác").strip(),
            "summary": (data.get("summary") or "").strip(),
            "topics": [str(t).strip() for t in (data.get("topics") or [])][:6],
        }
    except Exception as e:
        logger.warning("[DEEPSEEK enrich] %s lỗi (%.2fs): %s — dùng fallback",
                       source_name, time.perf_counter() - t0, e)
        return fallback
