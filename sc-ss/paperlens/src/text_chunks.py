from typing import Dict, List


def split_words_with_overlap(
    words: List[str],
    chunk_size: int = 220,
    overlap: int = 40,
) -> List[List[str]]:
    """Split words into overlapping chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap cannot be negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size
        chunks.append(words[start:end])

        if end >= len(words):
            break

        start = end - overlap

    return chunks


def make_text_chunks(
    pages: List[Dict],
    chunk_size: int = 220,
    overlap: int = 40,
) -> List[Dict]:
    """
    Convert page-level paper text into searchable chunks.

    This version chunks within each page so citation page numbers stay reliable.
    """
    all_chunks = []

    for page in pages:
        words = page["text"].split()
        word_chunks = split_words_with_overlap(
            words=words,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        for chunk_index, word_chunk in enumerate(word_chunks, start=1):
            chunk_text = " ".join(word_chunk)

            if not chunk_text.strip():
                continue

            chunk_id = (
                f"{page['file_name'].replace('.pdf', '')}"
                f"_page_{page['page_number']}"
                f"_chunk_{chunk_index}"
            )

            all_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "paper_title": page["paper_title"],
                    "file_name": page["file_name"],
                    "page_number": page["page_number"],
                    "chunk_number": chunk_index,
                    "text": chunk_text,
                    "word_count": len(word_chunk),
                }
            )

    return all_chunks