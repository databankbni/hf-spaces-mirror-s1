"use client";

import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from "react";
import ChatBox, { Message } from "@/components/ChatBox";
import { sendQueryStream, indexFolderStream, uploadFiles, fetchHealth, clearIndex, IndexResponse, HistoryMessage } from "@/utils/api";

const STORAGE_KEY = "rag_drive_url";

function BrainLogo({ className = "" }: { className?: string }) {
  return (
    <span className={`brain-logo ${className}`} aria-hidden="true">
      <svg viewBox="0 0 48 48" role="img">
        <defs>
          <linearGradient id="brainShell" x1="7" y1="6" x2="41" y2="43">
            <stop offset="0" stopColor="#8ea0ff" />
            <stop offset="0.52" stopColor="#5c6ef7" />
            <stop offset="1" stopColor="#43c78a" />
          </linearGradient>
          <radialGradient id="brainGlow" cx="50%" cy="45%" r="60%">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.28" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
          </radialGradient>
        </defs>
        <path
          className="brain-outline"
          d="M20 10.5c-4.8-2-10.1 1.7-10.1 7 0 .8.1 1.6.4 2.4A7.8 7.8 0 0 0 7 26.3c0 4 3 7.4 6.9 7.8 1.1 3.1 4 5.4 7.5 5.4 1.8 0 3.3-.6 4.6-1.5 1.3.9 2.9 1.5 4.7 1.5 3.4 0 6.4-2.2 7.4-5.4 3.9-.4 6.9-3.8 6.9-7.8 0-2.6-1.2-4.9-3.2-6.3.2-.8.4-1.6.4-2.4 0-5.4-5.4-9-10.2-7A7.8 7.8 0 0 0 26 7a7.8 7.8 0 0 0-6 3.5Z"
        />
        <path
          className="brain-glow"
          d="M20 10.5c-4.8-2-10.1 1.7-10.1 7 0 .8.1 1.6.4 2.4A7.8 7.8 0 0 0 7 26.3c0 4 3 7.4 6.9 7.8 1.1 3.1 4 5.4 7.5 5.4 1.8 0 3.3-.6 4.6-1.5 1.3.9 2.9 1.5 4.7 1.5 3.4 0 6.4-2.2 7.4-5.4 3.9-.4 6.9-3.8 6.9-7.8 0-2.6-1.2-4.9-3.2-6.3.2-.8.4-1.6.4-2.4 0-5.4-5.4-9-10.2-7A7.8 7.8 0 0 0 26 7a7.8 7.8 0 0 0-6 3.5Z"
        />
        <g className="brain-network">
          <path d="M16 20h7l5-5" />
          <path d="M18 29h8l6 5" />
          <path d="M25 24h9" />
          <path d="M25 24l-5 5" />
          <circle cx="16" cy="20" r="2.2" />
          <circle cx="28" cy="15" r="2" />
          <circle cx="34" cy="24" r="2.3" />
          <circle cx="18" cy="29" r="2.1" />
          <circle cx="32" cy="34" r="2" />
        </g>
      </svg>
    </span>
  );
}

function IndexResultBox({ result }: { result: IndexResponse }) {
  return (
    <div className="text-[0.82rem] px-3 py-2.5 rounded-lg bg-[#1a2e26] text-success">
      <strong>{result.message}</strong>
      <ul className="mt-1.5 pl-4 list-disc">
        <li>File mới: {result.indexed_files}</li>
        <li>Bỏ qua (đã có): {result.skipped_files}</li>
        <li>Chunk mới: {result.total_chunks}</li>
      </ul>
    </div>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <div className="text-[0.82rem] px-3 py-2.5 rounded-lg bg-[#2e1a1a] text-danger">
      {text}
    </div>
  );
}

let msgCounter = 0;
const uid = () => String(++msgCounter);

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const [driveUrl, setDriveUrl] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [indexProgress, setIndexProgress] = useState<{ file: string; indexed: number; skipped: number; syncing?: boolean } | null>(null);
  const [indexResult, setIndexResult] = useState<IndexResponse | null>(null);
  const [indexError, setIndexError] = useState("");

  const [totalDocuments, setTotalDocuments] = useState<number | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [indexMode, setIndexMode] = useState<"drive" | "upload">("drive");

  const [uploadFiles_, setUploadFiles_] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<IndexResponse | null>(null);
  const [uploadError, setUploadError] = useState("");
  const [clearingIndex, setClearingIndex] = useState(false);
  const [clearIndexMessage, setClearIndexMessage] = useState("");
  const [clearIndexError, setClearIndexError] = useState("");

  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) setDriveUrl(saved);

    fetchHealth()
      .then((h) => { setBackendOnline(true); setTotalDocuments(h.total_documents); })
      .catch(() => setBackendOnline(false));
  }, []);

  const appendMessage = (msg: Message) =>
    setMessages((prev) => [...prev, msg]);

  const handleSend = async (overrideText?: string) => {
    const question = (overrideText ?? input).trim();
    if (!question || loading) return;

    appendMessage({ id: uid(), role: "user", content: question });
    setInput("");
    setLoading(true);

    const assistantId = uid();
    appendMessage({ id: assistantId, role: "assistant", content: "" });

    try {
      const history: HistoryMessage[] = messages
        .filter((m) => !m.error)
        .map((m) => ({ role: m.role, content: m.content }));

      await sendQueryStream(question, history, (ev) => {
        if (ev.type === "delta") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + ev.text } : m
            )
          );
        } else if (ev.type === "replace") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: ev.text } : m
            )
          );
        } else if (ev.type === "done") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, sources: ev.sources } : m
            )
          );
        }
      });
    } catch (err: any) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: err.message ?? "Có lỗi xảy ra.", error: true }
            : m
        )
      );
    } finally {
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleIndex = async (e: FormEvent) => {
    e.preventDefault();
    if (!driveUrl.trim() || indexing) return;

    localStorage.setItem(STORAGE_KEY, driveUrl.trim());
    setIndexing(true);
    setIndexProgress(null);
    setIndexResult(null);
    setIndexError("");
    try {
      const res = await indexFolderStream(driveUrl.trim(), (p) => {
        if (p.status === "processing" || p.status === "skipped") {
          setIndexProgress({ file: p.file ?? "", indexed: p.indexed, skipped: p.skipped });
        } else if (p.status === "syncing") {
          setIndexProgress({ file: "", indexed: p.indexed, skipped: p.skipped, syncing: true });
        }
      });
      setIndexResult(res);
      setIndexProgress(null);
      setTotalDocuments((prev) => (prev ?? 0) + res.indexed_files);
    } catch (err: any) {
      setIndexError(err.message ?? "Index thất bại");
    } finally {
      setIndexing(false);
    }
  };

  const handleUpload = async () => {
    if (!uploadFiles_.length || uploading) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError("");
    try {
      const res = await uploadFiles(uploadFiles_);
      setUploadResult(res);
      setUploadFiles_([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTotalDocuments((prev) => (prev ?? 0) + res.indexed_files);
    } catch (err: any) {
      setUploadError(err.message ?? "Upload thất bại");
    } finally {
      setUploading(false);
    }
  };

  const handleClearIndex = async () => {
    if (clearingIndex || indexing || uploading) return;
    const ok = window.confirm("Xóa toàn bộ index local và index đã sync trên Google Drive?");
    if (!ok) return;

    setClearingIndex(true);
    setClearIndexMessage("");
    setClearIndexError("");
    try {
      const res = await clearIndex();
      setIndexResult(null);
      setUploadResult(null);
      setIndexProgress(null);
      setTotalDocuments(0);
      setMessages([]);
      setClearIndexMessage(
        `${res.message} Local: ${res.local_deleted}, Drive: ${res.remote_deleted}.`
      );
    } catch (err: any) {
      setClearIndexError(err.message ?? "Xóa index thất bại");
    } finally {
      setClearingIndex(false);
    }
  };

  const statusBadge = (() => {
    if (backendOnline === null)
      return { text: "Đang kết nối…", cls: "bg-panel-bot text-ink-muted" };
    if (!backendOnline)
      return { text: "Backend offline", cls: "bg-[#2e1a1a] text-danger" };
    return {
      text: `Tổng số tài liệu có trong thư viện: ${(totalDocuments ?? 0).toLocaleString()}`,
      cls: totalDocuments === 0 ? "bg-[#302715] text-warn" : "bg-[#172f29] text-success",
    };
  })();

  // Class tổ hợp: nút tím chính dùng nhiều nơi
  const btnPrimary =
    "bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed " +
    "text-white border-none rounded-lg font-semibold transition-colors";

  return (
    <main className="flex h-screen [height:100dvh] overflow-hidden">
      {/* Backdrop khi mở sidebar trên mobile */}
      <div
        className={`fixed inset-0 bg-black/50 z-[90] md:hidden transition-opacity ${
          sidebarOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
        }`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* Sidebar — drawer trên mobile, cố định trên desktop */}
      <aside
        className={[
          "bg-panel border-r border-line overflow-y-auto",
          "flex flex-col gap-3 sm:gap-4",
          "p-4 sm:p-5",
          "fixed md:static top-0 left-0 bottom-0 z-[100]",
          "w-[84%] max-w-[320px] md:w-[260px] lg:w-[280px] md:max-w-none",
          "shadow-2xl md:shadow-none",
          "transition-transform duration-250 ease-out",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0",
        ].join(" ")}
      >
        <button
          aria-label="Đóng menu"
          onClick={() => setSidebarOpen(false)}
          className="md:hidden self-end text-ink-muted text-2xl leading-none px-1 -mt-1"
        >
          ×
        </button>

        <div className="flex items-center gap-2.5">
          <BrainLogo className="h-9 w-9 shrink-0" />
          <h2 className="text-ink font-semibold text-base tracking-wide">Thư viện hỏi đáp</h2>
        </div>

        <div className={`text-xs px-2.5 py-1.5 rounded-full font-medium text-center ${statusBadge.cls}`}>
          {statusBadge.text}
        </div>

        <button
          onClick={handleClearIndex}
          disabled={clearingIndex || indexing || uploading || !backendOnline}
          className="border border-danger/50 text-danger hover:bg-[#2e1a1a] disabled:opacity-40 disabled:cursor-not-allowed rounded-lg py-2 text-[0.85rem] font-semibold transition-colors"
        >
          {clearingIndex ? "Đang xóa index…" : "Xóa index"}
        </button>
        {clearIndexMessage && (
          <div className="text-[0.78rem] px-3 py-2 rounded-lg bg-[#1a2e26] text-success">
            {clearIndexMessage}
          </div>
        )}
        {clearIndexError && <ErrorBox text={clearIndexError} />}

        {/* Tab toggle */}
        <div className="flex rounded-lg overflow-hidden border border-line text-[0.82rem] font-medium">
          {(["drive", "upload"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setIndexMode(mode)}
              className={`flex-1 py-1.5 transition-colors ${
                indexMode === mode
                  ? "bg-accent text-white"
                  : "bg-page text-ink-muted hover:text-ink"
              }`}
            >
              {mode === "drive" ? "Google Drive" : "Tải lên"}
            </button>
          ))}
        </div>

        {indexMode === "drive" ? (
          <>
            <p className="text-[0.82rem] text-ink-muted">
              {totalDocuments === 0
                ? "Paste link Drive (folder hoặc 1 file PDF) để bắt đầu index."
                : "Index sẵn sàng. Thêm folder hoặc 1 file PDF mới bằng cách index lại."}
            </p>
            <form onSubmit={handleIndex} className="flex flex-col gap-2">
              <input
                type="text"
                placeholder="Link Google Drive (folder hoặc file PDF)"
                value={driveUrl}
                onChange={(e) => setDriveUrl(e.target.value)}
                disabled={indexing}
                className="bg-page border border-line rounded-lg text-ink px-2.5 py-2 text-[0.85rem] outline-none focus:border-accent transition-colors"
              />
              <button
                type="submit"
                disabled={indexing || !driveUrl.trim()}
                className={`${btnPrimary} py-2 text-[0.87rem]`}
              >
                {indexing
                  ? indexProgress?.syncing
                    ? "Đang sync với Drive…"
                    : indexProgress
                      ? `Đã xong ${indexProgress.indexed} file, bỏ qua ${indexProgress.skipped}…`
                      : "Đang chuẩn bị…"
                  : totalDocuments ? "Sync file mới" : "Index từ Drive"}
              </button>
            </form>
            {totalDocuments !== null && totalDocuments > 0 && !indexResult && (
              <p className="text-[0.78rem] text-ink-muted border-l-2 border-line pl-2 leading-snug">
                File đã index sẽ được bỏ qua tự động.
              </p>
            )}
            {indexResult && <IndexResultBox result={indexResult} />}
            {indexError && <ErrorBox text={indexError} />}
          </>
        ) : (
          <>
            <p className="text-[0.82rem] text-ink-muted">
              Chọn một hoặc nhiều file PDF từ thiết bị để index.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              multiple
              disabled={uploading}
              onChange={(e) => {
                const selected = Array.from(e.target.files ?? []);
                const nonPdf = selected.filter((f) => !f.name.toLowerCase().endsWith(".pdf"));
                if (nonPdf.length) {
                  setUploadError(`Chỉ chấp nhận file PDF: ${nonPdf.map((f) => f.name).join(", ")}`);
                  e.target.value = "";
                  return;
                }
                setUploadError("");
                setUploadFiles_(selected);
              }}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="border border-line rounded-lg py-2 text-[0.85rem] text-ink-muted hover:border-accent hover:text-accent transition-colors"
            >
              Chọn file PDF…
            </button>
            {uploadFiles_.length > 0 && (
              <ul className="text-[0.78rem] text-ink-muted flex flex-col gap-0.5 max-h-32 overflow-y-auto pl-1">
                {uploadFiles_.map((f) => (
                  <li key={f.name} className="truncate">{f.name}</li>
                ))}
              </ul>
            )}
            <button
              onClick={handleUpload}
              disabled={uploading || !uploadFiles_.length}
              className={`${btnPrimary} py-2 text-[0.87rem]`}
            >
              {uploading ? "Đang xử lý…" : `Index ${uploadFiles_.length || ""} file`}
            </button>
            {uploadResult && <IndexResultBox result={uploadResult} />}
            {uploadError && <ErrorBox text={uploadError} />}
          </>
        )}
      </aside>

      {/* Main chat */}
      <section className="flex-1 flex flex-col overflow-hidden w-full">
        <header className="flex items-center px-3.5 sm:px-5 py-2.5 sm:py-3.5 border-b border-line bg-panel/95 font-semibold text-sm sm:text-[0.95rem]">
          <button
            aria-label="Mở menu"
            onClick={() => setSidebarOpen(true)}
            className="md:hidden text-ink text-xl mr-2 px-1.5"
          >
            ☰
          </button>
          <div className="flex items-center gap-2.5">
            <BrainLogo className="h-8 w-8 shrink-0" />
            <span>Thư viện hỏi đáp</span>
          </div>
        </header>

        <ChatBox
          messages={messages}
          loading={loading}
          onQuickSelect={(text) => handleSend(text)}
        />

        <div className="flex gap-2 sm:gap-2.5 p-2.5 sm:p-3.5 border-t border-line bg-panel items-end">
          <textarea
            ref={inputRef}
            rows={1}
            placeholder="Nhập câu hỏi…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
            className="flex-1 resize-none overflow-y-auto max-h-40 bg-page border border-line rounded-xl text-ink px-3.5 py-2.5 text-[0.92rem] outline-none focus:border-accent transition-colors leading-snug font-sans"
          />
          <button
            onClick={() => handleSend()}
            disabled={loading || !input.trim()}
            className={`${btnPrimary} px-4 sm:px-5 py-2.5 text-[0.88rem] whitespace-nowrap`}
          >
            Gửi
          </button>
        </div>
      </section>
    </main>
  );
}
