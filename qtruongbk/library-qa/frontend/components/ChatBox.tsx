"use client";

import { useEffect, useRef } from "react";
import { Source } from "@/utils/api";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  error?: boolean;
  needs_web_search?: boolean;
}

const QUICK_OPTIONS = [
  "Liệt kê tổng số tài liệu có trong thư viện",
];

interface Props {
  messages: Message[];
  loading: boolean;
  onQuickSelect?: (text: string) => void;
}

export default function ChatBox({ messages, loading, onQuickSelect }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const showLoadingBubble =
    loading &&
    (messages.length === 0 ||
      messages[messages.length - 1].role !== "assistant" ||
      messages[messages.length - 1].content.length === 0);

  return (
    <div className="flex-1 overflow-y-auto p-3 sm:p-5 flex flex-col gap-2.5 sm:gap-3.5">
      {messages.length === 0 && (
        <div className="flex flex-col items-center gap-4 mt-8 sm:mt-16 px-4">
          <p className="text-ink-muted text-center text-sm">
            Hỏi bất cứ điều gì về tài liệu trong thư viện.
          </p>
          {!loading && (
            <div className="flex flex-wrap justify-center gap-2">
              {QUICK_OPTIONS.map((opt) => (
                <button
                  key={opt}
                  onClick={() => onQuickSelect?.(opt)}
                  className="px-3.5 py-2 rounded-xl border border-line bg-panel-bot text-ink text-[0.84rem] hover:border-accent hover:text-accent transition-colors"
                >
                  {opt}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={[
              "max-w-[88%] sm:max-w-[82%] lg:max-w-[72%]",
              "px-3.5 py-2.5 sm:px-4 sm:py-3 rounded-xl",
              "text-[0.9rem] sm:text-[0.92rem] leading-relaxed",
              "whitespace-pre-wrap break-words",
              msg.role === "user"
                ? "bg-panel-user rounded-br-sm"
                : "bg-panel-bot rounded-bl-sm",
              msg.error ? "text-danger" : "",
            ].join(" ")}
          >
            <p className="whitespace-pre-wrap">{msg.content}</p>

            {/* Chỉ hiển thị nguồn có độ liên quan trên 85% */}
            {msg.sources && msg.sources.filter((s) => s.score >= 0.85).length > 0 && (
              <details className="mt-2.5 text-[0.78rem] sm:text-xs text-ink-muted">
                <summary className="cursor-pointer select-none text-accent">
                  Nguồn trích dẫn ({msg.sources.filter((s) => s.score >= 0.85).length})
                </summary>
                <ul className="mt-1.5 pl-4 flex flex-col gap-0.5">
                  {msg.sources
                    .filter((s) => s.score >= 0.85)
                    .map((s, i) => (
                      <li key={i}>
                        <span className="text-ink">{s.file}</span>
                        {" — trang "}
                        <strong>
                          {s.page_start}–{s.page_end}
                        </strong>
                        <span className="text-ink-muted">
                          {" "}({(s.score * 100).toFixed(1)}%)
                        </span>
                      </li>
                    ))}
                </ul>
              </details>
            )}
          </div>
        </div>
      ))}

      {showLoadingBubble && (
        <div className="flex justify-start">
          <div className="bg-panel-bot rounded-xl rounded-bl-sm px-4 py-3.5 flex items-center gap-1.5 min-w-[56px]">
            <span className="loading-dot" />
            <span className="loading-dot" />
            <span className="loading-dot" />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
