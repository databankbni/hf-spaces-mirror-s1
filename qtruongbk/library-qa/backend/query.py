"""
Pipeline trả lời câu hỏi — 3 luồng xử lý:

  LUỒNG 1 — Library queries (truy vấn thư viện)
    "có bao nhiêu tài liệu", "bao nhiêu loại sách", "danh sách tài liệu"
    → Trả về trực tiếp từ SQLite, KHÔNG cần LLM hay RAG

  LUỒNG 2 — Document overview (tổng quan tài liệu cụ thể)
    "tóm tắt sách X", "mục lục của X", "X nói về gì"
    → Dùng L1 chunk + L2 (tìm theo tên tài liệu)

  LUỒNG 3 — Detail queries (câu hỏi chi tiết, cần trích dẫn)
    "cái này là gì", "giải thích khái niệm X"
    → Hybrid search L2+L3, trích dẫn đầy đủ (tài liệu, mục, trang)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterator

from openai import OpenAI

from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    TOP_K,
)
from embedding import embed_query
from vector_store import get_store

logger = logging.getLogger(__name__)

_llm_client: OpenAI | None = None

# ── Intent detection patterns ──────────────────────────────────────────────────

_OVERVIEW_TOP_K = 20
_DETAIL_TOP_K = TOP_K

_INTENT_CLASSIFIER_PROMPT = """Bạn là bộ phân loại câu hỏi cho hệ thống thư viện tài liệu.

Phân loại câu hỏi thành MỘT trong 5 intent sau:

- library_list   : Hỏi danh sách, liệt kê tài liệu/sách/file có trong thư viện
                   Ví dụ: "có những sách nào?", "liệt kê tài liệu đã index", "kho có gì?",
                          "thư viện có file nào?", "show me all books"
- library_stats  : Hỏi SỐ LƯỢNG, thống kê, phân loại, chủ đề
                   Ví dụ: "có bao nhiêu file?", "thư viện có mấy sách?", "kho có bao nhiêu tài liệu?",
                          "có bao nhiêu loại?", "chia theo chủ đề nào?", "tổng số trang?"
- doc_toc        : Hỏi mục lục, cấu trúc, các chương/phần của một tài liệu cụ thể
                   Ví dụ: "mục lục sách X", "sách Y có những chương gì?"
- doc_summary    : Hỏi tóm tắt, nội dung tổng quát của một tài liệu cụ thể
                   Ví dụ: "tóm tắt sách X", "sách Y nói về gì?"
- detail         : Câu hỏi chi tiết về nội dung, khái niệm, số liệu cần trích dẫn từ nội dung sách
                   Ví dụ: "định nghĩa X là gì?", "quy trình Y như thế nào?"

QUAN TRỌNG: Câu hỏi có "bao nhiêu/mấy" + "file/tài liệu/sách/kho/thư viện" → LUÔN là library_stats.

Chỉ trả về đúng một từ: library_list | library_stats | doc_toc | doc_summary | detail"""


# Fast-path: pattern rõ ràng → bỏ qua LLM, trả lời tức thì
_LIB_STATS_PATTERN = re.compile(
    r"(bao\s*nhi[êe]u|m[ấâa]y|t[ổô]ng\s*s[ốo]|how\s+many).{0,30}"
    r"(file|t[àa]i\s*li[ệe]u|s[áa]ch|cu[ốô]n|quy[ểe]n|kho|th[ưu]\s*vi[ệe]n|loại|chủ\s*đề|trang)",
    re.IGNORECASE,
)
_LIB_LIST_PATTERN = re.compile(
    # "liệt kê / danh sách" PHẢI đi kèm scope thư viện (file/sách/tài liệu/...) trong 30 ký tự kế tiếp,
    # nếu không sẽ nhầm với "liệt kê mục lục của X" / "liệt kê chương của X"
    r"((li[ệe]t\s*k[êe]|danh\s*s[áa]ch).{0,30}?(file|t[àa]i\s*li[ệe]u|s[áa]ch|cu[ốô]n|quy[ểe]n)"
    r"|kho\s*c[óo]\s*g[ìi]|th[ưu]\s*vi[ệe]n\s*c[óo]\s*g[ìi]|c[óo]\s*nh[ữu]ng\s*(file|s[áa]ch|t[àa]i\s*li[ệe]u)"
    r"|show\s+me\s+all)",
    re.IGNORECASE,
)
# Câu nhắc đến mục lục / chương / phần / cấu trúc của 1 tài liệu cụ thể → doc_toc
_DOC_TOC_PATTERN = re.compile(
    r"(m[ụu]c\s*l[ụu]c|table\s+of\s+contents|c[áa]c\s*ch[ưươ][ơo]ng|c[áa]c\s*ph[ầâ]n|c[ấâa]u\s*tr[úu]c)",
    re.IGNORECASE,
)
# Câu hỏi tổng quan toàn thư viện: "các file/sách này nói về gì", "chủ đề chính"
_LIB_TOPICS_PATTERN = re.compile(
    r"(c[áa]c\s*(file|s[áa]ch|t[àa]i\s*li[ệe]u|cu[ốô]n).{0,20}(n[óo]i\s*v[ềe]|ch[ủu]\s*đ[ềe]|n[ộo]i\s*dung)"
    r"|ch[ủu]\s*đ[ềe]\s*ch[íi]nh|t[ổô]ng\s*quan\s*kho|t[ổô]ng\s*quan\s*th[ưu]\s*vi[ệe]n)",
    re.IGNORECASE,
)


def _get_llm() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _llm_client


def _detect_intent(question: str) -> str:
    """Fast-path regex cho câu rõ ràng, fallback LLM cho phần còn lại."""
    # Ưu tiên doc_toc trước: "liệt kê mục lục của X" KHÔNG phải library_list
    if _DOC_TOC_PATTERN.search(question):
        logger.info("  [intent] fast-path → doc_toc")
        return "doc_toc"
    if _LIB_TOPICS_PATTERN.search(question):
        logger.info("  [intent] fast-path → library_topics")
        return "library_topics"
    if _LIB_STATS_PATTERN.search(question):
        logger.info("  [intent] fast-path → library_stats")
        return "library_stats"
    if _LIB_LIST_PATTERN.search(question):
        logger.info("  [intent] fast-path → library_list")
        return "library_list"

    t0 = time.perf_counter()
    try:
        client = _get_llm()
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _INTENT_CLASSIFIER_PROMPT},
                {"role": "user", "content": question},
            ],
            max_tokens=10,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip().lower()
        match = re.search(r"\b(library_list|library_stats|doc_toc|doc_summary|detail)\b", raw)
        token = match.group(1) if match else ""
        usage = resp.usage
        logger.info("  [DEEPSEEK intent] %.2fs | in=%d out=%d | token=%r",
                    time.perf_counter() - t0,
                    usage.prompt_tokens if usage else -1,
                    usage.completion_tokens if usage else -1,
                    token)
        return token or "detail"
    except Exception as e:
        logger.warning("[DEEPSEEK intent] %.2fs lỗi: %s — fallback detail",
                       time.perf_counter() - t0, e)
        return "detail"


_CONTEXTUALIZE_PROMPT = """Bạn là bộ viết lại câu hỏi cho hệ thống RAG.

Cho lịch sử hội thoại gần đây và câu hỏi mới, viết lại câu hỏi mới thành một câu
TỰ ĐỨNG ĐỘC LẬP, đầy đủ ngữ cảnh — để hệ thống tìm kiếm có thể hiểu mà không
cần đọc lại lịch sử.

Quy tắc:
1. Nếu câu hỏi mới đã rõ ràng (có tên tài liệu/khái niệm cụ thể) → giữ NGUYÊN.
2. Nếu câu hỏi dùng đại từ ("nó", "cái này", "sách này", "tài liệu đó") hoặc
   tham chiếu ngầm → thay bằng tên tài liệu/khái niệm cụ thể từ lịch sử.
3. Nếu câu hỏi tiếp nối chủ đề (vd: "còn chương 3 thì sao?") → bổ sung tên
   tài liệu đang nói tới.
4. KHÔNG thêm thông tin không có trong lịch sử. KHÔNG trả lời câu hỏi.
5. Giữ nguyên ngôn ngữ (tiếng Việt → tiếng Việt).

Chỉ trả về DUY NHẤT câu hỏi đã viết lại, không giải thích, không quote."""


def _contextualize_question(question: str, history: list[dict] | None) -> str:
    """Viết lại câu hỏi thành tự-đứng-độc-lập dựa trên 3-4 turn gần nhất.

    Bỏ qua nếu không có history hoặc câu hỏi đã đủ dài/rõ.
    """
    if not history:
        return question

    # Chỉ lấy 3 turn gần nhất (6 message: user/assistant xen kẽ)
    recent = history[-6:]
    if not recent:
        return question

    # Tóm tắt assistant messages dài cho gọn (giữ 300 ký tự đầu)
    convo_lines = []
    for m in recent:
        role = "Người dùng" if m["role"] == "user" else "Trợ lý"
        content = m["content"]
        if m["role"] == "assistant" and len(content) > 300:
            content = content[:300] + "…"
        convo_lines.append(f"{role}: {content}")
    convo = "\n".join(convo_lines)

    user_msg = f"Lịch sử hội thoại:\n{convo}\n\nCâu hỏi mới: {question}\n\nCâu hỏi đã viết lại:"

    t0 = time.perf_counter()
    try:
        client = _get_llm()
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": _CONTEXTUALIZE_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=150,
            temperature=0,
        )
        rewritten = (resp.choices[0].message.content or "").strip()
        # Loại bỏ quote nếu LLM lỡ thêm
        rewritten = rewritten.strip('"').strip("'").strip("`").strip()
        usage = resp.usage
        logger.info("  [DEEPSEEK rewrite] %.2fs | in=%d out=%d | %r → %r",
                    time.perf_counter() - t0,
                    usage.prompt_tokens if usage else -1,
                    usage.completion_tokens if usage else -1,
                    question[:50], rewritten[:80])
        return rewritten if rewritten and len(rewritten) > 2 else question
    except Exception as e:
        logger.warning("[DEEPSEEK rewrite] %.2fs lỗi: %s — dùng câu gốc",
                       time.perf_counter() - t0, e)
        return question


def _extract_doc_keyword(question: str, doc_names: list[str]) -> str | None:
    """
    Tìm tên tài liệu được nhắc đến trong câu hỏi.
    Ưu tiên khớp chính xác tên file, sau đó khớp từ khóa một phần.
    """
    q = question.lower()
    # Khớp tên file chính xác (không phân biệt hoa thường)
    for name in doc_names:
        if name.lower() in q:
            return name
    # Khớp một phần (bỏ extension, thay _ bằng space)
    for name in doc_names:
        stem = re.sub(r"[_\-]+", " ", name.rsplit(".", 1)[0]).lower()
        words = [w for w in stem.split() if len(w) > 3]
        if words and all(w in q for w in words[:2]):
            return name
    return None


# ── System prompts ─────────────────────────────────────────────────────────────

_SYSTEM_DETAIL = """Bạn là trợ lý đọc tài liệu thông minh. Tuân thủ các quy tắc sau:
1. Trả lời bằng tiếng Việt.
2. Chỉ trả lời dựa trên tài liệu được cung cấp — không bịa đặt.
3. Trả lời ĐẦY ĐỦ, CHI TIẾT. Không rút gọn ý quan trọng.
4. SAU MỖI Ý QUAN TRỌNG, trích dẫn nguồn: [Tên tài liệu | Mục: ... | Trang X]
5. Nếu thông tin trải nhiều trang: [Tên tài liệu | Mục: ... | Trang X–Y]
6. Nếu không có thông tin: chỉ trả lời đúng 1 câu: KHÔNG_ĐỦ_THÔNG_TIN"""

_SYSTEM_DIAGNOSTIC_REPORT = """Bạn là trợ lý hỗ trợ tổng hợp báo cáo tham khảo cho hồ sơ bệnh nhân theo Y học cổ truyền.

Yêu cầu chung:
1. Viết bằng tiếng Việt, văn phong chuyên môn, thận trọng, dễ đưa vào PDF.
2. Chỉ dựa trên thông tin người dùng cung cấp trong prompt. Nếu thiếu dữ kiện, nêu rõ dữ kiện còn thiếu và mức độ bất định.
3. Không tự xưng là AI, không nhắc tên nhà cung cấp hoặc mô hình như DeepSeek, không dùng cụm "AI Diagnostic".
4. Trả về HTML fragment để app hiển thị trực tiếp. Chỉ dùng các thẻ cơ bản: h2, h3, p, ul, li, strong, em, br. Không bọc trong html/body, không dùng markdown.
5. Nội dung chỉ mang tính tham khảo chuyên môn, cần được đối chiếu với thăm khám trực tiếp và quyết định của người có chuyên môn.
6. Không đưa chỉ định cấp cứu, kê đơn bắt buộc, hoặc khẳng định chẩn đoán chắc chắn nếu dữ kiện chưa đủ.
7. Không chèn tên thương hiệu, không nhắc "DeepSeek" hoặc "AI Diagnostic" trong nội dung.
8. Kết thúc bằng đoạn ghi chú HTML ngắn: nội dung tham khảo, cần đối chiếu với thăm khám trực tiếp và ý kiến chuyên môn.

Cấu trúc bắt buộc:
<h2>I. PHÂN TÍCH BIỆN CHỨNG KHÍ HUYẾT & LÂM SÀNG</h2>
- Biện chứng Tứ chẩn hợp tham, gồm phần Thiệt chẩn/lưỡi.
- Cơ chế bệnh sinh tổng quát.
- Liên hệ triệu chứng.
- Cảnh báo biến chứng cần lưu ý.

<h2>II. PHƯƠNG PHÁP ĐIỀU TRỊ (LẬP PHÁP)</h2>
- Nêu pháp trị phù hợp.

<h2>III. BÀI THUỐC CHỦ TRỊ ĐỀ XUẤT</h2>
- Đề xuất bài thuốc chủ trị hoặc phối ngũ.
- Nêu danh sách vị thuốc và liều lượng tham khảo nếu phù hợp.
- Gia giảm theo biến chứng lâm sàng.

<h2>IV. ĐÁNH GIÁ PHƯƠNG THUỐC TRÊN LÂM SÀNG</h2>
- Đánh giá mục tiêu tác động và giới hạn.

<h2>V. THÔNG TIN THÊM</h2>
- Bài thuốc điều chỉnh chuyên biệt nếu cần.
- Thành phần và hàm lượng điều chỉnh.
- Phân tích cơ chế phòng ngừa biến chứng.
- Lưu ý gia giảm thêm."""

_LEVEL_LABEL = {1: "Tổng quan tài liệu", 2: "Phần/Chương", 3: "Đoạn văn"}


def _build_rag_prompt(question: str, chunks: list[dict]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        level_label = _LEVEL_LABEL.get(chunk.get("level", 3), "Đoạn văn")
        heading = chunk.get("heading", "")
        heading_line = f" | Mục: {heading}" if heading else ""
        parts.append(
            f"[Đoạn {i} — {level_label}] "
            f"Tài liệu: {chunk['source_file']}{heading_line} | "
            f"Trang: {chunk['page_start']}–{chunk['page_end']}\n"
            f"{chunk['text']}"
        )
    context = "\n\n---\n\n".join(parts)
    return f"Tài liệu tham khảo:\n\n{context}\n\n---\n\nCâu hỏi: {question}"


def _sources_from_chunks(chunks: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    sources = []
    for chunk in sorted(chunks, key=lambda c: -c.get("level", 3)):
        key = (chunk["source_file"], chunk["page_start"])
        if key not in seen:
            seen.add(key)
            sources.append({
                "file": chunk["source_file"],
                "heading": chunk.get("heading", ""),
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "score": round(chunk.get("score", 0), 4),
            })
    return sources


# ── Luồng 1: Library queries ───────────────────────────────────────────────────

def _answer_library_list() -> dict[str, Any]:
    store = get_store()
    docs = store.get_all_documents()
    if not docs:
        return {
            "answer": "Thư viện hiện chưa có tài liệu nào. Hãy index một thư mục Google Drive trước.",
            "sources": [], "needs_web_search": False,
        }

    lines = [f"**Thư viện có {len(docs)} tài liệu:**\n"]
    for i, doc in enumerate(docs, 1):
        lines.append(
            f"{i}. **{doc['title']}** (`{doc['name']}`)\n"
            f"   - Phân loại: {doc['category']}\n"
            f"   - Số trang: {doc['page_count']}\n"
            f"   - Đã index: {doc['indexed_at']}"
        )
    return {"answer": "\n".join(lines), "sources": [], "needs_web_search": False}


def _answer_library_topics() -> dict[str, Any]:
    """Tổng hợp chủ đề toàn thư viện từ summary + topics đã lưu lúc index."""
    store = get_store()
    docs = store.get_all_documents()
    if not docs:
        return {"answer": "Thư viện chưa có tài liệu nào.", "sources": [], "needs_web_search": False}

    # Gom tần suất topic
    topic_count: dict[str, int] = {}
    for d in docs:
        for t in d.get("topics", []) or []:
            key = t.strip()
            if key:
                topic_count[key] = topic_count.get(key, 0) + 1

    lines = [f"**Tổng quan {len(docs)} tài liệu trong thư viện:**\n"]

    if topic_count:
        sorted_topics = sorted(topic_count.items(), key=lambda x: -x[1])
        lines.append("**Các chủ đề chính:**")
        for topic, count in sorted_topics[:20]:
            lines.append(f"- {topic} ({count} tài liệu)")
        lines.append("")

    lines.append("**Chi tiết từng tài liệu:**")
    for i, d in enumerate(docs, 1):
        summary = (d.get("summary") or "").strip()
        topics = ", ".join(d.get("topics", []) or [])
        lines.append(f"\n{i}. **{d['title']}** ({d['category']})")
        if topics:
            lines.append(f"   - Chủ đề: {topics}")
        if summary:
            lines.append(f"   - Tóm tắt: {summary}")

    return {"answer": "\n".join(lines), "sources": [], "needs_web_search": False}


def _answer_library_stats() -> dict[str, Any]:
    store = get_store()
    stats = store.get_library_stats()
    if stats["total_documents"] == 0:
        return {
            "answer": "Thư viện hiện chưa có tài liệu nào.",
            "sources": [], "needs_web_search": False,
        }

    lines = [
        f"**Tổng quan thư viện:**\n",
        f"- Tổng số tài liệu: **{stats['total_documents']}**",
        f"- Tổng số trang: **{stats['total_pages']}**",
        f"- Số đoạn đã index: **{stats['total_chunks']}**",
        f"\n**Phân loại ({len(stats['categories'])} loại):**",
    ]
    for cat in stats["categories"]:
        lines.append(f"- {cat['category']}: **{cat['count']}** tài liệu")

    return {"answer": "\n".join(lines), "sources": [], "needs_web_search": False}


# ── Luồng 2: Document TOC ─────────────────────────────────────────────────────

def _answer_doc_toc(question: str) -> dict[str, Any]:
    store = get_store()
    all_docs = store.get_all_documents()
    doc_names = [d["name"] for d in all_docs]

    # Thử tìm tài liệu cụ thể được nhắc đến
    doc_name = _extract_doc_keyword(question, doc_names)
    if doc_name:
        doc = store.get_document(doc_name)
    else:
        # Không chỉ định → hỏi toàn bộ hoặc không rõ, dùng RAG
        doc = None

    if doc and doc.get("toc"):
        toc = doc["toc"]
        lines = [f"**Mục lục: {doc['title']}** (`{doc['name']}`)\n"]
        for item in toc:
            lines.append(f"- {item['heading']} *(trang {item['page']})*")
        return {
            "answer": "\n".join(lines),
            "sources": [{"file": doc["name"], "page_start": 1, "page_end": doc["page_count"], "heading": "", "score": 1.0}],
            "needs_web_search": False,
        }

    # Không tìm thấy hoặc không có TOC → fallback sang RAG
    return _answer_detail(question, source_filter=doc_name)


# ── Luồng 2b: Document summary ────────────────────────────────────────────────

def _answer_doc_summary(question: str, history: list[dict] | None) -> dict[str, Any]:
    store = get_store()
    all_docs = store.get_all_documents()
    doc_names = [d["name"] for d in all_docs]

    doc_name = _extract_doc_keyword(question, doc_names)
    source_filter = doc_name

    if doc_name:
        # Ưu tiên L1 chunk của tài liệu đó
        l1 = store.get_l1_chunk(doc_name)
        if l1:
            chunks = [l1]
            # Bổ sung thêm L2 để summary chi tiết hơn
            q_emb = embed_query(question)
            l2_chunks = store.hybrid_search(q_emb, question, k=10, levels=(2,), source_filter=doc_name)
            chunks = [l1] + l2_chunks
        else:
            q_emb = embed_query(question)
            chunks = store.hybrid_search(q_emb, question, k=_OVERVIEW_TOP_K, levels=(1, 2), source_filter=source_filter)
    else:
        q_emb = embed_query(question)
        chunks = store.hybrid_search(q_emb, question, k=_OVERVIEW_TOP_K, levels=(1, 2))

    chunks = sorted(chunks, key=lambda c: (c["source_file"], c["page_start"]))

    if not chunks:
        return {"answer": "Không tìm thấy tài liệu phù hợp.", "sources": [], "needs_web_search": False}

    return _call_llm(question, chunks, history, system=_SYSTEM_DETAIL)


# ── Luồng 3: Detail queries ────────────────────────────────────────────────────

def _answer_detail(question: str, history: list[dict] | None = None, source_filter: str | None = None) -> dict[str, Any]:
    store = get_store()
    q_emb = embed_query(question)
    chunks = store.hybrid_search(q_emb, question, k=_DETAIL_TOP_K, levels=(2, 3), source_filter=source_filter)
    if not chunks:
        return {"answer": "Không tìm thấy thông tin liên quan trong tài liệu.", "sources": [], "needs_web_search": False}
    return _call_llm(question, chunks, history, system=_SYSTEM_DETAIL)


# ── LLM call ───────────────────────────────────────────────────────────────────

def _call_llm_stream(
    question: str,
    chunks: list[dict],
    history: list[dict] | None,
    system: str,
) -> Iterator[dict[str, Any]]:
    """Stream LLM output token-by-token.

    Yields:
      {"type": "delta", "text": "..."} cho mỗi token
      {"type": "done",  "sources": [...]} ở cuối
    """
    t0 = time.perf_counter()
    user_message = _build_rag_prompt(question, chunks)
    client = _get_llm()
    recent_history = (history or [])[-10:]
    messages = [{"role": "system", "content": system}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
        stream=True,
    )

    full = []
    for event in response:
        if not event.choices:
            continue
        delta = event.choices[0].delta.content or ""
        if delta:
            full.append(delta)
            yield {"type": "delta", "text": delta}

    raw = "".join(full).strip()
    logger.info("  [DEEPSEEK answer-stream] %.2fs | %d chunks ctx | %d chars out",
                time.perf_counter() - t0, len(chunks), len(raw))

    stripped = raw.strip().strip(".!?")
    if stripped == "KHÔNG_ĐỦ_THÔNG_TIN" or (len(raw) < 60 and "KHÔNG_ĐỦ_THÔNG_TIN" in raw):
        yield {"type": "replace", "text": "Tài liệu không có thông tin liên quan đến câu hỏi này."}
        yield {"type": "done", "sources": []}
        return

    yield {"type": "done", "sources": _sources_from_chunks(chunks)}


def _call_llm(
    question: str,
    chunks: list[dict],
    history: list[dict] | None,
    system: str,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    user_message = _build_rag_prompt(question, chunks)
    client = _get_llm()
    recent_history = (history or [])[-10:]
    messages = [{"role": "system", "content": system}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    raw = response.choices[0].message.content.strip()
    usage = response.usage
    logger.info("  [DEEPSEEK answer] %.2fs | in=%d out=%d | %d chunks ctx",
                time.perf_counter() - t0,
                usage.prompt_tokens if usage else -1,
                usage.completion_tokens if usage else -1,
                len(chunks))

    # Chỉ coi là "không đủ thông tin" khi câu trả lời CHỈ chứa marker đó (ngắn, không có nội dung khác)
    stripped = raw.strip().strip(".!?")
    if stripped == "KHÔNG_ĐỦ_THÔNG_TIN" or (len(raw) < 60 and "KHÔNG_ĐỦ_THÔNG_TIN" in raw):
        return {"answer": "Tài liệu không có thông tin liên quan đến câu hỏi này.",
                "sources": [], "needs_web_search": False}

    return {"answer": raw, "sources": _sources_from_chunks(chunks), "needs_web_search": False}


# ── Entry point ────────────────────────────────────────────────────────────────

def answer_question(question: str, k: int = _DETAIL_TOP_K, history: list[dict] | None = None) -> dict[str, Any]:
    store = get_store()
    question = _contextualize_question(question, history)
    intent = _detect_intent(question)
    logger.info("── /query intent=%s | %r", intent, question[:80])

    # Library queries chỉ cần SQLite — không cần vector
    if intent == "library_list":
        return _answer_library_list()
    if intent == "library_stats":
        return _answer_library_stats()
    if intent == "library_topics":
        return _answer_library_topics()

    # Các intent còn lại cần vector (RAG)
    if store.total_vectors == 0:
        return {
            "answer": "Thư viện chưa có tài liệu nào được index. Vui lòng index một thư mục Google Drive trước.",
            "sources": [], "needs_web_search": False,
        }
    if intent == "doc_toc":
        return _answer_doc_toc(question)

    if intent == "doc_summary":
        return _answer_doc_summary(question, history)

    # intent == "detail"
    t0 = time.perf_counter()
    store2 = get_store()
    q_emb = embed_query(question)
    chunks = store2.hybrid_search(q_emb, question, k=k, levels=(2, 3))
    if not chunks:
        return {"answer": "Không tìm thấy thông tin liên quan trong tài liệu.", "sources": [], "needs_web_search": False}
    result = _call_llm(question, chunks, history, system=_SYSTEM_DETAIL)
    logger.info("── /query xong: %.3fs | sources=%d", time.perf_counter() - t0, len(result["sources"]))
    return result


def answer_question_stream(
    question: str,
    k: int = _DETAIL_TOP_K,
    history: list[dict] | None = None,
) -> Iterator[dict[str, Any]]:
    """Streaming variant of answer_question.

    Yields events:
      {"type": "delta",   "text": "..."} — append vào câu trả lời
      {"type": "replace", "text": "..."} — thay toàn bộ câu trả lời (canned answers)
      {"type": "done",    "sources": [...]}
    """
    store = get_store()
    question = _contextualize_question(question, history)
    intent = _detect_intent(question)
    logger.info("── /query/stream intent=%s | %r", intent, question[:80])

    # Library queries — không LLM, trả nguyên văn
    if intent == "library_list":
        result = _answer_library_list()
        yield {"type": "replace", "text": result["answer"]}
        yield {"type": "done", "sources": result["sources"]}
        return
    if intent == "library_stats":
        result = _answer_library_stats()
        yield {"type": "replace", "text": result["answer"]}
        yield {"type": "done", "sources": result["sources"]}
        return
    if intent == "library_topics":
        result = _answer_library_topics()
        yield {"type": "replace", "text": result["answer"]}
        yield {"type": "done", "sources": result["sources"]}
        return

    if store.total_vectors == 0:
        yield {"type": "replace",
               "text": "Thư viện chưa có tài liệu nào được index. Vui lòng index một thư mục Google Drive trước."}
        yield {"type": "done", "sources": []}
        return

    # doc_toc: nếu có TOC sẵn → trả ngay; không có → fallback sang detail (stream)
    source_filter: str | None = None
    if intent == "doc_toc":
        all_docs = store.get_all_documents()
        doc_names = [d["name"] for d in all_docs]
        doc_name = _extract_doc_keyword(question, doc_names)
        if doc_name:
            doc = store.get_document(doc_name)
            if doc and doc.get("toc"):
                lines = [f"**Mục lục: {doc['title']}** (`{doc['name']}`)\n"]
                for item in doc["toc"]:
                    lines.append(f"- {item['heading']} *(trang {item['page']})*")
                yield {"type": "replace", "text": "\n".join(lines)}
                yield {"type": "done", "sources": [{
                    "file": doc["name"], "page_start": 1,
                    "page_end": doc["page_count"], "heading": "", "score": 1.0,
                }]}
                return
            source_filter = doc_name

    # doc_summary: lấy L1 + L2 của tài liệu
    if intent == "doc_summary":
        all_docs = store.get_all_documents()
        doc_names = [d["name"] for d in all_docs]
        doc_name = _extract_doc_keyword(question, doc_names)
        if doc_name:
            l1 = store.get_l1_chunk(doc_name)
            q_emb = embed_query(question)
            if l1:
                l2_chunks = store.hybrid_search(q_emb, question, k=10, levels=(2,), source_filter=doc_name)
                chunks = [l1] + l2_chunks
            else:
                chunks = store.hybrid_search(q_emb, question, k=_OVERVIEW_TOP_K, levels=(1, 2), source_filter=doc_name)
        else:
            q_emb = embed_query(question)
            chunks = store.hybrid_search(q_emb, question, k=_OVERVIEW_TOP_K, levels=(1, 2))
        chunks = sorted(chunks, key=lambda c: (c["source_file"], c["page_start"]))
    else:
        # detail (hoặc doc_toc fallback)
        q_emb = embed_query(question)
        chunks = store.hybrid_search(q_emb, question, k=k, levels=(2, 3), source_filter=source_filter)

    if not chunks:
        yield {"type": "replace", "text": "Không tìm thấy thông tin liên quan trong tài liệu."}
        yield {"type": "done", "sources": []}
        return

    yield from _call_llm_stream(question, chunks, history, system=_SYSTEM_DETAIL)


def answer_diagnostic_report(
    question: str,
    history: list[dict] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a standalone diagnostic report from app-provided patient context."""
    t0 = time.perf_counter()
    client = _get_llm()
    recent_history = (history or [])[-10:]
    metadata = metadata or {}
    source = metadata.get("source", "")
    report_type = metadata.get("report_type", "")
    user_message = (
        "Dữ liệu từ app:\n"
        f"- source: {source}\n"
        f"- report_type: {report_type}\n\n"
        "Prompt/hồ sơ bệnh nhân cần phân tích:\n"
        f"{question}"
    )
    messages = [{"role": "system", "content": _SYSTEM_DIAGNOSTIC_REPORT}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )
    answer = (response.choices[0].message.content or "").strip()
    usage = response.usage
    logger.info("  [diagnostic-report] %.2fs | in=%d out=%d | %d chars",
                time.perf_counter() - t0,
                usage.prompt_tokens if usage else -1,
                usage.completion_tokens if usage else -1,
                len(answer))

    return {"answer": answer, "sources": [], "needs_web_search": False}


def web_search_question(question: str) -> dict[str, Any]:
    client = _get_llm()
    tools = [{"type": "web_search"}]
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "Tìm kiếm và trả lời câu hỏi bằng tiếng Việt. Trích dẫn nguồn web: [Tên trang - URL] sau mỗi ý."},
                {"role": "user", "content": question},
            ],
            tools=tools,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )
        answer = response.choices[0].message.content or ""
        return {"answer": answer.strip() or "Không tìm được kết quả.", "sources": [], "needs_web_search": False}
    except Exception as e:
        logger.error("Web search lỗi: %s", e)
        return {"answer": f"Tìm kiếm thất bại: {e}", "sources": [], "needs_web_search": False}
