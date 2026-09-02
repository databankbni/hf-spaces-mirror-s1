from urllib.parse import urlparse


def normalize_source_url(url: str) -> str:
    normalized = url.strip()
    return normalized if normalized.endswith("/") else normalized + "/"


def format_chapter_url(url: str) -> str:
    url = url.strip()
    if url.endswith(".htm"):
        return url.rsplit('.', 1)[0] + "/"
    if not url.endswith("/"):
        return url + "/"
    return url
