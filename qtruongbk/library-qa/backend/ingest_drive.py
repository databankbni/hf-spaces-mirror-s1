"""
Module tải PDF từ Google Drive.
Hỗ trợ:
  - Folder URL (public/private): tải toàn bộ PDF trong folder
  - Single file URL (public/private): tải đúng 1 file PDF
"""

import re
import logging
from pathlib import Path
from typing import Generator, Literal

from config import TEMP_PDF_DIR

logger = logging.getLogger(__name__)


# ── Phân loại URL ──────────────────────────────────────────────────────────────

_FOLDER_RE = re.compile(r"folders/([a-zA-Z0-9_-]+)")
_FILE_RE = re.compile(r"/file/d/([a-zA-Z0-9_-]+)")
_OPEN_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")
_BARE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{20,}$")


def classify_drive_url(url_or_id: str) -> tuple[Literal["folder", "file"], str]:
    """Phân loại URL/ID Drive và trả về (kind, id).
    - folder: URL có "/folders/{id}"
    - file: URL có "/file/d/{id}" hoặc "?id={id}"
    - ID thô: mặc định là folder (giữ tương thích với hành vi cũ)
    """
    s = (url_or_id or "").strip()
    m = _FOLDER_RE.search(s)
    if m:
        return "folder", m.group(1)
    m = _FILE_RE.search(s)
    if m:
        return "file", m.group(1)
    m = _OPEN_RE.search(s)
    if m:
        return "file", m.group(1)
    if _BARE_ID_RE.match(s):
        return "folder", s
    raise ValueError(
        f"Không nhận diện được URL Google Drive: {s!r}. "
        "Hỗ trợ folder ('/folders/...') hoặc file ('/file/d/...')."
    )


def extract_folder_id(url_or_id: str) -> str:
    """Trích xuất folder ID từ URL Drive hoặc trả về ID thô (giữ tương thích cũ)."""
    match = _FOLDER_RE.search(url_or_id)
    if match:
        return match.group(1)
    return url_or_id.strip()


# ── Chế độ PUBLIC (gdown) ──────────────────────────────────────────────────────

def _iter_pdfs_public(folder_id: str) -> Generator[tuple[Path, str], None, None]:
    """Tải PDF từ folder Drive public bằng gdown — không cần credentials."""
    try:
        import gdown
    except ImportError:
        raise RuntimeError("Thiếu thư viện: pip install gdown")

    output_dir = TEMP_PDF_DIR / folder_id
    output_dir.mkdir(exist_ok=True)

    logger.info("Đang tải folder public: %s", folder_id)
    gdown.download_folder(
        id=folder_id,
        output=str(output_dir),
        quiet=True,
        use_cookies=False,
    )

    pdf_files = sorted(output_dir.rglob("*.pdf"))
    if not pdf_files:
        logger.warning("Không tải được file nào — kiểm tra folder có public không")
        return

    logger.info("Folder public có %d file PDF đã tải", len(pdf_files))
    for path in pdf_files:
        yield path, path.name


def _iter_pdf_file_public(file_id: str) -> Generator[tuple[Path, str], None, None]:
    """Tải 1 file PDF public từ Drive bằng gdown."""
    try:
        import gdown
    except ImportError:
        raise RuntimeError("Thiếu thư viện: pip install gdown")

    output_dir = TEMP_PDF_DIR / f"file_{file_id}"
    output_dir.mkdir(exist_ok=True)

    # gdown 6.x: nếu output là thư mục đang tồn tại thì sẽ append tên gốc của Drive
    logger.info("Đang tải file public: %s", file_id)
    result = gdown.download(
        id=file_id,
        output=str(output_dir) + "/",
        quiet=True,
    )
    if not result:
        logger.warning("gdown không tải được file (kiểm tra link có public không): %s", file_id)
        return

    path = Path(result)
    if path.suffix.lower() != ".pdf":
        logger.warning("File tải về không phải PDF: %s", path.name)
        return
    yield path, path.name


# ── Chế độ PRIVATE (Google Drive API + service account) ───────────────────────

def _build_service():
    from drive_auth import get_drive_service
    return get_drive_service(["https://www.googleapis.com/auth/drive.readonly"])


def _list_pdfs_in_folder(service, folder_id: str) -> list[dict]:
    """Đệ quy liệt kê PDF trong folder private (kể cả thư mục con)."""
    results = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
                pageSize=100,
            )
            .execute()
        )
        for item in resp.get("files", []):
            if item["mimeType"] == "application/vnd.google-apps.folder":
                results.extend(_list_pdfs_in_folder(service, item["id"]))
            elif item["mimeType"] == "application/pdf":
                results.append(item)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def _iter_pdfs_private(folder_id: str) -> Generator[tuple[Path, str], None, None]:
    """Tải PDF từ folder private qua service account."""
    from googleapiclient.http import MediaIoBaseDownload

    service = _build_service()
    logger.info("Đang liệt kê PDF trong folder private: %s", folder_id)

    pdf_files = _list_pdfs_in_folder(service, folder_id)
    logger.info("Tìm thấy %d file PDF", len(pdf_files))

    for item in pdf_files:
        dest = TEMP_PDF_DIR / f"{item['id']}.pdf"
        if not dest.exists():
            logger.info("Đang tải: %s", item["name"])
            request = service.files().get_media(fileId=item["id"])
            with open(dest, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
        else:
            logger.info("Dùng cache: %s", item["name"])
        yield dest, item["name"]


def _iter_pdf_file_private(file_id: str) -> Generator[tuple[Path, str], None, None]:
    """Tải 1 file PDF private từ Drive qua service account."""
    from googleapiclient.http import MediaIoBaseDownload

    service = _build_service()
    meta = service.files().get(fileId=file_id, fields="id,name,mimeType").execute()
    if meta.get("mimeType") != "application/pdf":
        logger.warning("File %s không phải PDF (mimeType=%s)", meta.get("name"), meta.get("mimeType"))
        return

    name = meta["name"]
    dest = TEMP_PDF_DIR / f"{file_id}.pdf"
    if not dest.exists():
        logger.info("Đang tải file private: %s", name)
        request = service.files().get_media(fileId=file_id)
        with open(dest, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
    else:
        logger.info("Dùng cache: %s", name)
    yield dest, name


# ── Entry point chính ──────────────────────────────────────────────────────────

def iter_pdfs_from_drive(
    folder_url: str,
    public: bool = True,
) -> Generator[tuple[Path, str], None, None]:
    """
    Yield (local_path, file_name) cho mỗi PDF từ Drive.

    Args:
        folder_url: URL hoặc ID — chấp nhận cả folder URL và single-file URL.
        public: True  = link public, dùng gdown, không cần credentials.json
                False = link private, cần credentials.json + share quyền truy cập
    """
    kind, drive_id = classify_drive_url(folder_url)
    logger.info("Drive URL phân loại: kind=%s id=%s", kind, drive_id)
    if kind == "folder":
        if public:
            yield from _iter_pdfs_public(drive_id)
        else:
            yield from _iter_pdfs_private(drive_id)
    else:  # file
        if public:
            yield from _iter_pdf_file_public(drive_id)
        else:
            yield from _iter_pdf_file_private(drive_id)
