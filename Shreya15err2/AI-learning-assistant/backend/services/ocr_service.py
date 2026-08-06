import os
import re
import pytesseract
from pypdf import PdfReader
from pdf2image import convert_from_path
from typing import Tuple

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH = r"C:\poppler\poppler-26.02.0\Library\bin"

if os.name == "nt" and os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def extract_text_from_pdf(pdf_path: str) -> Tuple[str, int]:
    """
    Extract text from a PDF. Try extracting text instantly first.
    Falls back to slow OCR only if the PDF is scanned (contains no text layer).
    """
    # 1. Try instant text extraction via pypdf
    try:
        reader = PdfReader(pdf_path)
        pages_text = []
        page_count = len(reader.pages)
        
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(f"[Page {i + 1}]\n{text.strip()}")
                
        full_text = "\n\n".join(pages_text)
        if full_text.strip():
            return full_text, page_count
    except Exception:
        # Fallback to OCR on failure
        pass

    # 2. Slow OCR Fallback (for scanned images)
    try:
        pages = convert_from_path(
            pdf_path,
            dpi=300,  # Higher DPI = much better OCR accuracy
            poppler_path=POPPLER_PATH if os.name == "nt" else None
        )
    except Exception as e:
        raise RuntimeError(f"Failed to convert PDF to images: {str(e)}")

    all_text = []
    for i, page_image in enumerate(pages):
        try:
            text = pytesseract.image_to_string(
                page_image,
                lang="eng",
                config="--psm 3 --oem 1"  # psm 3 = auto layout, oem 1 = LSTM neural net
            )
            if text.strip():
                all_text.append(f"[Page {i + 1}]\n{text.strip()}")
        except Exception as e:
            all_text.append(f"[Page {i + 1}] OCR failed: {str(e)}")

    return clean_ocr_text("\n\n".join(all_text)), len(pages)


def clean_ocr_text(text: str) -> str:
    """
    Clean up common OCR errors:
    - Remove lines that are mostly garbage (very short random tokens)
    - Fix broken spacing
    - Remove non-printable characters
    """
    if not text:
        return text

    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        # Skip lines that are clearly OCR garbage:
        # - Less than 3 characters
        # - More than 60% non-alphanumeric characters
        if not line:
            cleaned_lines.append("")
            continue
        alnum_count = sum(1 for c in line if c.isalnum())
        if len(line) < 3:
            continue
        if len(line) > 3 and alnum_count / len(line) < 0.4:
            continue
        cleaned_lines.append(line)

    # Join and fix multiple spaces/newlines
    result = "\n".join(cleaned_lines)
    result = re.sub(r" {2,}", " ", result)      # multiple spaces -> single
    result = re.sub(r"\n{3,}", "\n\n", result)  # 3+ newlines -> double
    return result.strip()
