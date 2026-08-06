#!/usr/bin/env python3
"""
Full PDF OCR using olmOCR Python Toolkit
This processes the ENTIRE PDF without the 10-page demo limit.

Requirements:
    pip install olmocr[gpu]
    
Usage:
    python ocr-automation/ocr-full-python.py
"""

import os
import sys
import json
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

# Configuration
PDF_PATH = "/teamspace/studios/this_studio/works/tests/ocrwitholmcor/92d1b467-89a5-43ec-b155-74a815680461.pdf"
BASE_OUTPUT_DIR = "/teamspace/studios/this_studio/works/ocr-automation/outputs"
WORKSPACE_DIR = "/teamspace/studios/this_studio/works/ocr-automation/olmocr-workspace"

def check_olmocr_installed():
    """Check if olmOCR is installed"""
    try:
        result = subprocess.run(
            ["python", "-m", "olmocr.pipeline", "--help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False

def install_olmocr():
    """Install olmOCR package"""
    print("Installing olmOCR...")
    subprocess.run([
        sys.executable, "-m", "pip", "install", "olmocr[gpu]",
        "--extra-index-url", "https://download.pytorch.org/whl/cu128"
    ], check=True)
    print("olmOCR installed successfully!")

def run_olmocr_pipeline(pdf_path, output_dir):
    """Run olmOCR pipeline on PDF"""
    print(f"Processing PDF: {pdf_path}")
    print(f"Output directory: {output_dir}")
    
    # Create workspace
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    
    # Run olmOCR pipeline
    cmd = [
        sys.executable, "-m", "olmocr.pipeline",
        WORKSPACE_DIR,
        "--markdown",
        "--pdfs", pdf_path
    ]
    
    print(f"Running: {' '.join(cmd)}")
    print("This may take several minutes for large PDFs...")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode != 0:
            print(f"Warning: olmOCR returned non-zero exit code: {result.returncode}")
            if result.stderr:
                print(f"Error output: {result.stderr}")
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("Error: Processing timed out after 10 minutes")
        return False
    except Exception as e:
        print(f"Error running olmOCR: {e}")
        return False

def extract_results(output_dir):
    """Extract and organize OCR results"""
    # Find markdown files in workspace
    markdown_files = list(Path(WORKSPACE_DIR).glob("*.md"))
    
    if not markdown_files:
        print("No markdown files found in workspace")
        return None
    
    all_pages = []
    combined_text = []
    
    for md_file in sorted(markdown_files):
        content = md_file.read_text()
        
        # Extract page content (remove any metadata headers)
        lines = content.split('\n')
        clean_lines = []
        
        for line in lines:
            # Skip metadata lines
            if line.startswith('---') or line.startswith('page:') or line.startswith('tokens:'):
                continue
            clean_lines.append(line)
        
        page_content = '\n'.join(clean_lines).strip()
        
        if page_content:
            all_pages.append({
                "source_file": md_file.name,
                "content": page_content
            })
            combined_text.append(page_content)
    
    return {
        "pages": all_pages,
        "combined_text": '\n\n'.join(combined_text)
    }

def save_results(output_dir, results, pdf_path, processing_time):
    """Save results to organized output folder"""
    
    # Create structured lines
    structured_lines = []
    for page in results["pages"]:
        page_lines = page["content"].split('\n')
        for line in page_lines:
            trimmed = line.strip()
            if len(trimmed) > 30:
                structured_lines.append(trimmed)
    
    # Remove duplicates
    seen = set()
    unique_lines = []
    for line in structured_lines:
        normalized = line.lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_lines.append(line)
    
    # Create output
    output = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sourcePdf": os.path.basename(pdf_path),
            "method": "olmOCR Python Toolkit",
            "processingTimeSeconds": processing_time,
            "outputDirectory": output_dir
        },
        "content": {
            "pages": results["pages"],
            "combinedText": results["combined_text"],
            "structuredLines": unique_lines
        },
        "stats": {
            "totalPages": len(results["pages"]),
            "uniqueLines": len(unique_lines),
            "totalCharacters": len(results["combined_text"])
        }
    }
    
    # Save JSON
    json_path = os.path.join(output_dir, "ocr-result.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    # Save text
    txt_path = os.path.join(output_dir, "ocr-result.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        for i, page in enumerate(results["pages"], 1):
            f.write(f"=== Page {i} ({page['source_file']}) ===\n")
            f.write(page["content"])
            f.write("\n\n")
    
    # Save run info
    run_info = {
        "timestamp": datetime.now().isoformat(),
        "pdfFile": pdf_path,
        "outputDirectory": output_dir,
        "pagesExtracted": len(results["pages"]),
        "method": "olmOCR Python Toolkit"
    }
    with open(os.path.join(output_dir, "run-info.json"), 'w') as f:
        json.dump(run_info, f, indent=2)
    
    return output

def main():
    print("=" * 60)
    print("Full PDF OCR using olmOCR Python Toolkit")
    print("=" * 60)
    print(f"PDF: {PDF_PATH}")
    print("=" * 60)
    
    # Check PDF exists
    if not os.path.exists(PDF_PATH):
        print(f"Error: PDF not found at {PDF_PATH}")
        sys.exit(1)
    
    # Check/install olmOCR
    if not check_olmocr_installed():
        print("olmOCR not found. Installing...")
        try:
            install_olmocr()
        except Exception as e:
            print(f"Failed to install olmOCR: {e}")
            print("\nAlternative: Install manually with:")
            print("  pip install olmocr[gpu] --extra-index-url https://download.pytorch.org/whl/cu128")
            sys.exit(1)
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    output_dir = os.path.join(BASE_OUTPUT_DIR, f"run-{timestamp}-full")
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"\nOutput directory: {output_dir}")
    
    # Run processing
    start_time = datetime.now()
    success = run_olmocr_pipeline(PDF_PATH, output_dir)
    end_time = datetime.now()
    processing_time = (end_time - start_time).total_seconds()
    
    if not success:
        print("\nProcessing completed with warnings or errors")
    
    # Extract and save results
    print("\nExtracting results...")
    results = extract_results(output_dir)
    
    if results:
        output = save_results(output_dir, results, PDF_PATH, processing_time)
        
        print("\n" + "=" * 60)
        print("OCR Complete!")
        print("=" * 60)
        print(f"Output Directory: {output_dir}")
        print(f"Pages Extracted: {output['stats']['totalPages']}")
        print(f"Unique Lines: {output['stats']['uniqueLines']}")
        print(f"Total Characters: {output['stats']['totalCharacters']}")
        print(f"Processing Time: {processing_time:.1f} seconds")
        print("=" * 60)
    else:
        print("\nNo results extracted. Check workspace for output files.")
        print(f"Workspace: {WORKSPACE_DIR}")

if __name__ == "__main__":
    main()
