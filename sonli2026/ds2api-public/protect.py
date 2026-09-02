"""Lớp bảo vệ số liệu / thực thể không được phép dịch sai.

Trước khi dịch, ta thay mọi con số, %, tiền tệ, ngày tháng, đơn vị đo... bằng
placeholder dạng [[#N]]. Sau khi dịch xong thì khôi phục lại nguyên gốc.
Nhờ vậy engine dịch (kể cả LLM) KHÔNG BAO GIỜ làm tròn hay đổi số liệu.
"""
import re

# Thứ tự pattern quan trọng: cái cụ thể hơn đặt trước (vd "23.5%" phải khớp
# pattern phần trăm trước khi khớp pattern số trần).
_PATTERNS = [
    r'\d[\d.,]*\s?%',                       # phần trăm: 23.5%, 10 %
    r'[$€£¥₫]\s?\d[\d.,]*',                 # tiền tệ ký hiệu: $1,200.50
    r'\d[\d.,]*\s?(?:kg|km|cm|mm|nm|µm|m|g|mg|ml|l|MHz|GHz|kHz|Hz|'
    r'kWh|kW|MW|GW|°C|°F|USD|VND|EUR|JPY|GBP|bps|fps|dpi|px)\b',  # số + đơn vị
    r'\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b',   # ngày tháng: 12/05/2024
    r'\b[A-Z]{2,}[-_]?\d+[A-Z0-9-]*\b',         # mã/SKU/ISBN: AB-1234X
    r'\b\d[\d.,]*\b',                       # số trần: 1,234.56  3.14
]
_COMBINED = re.compile('|'.join(f'(?:{p})' for p in _PATTERNS))


def protect(text: str):
    """Trả về (text_đã_thay_placeholder, mapping placeholder->giá_trị_gốc)."""
    mapping = {}
    counter = [0]

    def repl(m):
        token = f"[[#{counter[0]}]]"
        mapping[token] = m.group(0)
        counter[0] += 1
        return token

    protected = _COMBINED.sub(repl, text)
    return protected, mapping


def _idx(token: str) -> int:
    m = re.search(r'\d+', token)
    return int(m.group()) if m else 0


def restore(text: str, mapping: dict) -> str:
    """Khôi phục giá trị gốc từ placeholder.

    Bền với mọi biến thể mà LLM hay tạo ra: [[#0]], [#0], [ # 0 ], thậm chí #0.
    Xử lý index giảm dần để [[#12]] không bị [[#1]] ăn mất.
    """
    for token, original in sorted(
        mapping.items(), key=lambda kv: _idx(kv[0]), reverse=True
    ):
        n = _idx(token)
        pat = re.compile(r'\[{0,2}\s*#\s*' + str(n) + r'(?!\d)\s*\]{0,2}')
        text = pat.sub(lambda m, o=original: o, text)
    return text


def count_protected(mapping: dict) -> int:
    return len(mapping)
