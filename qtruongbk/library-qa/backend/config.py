import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Load .env trước khi đọc bất kỳ biến môi trường nào
load_dotenv()

# ── Đường dẫn thư mục ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"        # Lưu file PDF tải về
INDEX_DIR = BASE_DIR / "index"      # Lưu FAISS index và metadata
CACHE_DIR = BASE_DIR / "cache"      # Cache embedding (dùng sau này)

DATA_DIR.mkdir(exist_ok=True)
INDEX_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# ── Mô hình embedding ─────────────────────────────────────────────────────────
# multilingual-MiniLM: đa ngôn ngữ, hỗ trợ tiếng Việt, dim 384, nhẹ và nhanh trên CPU
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384

# ── Cấu hình chia đoạn (chunking) ────────────────────────────────────────────
CHUNK_SIZE_TOKENS = 512     # bge-m3 hỗ trợ 8192 token, dùng chunk lớn hơn
CHUNK_OVERLAP_TOKENS = 80   # Overlap ~15% để không mất thông tin qua ranh giới

# ── Tham số truy xuất ─────────────────────────────────────────────────────────
TOP_K = 10  # Số đoạn văn bản trả về khi tìm kiếm

# ── Hybrid search (BM25 + vector) ────────────────────────────────────────────
BM25_WEIGHT = 0.3    # Trọng số BM25 (keyword match)
VECTOR_WEIGHT = 0.7  # Trọng số vector (semantic)

# ── File lưu trữ FAISS ────────────────────────────────────────────────────────
FAISS_INDEX_PATH = INDEX_DIR / "faiss.index"   # File nhị phân của FAISS
SQLITE_PATH = INDEX_DIR / "chunks.db"          # SQLite: text chunk + metadata

# ── Cấu hình LLM (DeepSeek) ───────────────────────────────────────────────────
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-pro"
LLM_MAX_TOKENS = 5000
LLM_TEMPERATURE = 0.3  # Thấp → câu trả lời ổn định, ít sáng tạo hơn

# ── Google Drive ───────────────────────────────────────────────────────────────
# Ưu tiên 1: GDRIVE_CREDENTIALS_JSON (dùng khi deploy HF Spaces — paste JSON vào HF Secret)
# Ưu tiên 2: GDRIVE_CREDENTIALS_PATH (đường dẫn file local, mặc định backend/credentials.json)
def _resolve_gdrive_credentials() -> str:
    creds_json = os.getenv("GDRIVE_CREDENTIALS_JSON")
    if creds_json:
        import json, tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
        json.dump(json.loads(creds_json), tmp)
        tmp.close()
        return tmp.name
    return os.getenv("GDRIVE_CREDENTIALS_PATH", str(BASE_DIR / "credentials.json"))

GDRIVE_CREDENTIALS_PATH = _resolve_gdrive_credentials()

# Folder Google Drive dùng để lưu FAISS index (persist qua deploy HF Spaces)
# Set GDRIVE_INDEX_FOLDER_URL = URL hoặc folder ID của Drive folder chứa index
def _extract_folder_id(url: str) -> str:
    m = re.search(r"folders/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else url.strip()

_gdrive_index_url = os.getenv("GDRIVE_INDEX_FOLDER_URL", "")
GDRIVE_INDEX_FOLDER_ID = _extract_folder_id(_gdrive_index_url) if _gdrive_index_url else ""
# Thư mục tạm chứa PDF vừa tải; xóa sau khi đã index xong
TEMP_PDF_DIR = DATA_DIR / "tmp_pdfs"
TEMP_PDF_DIR.mkdir(exist_ok=True)

# ── Xử lý theo lô (batch) ────────────────────────────────────────────────────
# Sau mỗi PDF_BATCH_SIZE file, ghi index xuống đĩa để tránh mất dữ liệu
PDF_BATCH_SIZE = 5
