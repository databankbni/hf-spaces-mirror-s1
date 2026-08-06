"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AskVerse,
  BibleLanguage,
  BibleVersion,
  ChapterResponse,
  PredictResponse,
  Topic,
  VerseResult,
} from "./types";
import { useFavorites, useHistory, useTheme, testKeyStore } from "./lib/storage";
import { BOOKS, EXAMPLES, SCOPES } from "./lib/bible";
import MicButton from "./components/MicButton";
import VerseCard from "./components/VerseCard";
import ChapterModal from "./components/ChapterModal";
import CommandPalette from "./components/CommandPalette";
import ActiveListening from "./components/ActiveListening";
import TestKeyGate from "./components/TestKeyGate";
import FeedbackButton from "./components/FeedbackButton";
import AccountMenu from "./components/AccountMenu";
import type { TestAccess } from "./types";
import {
  BookIcon,
  ChevronIcon,
  ListenIcon,
  MoonIcon,
  SearchIcon,
  SparkleIcon,
  Spinner,
  StarIcon,
  SunIcon,
  TypeIcon,
  MicIcon,
} from "./components/Icons";

type Mode = "speak" | "type" | "ask" | "listen";
type Status = "idle" | "recording" | "processing" | "done" | "error";

interface SpeechRec {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}
function getSpeechRecognition(): SpeechRec | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRec;
    webkitSpeechRecognition?: new () => SpeechRec;
  };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}
const haptic = () => navigator.vibrate?.(8);

export default function VerseFinder() {
  const { theme, toggle: toggleTheme } = useTheme();
  const { history, add: addHistory, clear: clearHistory } = useHistory();
  const { favorites, isFavorite, toggle: toggleFavorite } = useFavorites();

  const [mode, setMode] = useState<Mode>("speak");
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [question, setQuestion] = useState("");
  const [interim, setInterim] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [micStream, setMicStream] = useState<MediaStream | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // Q&A streaming state
  const [askAnswer, setAskAnswer] = useState("");
  const [askVerses, setAskVerses] = useState<AskVerse[]>([]);
  const [askError, setAskError] = useState<string | null>(null);

  const [versions, setVersions] = useState<BibleVersion[]>([]);
  const [languages, setLanguages] = useState<BibleLanguage[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [version, setVersion] = useState("all");
  const [scope, setScope] = useState("all");
  const [spokenLang, setSpokenLang] = useState("auto");
  const [ready, setReady] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [config, setConfig] = useState<{
    ask_enabled: boolean;
    listen_enabled: boolean;
    maintenance: boolean;
    disabled: boolean;
    test_mode: boolean;
  }>({ ask_enabled: true, listen_enabled: true, maintenance: false, disabled: false, test_mode: false });
  const [testKey, setTestKey] = useState<string>("");
  const [access, setAccess] = useState<TestAccess | null>(null);
  const [bootChecked, setBootChecked] = useState(false);

  const [chapter, setChapter] = useState<ChapterResponse | null>(null);
  const [chapterLoading, setChapterLoading] = useState(false);
  const [chapterOpen, setChapterOpen] = useState(false);
  const [highlightVerse, setHighlightVerse] = useState<number | undefined>();

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const recogRef = useRef<SpeechRec | null>(null);

  const flashToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2000);
  }, []);

  useEffect(() => {
    fetch("/api/versions")
      .then((r) => r.json())
      .then((d: { versions?: BibleVersion[]; languages?: BibleLanguage[] }) => {
        setVersions(d.versions ?? []);
        setLanguages(d.languages ?? []);
      })
      .catch(() => undefined);
    fetch("/api/topics")
      .then((r) => r.json())
      .then((d: { topics?: Topic[] }) => setTopics(d.topics ?? []))
      .catch(() => undefined);
    fetch("/api/config")
      .then((r) => r.json())
      .then((d) =>
        setConfig({
          ask_enabled: d.ask_enabled !== false,
          listen_enabled: d.listen_enabled !== false,
          maintenance: !!d.maintenance,
          disabled: !!d.disabled,
          test_mode: !!d.test_mode,
        }),
      )
      .catch(() => undefined);
  }, []);

  // Initial test-key validation: pick up ?testkey= from the URL (one-click
  // invite), else from localStorage; then fetch its permissions.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("testkey")?.trim();
    const saved = fromUrl || testKeyStore.get();
    if (!saved) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setBootChecked(true);
      return;
    }
    fetch("/api/test/access", { method: "POST", headers: { "X-Test-Key": saved } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.valid) {
          testKeyStore.set(saved);
          setTestKey(saved);
          setAccess(d);
          if (fromUrl) {
            params.delete("testkey");
            const q = params.toString();
            window.history.replaceState({}, "", window.location.pathname + (q ? "?" + q : ""));
          }
        } else {
          testKeyStore.clear();
        }
      })
      .catch(() => undefined)
      .finally(() => setBootChecked(true));
  }, []);

  // Poll config so admin flag changes (e.g. the kill switch) propagate live.
  useEffect(() => {
    const id = setInterval(() => {
      fetch("/api/config")
        .then((r) => r.json())
        .then((d) =>
          setConfig({
            ask_enabled: d.ask_enabled !== false,
            listen_enabled: d.listen_enabled !== false,
            maintenance: !!d.maintenance,
            disabled: !!d.disabled,
            test_mode: !!d.test_mode,
          }),
        )
        .catch(() => undefined);
    }, 15000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const d = await (await fetch("/api/health")).json();
        if (!cancelled && d.ready) return setReady(true);
      } catch {
        /* not reachable yet */
      }
      if (!cancelled) setTimeout(check, 2000);
    };
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  // ⌘K / Ctrl+K opens the command palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Inject the X-Test-Key header on every public action so it propagates
  // through the Next proxies to the backend.
  const testKeyHeaders = useCallback(
    (extra?: Record<string, string>) =>
      testKey ? { "X-Test-Key": testKey, ...(extra ?? {}) } : (extra ?? {}),
    [testKey],
  );

  // -- searches ------------------------------------------------------------
  const runSearch = useCallback(
    async (query: string, searchMode: "type" | "speak", ver: string, sc: string) => {
      setStatus("processing");
      setError(null);
      setAskAnswer("");
      setAskVerses([]);
      setLastQuery(query);
      try {
        const res = await fetch("/api/search", {
          method: "POST",
          headers: testKeyHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ text: query, version: ver, scope: sc }),
        });
        const data: PredictResponse = await res.json();
        if (!res.ok || data.error) throw new Error(data.error ?? "Request failed");
        setResult(data);
        setStatus("done");
        haptic();
        addHistory({ query, mode: searchMode, ref: data.results[0]?.ref });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong");
        setStatus("error");
      }
    },
    [addHistory, testKeyHeaders],
  );

  const runAsk = useCallback(
    async (q: string, ver: string) => {
      setStatus("processing");
      setError(null);
      setResult(null);
      setAskAnswer("");
      setAskVerses([]);
      setAskError(null);
      setLastQuery(q);
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: testKeyHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ question: q, version: ver }),
        });
        if (res.status === 429) {
          setAskError("Too many questions — please wait a minute and try again.");
          setStatus("error");
          return;
        }
        const reader = res.body?.getReader();
        if (!reader) throw new Error("No stream");
        const dec = new TextDecoder();
        let buf = "";
        let answer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const chunks = buf.split("\n\n");
          buf = chunks.pop() ?? "";
          for (const c of chunks) {
            const line = c.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            const ev = JSON.parse(line.slice(6));
            if (ev.type === "verses") setAskVerses(ev.verses);
            else if (ev.type === "delta") {
              answer += ev.text;
              setAskAnswer(answer);
            } else if (ev.type === "error") setAskError(ev.error);
          }
        }
        setStatus("done");
        addHistory({ query: q, mode: "ask" });
      } catch {
        setAskError("Could not reach the Q&A service.");
        setStatus("error");
      }
    },
    [addHistory, testKeyHeaders],
  );

  // -- speech --------------------------------------------------------------
  const sendAudio = useCallback(
    async (blob: Blob, ver: string, lang: string, sc: string) => {
      setStatus("processing");
      const form = new FormData();
      form.append("audio", blob, "recording.webm");
      try {
        const qs = new URLSearchParams({ version: ver, lang, scope: sc }).toString();
        const res = await fetch(`/api/predict?${qs}`, {
          method: "POST",
          headers: testKeyHeaders(),
          body: form,
        });
        const data: PredictResponse = await res.json();
        if (!res.ok || data.error) throw new Error(data.error ?? "Request failed");
        setResult(data);
        setLastQuery(data.transcript);
        setStatus("done");
        haptic();
        addHistory({ query: data.transcript, mode: "speak", ref: data.results[0]?.ref });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong");
        setStatus("error");
      }
    },
    [addHistory, testKeyHeaders],
  );

  const startRecording = useCallback(async () => {
    setError(null);
    setResult(null);
    setInterim("");
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    const ver = version;
    const lang = spokenLang;
    const sc = scope;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setMicStream(stream);
      chunksRef.current = [];

      const recog = getSpeechRecognition();
      if (recog) {
        recog.lang = lang === "es" ? "es-ES" : "en-US";
        recog.continuous = true;
        recog.interimResults = true;
        recog.onresult = (e) => {
          let live = "";
          for (let i = 0; i < e.results.length; i++) live += e.results[i][0].transcript;
          setInterim(live);
        };
        recog.onerror = () => undefined;
        recog.onend = () => undefined;
        try {
          recog.start();
        } catch {
          /* already started */
        }
        recogRef.current = recog;
      }

      const mimeType = pickMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        setMicStream(null);
        recogRef.current?.stop();
        recogRef.current = null;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        setAudioUrl(URL.createObjectURL(blob));
        void sendAudio(blob, ver, lang, sc);
      };
      recorder.start();
      mediaRecorderRef.current = recorder;
      setStatus("recording");
    } catch {
      setError("Microphone access was denied or is unavailable. Try typing instead.");
      setStatus("error");
    }
  }, [version, spokenLang, scope, audioUrl, sendAudio]);

  const stopRecording = useCallback(() => mediaRecorderRef.current?.stop(), []);

  // -- chapter / refs ------------------------------------------------------
  const openChapter = useCallback(
    async (bookNo: number, ch: number, ver: string, verse: number) => {
      setChapterOpen(true);
      setChapterLoading(true);
      setChapter(null);
      setHighlightVerse(verse);
      try {
        const qs = new URLSearchParams({
          book_no: String(bookNo),
          chapter: String(ch),
          version: ver === "all" ? "KJV" : ver,
        }).toString();
        const data: ChapterResponse = await (await fetch(`/api/chapter?${qs}`)).json();
        setChapter(data.error ? null : data);
      } catch {
        setChapter(null);
      } finally {
        setChapterLoading(false);
      }
    },
    [],
  );

  const shareVerse = useCallback(
    async (r: VerseResult) => {
      const url = `${window.location.origin}/verse/${r.ref.toLowerCase().replace(/\s+/g, "-").replace(/:/g, "-").replace(/[^a-z0-9-]/g, "")}`;
      try {
        if (navigator.share) await navigator.share({ title: r.ref, text: `${r.text} — ${r.ref}`, url });
        else {
          await navigator.clipboard.writeText(url);
          flashToast("Share link copied");
        }
      } catch {
        /* cancelled */
      }
    },
    [flashToast],
  );

  const switchMode = useCallback((next: Mode) => {
    setMode(next);
    setStatus("idle");
    setError(null);
    setResult(null);
    setAskAnswer("");
    setAskVerses([]);
    setInterim("");
  }, []);

  const openRef = useCallback(
    (ref: string) => {
      switchMode("type");
      setText(ref);
      void runSearch(ref, "type", version, "all");
    },
    [runSearch, switchMode, version],
  );

  const replayQuery = useCallback(
    (query: string, m: Mode) => {
      setShowSidebar(false);
      setPaletteOpen(false);
      if (m === "ask") {
        switchMode("ask");
        setQuestion(query);
        void runAsk(query, version);
      } else {
        switchMode("type");
        setText(query);
        void runSearch(query, "type", version, scope);
      }
    },
    [runAsk, runSearch, switchMode, version, scope],
  );

  // deep links (?mode=&q=)
  const didDeepLink = useRef(false);
  useEffect(() => {
    if (didDeepLink.current || !ready) return;
    const params = new URLSearchParams(window.location.search);
    const q = params.get("q");
    const m = params.get("mode") as Mode | null;
    if (!q) return;
    didDeepLink.current = true;
    queueMicrotask(() => replayQuery(q, m === "ask" ? "ask" : "type"));
  }, [ready, replayQuery]);

  // -- autocomplete (book references) --------------------------------------
  const suggestions = useMemo(() => {
    const v = text.trim().toLowerCase();
    if (v.length < 2) return [];
    const m = /^([1-3]?\s?[a-z ]+)/.exec(v);
    const frag = (m?.[1] ?? v).trim();
    if (frag.length < 2) return [];
    return BOOKS.filter((b) => b.toLowerCase().startsWith(frag)).slice(0, 5);
  }, [text]);

  const isRecording = status === "recording";
  const isProcessing = status === "processing";
  const asking = mode === "ask" && isProcessing;
  // Per-feature visibility: gate by admin flag, and by the tester's key
  // permissions when in test mode.
  const inTest = config.test_mode && !!access;
  const featOn = (name: "speak" | "type" | "ask" | "listen", flag = true) =>
    flag && (!inTest || access!.features[name]);
  const showAsk = featOn("ask", config.ask_enabled);
  const showListen = featOn("listen", config.listen_enabled);
  const showSpeak = featOn("speak");
  const showType = featOn("type");
  // Literal class strings so Tailwind's JIT picks them up.
  const modeCount = (showSpeak ? 1 : 0) + (showType ? 1 : 0) + (showAsk ? 1 : 0) + (showListen ? 1 : 0);
  const modeCols = { 1: "grid-cols-1", 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4" }[modeCount] ?? "grid-cols-2";

  // Test-mode gate: still booting? wait. No valid key? show the gate.
  if (config.test_mode && bootChecked && !access) {
    return <TestKeyGate onUnlocked={() => window.location.reload()} />;
  }

  return (
    <div className="w-full max-w-2xl">
      {/* Top bar */}
      <div className="mb-5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowSidebar((s) => !s)}
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            <StarIcon size={14} /> Saved & recent
          </button>
          <Link
            href="/studio"
            className="hidden items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 sm:inline-flex dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            <BookIcon size={14} /> Sermon Studio
          </Link>
        </div>
        {inTest && (
          <span
            className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300"
            title={`Tester key: ${testKey}`}
          >
            🧪 Test mode{access?.label ? ` · ${access.label}` : ""}
          </span>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="hidden items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 transition hover:border-slate-300 sm:inline-flex dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            <SearchIcon size={13} /> Search
            <kbd className="rounded bg-slate-100 px-1 text-[10px] dark:bg-white/10">⌘K</kbd>
          </button>
          <button
            type="button"
            onClick={toggleTheme}
            aria-label="Toggle theme"
            className="rounded-full border border-slate-200 bg-white p-2 text-slate-600 transition hover:border-slate-300 dark:border-white/10 dark:bg-white/5 dark:text-slate-300"
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
          <AccountMenu />
        </div>
      </div>

      {config.disabled && (
        <div className="mb-5 rounded-2xl border border-rose-300 bg-rose-100 px-4 py-3 text-sm font-medium text-rose-900 dark:border-rose-400/30 dark:bg-rose-500/15 dark:text-rose-200">
          ⏸️ Verseo has been paused by an administrator — actions are unavailable.
        </div>
      )}
      {config.maintenance && !config.disabled && (
        <div className="mb-5 rounded-2xl border border-amber-300 bg-amber-100 px-4 py-3 text-sm font-medium text-amber-900 dark:border-amber-400/30 dark:bg-amber-500/15 dark:text-amber-200">
          🛠️ Verseo is in maintenance mode — some features may be unavailable.
        </div>
      )}
      {!ready && (
        <div className="mb-5 flex items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">
          <Spinner size={16} /> Warming up the model — one moment…
        </div>
      )}

      {/* Input card */}
      <div className="relative rounded-3xl border border-white/60 bg-white/70 p-6 shadow-lg shadow-violet-500/5 backdrop-blur-xl sm:p-8 dark:border-white/10 dark:bg-white/5">
        {config.disabled && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-3xl bg-white/75 backdrop-blur-sm dark:bg-slate-900/75">
            <div className="px-6 text-center">
              <div className="mb-2 text-4xl">⏸️</div>
              <p className="font-semibold">Verseo is temporarily unavailable</p>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                An administrator has paused all actions. Please check back soon.
              </p>
            </div>
          </div>
        )}
        <div className="mb-5 flex flex-wrap items-center justify-center gap-3 text-sm">
          {versions.length > 0 && (
            <label className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
              Version
              <Select value={version} onChange={setVersion}>
                <option value="all">All</option>
                {versions.map((v) => (
                  <option key={v.code} value={v.code}>
                    {v.code}
                  </option>
                ))}
              </Select>
            </label>
          )}
          <label className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
            Scope
            <Select value={scope} onChange={setScope}>
              {SCOPES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </Select>
          </label>
          {(mode === "speak" || mode === "listen") && languages.length > 1 && (
            <label className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
              Spoken
              <Select value={spokenLang} onChange={setSpokenLang}>
                <option value="auto">Auto</option>
                {languages.map((l) => (
                  <option key={l.code} value={l.code}>
                    {l.name}
                  </option>
                ))}
              </Select>
            </label>
          )}
        </div>

        <div className={["mx-auto mb-7 grid w-full max-w-md gap-1 rounded-full bg-slate-100 p-1 dark:bg-black/30", modeCols].join(" ")}>
          {showSpeak && <ToggleButton active={mode === "speak"} onClick={() => switchMode("speak")} icon={<MicIcon size={15} />} label="Speak" />}
          {showType && <ToggleButton active={mode === "type"} onClick={() => switchMode("type")} icon={<TypeIcon size={15} />} label="Type" />}
          {showAsk && (
            <ToggleButton active={mode === "ask"} onClick={() => switchMode("ask")} icon={<SparkleIcon size={15} />} label="Ask" />
          )}
          {showListen && (
            <ToggleButton active={mode === "listen"} onClick={() => switchMode("listen")} icon={<ListenIcon size={15} />} label="Listen" />
          )}
        </div>

        {mode === "speak" && (
          <div className="flex flex-col items-center gap-4">
            <MicButton
              status={status}
              stream={micStream}
              disabled={!ready}
              onStart={startRecording}
              onStop={stopRecording}
            />
            <p className="text-sm font-medium text-slate-500 dark:text-slate-400" aria-live="polite">
              {status === "idle" && "Tap to record · or hold to talk"}
              {isRecording && "Listening… release or tap to stop"}
              {isProcessing && "Identifying the scripture…"}
              {status === "done" && "Tap to try another"}
              {status === "error" && "Tap to try again"}
            </p>
            {interim && <p className="max-w-md text-center text-sm italic text-slate-400">“{interim}”</p>}
            {audioUrl && !isRecording && (
              <div className="flex items-center gap-3">
                <audio controls src={audioUrl} className="h-9" />
                <button
                  type="button"
                  onClick={startRecording}
                  disabled={isProcessing}
                  className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-200 disabled:opacity-50 dark:bg-white/5 dark:text-slate-300 dark:hover:bg-white/10"
                >
                  Record again
                </button>
              </div>
            )}
          </div>
        )}

        {mode === "type" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim() && ready) void runSearch(text.trim(), "type", version, scope);
            }}
            className="flex flex-col gap-3"
          >
            <div className="relative">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && text.trim() && ready) {
                    e.preventDefault();
                    void runSearch(text.trim(), "type", version, scope);
                  }
                }}
                rows={3}
                placeholder="Type part of a verse, or a reference like John 3:16…"
                className="w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30 dark:border-white/10 dark:bg-black/20 dark:text-slate-100"
              />
              {suggestions.length > 0 && (
                <div className="absolute left-3 top-full z-10 mt-1 flex flex-wrap gap-1.5">
                  {suggestions.map((b) => (
                    <button
                      key={b}
                      type="button"
                      onClick={() => setText(b + " ")}
                      className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-600 shadow-sm transition hover:border-indigo-300 dark:border-white/10 dark:bg-slate-800 dark:text-slate-300"
                    >
                      {b}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <SubmitButton disabled={!text.trim() || isProcessing || !ready} processing={isProcessing} label="Find verse" />
          </form>
        )}

        {mode === "ask" && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim() && ready) void runAsk(question.trim(), version);
            }}
            className="flex flex-col gap-3"
          >
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && question.trim() && ready) {
                  e.preventDefault();
                  void runAsk(question.trim(), version);
                }
              }}
              rows={3}
              placeholder="Ask a question, e.g. “What does the Bible say about forgiveness?”"
              className="w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30 dark:border-white/10 dark:bg-black/20 dark:text-slate-100"
            />
            <SubmitButton disabled={!question.trim() || asking || !ready} processing={asking} label="Ask" icon={<SparkleIcon size={16} />} />
          </form>
        )}

        {mode === "listen" && (
          <ActiveListening
            version={version}
            spokenLang={spokenLang}
            disabled={!ready || config.disabled}
            testKey={testKey}
            onOpenRef={openRef}
          />
        )}
      </div>

      {/* Example + topic chips (when idle) */}
      {status === "idle" && (
        <div className="mt-5 space-y-3">
          <ChipRow label="Try">
            {EXAMPLES.map((ex) => (
              <Chip key={ex} onClick={() => replayQuery(ex, "type")}>
                {ex}
              </Chip>
            ))}
          </ChipRow>
          {topics.length > 0 && (
            <ChipRow label="Topics">
              {topics.map((t) => (
                <Chip key={t.label} onClick={() => replayQuery(t.query, "type")}>
                  <span className="mr-1">{t.emoji}</span>
                  {t.label}
                </Chip>
              ))}
            </ChipRow>
          )}
        </div>
      )}

      {error && (
        <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/20 dark:bg-rose-500/10 dark:text-rose-200">
          {error}
        </div>
      )}

      {/* Skeleton while processing a fresh query */}
      {isProcessing && !asking && (
        <div className="mt-7 space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="animate-pulse rounded-2xl border border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-white/5">
              <div className="mb-3 h-4 w-32 rounded bg-slate-200 dark:bg-white/10" />
              <div className="mb-2 h-3 w-full rounded bg-slate-200 dark:bg-white/10" />
              <div className="h-3 w-2/3 rounded bg-slate-200 dark:bg-white/10" />
            </div>
          ))}
        </div>
      )}

      {/* Q&A answer (streaming) */}
      {mode === "ask" && (askAnswer || askVerses.length > 0 || asking) && status !== "error" && (
        <div className="mt-7 space-y-4">
          <div className="rounded-2xl border border-indigo-200 bg-indigo-50/70 p-5 dark:border-indigo-400/30 dark:bg-indigo-500/10">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-indigo-600 dark:text-indigo-300">
              <SparkleIcon size={14} /> Answer
            </div>
            <p className="whitespace-pre-wrap leading-relaxed text-slate-700 dark:text-slate-200">
              {askAnswer}
              {asking && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-indigo-400 align-middle" />}
            </p>
            <p className="mt-3 text-[11px] text-slate-400">
              AI-generated from the verses below — always verify with Scripture.
            </p>
          </div>
          {askError && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">
              {askError}
            </div>
          )}
          {askVerses.length > 0 && (
            <div>
              <p className="mb-3 text-xs font-medium uppercase tracking-widest text-slate-400">Relevant verses</p>
              <ul className="space-y-2">
                {askVerses.map((v) => (
                  <li key={v.ref}>
                    <button
                      type="button"
                      onClick={() => openRef(v.ref)}
                      className="w-full rounded-xl border border-slate-200 bg-white p-3 text-left text-sm transition hover:border-indigo-300 dark:border-white/10 dark:bg-white/5"
                    >
                      <span className="font-semibold text-slate-800 dark:text-slate-100">{v.ref}</span>
                      <span className="text-slate-600 dark:text-slate-300"> — {v.text}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Verse results */}
      {mode !== "ask" && result && result.results.length > 0 && status === "done" && (
        <div className="mt-7 space-y-4">
          {result.transcript && <p className="text-center text-sm italic text-slate-400">“{result.transcript}”</p>}
          {!result.confident && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">
              No confident match — here are the closest guesses.
            </div>
          )}
          <p className="text-xs font-medium uppercase tracking-widest text-slate-400">
            {result.results.length} closest match{result.results.length > 1 ? "es" : ""}
          </p>
          <ol className="space-y-3">
            {result.results.map((r, idx) => (
              <VerseCard
                key={`${r.ref}-${r.version}`}
                result={r}
                top={idx === 0}
                query={lastQuery}
                isFavorite={isFavorite(r.ref, r.version)}
                onToggleFavorite={() => toggleFavorite({ ref: r.ref, version: r.version, text: r.text })}
                onShare={() => shareVerse(r)}
                onReadChapter={() => openChapter(r.book_no, r.chapter, r.version, r.verse)}
                onOpenRef={openRef}
              />
            ))}
          </ol>
        </div>
      )}

      {mode !== "ask" && result && result.results.length === 0 && status === "done" && (
        <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-400/20 dark:bg-amber-500/10 dark:text-amber-200">
          {mode === "speak" ? "No speech detected. Please try again and recite clearly." : "No matching verse found."}
        </div>
      )}

      {showSidebar && (
        <Sidebar
          favorites={favorites}
          history={history}
          onClose={() => setShowSidebar(false)}
          onClearHistory={clearHistory}
          onReplay={replayQuery}
          onFavoriteClick={(ref) => replayQuery(ref, "type")}
        />
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} topics={topics} onRun={replayQuery} />

      {chapterOpen && (
        <ChapterModal data={chapter} loading={chapterLoading} highlightVerse={highlightVerse} onClose={() => setChapterOpen(false)} />
      )}

      {toast && (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-sm text-white shadow-lg dark:bg-white dark:text-slate-900">
          {toast}
        </div>
      )}

      {/* Floating feedback button — testers only */}
      {inTest && <FeedbackButton testKey={testKey} />}
    </div>
  );
}

function Select({ value, onChange, children }: { value: string; onChange: (v: string) => void; children: React.ReactNode }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="appearance-none rounded-full border border-slate-200 bg-white py-1.5 pl-3 pr-8 font-medium text-slate-900 outline-none transition hover:border-slate-300 focus:border-indigo-400 focus:ring-2 focus:ring-indigo-400/30 dark:border-white/10 dark:bg-black/30 dark:text-slate-100"
      >
        {children}
      </select>
      <ChevronIcon className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
    </div>
  );
}

function ToggleButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "flex items-center justify-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium transition",
        active ? "bg-gradient-to-r from-violet-600 to-fuchsia-500 text-white shadow-sm" : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function SubmitButton({ disabled, processing, label, icon }: { disabled: boolean; processing: boolean; label: string; icon?: React.ReactNode }) {
  return (
    <button
      type="submit"
      disabled={disabled}
      className="inline-flex items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-violet-600 via-fuchsia-500 to-pink-500 px-5 py-3 font-medium text-white shadow-md shadow-fuchsia-500/25 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {processing ? <Spinner size={18} /> : (icon ?? <SearchIcon />)}
      {processing ? "Working…" : label}
    </button>
  );
}

function ChipRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</span>
      {children}
    </div>
  );
}

function Chip({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-300 dark:hover:border-indigo-400/40"
    >
      {children}
    </button>
  );
}

function Sidebar({
  favorites,
  history,
  onClose,
  onClearHistory,
  onReplay,
  onFavoriteClick,
}: {
  favorites: { ref: string; version: string; text: string }[];
  history: { query: string; mode: Mode; ref?: string }[];
  onClose: () => void;
  onClearHistory: () => void;
  onReplay: (query: string, mode: Mode) => void;
  onFavoriteClick: (ref: string) => void;
}) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside className="h-full w-full max-w-sm overflow-y-auto border-l border-slate-200 bg-white p-5 dark:border-white/10 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Saved & recent</h2>
          <button type="button" onClick={onClose} className="text-sm text-slate-500">
            Close
          </button>
        </div>
        <section className="mb-6">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            <StarIcon size={13} /> Favorites
          </div>
          {favorites.length === 0 ? (
            <p className="text-sm text-slate-400">Star a verse to save it here.</p>
          ) : (
            <ul className="space-y-2">
              {favorites.map((f) => (
                <li key={`${f.ref}-${f.version}`}>
                  <button type="button" onClick={() => onFavoriteClick(f.ref)} className="w-full rounded-lg border border-slate-200 bg-white p-2 text-left text-sm transition hover:border-indigo-300 dark:border-white/10 dark:bg-white/5">
                    <span className="font-medium">{f.ref}</span> <span className="text-xs text-slate-400">{f.version}</span>
                    <span className="block truncate text-xs text-slate-500 dark:text-slate-400">{f.text}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">Recent searches</span>
            {history.length > 0 && (
              <button type="button" onClick={onClearHistory} className="text-xs text-slate-400 hover:text-slate-600">
                Clear
              </button>
            )}
          </div>
          {history.length === 0 ? (
            <p className="text-sm text-slate-400">Your searches will appear here.</p>
          ) : (
            <ul className="space-y-1.5">
              {history.map((h, i) => (
                <li key={`${h.query}-${i}`}>
                  <button type="button" onClick={() => onReplay(h.query, h.mode)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-slate-100 dark:hover:bg-white/5">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500 dark:bg-white/10 dark:text-slate-400">{h.mode}</span>
                    <span className="truncate">{h.query}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}
