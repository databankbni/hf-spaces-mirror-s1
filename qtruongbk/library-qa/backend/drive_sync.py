"""
Sync toàn bộ INDEX_DIR với Google Drive.

  push_index_to_drive() — upload tất cả file trong INDEX_DIR lên Drive folder
  pull_index_from_drive() — download tất cả file từ Drive folder về INDEX_DIR

Auth: dùng OAuth user (Gmail) nếu có oauth_client.json/oauth_token.json,
fallback Service Account. Xem drive_auth.py.
"""

from __future__ import annotations

import logging
import shutil

from config import GDRIVE_INDEX_FOLDER_ID, INDEX_DIR
from drive_auth import get_drive_service

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _build_service():
    return get_drive_service(SCOPES)


def push_index_to_drive(folder_id: str = GDRIVE_INDEX_FOLDER_ID) -> None:
    """Upload toàn bộ file trong INDEX_DIR lên Google Drive folder (replace nếu đã có)."""
    if not folder_id:
        logger.warning("push_index: GDRIVE_INDEX_FOLDER_ID chưa cấu hình, bỏ qua")
        return

    from googleapiclient.http import MediaFileUpload

    try:
        svc = _build_service()
        files = [f for f in INDEX_DIR.iterdir() if f.is_file()]
        if not files:
            logger.warning("push_index: INDEX_DIR trống, không có gì để upload")
            return

        for local_path in files:
            filename = local_path.name
            q = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
            existing = svc.files().list(q=q, fields="files(id,name)").execute().get("files", [])
            media = MediaFileUpload(str(local_path), resumable=True)

            if existing:
                file_id = existing[0]["id"]
                svc.files().update(fileId=file_id, media_body=media).execute()
                logger.info("push_index: cập nhật %s (id=%s)", filename, file_id)
            else:
                metadata = {"name": filename, "parents": [folder_id]}
                result = svc.files().create(body=metadata, media_body=media, fields="id").execute()
                logger.info("push_index: tạo mới %s (id=%s)", filename, result["id"])

        logger.info("push_index: hoàn tất — đã sync %d file lên Drive", len(files))

    except Exception:
        logger.exception("push_index: lỗi khi upload index lên Drive")


def pull_index_from_drive(folder_id: str = GDRIVE_INDEX_FOLDER_ID) -> bool:
    """Download toàn bộ file từ Drive folder về INDEX_DIR (replace nếu đã có).
    Trả về True nếu tải được ít nhất 1 file.
    """
    if not folder_id:
        logger.info("pull_index: GDRIVE_INDEX_FOLDER_ID chưa cấu hình, bỏ qua")
        return False

    from googleapiclient.http import MediaIoBaseDownload

    try:
        svc = _build_service()
        q = f"'{folder_id}' in parents and trashed=false"
        drive_files = svc.files().list(q=q, fields="files(id,name)").execute().get("files", [])

        if not drive_files:
            logger.info("pull_index: folder Drive trống, bỏ qua")
            return False

        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        pulled = 0

        for item in drive_files:
            local_path = INDEX_DIR / item["name"]
            request = svc.files().get_media(fileId=item["id"])

            with open(local_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

            logger.info("pull_index: đã tải %s (%d bytes)", item["name"], local_path.stat().st_size)
            pulled += 1

        logger.info("pull_index: hoàn tất — đã sync %d file từ Drive", pulled)
        return pulled > 0

    except Exception:
        logger.exception("pull_index: lỗi khi tải index từ Drive")
        return False


def clear_local_index() -> int:
    """Xóa toàn bộ dữ liệu trong INDEX_DIR.

    Trả về số mục (file + folder) đã xóa.
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    deleted = 0
    for path in INDEX_DIR.iterdir():
        try:
            if path.is_file():
                path.unlink()
                deleted += 1
            elif path.is_dir():
                shutil.rmtree(path)
                deleted += 1
        except Exception:
            logger.exception("clear_local_index: lỗi khi xóa %s", path)
    logger.info("clear_local_index: đã xóa %d mục trong %s", deleted, INDEX_DIR)
    return deleted


def clear_drive_index(folder_id: str = GDRIVE_INDEX_FOLDER_ID) -> int:
    """Xóa toàn bộ file trong thư mục Google Drive đã cấu hình.

    Trả về số file đã xóa.
    """
    if not folder_id:
        logger.warning("clear_drive_index: GDRIVE_INDEX_FOLDER_ID chưa cấu hình, bỏ qua")
        return 0

    try:
        svc = _build_service()
        q = f"'{folder_id}' in parents and trashed=false"
        drive_files = svc.files().list(q=q, fields="files(id,name)").execute().get("files", [])

        if not drive_files:
            logger.info("clear_drive_index: folder Drive trống, không có gì để xóa")
            return 0

        deleted = 0
        for item in drive_files:
            svc.files().delete(fileId=item["id"]).execute()
            logger.info("clear_drive_index: đã xóa %s (id=%s)", item["name"], item["id"])
            deleted += 1

        logger.info("clear_drive_index: đã xóa %d file khỏi Drive folder %s", deleted, folder_id)
        return deleted

    except Exception:
        logger.exception("clear_drive_index: lỗi khi xóa file trên Drive")
        return 0
