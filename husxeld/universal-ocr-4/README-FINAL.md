# OCR Automation - Complete Solution

Automated OCR extraction from PDFs using multiple methods to bypass limitations.

## Problem Solved

The olmOCR web demo (https://olmocr.allenai.org/) has a **10-page preview limit**. This solution bypasses that limit by:

1. **Splitting** the PDF into smaller chunks (6 pages each)
2. **Processing** each chunk through olmOCR separately
3. **Combining** all results into a single output

## Folder Structure

```
ocr-automation/
├── olmocr-split-combine.py    # Main script (RECOMMENDED)
├── ocr-tesseract-full.py      # Alternative: Tesseract OCR
├── ocr-automation.js          # Legacy: Single-page extraction
├── temp-split/                # Temporary chunk files
└── outputs/
    └── run-YYYY-MM-DDTHH-MM-SS-split-combine/
        ├── ocr-result.json    # Full structured output
        ├── ocr-result.txt     # Clean text file
        └── run-info.json      # Run metadata
```

## Quick Start

```bash
# Run the split & combine method (BEST QUALITY)
python3 ocr-automation/olmocr-split-combine.py

# Output will be in:
# ocr-automation/outputs/run-TIMESTAMP-split-combine/
```

## Requirements

```bash
# For split & combine method (recommended)
pip install pypdf playwright
playwright install chromium

# For Tesseract method (offline, lower quality)
pip install pytesseract pdf2image pillow opencv-python-headless
sudo apt-get install tesseract-ocr tesseract-ocr-hin poppler-utils
```

## Methods Comparison

| Method | Quality | Speed | Pages | Notes |
|--------|---------|-------|-------|-------|
| **olmOCR Split & Combine** | ⭐⭐⭐⭐⭐ | Medium | Unlimited | Best for Hindi/English docs |
| Tesseract OCR | ⭐⭐⭐ | Slow | Unlimited | Works offline, needs preprocessing |
| Single Web Run | ⭐⭐⭐⭐⭐ | Fast | 10 max | Limited by demo |

## Output Format

### JSON (`ocr-result.json`)

```json
{
  "metadata": {
    "timestamp": "2026-02-20T14:33:01",
    "sourcePdf": "92d1b467-89a5-43ec-b155-74a815680461.pdf",
    "method": "olmOCR with PDF splitting",
    "outputDirectory": "..."
  },
  "content": {
    "pages": [
      {
        "originalPage": 267,
        "content": "गांधी युग\nमहात्मा गांधी का जन्म..."
      }
    ],
    "combinedText": "Full text combined...",
    "structuredLines": ["Line 1", "Line 2", ...]
  },
  "stats": {
    "totalPages": 15,
    "uniqueLines": 76,
    "totalCharacters": 8082
  }
}
```

### Text (`ocr-result.txt`)

```
=== Page 267 ===
गांधी युग
महात्मा गांधी का जन्म 2 अक्टूबर, 1869 ई. को गुजरात के पोरबंदर में हुआ।
...

=== Page 370 ===
1891 ई. में पढ़ाई पूरी कर भारत लौटे...
```

## How It Works

### Split & Combine Method

1. **Split PDF**: Uses `pypdf` to divide PDF into 6-page chunks
2. **Process Each**: Opens olmOCR website for each chunk
3. **Wait**: Allows full OCR processing (~60s per chunk)
4. **Extract**: Scrapes all page content with regex
5. **Combine**: Merges results, adjusts page numbers
6. **Clean**: Removes UI noise, deduplicates lines

### Page Number Tracking

The script preserves original page numbers from the PDF:
- If PDF has internal page numbers (like 267, 370, etc.), those are kept
- Sequential page order is maintained

## Example Output

For a 17-page Gandhi biography PDF:

```
Total Pages Extracted: 15
Unique Lines: 76
Total Characters: 8,082
```

Content includes:
- Birth and early life (1869, Gujarat)
- Education in London (LLB)
- South Africa experience
- Satyagraha movements
- Return to India (1915)
- Champaran satyagraha (1917)
- Various titles and honors

## Troubleshooting

### "No module named 'pypdf'"
```bash
pip install pypdf
```

### "Browser not found"
```bash
playwright install chromium
```

### "Tesseract not found"
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-hin
```

### Extraction stops at 10 pages
This is expected for single-run method. Use `olmocr-split-combine.py` instead.

### Poor OCR quality
- Ensure PDF has clear text/images
- Try Tesseract with preprocessing: `ocr-tesseract-improved.py`
- For scanned documents, increase DPI in conversion

## Configuration

Edit top of `olmocr-split-combine.py`:

```python
PDF_PATH = "/path/to/your.pdf"       # Input PDF
PAGES_PER_CHUNK = 6                   # Pages per batch
BASE_OUTPUT_DIR = ".../outputs"      # Output location
```

## Files Created

Each run creates:
- `ocr-result.json` - Full structured data
- `ocr-result.txt` - Readable text file
- `run-info.json` - Metadata about the run

All saved in timestamped folders under `outputs/`.

## Limitations

- olmOCR demo may have rate limits for many requests
- Some pages (pure images/diagrams) may not extract text
- Processing time: ~60s per 6-page chunk

## Alternative: Local olmOCR

For unlimited processing without demo limits:

```bash
pip install olmocr[gpu] --extra-index-url https://download.pytorch.org/whl/cu128
python -m olmocr.pipeline ./output --markdown --pdfs your.pdf
```

Requires: NVIDIA GPU with 12+ GB VRAM.
