import os
import re
import fitz
from translator import translate_text


def _chunks(text, limit=1100):
    parts = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    out, current = [], ""
    for part in parts:
        if len(current) + len(part) + 1 > limit and current:
            out.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        out.append(current)
    return out


def translate_pdf(source_path, output_path, source="en", target="vi", progress_cb=None):
    doc = fitz.open(source_path)
    total = len(doc)
    for page_index, page in enumerate(doc):
        blocks = page.get_text("blocks")
        for block in blocks:
            x0, y0, x1, y1, text = block[:5]
            if not text.strip() or len(text.strip()) < 2:
                continue
            translated = "\n".join(translate_text(c, source, target) for c in _chunks(text))
            rect = fitz.Rect(x0, y0, x1, y1)
            page.add_redact_annot(rect, fill=(0.98, 0.97, 0.94))
            page.apply_redactions()
            fontsize = max(6, min(14, (y1 - y0) * 0.42))
            page.insert_textbox(rect, translated, fontsize=fontsize, fontname="helv", color=(0.10, 0.10, 0.10), align=0)
        if progress_cb:
            progress_cb(page_index + 1, total)
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return total, 0

