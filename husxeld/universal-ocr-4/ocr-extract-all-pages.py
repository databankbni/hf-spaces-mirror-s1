#!/usr/bin/env python3
"""
Full PDF Text Extraction using PyMuPDF (fitz)
Extracts text from ALL pages of the PDF.

For PDFs with text layers (not scanned images).
If PDF has scanned images, OCR would be needed.

Usage:
    python ocr-automation/ocr-extract-all-pages.py
"""

import os
import sys
import json
import fitz  # PyMuPDF
import pymupdf4llm
from pathlib import Path
from datetime import datetime

# Configuration
PDF_PATH = "/teamspace/studios/this_studio/works/tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf"
BASE_OUTPUT_DIR = "/teamspace/studios/this_studio/works/ocr-automation/outputs"

def extract_text_with_pymupdf4llm(pdf_path):
    """Extract text using pymupdf4llm (better formatting)"""
    try:
        md_text = pymupdf4llm.to_markdown(pdf_path)
        return md_text
    except Exception as e:
        print(f"pymupdf4llm failed: {e}")
        return None

def extract_text_with_fitz(pdf_path):
    """Extract text using PyMuPDF fitz"""
    doc = fitz.open(pdf_path)
    pages_data = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        
        if text.strip():
            pages_data.append({
                "page_number": page_num + 1,
                "pdf_page_number": page_num + 1,
                "content": text.strip()
            })
    
    doc.close()
    return pages_data

def clean_text(text):
    """Clean extracted text"""
    # Remove excessive whitespace
    lines = text.split('\n')
    clean_lines = []
    
    for line in lines:
        cleaned = line.strip()
        if cleaned:  # Skip empty lines
            clean_lines.append(cleaned)
    
    return '\n'.join(clean_lines)

def deduplicate_lines(lines):
    """Remove duplicate lines"""
    seen = set()
    unique = []
    
    for line in lines:
        normalized = line.strip().lower()
        if normalized not in seen and len(line.strip()) > 20:
            seen.add(normalized)
            unique.append(line.strip())
    
    return unique

def save_results(output_dir, pages_data, combined_text, pdf_path, method):
    """Save results to output files"""
    
    # Create structured lines
    all_lines = []
    for page in pages_data:
        page_lines = page["content"].split('\n')
        all_lines.extend(page_lines)
    
    unique_lines = deduplicate_lines(all_lines)
    
    # Create output
    output = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sourcePdf": os.path.basename(pdf_path),
            "method": method,
            "outputDirectory": output_dir
        },
        "content": {
            "pages": pages_data,
            "combinedText": combined_text,
            "structuredLines": unique_lines
        },
        "stats": {
            "totalPages": len(pages_data),
            "uniqueLines": len(unique_lines),
            "totalCharacters": len(combined_text)
        }
    }
    
    # Save JSON
    json_path = os.path.join(output_dir, "ocr-result.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # Save text file
    txt_path = os.path.join(output_dir, "ocr-result.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        for page in pages_data:
            f.write(f"=== Page {page['page_number']} ===\n")
            f.write(page["content"])
            f.write("\n\n")
    
    # Save run info
    run_info = {
        "timestamp": datetime.now().isoformat(),
        "pdfFile": pdf_path,
        "outputDirectory": output_dir,
        "pagesExtracted": len(pages_data),
        "method": method
    }
    with open(os.path.join(output_dir, "run-info.json"), 'w') as f:
        json.dump(run_info, f, indent=2)
    
    return output

def main():
    print("=" * 60)
    print("Full PDF Text Extraction (All Pages)")
    print("=" * 60)
    print(f"PDF: {PDF_PATH}")
    print("=" * 60)
    
    # Check PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"Error: PDF not found at {PDF_PATH}")
        sys.exit(1)
    
    # Get PDF info
    doc = fitz.open(PDF_PATH)
    total_pages = len(doc)
    print(f"Total pages in PDF: {total_pages}")
    doc.close()
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output_dir = os.path.join(BASE_OUTPUT_DIR, f"run-{timestamp}-all-pages")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Output directory: {output_dir}")
    
    # Try pymupdf4llm first (better formatting)
    print("\nExtracting text with pymupdf4llm...")
    md_text = extract_text_with_pymupdf4llm(PDF_PATH)
    
    if md_text:
        print("pymupdf4llm extraction successful!")
        # Parse markdown into pages
        pages_data = [{
            "page_number": 1,
            "pdf_page_number": 1,
            "content": md_text
        }]
        combined_text = md_text
        method = "pymupdf4llm"
    else:
        # Fallback to fitz
        print("Falling back to fitz extraction...")
        pages_data = extract_text_with_fitz(PDF_PATH)
        combined_text = '\n\n'.join([p["content"] for p in pages_data])
        method = "PyMuPDF fitz"
    
    # Clean combined text
    combined_text = clean_text(combined_text)
    
    # Save results
    print("\nSaving results...")
    output = save_results(output_dir, pages_data, combined_text, PDF_PATH, method)
    
    print("\n" + "=" * 60)
    print("Extraction Complete!")
    print("=" * 60)
    print(f"Output Directory: {output_dir}")
    print(f"Pages Extracted: {output['stats']['totalPages']}")
    print(f"Unique Lines: {output['stats']['uniqueLines']}")
    print(f"Total Characters: {output['stats']['totalCharacters']}")
    print(f"Method: {method}")
    print("=" * 60)
    
    # Show first few lines of content
    print("\nFirst 500 characters of extracted text:")
    print("-" * 40)
    print(combined_text[:500])
    print("-" * 40)

if __name__ == "__main__":
    main()
