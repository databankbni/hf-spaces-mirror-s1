---
title: RAG Library API
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# RAG Library API

FastAPI backend cho hệ thống RAG thư viện tài liệu PDF (Google Drive → FAISS + BM25 hybrid → DeepSeek LLM).

## Endpoints

- `POST /index` — Index thư mục Google Drive
- `POST /index/stream` — Index có stream tiến độ (SSE)
- `GET  /library` — Danh sách tài liệu
- `GET  /library/stats` — Thống kê
- `GET  /library/{doc_name}` — Chi tiết tài liệu
- `POST /query` — Hỏi đáp
- `POST /query/stream` — Hỏi đáp streaming
- `POST /diagnostic-report` — Tạo báo cáo phân tích chuyên sâu từ prompt hồ sơ bệnh nhân, không dùng RAG
- `POST /web_search` — Tìm kiếm internet
- `GET  /health` — Health check

### `POST /diagnostic-report`

Request:

```json
{
  "question": "Prompt phân tích đầy đủ từ hồ sơ bệnh nhân...",
  "history": [],
  "metadata": {
    "source": "export_pdf",
    "report_type": "tcm_diagnostic"
  }
}
```

Response cùng format với `/query`:

```json
{
  "answer": "<h2>I. PHÂN TÍCH...</h2>...",
  "sources": [],
  "needs_web_search": false
}
```

## Secrets cần cấu hình trên Space

- `DEEPSEEK_API_KEY` — API key của DeepSeek
- `GDRIVE_CREDENTIALS_PATH` (optional) — Đường dẫn service account JSON cho Drive private. Mặc định `/app/credentials.json`.

## Lưu ý

- Storage trên HF Spaces là **ephemeral**: mỗi lần restart sẽ reset thư mục `data/` và `index/` về trạng thái commit. Nếu cần giữ index sau khi index mới, cần bật Persistent Storage hoặc commit `index/` vào repo.
- Lần khởi động đầu tiên sẽ tải model embedding (~120MB) → mất ~30-60s.

## deploy hugging face 
- dùng HF do free
cd backend
git init
git remote add hf https://huggingface.co/spaces/<username>/<space-name>
git add .
git commit -m "initial"
git push -u hf main
