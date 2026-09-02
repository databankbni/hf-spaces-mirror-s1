"""
Medical Report Parser - OCR and PDF extraction for healthcare reports.
Uses free Tesseract OCR for images and pdfplumber for PDFs.
"""

import os
import zipfile
from typing import Optional, Dict, List
from xml.etree import ElementTree

# Common Tesseract installation paths to try automatically
COMMON_TESSERACT_PATHS = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
    r'C:\Users\Muham\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    r'C:\Users\Muham\AppData\Local\Tesseract-OCR\tesseract.exe',
    '/usr/bin/tesseract',
    '/usr/local/bin/tesseract'
]

SUPPORTED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']
SUPPORTED_PDF_EXTENSION = '.pdf'
SUPPORTED_TEXT_EXTENSIONS = ['.txt']
SUPPORTED_DOCX_EXTENSIONS = ['.docx']
SUPPORTED_DOC_EXTENSIONS = ['.doc']
SUPPORTED_IMAGE_MIME_TYPES = ['image/jpeg', 'image/png', 'image/bmp', 'image/tiff']
SUPPORTED_PDF_MIME_TYPE = 'application/pdf'
SUPPORTED_TEXT_MIME_TYPES = ['text/plain']
SUPPORTED_DOCX_MIME_TYPES = ['application/vnd.openxmlformats-officedocument.wordprocessingml.document']
SUPPORTED_DOC_MIME_TYPES = ['application/msword']
SUPPORTED_IMAGE_TYPES = SUPPORTED_IMAGE_MIME_TYPES
SUPPORTED_PDF_TYPE = SUPPORTED_PDF_MIME_TYPE

# Try to import optional dependencies with fallbacks
has_pytesseract = False
has_pil = False
has_pdfplumber = False
has_magic = False
tesseract_found = False

try:
    import pytesseract
    has_pytesseract = True
    
    # Try to find Tesseract in common paths
    for path in COMMON_TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            tesseract_found = True
            print(f"Tesseract found at: {path}")
            break
            
    if not tesseract_found:
        print("Tesseract OCR not found in common paths")
        print("   Please install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki")
        
except ImportError:
    pass

try:
    from PIL import Image
    has_pil = True
except ImportError:
    pass

try:
    import pdfplumber
    has_pdfplumber = True
except ImportError:
    pass

try:
    import magic
    has_magic = True
except ImportError:
    pass


def detect_file_type(file_path: str) -> str:
    """Detect file type using magic numbers or file extension"""
    # First try magic if available
    if has_magic:
        try:
            mime = magic.Magic(mime=True)
            detected = mime.from_file(file_path)
            if detected:
                return detected
        except Exception:
            pass
    
    # Fallback to file extension
    ext = os.path.splitext(file_path)[1].lower()
    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        if ext in ['.jpg', '.jpeg']:
            return 'image/jpeg'
        elif ext == '.png':
            return 'image/png'
        elif ext == '.bmp':
            return 'image/bmp'
        elif ext in ['.tiff', '.tif']:
            return 'image/tiff'
    elif ext == SUPPORTED_PDF_EXTENSION:
        return 'application/pdf'
    elif ext in SUPPORTED_TEXT_EXTENSIONS:
        return 'text/plain'
    elif ext in SUPPORTED_DOCX_EXTENSIONS:
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext in SUPPORTED_DOC_EXTENSIONS:
        return 'application/msword'
    
    return 'application/octet-stream'


def extract_text_from_image(image_path: str) -> str:
    """Extract text from image using Tesseract OCR (if available)"""
    if not has_pil:
        return "Missing dependency for OCR: Pillow (Python Imaging Library). Please install it."
    if not has_pytesseract:
        return "Missing dependency for OCR: pytesseract. Please install it."
    if not tesseract_found:
        return "Tesseract OCR engine not found. Please install Tesseract from: https://github.com/UB-Mannheim/tesseract/wiki"
    
    try:
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang='eng')
        return text.strip()
    except Exception as e:
        return f"OCR Error: {str(e)}"


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using pdfplumber (if available)"""
    if not has_pdfplumber:
        return "Missing dependency for PDF extraction: pdfplumber. Please install it."
    
    try:
        text_parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i+1} ---\n{page_text}")
        return "\n\n".join(text_parts)
    except Exception as e:
        return f"PDF Error: {str(e)}"


def extract_text_from_txt(text_path: str) -> str:
    """Extract text from a plain text file."""
    encodings = ("utf-8", "utf-8-sig", "cp1252", "latin-1")
    for encoding in encodings:
        try:
            with open(text_path, "r", encoding=encoding) as handle:
                return handle.read().strip()
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return f"Text file error: {str(e)}"
    return "Text file error: could not decode file contents."


def extract_text_from_docx(docx_path: str) -> str:
    """Extract visible text from a .docx file without extra dependencies."""
    try:
        with zipfile.ZipFile(docx_path) as archive:
            xml_bytes = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_bytes)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = []
        for paragraph in root.findall(".//w:p", namespace):
            runs = [node.text for node in paragraph.findall(".//w:t", namespace) if node.text]
            line = "".join(runs).strip()
            if line:
                paragraphs.append(line)
        return "\n".join(paragraphs).strip()
    except KeyError:
        return "DOCX Error: word/document.xml not found."
    except Exception as e:
        return f"DOCX Error: {str(e)}"


def parse_medical_report(file_path: str) -> Dict:
    """
    Parse a medical report (image or PDF) and extract structured data
    
    Returns:
        {
            "success": bool,
            "text": str,  # Full extracted text
            "file_type": str,
            "pages": int,
            "error": str or None
        }
    """
    result = {
        "success": False,
        "text": "",
        "file_type": "",
        "pages": 0,
        "error": None
    }
    
    if not os.path.exists(file_path):
        result["error"] = "File not found"
        return result
    
    try:
        file_type = detect_file_type(file_path)
        result["file_type"] = file_type
        
        ext = os.path.splitext(file_path)[1].lower()
        is_image = (file_type in SUPPORTED_IMAGE_MIME_TYPES) or (ext in SUPPORTED_IMAGE_EXTENSIONS)
        is_pdf = (file_type == SUPPORTED_PDF_MIME_TYPE) or (ext == SUPPORTED_PDF_EXTENSION)
        is_txt = (file_type in SUPPORTED_TEXT_MIME_TYPES) or (ext in SUPPORTED_TEXT_EXTENSIONS)
        is_docx = (file_type in SUPPORTED_DOCX_MIME_TYPES) or (ext in SUPPORTED_DOCX_EXTENSIONS)
        is_doc = (file_type in SUPPORTED_DOC_MIME_TYPES) or (ext in SUPPORTED_DOC_EXTENSIONS)
        
        if is_image:
            extracted = extract_text_from_image(file_path)
            result["text"] = extracted
            result["pages"] = 1
            result["success"] = True
            result["file_type"] = file_type if file_type in SUPPORTED_IMAGE_MIME_TYPES else 'image/jpeg'
            
        elif is_pdf:
            extracted = extract_text_from_pdf(file_path)
            result["text"] = extracted
            result["file_type"] = file_type if file_type == SUPPORTED_PDF_MIME_TYPE else 'application/pdf'
            if has_pdfplumber:
                try:
                    with pdfplumber.open(file_path) as pdf:
                        result["pages"] = len(pdf.pages)
                except Exception:
                    result["pages"] = 1
            else:
                result["pages"] = 1
            result["success"] = True

        elif is_txt:
            extracted = extract_text_from_txt(file_path)
            result["text"] = extracted
            result["pages"] = 1
            result["success"] = True
            result["file_type"] = "text/plain"

        elif is_docx:
            extracted = extract_text_from_docx(file_path)
            result["text"] = extracted
            result["pages"] = max(1, extracted.count("\n\n") + 1) if extracted else 1
            result["success"] = True
            result["file_type"] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

        elif is_doc:
            result["error"] = (
                "Legacy .doc files are not supported for text extraction yet. "
                "Please save the document as .docx, PDF, or plain text and upload again."
            )
            
        else:
            result["error"] = f"Unsupported file type: {file_type}"

        if result["success"] and not result["text"].strip():
            result["text"] = (
                "No readable text could be extracted from this file. "
                "The image or document may be too blurry, empty, or not text-based."
            )
            
    except Exception as e:
        result["error"] = str(e)
    
    return result

def extract_vitals(text: str) -> Dict:
    """
    Extract common medical vitals and lab values from report text
    
    Returns dict with found values like:
    {
        "blood_pressure": "120/80",
        "heart_rate": "72 bpm",
        "glucose": "95 mg/dL",
        "hemoglobin": "14.2 g/dL",
        "cholesterol": "180 mg/dL",
        ...
    }
    """
    import re
    
    vitals = {}
    text_lower = text.lower()
    
    # Blood Pressure patterns
    bp_patterns = [
        r'blood\s*pressure[:\s]+(\d{2,3})\s*/\s*(\d{2,3})',
        r'bp[:\s]+(\d{2,3})\s*/\s*(\d{2,3})',
        r'(\d{2,3})\s*/\s*(\d{2,3})\s*(?:mmhg|mm\s*hg)'
    ]
    for pattern in bp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["blood_pressure"] = f"{match.group(1)}/{match.group(2)} mmHg"
            break
    
    # Heart Rate
    hr_patterns = [
        r'heart\s*rate[:\s]+(\d+)\s*(?:bpm|beats?/min)',
        r'pulse[:\s]+(\d+)\s*(?:bpm|beats?/min)',
        r'(\d+)\s*(?:bpm)\s*(?:heart|pulse)'
    ]
    for pattern in hr_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["heart_rate"] = f"{match.group(1)} bpm"
            break
    
    # Glucose/Blood Sugar
    glucose_patterns = [
        r'(?:blood\s*sugar|glucose|fasting\s*glucose)[:\s]+(\d+)\s*(?:mg/dl|mg\s*/\s*dl)',
        r'(\d+)\s*(?:mg/dl)\s*(?:glucose|blood\s*sugar)'
    ]
    for pattern in glucose_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["glucose"] = f"{match.group(1)} mg/dL"
            break
    
    # Hemoglobin
    hgb_patterns = [
        r'hemoglobin[:\s]+([\d.]+)\s*(?:g/dl|g\s*/\s*dl)',
        r'hgb[:\s]+([\d.]+)\s*(?:g/dl)',
        r'([\d.]+)\s*(?:g/dl)\s*hemoglobin'
    ]
    for pattern in hgb_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["hemoglobin"] = f"{match.group(1)} g/dL"
            break
    
    # Cholesterol
    chol_patterns = [
        r'(?:total\s*cholesterol|cholesterol)[:\s]+(\d+)\s*(?:mg/dl)',
        r'(\d+)\s*(?:mg/dl)\s*(?:cholesterol)'
    ]
    for pattern in chol_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["cholesterol"] = f"{match.group(1)} mg/dL"
            break
    
    # Creatinine
    creat_patterns = [
        r'creatinine[:\s]+([\d.]+)\s*(?:mg/dl)',
        r'([\d.]+)\s*(?:mg/dl)\s*creatinine'
    ]
    for pattern in creat_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["creatinine"] = f"{match.group(1)} mg/dL"
            break
    
    # HbA1c
    hba1c_patterns = [
        r'hba1c[:\s]+([\d.]+)\s*(?:%)',
        r'([\d.]+)\s*(?:%)\s*hba1c',
        r'a1c[:\s]+([\d.]+)\s*(?:%)'
    ]
    for pattern in hba1c_patterns:
        match = re.search(pattern, text_lower)
        if match:
            vitals["hba1c"] = f"{match.group(1)}%"
            break
    
    return vitals

def analyze_report_health(text: str, vitals: Dict) -> str:
    """
    Generate health insights from extracted report data
    Returns a summary with normal/abnormal flags
    """
    insights = []
    
    # Blood Pressure Analysis
    if "blood_pressure" in vitals:
        bp = vitals["blood_pressure"]
        try:
            systolic, diastolic = map(int, bp.replace(" mmHg", "").split("/"))
            if systolic <= 120 and diastolic <= 80:
                insights.append(f"✓ Blood Pressure ({bp}): Normal range")
            elif systolic < 130 and diastolic < 80:
                insights.append(f"⚠ Blood Pressure ({bp}): Elevated - monitor regularly")
            elif systolic >= 130 or diastolic > 80:
                insights.append(f"⚠ Blood Pressure ({bp}): High - consult doctor")
        except:
            pass
    
    # Glucose Analysis
    if "glucose" in vitals:
        try:
            glucose = int(vitals["glucose"].replace(" mg/dL", ""))
            if 70 <= glucose <= 99:
                insights.append(f"✓ Blood Glucose ({vitals['glucose']}): Normal")
            elif 100 <= glucose <= 125:
                insights.append(f"⚠ Blood Glucose ({vitals['glucose']}): Prediabetes range")
            elif glucose >= 126:
                insights.append(f"⚠ Blood Glucose ({vitals['glucose']}): High - diabetes screening recommended")
        except:
            pass
    
    # HbA1c Analysis
    if "hba1c" in vitals:
        try:
            hba1c = float(vitals["hba1c"].replace("%", ""))
            if hba1c < 5.7:
                insights.append(f"✓ HbA1c ({vitals['hba1c']}): Normal")
            elif 5.7 <= hba1c <= 6.4:
                insights.append(f"⚠ HbA1c ({vitals['hba1c']}): Prediabetes")
            elif hba1c >= 6.5:
                insights.append(f"⚠ HbA1c ({vitals['hba1c']}): Diabetes range - consult doctor")
        except:
            pass
    
    # Cholesterol Analysis
    if "cholesterol" in vitals:
        try:
            chol = int(vitals["cholesterol"].replace(" mg/dL", ""))
            if chol < 200:
                insights.append(f"✓ Cholesterol ({vitals['cholesterol']}): Desirable")
            elif 200 <= chol <= 239:
                insights.append(f"⚠ Cholesterol ({vitals['cholesterol']}): Borderline high")
            elif chol >= 240:
                insights.append(f"⚠ Cholesterol ({vitals['cholesterol']}): High - lifestyle changes recommended")
        except:
            pass
    
    # Hemoglobin Analysis
    if "hemoglobin" in vitals:
        try:
            hgb = float(vitals["hemoglobin"].replace(" g/dL", ""))
            if 13.5 <= hgb <= 17.5:  # Male range
                insights.append(f"✓ Hemoglobin ({vitals['hemoglobin']}): Normal (male range)")
            elif 12.0 <= hgb <= 15.5:  # Female range
                insights.append(f"✓ Hemoglobin ({vitals['hemoglobin']}): Normal (female range)")
            elif hgb < 12.0:
                insights.append(f"⚠ Hemoglobin ({vitals['hemoglobin']}): Low - possible anemia")
            elif hgb > 17.5:
                insights.append(f"⚠ Hemoglobin ({vitals['hemoglobin']}): High - consult doctor")
        except:
            pass
    
    if not insights:
        return "No specific vitals detected. The AI will analyze the full report text."
    
    return "\n".join(insights)

if __name__ == "__main__":
    # Test the parser
    print("Medical Report Parser Test")
    print("=" * 50)
    print("Tesseract path:", pytesseract.pytesseract.tesseract_cmd)
    print("\nSupported formats:")
    print("- Images: JPEG, PNG, BMP, TIFF")
    print("- Documents: PDF, TXT, DOCX")
    print("\nExample usage:")
    print('  result = parse_medical_report("report.pdf")')
    print('  vitals = extract_vitals(result["text"])')
    print('  insights = analyze_report_health(result["text"], vitals)')
