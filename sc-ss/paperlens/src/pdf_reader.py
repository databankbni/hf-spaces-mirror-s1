from pathlib import Path
from typing import Dict, List

from pypdf import PdfReader


def clean_page_text(text: str) -> str:
    """Clean extracted PDF text while keeping the original meaning intact."""
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]

    return " ".join(lines)


def read_pdf_pages(pdf_path: str, paper_title: str | None = None) -> List[Dict]:
    """
    Read a PDF and return one record per page.

    Each page record contains:
    - paper_title
    - file_name
    - page_number
    - text
    """
    path = Path(pdf_path)

    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    title = paper_title or path.stem.replace("_", " ").title()
    reader = PdfReader(str(path))

    pages = []

    for page_index, page in enumerate(reader.pages):
        raw_text = page.extract_text() or ""
        cleaned_text = clean_page_text(raw_text)

        if not cleaned_text:
            continue

        pages.append(
            {
                "paper_title": title,
                "file_name": path.name,
                "page_number": page_index + 1,
                "text": cleaned_text,
            }
        )

    return pages


def read_many_pdfs(papers: List[Dict]) -> List[Dict]:
    """
    Read multiple PDFs.

    Expected input:
    [
        {"path": "data/papers/example.pdf", "title": "Example Paper"}
    ]
    """
    all_pages = []

    for paper in papers:
        pages = read_pdf_pages(
            pdf_path=paper["path"],
            paper_title=paper.get("title"),
        )
        all_pages.extend(pages)

    return all_pages