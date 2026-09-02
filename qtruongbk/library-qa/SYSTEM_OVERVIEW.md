# Tổng quan hệ thống RAG

---

## 1. Kiến trúc tổng thể

```
┌─────────────────────────────────────────────────────────────────┐
│                        NGƯỜI DÙNG                               │
│                   (trình duyệt / React Native)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP
              ┌──────────────┴──────────────┐
              │                             │
              ▼                             ▼
     POST /index                  POST /query/stream (SSE)
  (lần đầu dùng)                   (mỗi khi hỏi — chạy chữ)
              │                             │
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │        FastAPI Backend       │
              │         (api.py)            │
              └──────────────┬──────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
  Google Drive          FAISS Index           DeepSeek API
  (ingest_drive)      (vector_store)          (query.py)
  chunking.py          chunks.db
  embedding.py
```

---

## 2. Luồng INDEX (chạy 1 lần khi có tài liệu mới)

```
Người dùng paste URL Drive
         │
         ▼
┌─────────────────────┐
│  1. Xác thực Drive  │  credentials.json (service account)
│  ingest_drive.py    │
└──────────┬──────────┘
           │  liệt kê đệ quy tất cả PDF
           ▼
┌─────────────────────┐
│  2. Tải PDF         │  từng file một → backend/data/tmp_pdfs/
│  (streaming 4MB/lần)│  ← KHÔNG load hết vào RAM cùng lúc
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. Trích xuất text │  pdfplumber đọc từng trang
│  chunking.py        │  → tách đoạn văn → gộp ~700 token
│                     │  → overlap 100 token giữa các chunk
└──────────┬──────────┘
           │  danh sách Chunk objects
           ▼
┌─────────────────────┐
│  4. Tạo Embedding   │  all-MiniLM-L6-v2 chạy LOCAL trên CPU
│  embedding.py       │  batch 64 chunk/lần → vector float32 (384 chiều)
│                     │  ← KHÔNG gọi API ngoài, MIỄN PHÍ
└──────────┬──────────┘
           │  numpy array (N × 384)
           ▼
┌─────────────────────┐
│  5. Lưu trữ         │  FAISS: lưu vectors vào faiss.index
│  vector_store.py    │  SQLite: lưu text + metadata vào chunks.db
│                     │  → ghi xuống đĩa sau mỗi 5 file (batch)
└─────────────────────┘
           │
           ▼
     Hoàn tất index
  (file đã index được
   ghi vào SQLite →
   lần sau tự skip)
```

---

## 3. Luồng QUERY (mỗi khi người dùng hỏi)

```
Người dùng nhập câu hỏi
         │
         ▼
┌─────────────────────┐
│  1. Embed câu hỏi   │  all-MiniLM-L6-v2 LOCAL
│  embedding.py       │  → vector (1 × 384)
│                     │  ← MIỄN PHÍ
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Tìm kiếm FAISS  │  so sánh cosine similarity
│  vector_store.py    │  → trả về top-5 chunk id
│                     │  → đọc text từ SQLite (chỉ 5 row)
└──────────┬──────────┘
           │  5 đoạn văn liên quan nhất
           ▼
┌─────────────────────┐
│  3. Xây dựng Prompt │  System: chống hallucination
│  query.py           │  Context: 5 đoạn văn + nguồn
│                     │  Question: câu hỏi người dùng
└──────────┬──────────┘
           │  ~1500-2500 token input
           ▼
┌─────────────────────┐
│  4. Gọi DeepSeek    │  deepseek-chat API với stream=True
│  query.py           │  ← CÓ PHÍ (xem bảng bên dưới)
│  (_call_llm_stream) │  → yield từng token ngay khi DeepSeek sinh ra
└──────────┬──────────┘
           │  Server-Sent Events (text/event-stream)
           ▼
  data: {"type":"delta","text":"..."}     ← lặp lại N lần
  data: {"type":"done","sources":[...]}   ← kết thúc

  Frontend (page.tsx + sendQueryStream):
  - tạo bubble assistant rỗng
  - mỗi "delta" → append vào content (chữ chạy giống ChatGPT)
  - "done" → set sources, hiển thị nguồn trích dẫn
```

> **Tại sao streaming?** DeepSeek sinh ra ~30–50 token/s. Câu trả lời 1500 token
> = 30–50s. Trước khi có streaming, user nhìn màn hình im lặng cả phút rồi câu
> trả lời mới hiện ra cùng lúc. Streaming giúp token đầu tiên về trong 1–3s và
> chữ chạy dần — tổng thời gian không đổi nhưng UX khác hẳn.
>
> Các câu hỏi loại `library_list` / `library_stats` / `library_topics` (hỏi
> thư viện) **không gọi LLM** mà trả nguyên văn từ SQLite qua event `replace` —
> phản hồi gần như tức thì.

---

## 4. Chi phí ước tính

### 4.1 Bước INDEX — embedding tài liệu

| Thành phần | Chi phí | Ghi chú |
|---|---|---|
| Tải PDF từ Drive | **$0** | Google Drive API miễn phí (15GB/ngày) |
| Trích xuất text (pdfplumber) | **$0** | Chạy local |
| Tạo embedding (MiniLM) | **$0** | Model local, không gọi API |
| Lưu FAISS + SQLite | **$0** | File trên ổ cứng |
| **Tổng bước INDEX** | **$0** | Hoàn toàn miễn phí |

> Index 200MB PDF (~10.000 chunk) tốn khoảng **5–15 phút** trên CPU, **$0**.

---

### 4.2 Bước QUERY — mỗi câu hỏi

DeepSeek pricing (tại thời điểm viết, kiểm tra lại tại [platform.deepseek.com/pricing](https://platform.deepseek.com/pricing)):

| Model | Input (per 1M token) | Output (per 1M token) |
|---|---|---|
| deepseek-chat (V3) | $0.27 | $1.10 |

**Ước tính mỗi câu hỏi:**

```
Input  = system prompt (~150 token)
       + 5 chunk context (~2000 token)
       + câu hỏi (~50 token)
       = ~2200 token input

Output = câu trả lời (~300 token)
```

| Lượt hỏi | Token input | Token output | Chi phí |
|---|---|---|---|
| 1 câu hỏi | ~2.200 | ~300 | ~$0.0009 |
| 100 câu hỏi | ~220.000 | ~30.000 | ~$0.09 |
| 1.000 câu hỏi | ~2.200.000 | ~300.000 | ~$0.93 |
| 10.000 câu hỏi | ~22.000.000 | ~3.000.000 | ~$9.24 |

> **Tóm tắt:** ~$1 cho ~1.000 câu hỏi. Rất rẻ cho hệ thống cá nhân.

---

### 4.3 So sánh nếu dùng embedding API thay vì local

| Phương án | Embedding | Chi phí index 10.000 chunk |
|---|---|---|
| **Hiện tại** (MiniLM local) | Local CPU | **$0** |
| OpenAI text-embedding-3-small | $0.02/1M token | ~$0.14 |
| OpenAI text-embedding-3-large | $0.13/1M token | ~$0.91 |

→ Dùng local model tiết kiệm hoàn toàn chi phí embedding.

---

## 5. Checklist khởi động hệ thống

### Cần chuẩn bị (1 lần duy nhất)

```
□ Python 3.11+ đã cài
□ Node.js 18+ đã cài
□ Tài khoản DeepSeek → lấy API key
□ Google Cloud project → enable Drive API → tạo service account → tải credentials.json
□ Share thư mục Drive với email service account (quyền Viewer)
```

### Cấu hình

```
□ cd backend && cp .env.example .env
□ Điền DEEPSEEK_API_KEY vào .env
□ Đặt credentials.json vào backend/
```

### Cài thư viện

```
□ cd backend && python -m venv venv && venv\Scripts\activate
□ python -m pip install --upgrade pip
□ pip install -r requirements.txt
□ cd frontend && npm install
```

### Chạy

```
□ Terminal 1: cd backend  → uvicorn api:app --reload --port 8000
□ Terminal 2: cd frontend → npm run dev          (port 2000)
□ Mở trình duyệt: http://localhost:2000
□ Paste URL Drive → bấm Index Folder (chờ xong)
□ Bắt đầu hỏi
```

---

## 6. Cấu trúc file sau khi chạy

```
backend/
├── data/
│   └── tmp_pdfs/          ← PDF tạm tải về (có thể xóa sau index)
├── index/
│   ├── faiss.index        ← vectors (sinh ra sau lần index đầu)
│   └── chunks.db          ← text + metadata (SQLite)
├── credentials.json       ← Google service account (KHÔNG commit git)
└── .env                   ← API keys (KHÔNG commit git)
```

---

## 7. Giới hạn & mở rộng

| Giới hạn | Ngưỡng | Giải pháp khi vượt |
|---|---|---|
| RAM (FAISS) | ~500k chunk ≈ ~750MB | Đổi sang `IndexIVFFlat` |
| Ổ cứng | Tuỳ máy | Xóa tmp_pdfs sau index |
| Tốc độ index | ~50–100 trang/phút (CPU) | Tăng batch size |
| Đồng thời nhiều user | Hiện tại 1 user | Thêm async queue (Celery) |
