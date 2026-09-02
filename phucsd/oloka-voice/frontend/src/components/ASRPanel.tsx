import React, { useState, useEffect, useRef } from "react";
import { 
  Play, 
  Pause, 
  Download, 
  Volume2, 
  Copy, 
  Check, 
  Sparkles, 
  AlertCircle, 
  Info, 
  FileText, 
  Loader2,
  AlignLeft,
  Mic,
  Trash2
} from "lucide-react";
import { api } from "../api/client";
import type { JobStatusResponse } from "../api/client";
import { PageHeader } from "./ui/PageHeader";
import { SectionCard } from "./ui/SectionCard";

export const ASRPanel: React.FC = () => {
  const [asrFile, setAsrFile] = useState<File | null>(null);
  const [resultTab, setResultTab] = useState<"text" | "subtitles" | "karaoke">("text");
  
  // Job Polling States
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Karaoke Player States
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [durationAudio, setDurationAudio] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [copied, setCopied] = useState(false);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);

  const pollIntervalRef = useRef<number | null>(null);
  const timeoutRef = useRef<number | null>(null);
  const playWordRangeRef = useRef<{ start: number, end: number } | null>(null);
  const isSeekingWordRef = useRef(false);
  const animationFrameRef = useRef<number | null>(null);

  const handleASRSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!asrFile) return;

    setLoading(true);
    setJobId(null);
    setJobStatus(null);
    setErrorMsg(null);
    setIsPlaying(false);
    setCurrentTime(0);
    setDurationAudio(0);
    setResultTab("text");

    try {
      const res = await api.createASRJob(asrFile);
      setJobId(res.job_id);
      localStorage.setItem("VITE_ASR_PANEL_JOB_ID", res.job_id);
      setJobStatus({
        job_id: res.job_id,
        status: res.status,
        message: res.message,
        progress: 0,
        audio_url: null,
        error_message: null
      });
      setIsPolling(true);
    } catch (err: any) {
      setErrorMsg(err.message || "Không thể khởi tạo tiến trình ASR.");
      setLoading(false);
    }
  };

  const handleClearJob = () => {
    setJobId(null);
    setJobStatus(null);
    setAsrFile(null);
    localStorage.removeItem("VITE_ASR_PANEL_JOB_ID");
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem("VITE_ASR_PANEL_JOB_ID");
    if (savedJobId) {
      setJobId(savedJobId);
      setLoading(true);
      api.getJobStatus(savedJobId)
        .then((status) => {
          setJobStatus(status);
          setLoading(false);
          if (status.status !== "completed" && status.status !== "failed") {
            setIsPolling(true);
          }
        })
        .catch((err) => {
          console.error("Lỗi khôi phục ASR Panel job status:", err);
          setLoading(false);
        });
    }
  }, []);

  // Job Polling Loop
  useEffect(() => {
    if (!isPolling || !jobId) return;

    const poll = async () => {
      try {
        const status = await api.getJobStatus(jobId);
        setJobStatus(status);

        if (status.status === "completed" || status.status === "failed") {
          setIsPolling(false);
          setLoading(false);
        }
      } catch (err: any) {
        console.error("ASR job polling error:", err);
        setErrorMsg(err.message || "Lỗi khi kiểm tra trạng thái tác vụ.");
        setIsPolling(false);
        setLoading(false);
      }
    };

    pollIntervalRef.current = window.setInterval(poll, 1500);

    timeoutRef.current = window.setTimeout(() => {
      setIsPolling(false);
      setLoading(false);
      setErrorMsg("Hết thời gian chờ kết quả (Timeout).");
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    }, 600000); // 10 minutes timeout

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [isPolling, jobId]);

  // Cleanup tracking frame on unmount
  useEffect(() => {
    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  // Parse & Normalize Alignment Timestamps
  const alignmentList = React.useMemo(() => {
    if (!jobStatus || !jobStatus.alignment) return [];
    
    // In our backend schema worker returns direct list/dict or alignment JSON string
    let alignmentData = jobStatus.alignment;
    if (typeof alignmentData === "string") {
      try {
        alignmentData = JSON.parse(alignmentData);
      } catch (e) {
        console.error("Lỗi parse alignment JSON string:", e);
        return [];
      }
    }

    let rawList: any[] = [];
    if (Array.isArray(alignmentData)) {
      rawList = alignmentData;
    } else if (alignmentData && typeof alignmentData === "object") {
      if (Array.isArray((alignmentData as any).words)) {
        rawList = (alignmentData as any).words;
      } else if (Array.isArray((alignmentData as any).chunks)) {
        rawList = (alignmentData as any).chunks;
      }
    }

    return rawList.map((item: any) => {
      if (!item) return { word: "", start: 0, end: 0 };
      
      // Handle Hugging Face Whisper chunk format: { text: "...", timestamp: [start, end] }
      if (item.timestamp !== undefined) {
        let start = 0;
        let end = 0;
        if (Array.isArray(item.timestamp)) {
          start = typeof item.timestamp[0] === "number" ? item.timestamp[0] : 0;
          end = typeof item.timestamp[1] === "number" ? item.timestamp[1] : start + 0.3;
        } else if (typeof item.timestamp === "object" && item.timestamp !== null) {
          start = typeof item.timestamp.start === "number" ? item.timestamp.start : 0;
          end = typeof item.timestamp.end === "number" ? item.timestamp.end : start + 0.3;
        }
        return {
          word: (item.text || item.word || "").toString(),
          start: typeof start === "number" && !isNaN(start) ? start : 0,
          end: typeof end === "number" && !isNaN(end) ? end : start + 0.3
        };
      }

      const start = typeof item.start === "number" ? item.start : (typeof item.start_time === "number" ? item.start_time : 0);
      const end = typeof item.end === "number" ? item.end : (typeof item.end_time === "number" ? item.end_time : start + 0.3);

      return {
        word: (item.word || item.text || "").toString(),
        start: !isNaN(start) ? start : 0,
        end: !isNaN(end) ? end : start + 0.3
      };
    }).filter(item => item.word.trim().length > 0 || item.end > item.start);
  }, [jobStatus]);

  // Convert raw alignment list into logical subtitle segments (SRT chunks)
  const subtitleSegments = React.useMemo(() => {
    if (!alignmentList || alignmentList.length === 0) return [];
    
    const segments: { start: number; end: number; text: string }[] = [];
    let currentSegmentWords: string[] = [];
    let segmentStart = alignmentList[0]?.start ?? 0;
    
    alignmentList.forEach((item: { word: string; start: number; end: number }, index: number) => {
      currentSegmentWords.push(item.word);
      const isLastWord = index === alignmentList.length - 1;
      
      const charLength = currentSegmentWords.join(" ").length;
      const nextItem = alignmentList[index + 1];
      const hasPauseAfter = !isLastWord && nextItem && ((nextItem.start - item.end) > 0.45);
      const hasPunctuation = /[.,!?;:]$/.test(item.word.trim());
      
      if (currentSegmentWords.length >= 7 || charLength > 36 || hasPauseAfter || hasPunctuation || isLastWord) {
        segments.push({
          start: segmentStart,
          end: item.end,
          text: currentSegmentWords.join(" ").trim()
        });
        
        if (!isLastWord && nextItem) {
          segmentStart = nextItem.start;
          currentSegmentWords = [];
        }
      }
    });
    
    return segments;
  }, [alignmentList]);

  // Audio playback authenticated URL
  const authenticatedUrl = React.useMemo(() => {
    if (!jobStatus) return "";
    return api.getASRAudioUrl(jobStatus.job_id);
  }, [jobStatus]);

  // Audio Event Bindings
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handlePlay = () => {
      setIsPlaying(true);
      startPreciseTracking();
    };
    const handlePause = () => {
      setIsPlaying(false);
      stopPreciseTracking();
    };
    const handleTimeUpdate = () => {
      const time = audio.currentTime;
      setCurrentTime(time);
      const range = playWordRangeRef.current;
      if (range && !isSeekingWordRef.current) {
        const stopTime = range.end - Math.min(0.08, (range.end - range.start) * 0.4);
        if (time >= stopTime) {
          audio.pause();
          playWordRangeRef.current = null;
        }
      }
    };
    const handleSeeked = () => {
      isSeekingWordRef.current = false;
    };
    const handleLoadedMetadata = () => setDurationAudio(audio.duration);
    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
      stopPreciseTracking();
    };

    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("seeked", handleSeeked);
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("ended", handleEnded);

    return () => {
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("seeked", handleSeeked);
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("ended", handleEnded);
      stopPreciseTracking();
    };
  }, [authenticatedUrl]);

  // Speed Sync
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  // Player handlers
  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      playWordRangeRef.current = null;
      audio.play().catch(err => console.error(err));
    }
  };

  const handleWordClick = (start: number, end: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    
    isSeekingWordRef.current = true;
    playWordRangeRef.current = { start, end };
    
    audio.currentTime = start;
    setCurrentTime(start);
    audio.play().catch(err => console.error(err));
  };

  // High precision time tracker
  const startPreciseTracking = () => {
    if (animationFrameRef.current) return;
    
    const checkTime = () => {
      if (audioRef.current) {
        setCurrentTime(audioRef.current.currentTime);
      }
      animationFrameRef.current = requestAnimationFrame(checkTime);
    };

    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }
    animationFrameRef.current = requestAnimationFrame(checkTime);
  };

  const stopPreciseTracking = () => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  };

  // Subtitle Helpers
  const formatTime = (seconds: number) => {
    const min = Math.floor(seconds / 60);
    const sec = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${min.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}.${ms.toString().padStart(2, "0")}`;
  };

  const formatSRTTime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const min = Math.floor((seconds % 3600) / 60);
    const sec = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    
    return `${hrs.toString().padStart(2, "0")}:${min.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")},${ms.toString().padStart(3, "0")}`;
  };

  const handleDownloadSRT = () => {
    if (subtitleSegments.length === 0) return;
    
    let srtText = "";
    subtitleSegments.forEach((seg, idx) => {
      srtText += `${idx + 1}\n`;
      srtText += `${formatSRTTime(seg.start)} --> ${formatSRTTime(seg.end)}\n`;
      srtText += `${seg.text}\n\n`;
    });
    
    const blob = new Blob([srtText], { type: "text/srt;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `omnivoice_asr_subtitles_${jobStatus?.job_id || "download"}.srt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    if (!audio || !durationAudio) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const clickedPercentage = x / rect.width;
    const targetTime = clickedPercentage * durationAudio;
    
    playWordRangeRef.current = null;
    audio.currentTime = targetTime;
    setCurrentTime(targetTime);
  };

  return (
    <div className="w-full flex flex-col gap-6">
      <PageHeader 
        title="Nhận dạng giọng nói (ASR)" 
        description="Tải lên tệp âm thanh để nhận dạng giọng nói, chia phụ đề tự động và trình chiếu karaoke tương tác."
        icon={<Mic className="w-6 h-6" />}
      />

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        {/* Left Column: Drag & Drop Audio Upload (5/12) */}
        <div className="xl:col-span-5 flex flex-col gap-4">
          <SectionCard title="Cấu hình nhận dạng">
            <form onSubmit={handleASRSubmit} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-fluid-xs font-bold text-muted-foreground uppercase tracking-wider">Tệp âm thanh cần nhận dạng</label>
                <div className="border-2 border-dashed border-border/85 hover:border-primary/50 transition-all rounded-2xl p-8 flex flex-col items-center justify-center text-center gap-3 bg-secondary/10 hover:bg-secondary/20 relative cursor-pointer min-h-[160px]">
                  <input
                    type="file"
                    accept="audio/*"
                    onChange={(e) => {
                      if (e.target.files && e.target.files.length > 0) {
                        setAsrFile(e.target.files[0]);
                      }
                    }}
                    className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
                  />
                  <Volume2 className="w-9 h-9 text-muted-foreground/60" />
                  <div className="flex flex-col gap-1">
                    <span className="text-fluid-xs font-bold text-foreground leading-normal">
                      {asrFile ? asrFile.name : "Kéo thả hoặc click để chọn tệp âm thanh"}
                    </span>
                    <span className="text-[10px] text-muted-foreground font-semibold">
                      Hỗ trợ WAV, MP3, M4A, FLAC (Lên đến 15MB)
                    </span>
                  </div>
                </div>
              </div>

              {errorMsg && (
                <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive rounded-xl text-fluid-sm font-semibold flex gap-1.5 items-start">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{errorMsg}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loading || !asrFile}
                className={`w-full h-11 rounded-xl font-bold text-fluid-sm transition-all duration-150 active:scale-[0.99] flex items-center justify-center gap-2 cursor-pointer shadow-md ${
                  loading || !asrFile
                    ? "bg-muted text-muted-foreground border border-border cursor-not-allowed"
                    : "bg-gradient-to-r from-primary via-indigo-600 to-accent text-white hover:brightness-105 hover:shadow-lg border-none"
                }`}
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4.5 h-4.5 animate-spin" />
                    <span>Đang nhận dạng giọng nói...</span>
                  </>
                ) : (
                  <>
                    <Mic className="w-4.5 h-4.5" />
                    <span>Bắt đầu nhận dạng giọng nói (ASR)</span>
                  </>
                )}
              </button>
            </form>
          </SectionCard>
        </div>

        {/* Right Column: Results & Interactive Player (7/12) */}
        <div className="xl:col-span-7 flex flex-col gap-5">
          {jobId && jobStatus && (jobStatus.status === "completed" || jobStatus.status === "failed") && (
            <div className="flex justify-end select-none -mb-3">
              <button
                type="button"
                onClick={handleClearJob}
                className="text-[10px] text-muted-foreground hover:text-foreground underline cursor-pointer font-bold flex items-center gap-1"
              >
                <Trash2 className="w-3 h-3" /> Xóa kết quả hiển thị
              </button>
            </div>
          )}

          {/* Job status loading card */}
          {jobId && jobStatus && jobStatus.status !== "completed" && jobStatus.status !== "failed" && (
            <div className="bg-card border border-border rounded-2xl p-6 flex flex-col gap-4 shadow-sm animate-pulse">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-muted-foreground uppercase">Trạng thái ASR Job</span>
                <span className="px-2 py-0.5 bg-secondary text-foreground rounded text-[10px] font-bold uppercase tracking-wider font-mono">
                  {jobStatus.status}
                </span>
              </div>
              <div className="w-full bg-secondary h-2.5 rounded-full overflow-hidden">
                <div 
                  className="bg-primary h-full transition-all duration-300 rounded-full" 
                  style={{ width: `${jobStatus.progress}%` }}
                />
              </div>
              <div className="flex justify-between items-center text-xs text-muted-foreground">
                <span>{jobStatus.message || "Đang nhận dạng giọng nói..."}</span>
                <span className="font-bold font-mono">{jobStatus.progress}%</span>
              </div>
            </div>
          )}

          {/* Job failure notice */}
          {jobStatus?.status === "failed" && (
            <div className="bg-destructive/10 border border-destructive/20 rounded-2xl p-6 flex flex-col gap-3 shadow-sm text-destructive">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-5 h-5 shrink-0" />
                <h3 className="font-bold text-sm">Gửi nhận dạng ASR Thất Bại</h3>
              </div>
              <p className="text-xs font-medium leading-relaxed">
                Chi tiết lỗi: {jobStatus.error_message || jobStatus.message || "Không xác định"}
              </p>
            </div>
          )}

          {/* Ready state instructions */}
          {!jobId && (
            <div className="bg-card border border-border border-dashed rounded-2xl p-10 flex flex-col items-center justify-center text-center gap-4 text-muted-foreground h-[320px] select-none">
              <div className="w-12 h-12 bg-secondary rounded-full flex items-center justify-center">
                <Mic className="w-5 h-5 text-muted-foreground/60" />
              </div>
              <div className="flex flex-col gap-1 max-w-sm">
                <h3 className="font-bold text-sm text-foreground">Chưa có kết quả nhận dạng</h3>
                <p className="text-xs font-medium leading-normal text-muted-foreground/80">
                  Tải lên tệp âm thanh và nhấn "Bắt đầu nhận dạng giọng nói" để xem phụ đề phân đoạn và lời karaoke tương tác.
                </p>
              </div>
            </div>
          )}

          {/* Main Karaoke Stage */}
          {jobStatus?.status === "completed" && (
            <div className="bg-card border border-border rounded-2xl flex flex-col shadow-sm overflow-hidden animate-fadeIn">
              <audio ref={audioRef} src={authenticatedUrl} />

              {/* Display Alignment Analytics Metrics */}
              <div className="bg-secondary/25 border-b border-border p-4 grid grid-cols-3 gap-4 text-center select-none">
                <div className="flex flex-col">
                  <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">Số lượng từ</span>
                  <span className="text-fluid-md font-bold text-foreground font-mono mt-0.5">{alignmentList.length}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider">Thời lượng Audio</span>
                  <span className="text-fluid-md font-bold text-foreground font-mono mt-0.5">
                    {durationAudio ? `${durationAudio.toFixed(2)}s` : "--"}
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-muted-foreground font-bold uppercase tracking-wider font-mono">Từ / Giây</span>
                  <span className="text-fluid-md font-bold text-foreground font-mono mt-0.5">
                    {durationAudio && alignmentList.length 
                      ? (alignmentList.length / durationAudio).toFixed(1) 
                      : "--"}
                  </span>
                </div>
              </div>

              {/* Tab Selector */}
              <div className="flex border-b border-border bg-secondary/15 px-4 pt-2 gap-2 select-none">
                <button
                  type="button"
                  onClick={() => setResultTab("text")}
                  className={`px-4 py-2 text-xs font-bold transition-all border-b-2 rounded-t-lg cursor-pointer flex items-center gap-1.5 ${
                    resultTab === "text"
                      ? "border-primary text-primary bg-background/50"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <FileText className="w-3.5 h-3.5" />
                  Văn bản
                </button>
                {alignmentList.length > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setResultTab("subtitles")}
                      className={`px-4 py-2 text-xs font-bold transition-all border-b-2 rounded-t-lg cursor-pointer flex items-center gap-1.5 ${
                        resultTab === "subtitles"
                          ? "border-primary text-primary bg-background/50"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <AlignLeft className="w-3.5 h-3.5" />
                      Phụ đề (SRT)
                    </button>
                    <button
                      type="button"
                      onClick={() => setResultTab("karaoke")}
                      className={`px-4 py-2 text-xs font-bold transition-all border-b-2 rounded-t-lg cursor-pointer flex items-center gap-1.5 ${
                        resultTab === "karaoke"
                          ? "border-primary text-primary bg-background/50"
                          : "border-transparent text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      <Sparkles className="w-3.5 h-3.5" />
                      Karaoke
                    </button>
                  </>
                )}
              </div>

              {/* Tab Content Display Area */}
              <div className="p-6 md:p-8 min-h-[220px] max-h-[380px] overflow-y-auto bg-background/25 leading-loose text-justify relative">
                {resultTab === "text" && (
                  <div className="flex flex-col gap-4">
                    <textarea
                      readOnly
                      value={jobStatus?.text || ""}
                      className="w-full min-h-[120px] bg-transparent border-0 text-fluid-base text-foreground font-medium focus:outline-none resize-none leading-relaxed"
                    />
                    <div className="flex justify-end gap-2 select-none">
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard.writeText(jobStatus?.text || "");
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary/80 border border-border rounded-xl text-fluid-xs font-bold text-foreground cursor-pointer transition-colors"
                      >
                        {copied ? (
                          <>
                            <Check className="w-3.5 h-3.5 text-success" />
                            <span>Đã sao chép</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" />
                            <span>Sao chép văn bản</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )}

                {resultTab === "subtitles" && (
                  <div className="flex flex-col gap-3 animate-fadeIn">
                    <div className="flex justify-end select-none mb-1">
                      <button
                        type="button"
                        onClick={handleDownloadSRT}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 border border-primary/20 rounded-xl text-fluid-xs font-bold text-primary cursor-pointer transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Tải phụ đề (.srt)
                      </button>
                    </div>

                    {subtitleSegments.length > 0 ? (
                      <div className="flex flex-col gap-2.5">
                        {subtitleSegments.map((seg, idx) => {
                          const isCurrent = currentTime >= seg.start && currentTime <= seg.end;
                          return (
                            <button
                              key={idx}
                              type="button"
                              onClick={() => {
                                if (audioRef.current) {
                                  playWordRangeRef.current = null;
                                  audioRef.current.currentTime = seg.start;
                                  setCurrentTime(seg.start);
                                  audioRef.current.play().catch(err => console.error(err));
                                }
                              }}
                              className={`w-full text-left p-3 rounded-xl border transition-all cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 ${
                                isCurrent
                                  ? "bg-primary/10 border-primary/30 shadow-sm"
                                  : "bg-card/40 border-border/60 hover:bg-secondary/40 hover:border-border"
                              }`}
                            >
                              <span className={`text-fluid-sm font-semibold leading-relaxed flex-grow ${isCurrent ? "text-primary font-bold" : "text-foreground/95"}`}>
                                {seg.text}
                              </span>
                              <span className="text-[10px] font-mono font-bold text-muted-foreground bg-secondary/80 px-2 py-0.5 rounded-md self-start sm:self-center tabular-nums">
                                {formatTime(seg.start)} &rarr; {formatTime(seg.end)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="w-full flex flex-col items-center justify-center text-center text-muted-foreground py-10 gap-2 select-none">
                        <Info className="w-5 h-5" />
                        <span className="text-xs font-semibold">Không có dữ liệu phụ đề.</span>
                      </div>
                    )}
                  </div>
                )}

                {resultTab === "karaoke" && (
                  <div className="animate-fadeIn">
                    {alignmentList.length > 0 ? (
                      <div className="flex flex-wrap gap-x-1.5 gap-y-2.5 items-center select-none">
                        {alignmentList.map((item: any, index: number) => {
                          const isActive = currentTime >= item.start && currentTime <= item.end;
                          const isPast = currentTime > item.end;
                          
                          return (
                            <button
                              key={index}
                              type="button"
                              onClick={() => handleWordClick(item.start, item.end)}
                              className={`inline-block py-0.5 px-1.5 rounded-md text-fluid-base transition-all duration-100 cursor-pointer border ${
                                isActive
                                  ? "bg-primary/20 border-primary/40 text-primary font-black scale-110 shadow-sm animate-pulse"
                                  : isPast
                                  ? "bg-secondary/20 border-transparent text-muted-foreground/50 font-medium scale-95"
                                  : "bg-transparent border-transparent text-foreground hover:bg-secondary/40 hover:border-border font-medium"
                              }`}
                              title={`Nhấp để phát âm riêng từ này (Từ ${item.start}s - ${item.end}s)`}
                            >
                              {item.word}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="w-full flex flex-col items-center justify-center text-center text-muted-foreground py-10 gap-2 select-none">
                        <Info className="w-5 h-5" />
                        <span className="text-xs font-semibold">Không có dữ liệu căn thời gian karaoke.</span>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Bottom Custom Media Player Controls */}
              <div className="border-t border-border p-4 bg-secondary/15 flex flex-col gap-3 select-none">
                {/* Duration bar progress track */}
                <div 
                  onClick={handleProgressClick}
                  className="w-full h-1.5 bg-secondary rounded-full cursor-pointer relative overflow-hidden group"
                >
                  <div 
                    className="bg-primary h-full transition-all duration-75 rounded-full"
                    style={{ width: `${durationAudio ? (currentTime / durationAudio) * 100 : 0}%` }}
                  />
                  <div 
                    className="absolute top-0 right-0 bottom-0 left-0 bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity"
                  />
                </div>

                <div className="flex items-center justify-between gap-4">
                  {/* Left: Play/Pause and Timers */}
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={togglePlay}
                      className="w-9 h-9 rounded-full bg-primary hover:bg-primary/95 text-white flex items-center justify-center cursor-pointer shadow transition-all duration-150 active:scale-95 shrink-0"
                    >
                      {isPlaying ? <Pause className="w-4.5 h-4.5" /> : <Play className="w-4.5 h-4.5 fill-current ml-0.5" />}
                    </button>
                    
                    <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-foreground/80 tabular-nums">
                      <span>{formatTime(currentTime)}</span>
                      <span className="text-muted-foreground">/</span>
                      <span className="text-muted-foreground">{formatTime(durationAudio)}</span>
                    </div>
                  </div>

                  {/* Right: Playback Speed Dropdown */}
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setShowSpeedMenu(!showSpeedMenu)}
                      className="px-2.5 py-1.5 bg-secondary hover:bg-secondary/80 border border-border/80 rounded-xl text-fluid-xs font-bold text-foreground/90 cursor-pointer flex items-center gap-1 transition-colors"
                    >
                      <span>Tốc độ: {playbackRate.toFixed(2)}x</span>
                    </button>
                    {showSpeedMenu && (
                      <div className="absolute bottom-full right-0 mb-1 bg-card border border-border shadow-xl rounded-xl py-1.5 min-w-[90px] z-50 flex flex-col">
                        {[0.5, 0.75, 1.0, 1.25, 1.5, 2.0].map((r) => (
                          <button
                            key={r}
                            type="button"
                            onClick={() => {
                              setPlaybackRate(r);
                              setShowSpeedMenu(false);
                            }}
                            className={`w-full text-left px-3.5 py-1.5 text-xs font-semibold cursor-pointer ${
                              playbackRate === r 
                                ? "bg-primary/10 text-primary font-bold" 
                                : "text-foreground hover:bg-secondary/80"
                            }`}
                          >
                            {r.toFixed(2)}x
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
