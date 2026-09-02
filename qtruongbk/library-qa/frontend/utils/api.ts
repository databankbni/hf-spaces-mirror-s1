// URL gốc của backend FastAPI — đọc từ biến môi trường, mặc định localhost:8000
const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Wrapper fetch có log thời gian round-trip FE→BE.
 * Mở DevTools Console để xem chi tiết.
 */
async function timedFetch(url: string, init?: RequestInit): Promise<Response> {
  const method = init?.method ?? "GET";
  const path = url.replace(BASE_URL, "");
  const t0 = performance.now();
  try {
    const res = await fetch(url, init);
    const ms = (performance.now() - t0).toFixed(0);
    const tag = res.ok ? "✓" : "✗";
    console.log(`[FE→BE ${tag}] ${method} ${path} → ${res.status} | ${ms}ms`);
    return res;
  } catch (e) {
    const ms = (performance.now() - t0).toFixed(0);
    console.error(`[FE→BE ✗] ${method} ${path} → NETWORK ERROR | ${ms}ms`, e);
    throw e;
  }
}

// Kiểu dữ liệu cho một nguồn tài liệu được trích dẫn
export interface Source {
  file: string;
  page_start: number;
  page_end: number;
  score: number; // Điểm cosine similarity (0–1)
}

// Kết quả trả về từ endpoint /query
export interface QueryResponse {
  answer: string;
  sources: Source[];
}

// Kết quả trả về từ endpoint /index
export interface IndexResponse {
  message: string;
  indexed_files: number;
  skipped_files: number;
  total_chunks: number;
}

// Kết quả trả về từ endpoint /index/clear
export interface ClearIndexResponse {
  message: string;
  local_deleted: number;
  remote_deleted: number;
}

// Trạng thái thư viện hiện tại từ endpoint /health
export interface HealthResponse {
  status: string;
  total_documents: number;
  total_pages: number;
  total_chunks: number;
  categories: { category: string; count: number }[];
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * Gửi câu hỏi kèm lịch sử hội thoại để model có context.
 */
export async function sendQuery(
  question: string,
  history: HistoryMessage[] = [],
  k = 5
): Promise<QueryResponse> {
  const res = await timedFetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, k, history }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Gửi câu hỏi thất bại");
  }
  return res.json();
}

export type QueryStreamEvent =
  | { type: "delta"; text: string }
  | { type: "replace"; text: string }
  | { type: "done"; sources: Source[] }
  | { type: "error"; detail: string };

/**
 * Stream câu trả lời từ /query/stream qua SSE.
 * onEvent được gọi cho mỗi event (delta/replace/done/error).
 * Resolve với { sources } khi hoàn tất, reject khi lỗi.
 */
export function sendQueryStream(
  question: string,
  history: HistoryMessage[],
  onEvent: (e: QueryStreamEvent) => void,
  k = 5
): Promise<{ sources: Source[] }> {
  return new Promise(async (resolve, reject) => {
    try {
      const res = await timedFetch(`${BASE_URL}/query/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, k, history }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        return reject(new Error(err.detail ?? "Gửi câu hỏi thất bại"));
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const blocks = buf.split("\n\n");
        buf = blocks.pop() ?? "";
        for (const block of blocks) {
          const line = block.trim();
          if (!line.startsWith("data:")) continue;
          const payload: QueryStreamEvent = JSON.parse(line.slice(5).trim());
          onEvent(payload);
          if (payload.type === "done") {
            return resolve({ sources: payload.sources });
          }
          if (payload.type === "error") {
            return reject(new Error(payload.detail));
          }
        }
      }
      reject(new Error("Stream kết thúc đột ngột"));
    } catch (e: any) {
      reject(e);
    }
  });
}

/**
 * Yêu cầu backend index toàn bộ PDF trong thư mục Google Drive.
 * File đã index sẽ bị bỏ qua tự động (incremental).
 */
export async function indexFolder(
  google_drive_folder_url: string
): Promise<IndexResponse> {
  const res = await timedFetch(`${BASE_URL}/index`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ google_drive_folder_url }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Index thất bại");
  }
  return res.json();
}

export interface IndexProgress {
  status: "processing" | "skipped" | "syncing" | "done" | "error";
  file?: string;
  indexed: number;
  skipped: number;
  chunks_so_far: number;
  // khi done
  message?: string;
  indexed_files?: number;
  skipped_files?: number;
  total_chunks?: number;
  // khi error
  detail?: string;
}

/**
 * Stream tiến độ index qua SSE. Gọi onProgress mỗi khi có cập nhật.
 * Resolve với IndexResponse khi hoàn tất, reject khi lỗi.
 */
export function indexFolderStream(
  google_drive_folder_url: string,
  onProgress: (p: IndexProgress) => void
): Promise<IndexResponse> {
  return new Promise(async (resolve, reject) => {
    try {
      const res = await timedFetch(`${BASE_URL}/index/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ google_drive_folder_url }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        return reject(new Error(err.detail ?? "Index thất bại"));
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n\n");
        buf = lines.pop() ?? "";
        for (const block of lines) {
          const line = block.trim();
          if (!line.startsWith("data:")) continue;
          const payload: IndexProgress = JSON.parse(line.slice(5).trim());
          onProgress(payload);
          if (payload.status === "done") {
            return resolve({
              message: payload.message ?? "Indexing hoàn tất",
              indexed_files: payload.indexed_files ?? payload.indexed,
              skipped_files: payload.skipped_files ?? payload.skipped,
              total_chunks: payload.total_chunks ?? payload.chunks_so_far,
            });
          }
          if (payload.status === "error") {
            return reject(new Error(payload.detail ?? "Index thất bại"));
          }
        }
      }
    } catch (e: any) {
      reject(e);
    }
  });
}

/**
 * Upload nhiều file PDF lên backend để index.
 */
export async function uploadFiles(files: File[]): Promise<IndexResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await timedFetch(`${BASE_URL}/index/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload thất bại");
  }
  return res.json();
}

/**
 * Xóa toàn bộ index local trên backend và index đã sync trên Google Drive.
 */
export async function clearIndex(): Promise<ClearIndexResponse> {
  const res = await timedFetch(`${BASE_URL}/index/clear`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Xóa index thất bại");
  }
  return res.json();
}

/**
 * Tìm kiếm câu hỏi trên internet qua DeepSeek web search.
 */
export async function webSearch(question: string): Promise<QueryResponse> {
  const res = await timedFetch(`${BASE_URL}/web_search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Tìm kiếm thất bại");
  }
  return res.json();
}

/**
 * Lấy trạng thái hiện tại của backend và số tài liệu trong thư viện.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const res = await timedFetch(`${BASE_URL}/health`);
  if (!res.ok) throw new Error("Không kết nối được backend");
  return res.json();
}
