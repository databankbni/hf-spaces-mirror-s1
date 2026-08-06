import re
from typing import List


def clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\x00-\x7F]+', ' ', text)
    text = re.sub(r'\.{3,}', '...', text)
    text = text.strip()
    return text


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    if not text.strip():
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= chunk_size:
            current_chunk += " " + sentence if current_chunk else sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            if len(sentence) > chunk_size:
                words = sentence.split()
                temp = ""
                for word in words:
                    if len(temp) + len(word) <= chunk_size:
                        temp += " " + word if temp else word
                    else:
                        if temp:
                            chunks.append(temp.strip())
                        temp = word
                if temp:
                    current_chunk = temp
            else:
                current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk.strip())

    if overlap > 0 and len(chunks) > 1:
        overlapped = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                prev_words = chunks[i - 1].split()[-overlap // 10:]
                chunk = " ".join(prev_words) + " " + chunk
            overlapped.append(chunk.strip())
        return overlapped

    return chunks


def remove_duplicates(chunks: List[str]) -> List[str]:
    seen = set()
    unique = []
    for chunk in chunks:
        normalized = re.sub(r'\s+', ' ', chunk.lower().strip())
        if normalized not in seen and len(normalized) > 20:
            seen.add(normalized)
            unique.append(chunk)
    return unique


def merge_short_chunks(chunks: List[str], min_length: int = 100) -> List[str]:
    merged = []
    buffer = ""
    for chunk in chunks:
        if len(buffer) + len(chunk) < min_length * 2:
            buffer = buffer + " " + chunk if buffer else chunk
        else:
            if buffer:
                merged.append(buffer.strip())
            buffer = chunk
    if buffer:
        merged.append(buffer.strip())
    return merged
