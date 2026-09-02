import React, { useState, useEffect, useRef } from "react";
import { 
  Sparkles, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  Download, 
  FileText, 
  RefreshCw, 
  Save, 
  Key, 
  Sliders, 
  Wand2, 
  Loader2,
  Film,
  Music,
  Mic,
  Languages,
  Upload,
  PlaySquare,
  Cookie,
  ShieldCheck,
  Trash2,
  X,
  ExternalLink,
  Copy,
  Check,
  LogOut
} from "lucide-react";
import { api, type VideoDubbingJobResponse, type SubtitleSegment, type LLMProfile } from "../api/client";
import { PageHeader } from "./ui/PageHeader";
import { SectionCard } from "./ui/SectionCard";

// Pipeline steps definition
const PIPELINE_STEPS = [
  { id: "downloading", label: "Tải Video", desc: "Tải xuống video & trích xuất audio", icon: Download },
  { id: "separating_audio", label: "Tách Âm Thanh", desc: "Demucs GPU tách Vocals & BGM", icon: Music },
  { id: "transcribing", label: "Whisper ASR", desc: "Trích xuất phụ đề & mốc thời gian", icon: Mic },
  { id: "translating", label: "Dịch Thuật LLM", desc: "Dịch phụ đề qua AI Model", icon: Languages },
  { id: "awaiting_review", label: "Kiểm Duyệt", desc: "Xem trước & chỉnh sửa phụ đề", icon: FileText },
  { id: "generating_tts", label: "Sinh Giọng Clone", desc: "Tổng hợp thoại qua OmniVoice", icon: Wand2 },
  { id: "mixing_audio", label: "Trộn Âm Thanh", desc: "Khớp nhịp & trộn nhạc nền BGM", icon: Sliders },
  { id: "muxing_video", label: "Đóng Gói", desc: "Xuất video lồng tiếng MP4", icon: Film }
];

export default function DubbingStudio() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [targetLanguage, setTargetLanguage] = useState("Vietnamese"); // Default to Vietnamese
  const [smartSeparation, setSmartSeparation] = useState(true);
  
  // Upload States
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadedJobId, setUploadedJobId] = useState<string | null>(null);
  const [uploadedVideoUrl, setUploadedVideoUrl] = useState<string | null>(null);

  // Diagnostic Logs States
  const [jobLogs, setJobLogs] = useState("");
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Job States
  const [jobId, setJobId] = useState<string | null>(() => {
    return localStorage.getItem("active_dubbing_job_id") || null;
  });
  const [job, setJob] = useState<VideoDubbingJobResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // LLM Config state
  const [llmProvider, setLlmProvider] = useState("gemini");
  const [llmModel, setLlmModel] = useState("gemini-2.5-flash");
  const [llmCustomEndpoint, setLlmCustomEndpoint] = useState("");
  const [llmProfiles, setLlmProfiles] = useState<LLMProfile[]>([]);
  const [selectedLlmProfileId, setSelectedLlmProfileId] = useState<string>("");

  // Subtitle editor state
  const [originalSubs, setOriginalSubs] = useState<SubtitleSegment[]>([]);
  const [translatedSubs, setTranslatedSubs] = useState<SubtitleSegment[]>([]);
  const [selectedSegId, setSelectedSegId] = useState<number | null>(null);
  const [savingSubs, setSavingSubs] = useState(false);

  // Media Player Refs & Audio Mixer
  const videoPlayerRef = useRef<HTMLVideoElement>(null);
  const vocalsPlayerRef = useRef<HTMLAudioElement>(null);
  const bgmPlayerRef = useRef<HTMLAudioElement>(null);

  const [vocalsVolume, setVocalsVolume] = useState(1.0);
  const [bgmVolume, setBgmVolume] = useState(0.4);

  // YouTube Authentication States (OAuth & Cookie)
  const [activeModalTab, setActiveModalTab] = useState<"oauth" | "cookies">("oauth");
  const [oauthStatus, setOauthStatus] = useState<{ connected: boolean; expires_at?: number } | null>(null);
  const [oauthFlowData, setOauthFlowData] = useState<{ user_code: string; device_code: string; verification_url: string; interval: number } | null>(null);
  const [oauthStarting, setOauthStarting] = useState(false);
  const [oauthPolling, setOauthPolling] = useState(false);
  const [oauthCopied, setOauthCopied] = useState(false);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [oauthSuccessMsg, setOauthSuccessMsg] = useState<string | null>(null);
  const pollTimerRef = useRef<any>(null);

  const [cookieStatus, setCookieStatus] = useState<{ has_cookies: boolean; size_bytes?: number } | null>(null);
  const [showCookieModal, setShowCookieModal] = useState(false);
  const [cookieText, setCookieText] = useState("");
  const [cookieUploading, setCookieUploading] = useState(false);
  const [cookieMsg, setCookieMsg] = useState<string | null>(null);

  // Restore active job from localStorage on mount & fetch settings & auth statuses
  useEffect(() => {
    fetchSystemLlmSettings();
    fetchLlmProfiles();
    fetchCookieStatus();
    fetchOAuthStatus();
    if (jobId) {
      fetchJobDetails(jobId);
    }
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  const fetchOAuthStatus = async () => {
    try {
      const res = await api.getYouTubeOAuthStatus();
      setOauthStatus(res);
    } catch {}
  };

  const handleStartOAuth = async () => {
    setOauthStarting(true);
    setOauthError(null);
    setOauthSuccessMsg(null);
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    try {
      const data = await api.startYouTubeOAuth();
      setOauthFlowData(data);
      setOauthPolling(true);

      // Start polling
      const pollInterval = (data.interval || 5) * 1000;
      pollTimerRef.current = setInterval(async () => {
        try {
          const pollRes = await api.pollYouTubeOAuth(data.device_code);
          if (pollRes.status === "success") {
            clearInterval(pollTimerRef.current);
            setOauthPolling(false);
            setOauthSuccessMsg(pollRes.message || "Đã kết nối tài khoản YouTube thành công!");
            fetchOAuthStatus();
          } else if (pollRes.status === "error") {
            clearInterval(pollTimerRef.current);
            setOauthPolling(false);
            setOauthError(pollRes.error || "Quá trình xác thực không thành công.");
          }
        } catch (err: any) {
          // Keep polling on minor network hiccups
        }
      }, pollInterval);
    } catch (err: any) {
      setOauthError(err.message || "Không thể khởi tạo phiên đăng nhập Google");
    } finally {
      setOauthStarting(false);
    }
  };

  const handleDisconnectOAuth = async () => {
    if (!window.confirm("Bạn có chắc chắn muốn ngắt kết nối tài khoản YouTube?")) return;
    try {
      await api.disconnectYouTubeOAuth();
      setOauthStatus({ connected: false });
      setOauthFlowData(null);
      setOauthSuccessMsg(null);
    } catch (err: any) {
      alert(`Lỗi: ${err.message || "Không thể ngắt kết nối"}`);
    }
  };

  const handleCopyCode = () => {
    if (!oauthFlowData?.user_code) return;
    navigator.clipboard.writeText(oauthFlowData.user_code);
    setOauthCopied(true);
    setTimeout(() => setOauthCopied(false), 2500);
  };

  const fetchCookieStatus = async () => {
    try {
      const res = await api.getDubbingCookieStatus();
      setCookieStatus(res);
    } catch {}
  };

  const handleUploadCookieFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCookieUploading(true);
    setCookieMsg(null);
    try {
      const res = await api.uploadDubbingCookies(file);
      setCookieMsg(res.message);
      fetchCookieStatus();
    } catch (err: any) {
      setCookieMsg(`Lỗi: ${err.message || "Không thể tải cookie"}`);
    } finally {
      setCookieUploading(false);
    }
  };

  const handleSaveCookieText = async () => {
    if (!cookieText.trim()) return;
    setCookieUploading(true);
    setCookieMsg(null);
    try {
      const res = await api.uploadDubbingCookies(undefined, cookieText.trim());
      setCookieMsg(res.message);
      setCookieText("");
      fetchCookieStatus();
    } catch (err: any) {
      setCookieMsg(`Lỗi: ${err.message || "Không thể lưu cookie"}`);
    } finally {
      setCookieUploading(false);
    }
  };

  const handleDeleteCookies = async () => {
    if (!window.confirm("Bạn có chắc chắn muốn xóa file cookies đã lưu?")) return;
    setCookieUploading(true);
    setCookieMsg(null);
    try {
      const res = await api.deleteDubbingCookies();
      setCookieMsg(res.message);
      fetchCookieStatus();
    } catch (err: any) {
      setCookieMsg(`Lỗi: ${err.message || "Không thể xóa cookie"}`);
    } finally {
      setCookieUploading(false);
    }
  };

  const fetchLlmProfiles = async () => {
    try {
      const profiles = await api.listLlmProfiles();
      setLlmProfiles(profiles);
      const activeProf = profiles.find(p => p.is_active);
      if (activeProf) {
        setSelectedLlmProfileId(activeProf.id);
      } else if (profiles.length > 0) {
        setSelectedLlmProfileId(profiles[0].id);
      }
    } catch {
      // Non-admin fallback or ignore
    }
  };

  const fetchSystemLlmSettings = async () => {
    try {
      const settings = await api.adminGetSystemSettings();
      if (settings.llm_provider) setLlmProvider(settings.llm_provider);
      if (settings.llm_model) setLlmModel(settings.llm_model);
      if (settings.llm_custom_endpoint) setLlmCustomEndpoint(settings.llm_custom_endpoint);
    } catch {
      // Non-admin fallback or ignore
    }
  };

  const fetchJobDetails = async (id: string) => {
    try {
      const data = await api.getDubbingJob(id);
      setJob(data);
      if (data.original_subtitles) setOriginalSubs(data.original_subtitles);
      if (data.translated_subtitles) setTranslatedSubs(data.translated_subtitles);
      
      // Fetch logs
      try {
        const logData = await api.getDubbingJobLog(id);
        setJobLogs(logData.log);
      } catch {}
    } catch (err: any) {
      console.error("Lỗi lấy thông tin Job:", err);
    }
  };

  // Poll active job status and logs
  useEffect(() => {
    if (!jobId) return;

    localStorage.setItem("active_dubbing_job_id", jobId);

    // Initial fetch logs
    const fetchLogs = async () => {
      try {
        const logData = await api.getDubbingJobLog(jobId);
        setJobLogs(logData.log);
      } catch {}
    };
    fetchLogs();

    const interval = setInterval(async () => {
      try {
        const data = await api.getDubbingJob(jobId);
        setJob(data);

        if (data.original_subtitles && data.original_subtitles.length > 0) {
          setOriginalSubs(data.original_subtitles);
        }
        if (data.translated_subtitles && data.translated_subtitles.length > 0) {
          setTranslatedSubs(data.translated_subtitles);
        }

        // Fetch logs
        try {
          const logData = await api.getDubbingJobLog(jobId);
          setJobLogs(logData.log);
        } catch {}

        if (data.status === "completed" || data.status === "failed") {
          clearInterval(interval);
        }
      } catch (err: any) {
        console.error("Lỗi đồng bộ Job status:", err);
      }
    }, 2500);

    return () => clearInterval(interval);
  }, [jobId]);

  // Autoscroll logs terminal to bottom
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [jobLogs]);

  // Handle immediate file upload when selected
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    if (!file) return;

    setSelectedFile(file);
    setUploading(true);
    setUploadProgress(0);
    setError(null);
    setUploadedJobId(null);
    setUploadedVideoUrl(null);

    try {
      const response = await api.uploadDubbingVideo(file, (progress) => {
        setUploadProgress(progress);
      });
      setUploadedJobId(response.id);
      setUploadedVideoUrl(api.getDubbingFileUrl(response.id, "video"));
    } catch (err: any) {
      setError(err.message || "Tải video lên thất bại. Vui lòng thử lại.");
      setSelectedFile(null);
    } finally {
      setUploading(false);
    }
  };

  const handleStartDubbing = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      if (!selectedFile && !youtubeUrl.trim()) {
        throw new Error("Vui lòng tải lên tệp video hoặc dán link YouTube.");
      }

      const response = await api.createDubbingJob(
        uploadedJobId ? undefined : (selectedFile || undefined),
        youtubeUrl.trim() || undefined,
        targetLanguage,
        uploadedJobId || undefined,
        selectedLlmProfileId || undefined
      );

      setJobId(response.id);
      localStorage.setItem("active_dubbing_job_id", response.id);
      setJob(response);
    } catch (err: any) {
      setError(err.message || "Không thể khởi tạo tác vụ lồng tiếng.");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveSubtitles = async () => {
    if (!jobId) return;
    setSavingSubs(true);
    setError(null);
    try {
      await api.updateDubbingSubtitles(jobId, originalSubs, translatedSubs);
      alert("Đã lưu bản dịch phụ đề thành công!");
    } catch (err: any) {
      setError(err.message || "Lỗi lưu phụ đề.");
    } finally {
      setSavingSubs(false);
    }
  };

  const handleFinalize = async () => {
    if (!jobId) return;
    setError(null);
    setLoading(true);
    try {
      await api.updateDubbingSubtitles(jobId, originalSubs, translatedSubs);
      await api.finalizeDubbingJob(jobId, vocalsVolume, bgmVolume);
      const data = await api.getDubbingJob(jobId);
      setJob(data);
    } catch (err: any) {
      setError(err.message || "Lỗi hoàn tất lồng tiếng.");
    } finally {
      setLoading(false);
    }
  };

  const jumpToSegment = (start: number, id: number) => {
    setSelectedSegId(id);
    if (videoPlayerRef.current) {
      videoPlayerRef.current.currentTime = start;
      videoPlayerRef.current.play();
    }
  };

  const updateSubText = (id: number, text: string) => {
    setTranslatedSubs(prev =>
      prev.map(item => (item.id === id ? { ...item, text } : item))
    );
  };

  const resetState = () => {
    localStorage.removeItem("active_dubbing_job_id");
    setJobId(null);
    setJob(null);
    setYoutubeUrl("");
    setSelectedFile(null);
    setOriginalSubs([]);
    setTranslatedSubs([]);
    setSelectedSegId(null);
    setError(null);
    setUploading(false);
    setUploadProgress(0);
    setUploadedJobId(null);
    setUploadedVideoUrl(null);
    setJobLogs("");
  };

  // Sync separate audio tracks with video player
  const handleVideoPlay = () => {
    vocalsPlayerRef.current?.play();
    bgmPlayerRef.current?.play();
  };

  const handleVideoPause = () => {
    vocalsPlayerRef.current?.pause();
    bgmPlayerRef.current?.pause();
  };

  const handleVideoSeek = () => {
    if (videoPlayerRef.current) {
      const t = videoPlayerRef.current.currentTime;
      if (vocalsPlayerRef.current) vocalsPlayerRef.current.currentTime = t;
      if (bgmPlayerRef.current) bgmPlayerRef.current.currentTime = t;
    }
  };

  // Get current step index for the progress stepper
  const getActiveStepIndex = () => {
    if (!job) return 0;
    const statusMap: Record<string, number> = {
      queued: 0,
      downloading: 0,
      separating_audio: 1,
      transcribing: 2,
      translating: 3,
      awaiting_review: 4,
      generating_tts: 5,
      mixing_audio: 6,
      muxing_video: 7,
      completed: 8,
      failed: -1
    };
    return statusMap[job.status] !== undefined ? statusMap[job.status] : 0;
  };

  const currentStepIdx = getActiveStepIndex();

  return (
    <div className="w-full flex flex-col gap-6 animate-fadeIn">
      {/* Header */}
      <div className="flex justify-between items-center">
        <PageHeader
          title="Studio Lồng Tiếng Video AI"
          description="Dịch thuật phụ đề đa ngôn ngữ qua LLM, bóc tách nhạc nền Demucs và lồng tiếng tự động bằng OmniVoice Clone."
          icon={<Film className="w-5 h-5" />}
        />
        {jobId && (
          <button
            onClick={resetState}
            className="flex items-center gap-2 px-3.5 py-2 bg-secondary hover:bg-secondary/80 text-foreground text-xs font-semibold rounded-xl border border-border transition-colors cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Tạo dự án mới</span>
          </button>
        )}
      </div>

      {error && (
        <div className="p-4 bg-destructive/10 border border-destructive/30 text-destructive rounded-xl text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* --- STEPPER PROGRESS BAR (REALTIME PIPELINE) --- */}
      {jobId && job && (
        <SectionCard title="Tiến Trình Xử Lý Realtime">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary animate-pulse" />
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                  {job.status.toUpperCase()}
                </span>
              </div>
              <span className="text-xs font-bold text-primary">
                {job.progress}%
              </span>
            </div>

            {/* Stepper bubbles */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 pt-2">
              {PIPELINE_STEPS.map((step, idx) => {
                const IconComponent = step.icon;
                const isDone = currentStepIdx > idx || job.status === "completed";
                const isCurrent = currentStepIdx === idx && job.status !== "completed" && job.status !== "failed";
                const isFailed = job.status === "failed" && currentStepIdx === idx;

                return (
                  <div
                    key={step.id}
                    className={`flex flex-col items-center p-2.5 rounded-xl border transition-all text-center relative ${
                      isDone
                        ? "bg-primary/5 border-primary/30 text-foreground"
                        : isCurrent
                        ? "bg-primary/15 border-primary text-primary font-bold shadow-sm ring-2 ring-primary/20"
                        : isFailed
                        ? "bg-destructive/10 border-destructive text-destructive"
                        : "bg-secondary/20 border-border/50 text-muted-foreground opacity-60"
                    }`}
                  >
                    <div className="mb-1.5 relative">
                      {isDone ? (
                        <CheckCircle2 className="w-5 h-5 text-primary" />
                      ) : isCurrent ? (
                        <Loader2 className="w-5 h-5 text-primary animate-spin" />
                      ) : (
                        <IconComponent className="w-5 h-5" />
                      )}
                    </div>
                    <span className="text-[11px] leading-tight font-bold line-clamp-1">{step.label}</span>
                    <span className="text-[9px] text-muted-foreground mt-0.5 line-clamp-1 hidden sm:block">{step.desc}</span>
                  </div>
                );
              })}
            </div>

            {/* Live Message */}
            <div className="flex items-center gap-2 p-3 bg-secondary/40 border border-border/60 rounded-xl text-xs text-foreground">
              <Clock className="w-3.5 h-3.5 text-muted-foreground shrink-0 animate-spin" />
              <span className="font-medium">{job.message || "Đang xử lý tiến trình..."}</span>
            </div>

            {/* Console log terminal */}
            <div className="mt-4 flex flex-col gap-2">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                  <span className="inline-block w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                  Console Log Chẩn Đoán & Báo Cáo
                </span>
                <button
                  type="button"
                  onClick={async () => {
                    if (jobId) {
                      try {
                        const logData = await api.getDubbingJobLog(jobId);
                        setJobLogs(logData.log);
                      } catch {}
                    }
                  }}
                  className="text-[10px] text-primary hover:underline font-semibold flex items-center gap-1 cursor-pointer"
                >
                  <RefreshCw className="w-2.5 h-2.5" /> Làm mới log
                </button>
              </div>
              <div className="bg-[#18181b] border border-border/60 rounded-xl p-4 font-mono text-[11px] text-[#a1a1aa] overflow-y-auto max-h-60 flex flex-col gap-1.5 shadow-inner">
                {jobLogs ? (
                  jobLogs.split("\n").map((line, lIdx) => {
                    if (!line.trim()) return null;
                    let isError = line.includes("LỖI") || line.includes("FAILED") || line.includes("ERROR");
                    let isSuccess = line.includes("thành công") || line.includes("SUCCESS") || line.includes("hoàn tất");
                    let isKaggle = line.includes("[KAGGLE]") || line.includes("[MOCK]");
                    return (
                      <div key={lIdx} className="leading-relaxed break-all text-left">
                        <span className={isError ? "text-red-400 font-bold" : isSuccess ? "text-emerald-400" : isKaggle ? "text-cyan-400" : "text-zinc-300"}>
                          {line}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <div className="text-zinc-500 italic text-left">Đang tải nhật ký tiến trình...</div>
                )}
                <div ref={logsEndRef} />
              </div>
            </div>
          </div>
        </SectionCard>
      )}

      {/* --- FORM SETUP & LLM CONFIGURATION (STEP 1) --- */}
      {!jobId && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2">
            <SectionCard title="Tải Lên Video Đầu Vào">
              <form onSubmit={handleStartDubbing} className="flex flex-col gap-5">
                
                {/* Drag and Drop Card with Progress & Preview */}
                {!uploadedJobId && !uploading ? (
                  <div className="border-2 border-dashed border-border hover:border-primary/50 transition-colors rounded-2xl p-8 flex flex-col items-center justify-center cursor-pointer bg-secondary/20 relative group">
                    <input
                      type="file"
                      accept="video/*"
                      onChange={handleFileChange}
                      className="absolute inset-0 opacity-0 cursor-pointer"
                    />
                    <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-3 group-hover:scale-110 transition-transform">
                      <Upload className="w-6 h-6" />
                    </div>
                    <span className="text-xs font-bold text-foreground">
                      Tải lên tệp video từ máy tính
                    </span>
                    <span className="text-[10px] text-muted-foreground mt-1">Hỗ trợ các định dạng MP4, MKV, MOV</span>
                  </div>
                ) : uploading ? (
                  <div className="border-2 border-dashed border-primary/45 rounded-2xl p-8 flex flex-col items-center justify-center bg-primary/5">
                    <Loader2 className="w-8 h-8 text-primary animate-spin mb-3" />
                    <span className="text-xs font-bold text-foreground mb-2">Đang tải video lên máy chủ... {uploadProgress}%</span>
                    <div className="w-full max-w-xs bg-secondary h-2 rounded-full overflow-hidden border border-border">
                      <div className="bg-primary h-full transition-all duration-300" style={{ width: `${uploadProgress}%` }}></div>
                    </div>
                  </div>
                ) : (
                  <div className="border border-border rounded-2xl p-5 flex flex-col gap-3 bg-secondary/15">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                        <span className="text-xs font-bold text-foreground truncate max-w-xs sm:max-w-md">
                          {selectedFile ? selectedFile.name : "Video đã được tải lên"}
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedFile(null);
                          setUploadedJobId(null);
                          setUploadedVideoUrl(null);
                        }}
                        className="text-[10px] text-destructive hover:underline font-semibold cursor-pointer"
                      >
                        Chọn video khác
                      </button>
                    </div>
                    {uploadedVideoUrl && (
                      <div className="aspect-video w-full rounded-xl overflow-hidden bg-black border border-border relative">
                        <video
                          src={uploadedVideoUrl}
                          controls
                          className="w-full h-full object-contain"
                        />
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center my-1">
                  <div className="flex-grow border-t border-border"></div>
                  <span className="mx-3 text-[10px] text-muted-foreground font-bold tracking-wider uppercase">HOẶC DÁN LINK YOUTUBE</span>
                  <div className="flex-grow border-t border-border"></div>
                </div>

                {/* YouTube Link */}
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
                      <PlaySquare className="w-3.5 h-3.5 text-red-500" />
                      <span>Đường dẫn YouTube</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => setShowCookieModal(true)}
                      className={`text-[11px] px-2.5 py-1 rounded-lg border flex items-center gap-1.5 font-medium transition-all cursor-pointer ${
                        oauthStatus?.connected
                          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/25"
                          : cookieStatus?.has_cookies
                          ? "bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30 hover:bg-blue-500/25"
                          : "bg-primary/15 text-primary border-primary/30 hover:bg-primary/25"
                      }`}
                    >
                      {oauthStatus?.connected ? (
                        <>
                          <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                          <span>YouTube: Đã kết nối</span>
                        </>
                      ) : cookieStatus?.has_cookies ? (
                        <>
                          <Cookie className="w-3.5 h-3.5 text-blue-500" />
                          <span>Cookie: Đã cài đặt</span>
                        </>
                      ) : (
                        <>
                          <Key className="w-3.5 h-3.5 text-primary" />
                          <span>Kết nối YouTube (1-Click)</span>
                        </>
                      )}
                    </button>
                  </div>
                  <input
                    type="url"
                    placeholder="https://www.youtube.com/watch?v=..."
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    className="bg-background border border-border rounded-xl px-4 py-2.5 text-xs text-foreground focus:outline-none focus:border-primary"
                  />
                </div>

                {/* Smart separation toggle */}
                <div className="flex items-center gap-3 p-3.5 bg-secondary/30 rounded-xl border border-border">
                  <input
                    type="checkbox"
                    id="smart-sep"
                    checked={smartSeparation}
                    onChange={(e) => setSmartSeparation(e.target.checked)}
                    className="w-4 h-4 accent-primary rounded cursor-pointer"
                  />
                  <label htmlFor="smart-sep" className="text-xs text-foreground cursor-pointer flex-grow">
                    <span className="font-bold block">Tách giọng nói & nhạc nền (Demucs GPU)</span>
                    <span className="text-[10px] text-muted-foreground">Cô lập thoại để clone giọng chuẩn, giữ nguyên nhạc hiệu ứng.</span>
                  </label>
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-3 bg-gradient-to-r from-primary to-accent hover:brightness-105 text-white font-bold text-xs rounded-xl transition-all shadow-md shadow-primary/10 flex items-center justify-center gap-2 disabled:opacity-50 cursor-pointer"
                >
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Đang khởi tạo tác vụ...</span>
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-4 h-4" />
                      <span>Bắt Đầu Nhận Dạng & Dịch Thuật</span>
                    </>
                  )}
                </button>

              </form>
            </SectionCard>
          </div>

          {/* Right Configuration Sidecard */}
          <div className="flex flex-col gap-6">
            <SectionCard title="Cấu Hình Dịch Thuật">
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Ngôn ngữ đích</label>
                  <select
                    value={targetLanguage}
                    onChange={(e) => setTargetLanguage(e.target.value)}
                    className="bg-background border border-border rounded-xl px-3.5 py-2.5 text-xs text-foreground focus:outline-none focus:border-primary font-medium"
                  >
                    <option value="English">English (Tiếng Anh)</option>
                    <option value="Vietnamese">Tiếng Việt (Vietnamese)</option>
                    <option value="Japanese">日本語 (Japanese)</option>
                    <option value="Korean">한국어 (Korean)</option>
                    <option value="Chinese">中文 (Chinese)</option>
                    <option value="French">Français (French)</option>
                    <option value="Spanish">Español (Spanish)</option>
                  </select>
                </div>

                {/* LLM Admin Info Badge / Selector */}
                <div className="p-3.5 bg-secondary/30 rounded-xl border border-border flex flex-col gap-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Key className="w-3.5 h-3.5 text-primary" />
                      <span className="text-xs font-bold text-foreground">Mô hình Dịch AI (LLM)</span>
                    </div>
                    {llmProfiles.length > 0 && (
                      <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded-full border border-border/60 font-semibold">
                        {llmProfiles.length} Profile LLM
                      </span>
                    )}
                  </div>

                  {llmProfiles.length > 0 ? (
                    <div className="flex flex-col gap-1.5">
                      <label className="text-[10px] font-semibold text-muted-foreground">Chọn Profile LLM muốn sử dụng:</label>
                      <select
                        value={selectedLlmProfileId}
                        onChange={(e) => setSelectedLlmProfileId(e.target.value)}
                        className="w-full bg-background border border-border rounded-lg px-2.5 py-1.5 text-xs text-foreground font-medium focus:ring-1 focus:ring-primary outline-hidden cursor-pointer"
                      >
                        {llmProfiles.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} ({p.provider.toUpperCase()} - {p.model}) {p.is_active ? " [Mặc định]" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <div className="text-[10px] text-muted-foreground flex flex-col gap-1">
                      <span>Provider: <strong className="text-foreground">{llmProvider.toUpperCase()}</strong></span>
                      <span>Model: <strong className="text-foreground">{llmModel}</strong></span>
                      {llmCustomEndpoint && (
                        <span className="truncate">Endpoint: <strong className="text-foreground font-mono">{llmCustomEndpoint}</strong></span>
                      )}
                    </div>
                  )}

                  <span className="text-[9px] text-primary/80 italic mt-0.5">
                    💡 Quản lý, Thêm/Sửa API Key & Profile LLM tại Admin Portal -&gt; Tab Cấu hình LLM.
                  </span>
                </div>

                <div className="p-3.5 bg-secondary/20 rounded-xl border border-border/50 text-[11px] text-muted-foreground flex flex-col gap-1.5">
                  <span className="font-bold text-foreground">Quy trình tự động gồm:</span>
                  <p>1. Tách nhạc nền & giọng thoại (Demucs)</p>
                  <p>2. Chuyển đổi thoại thành văn bản (Whisper)</p>
                  <p>3. Dịch văn bản qua LLM</p>
                  <p>4. Chờ xem trước & duyệt phụ đề</p>
                  <p>5. Sinh giọng đọc clone đè đồng bộ (OmniVoice)</p>
                </div>
              </div>
            </SectionCard>
          </div>
        </div>
      )}

      {/* --- STEP 3: SUBTITLE REVIEW & EDIT STUDIO --- */}
      {jobId && job && job.status === "awaiting_review" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          
          {/* Left: Video Player & Audio Controls */}
          <SectionCard title="Video Xem Trước & Bộ Trộn Âm Thanh">
            <div className="flex flex-col gap-4">
              <div className="relative aspect-video rounded-xl bg-black overflow-hidden border border-border shadow-inner">
                <video
                  ref={videoPlayerRef}
                  src={api.getDubbingFileUrl(jobId, "video")}
                  controls
                  muted={Boolean(job.vocals_audio_path || job.bgm_audio_path)}
                  onPlay={handleVideoPlay}
                  onPause={handleVideoPause}
                  onSeeked={handleVideoSeek}
                  className="w-full h-full object-contain"
                />
                
                {job.vocals_audio_path && (
                  <audio ref={vocalsPlayerRef} src={api.getDubbingFileUrl(jobId, "vocals")} />
                )}
                {job.bgm_audio_path && (
                  <audio ref={bgmPlayerRef} src={api.getDubbingFileUrl(jobId, "bgm")} />
                )}
              </div>

              {/* Audio Track Mix Panel */}
              <div className="p-4 bg-secondary/30 rounded-xl border border-border flex flex-col gap-3">
                <div className="flex items-center gap-1.5 border-b border-border/60 pb-2">
                  <Sliders className="w-3.5 h-3.5 text-primary" />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-foreground">Bộ trộn tách kênh âm thanh</h4>
                </div>

                <div className="flex flex-col gap-3">
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-medium text-foreground">Giọng Thoại Đã Tách (Vocals)</span>
                    <div className="flex items-center gap-3 w-2/3">
                      <input
                        type="range"
                        min="0"
                        max="2"
                        step="0.1"
                        value={vocalsVolume}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          setVocalsVolume(val);
                          if (vocalsPlayerRef.current) vocalsPlayerRef.current.volume = val / 2;
                        }}
                        className="w-full accent-primary bg-secondary h-1.5 rounded-lg cursor-pointer"
                      />
                      <span className="text-[10px] font-bold text-muted-foreground w-8 text-right">{Math.round(vocalsVolume * 100)}%</span>
                    </div>
                  </div>

                  <div className="flex justify-between items-center">
                    <span className="text-xs font-medium text-foreground">Nhạc Nền / Hiệu Ứng (BGM)</span>
                    <div className="flex items-center gap-3 w-2/3">
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.05"
                        value={bgmVolume}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value);
                          setBgmVolume(val);
                          if (bgmPlayerRef.current) bgmPlayerRef.current.volume = val;
                        }}
                        className="w-full accent-primary bg-secondary h-1.5 rounded-lg cursor-pointer"
                      />
                      <span className="text-[10px] font-bold text-muted-foreground w-8 text-right">{Math.round(bgmVolume * 100)}%</span>
                    </div>
                  </div>
                </div>
              </div>

              <button
                onClick={handleFinalize}
                disabled={loading}
                className="w-full py-3 bg-gradient-to-r from-primary to-accent hover:brightness-105 text-white text-xs font-bold rounded-xl transition-all shadow-md shadow-primary/10 flex items-center justify-center gap-2 disabled:opacity-50 cursor-pointer"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Đang hoàn tất lồng tiếng...</span>
                  </>
                ) : (
                  <>
                    <Wand2 className="w-4 h-4" />
                    <span>Xác Nhận Bản Dịch & Lồng Tiếng Video</span>
                  </>
                )}
              </button>

            </div>
          </SectionCard>

          {/* Right: Subtitle Timeline Editor */}
          <SectionCard title="Biên Tập Bản Dịch Phụ Đề">
            <div className="flex flex-col gap-3">
              <div className="flex justify-end mb-1">
                <button
                  onClick={handleSaveSubtitles}
                  disabled={savingSubs}
                  className="px-3 py-1 bg-secondary hover:bg-secondary/80 text-foreground text-xs font-semibold rounded-lg border border-border transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <Save className="w-3.5 h-3.5 text-primary" />
                  <span>{savingSubs ? "Đang lưu..." : "Lưu phụ đề"}</span>
                </button>
              </div>

              <div className="flex flex-col h-[450px] overflow-y-auto pr-1 gap-3">
                {translatedSubs.map((seg, idx) => {
                  const origSeg = originalSubs[idx] || seg;
                  const isSelected = selectedSegId === seg.id;
                  return (
                    <div
                      key={seg.id}
                      onClick={() => jumpToSegment(seg.start, seg.id)}
                      className={`p-3.5 rounded-xl border transition-all cursor-pointer ${
                        isSelected
                          ? "bg-primary/10 border-primary shadow-sm"
                          : "bg-secondary/20 border-border/60 hover:border-border"
                      }`}
                    >
                      <div className="flex justify-between items-center mb-2">
                        <span className="text-[10px] font-bold text-primary tracking-wider">PHÂN ĐOẠN #{seg.id}</span>
                        <span className="text-[10px] font-mono font-bold text-muted-foreground bg-background px-2 py-0.5 rounded border border-border">
                          {typeof seg.start === "number" ? seg.start.toFixed(2) : "0.00"}s → {typeof seg.end === "number" ? seg.end.toFixed(2) : "0.00"}s ({typeof seg.start === "number" && typeof seg.end === "number" ? (seg.end - seg.start).toFixed(1) : "0.0"}s)
                        </span>
                      </div>
                      
                      <div className="flex flex-col gap-2">
                        <div>
                          <span className="text-[9px] uppercase font-bold text-muted-foreground tracking-wider">Gốc:</span>
                          <p className="text-xs text-muted-foreground italic mt-0.5">{origSeg.text}</p>
                        </div>
                        
                        <div>
                          <span className="text-[9px] uppercase font-bold text-primary tracking-wider">Dịch ({targetLanguage}):</span>
                          <textarea
                            value={seg.text}
                            onChange={(e) => updateSubText(seg.id, e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                            rows={2}
                            className="w-full bg-background border border-border rounded-lg p-2 text-xs text-foreground mt-1 focus:outline-none focus:border-primary font-medium"
                          />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </SectionCard>

        </div>
      )}

      {/* --- STEP 5: FINAL OUTPUT PREVIEW & DOWNLOAD --- */}
      {jobId && job && job.status === "completed" && (
        <SectionCard title="Hoàn Tất Lồng Tiếng Video!">
          <div className="flex flex-col items-center gap-6 text-center max-w-3xl mx-auto py-4">
            <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-500">
              <CheckCircle2 className="w-6 h-6" />
            </div>

            <div>
              <h2 className="text-lg font-bold text-foreground">Video Đã Được Lồng Tiếng Thành Công!</h2>
              <p className="text-xs text-muted-foreground mt-1">
                Giọng nói đã được tổng hợp clone chính xác và khớp thời lượng từng phân đoạn.
              </p>
            </div>

            <div className="aspect-video w-full max-w-2xl rounded-2xl overflow-hidden bg-black border border-border shadow-xl">
              <video
                src={api.getDubbingFileUrl(jobId, "output")}
                controls
                className="w-full h-full object-contain"
              />
            </div>

            <div className="flex flex-wrap gap-4 justify-center">
              <a
                href={api.getDubbingFileUrl(jobId, "output")}
                download={`dubbed_video_${jobId}.mp4`}
                className="px-5 py-2.5 bg-gradient-to-r from-primary to-accent hover:brightness-105 text-white font-bold text-xs rounded-xl transition-all shadow-md flex items-center gap-2 cursor-pointer"
              >
                <Download className="w-4 h-4" />
                <span>Tải Video MP4 Lồng Tiếng</span>
              </a>
              
              <button
                onClick={() => {
                  const srtText = originalSubs.map((seg, idx) => {
                    const trans = translatedSubs[idx] || seg;
                    const format = (s: number) => {
                      const h = Math.floor(s / 3600);
                      const m = Math.floor((s % 3600) / 60);
                      const sec = Math.floor(s % 60);
                      const ms = Math.floor((s % 1) * 1000);
                      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
                    };
                    return `${idx + 1}\n${format(seg.start)} --> ${format(seg.end)}\n${trans.text}\n`;
                  }).join("\n");
                  
                  const blob = new Blob([srtText], { type: "text/plain;charset=utf-8" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `subtitles_${jobId}.srt`;
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                }}
                className="px-5 py-2.5 bg-secondary hover:bg-secondary/80 text-foreground font-bold text-xs rounded-xl border border-border transition-colors flex items-center gap-2 cursor-pointer"
              >
                <FileText className="w-4 h-4" />
                <span>Tải Phụ Đề SRT</span>
              </button>
            </div>

          </div>
        </SectionCard>
      )}

      {/* --- YOUTUBE AUTHENTICATION MODAL --- */}
      {showCookieModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border border-border rounded-2xl max-w-lg w-full p-6 shadow-2xl flex flex-col gap-4 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between pb-3 border-b border-border">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-primary/10 text-primary rounded-xl">
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-foreground">Kết Nối Tài Khoản YouTube</h3>
                  <p className="text-[11px] text-muted-foreground">Mở khóa tải video YouTube Full HD 1080p 60fps siêu tốc</p>
                </div>
              </div>
              <button
                onClick={() => { setShowCookieModal(false); setCookieMsg(null); }}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="flex items-center gap-2 p-1 bg-secondary/50 rounded-xl border border-border">
              <button
                type="button"
                onClick={() => setActiveModalTab("oauth")}
                className={`flex-1 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
                  activeModalTab === "oauth"
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Key className="w-3.5 h-3.5" />
                <span>Đăng Nhập 1-Click (Khuyên Dùng)</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveModalTab("cookies")}
                className={`flex-1 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
                  activeModalTab === "cookies"
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Cookie className="w-3.5 h-3.5" />
                <span>Dán Cookies.txt</span>
              </button>
            </div>

            {/* TAB 1: 1-CLICK OAUTH */}
            {activeModalTab === "oauth" && (
              <div className="flex flex-col gap-3">
                {/* Connected State */}
                {oauthStatus?.connected ? (
                  <div className="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex flex-col gap-3">
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 rounded-full">
                        <ShieldCheck className="w-6 h-6" />
                      </div>
                      <div className="flex-grow">
                        <h4 className="text-xs font-bold text-foreground">Đã Kết Nối Tài Khoản YouTube (OAuth 2.0)</h4>
                        <p className="text-[11px] text-muted-foreground">Server đã được cấp quyền tải mọi video Full HD tốc độ cao mà không bị chặn bot.</p>
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="button"
                        onClick={handleDisconnectOAuth}
                        className="px-3 py-1.5 bg-destructive/10 hover:bg-destructive/20 text-destructive text-xs font-bold rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Ngắt Kết Nối</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    {!oauthFlowData ? (
                      <div className="flex flex-col gap-3 p-4 bg-secondary/30 border border-border rounded-xl">
                        <div className="flex items-start gap-2.5">
                          <Sparkles className="w-5 h-5 text-primary shrink-0 mt-0.5" />
                          <div className="text-xs text-muted-foreground leading-relaxed">
                            <b className="text-foreground">Không cần xuất file cookie thủ công!</b> Chỉ cần bấm nút bên dưới, mở trang xác nhận của Google và nhập mã gồm 8 ký tự để hoàn tất kết nối trong 3 giây.
                          </div>
                        </div>

                        {oauthError && (
                          <div className="p-2.5 bg-destructive/10 border border-destructive/30 rounded-lg text-xs text-destructive font-medium">
                            {oauthError}
                          </div>
                        )}

                        <button
                          type="button"
                          disabled={oauthStarting}
                          onClick={handleStartOAuth}
                          className="w-full py-2.5 bg-primary hover:brightness-105 text-primary-foreground font-bold text-xs rounded-xl transition-all shadow-md flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                        >
                          {oauthStarting ? (
                            <>
                              <Loader2 className="w-4 h-4 animate-spin" />
                              <span>Đang tạo mã kết nối...</span>
                            </>
                          ) : (
                            <>
                              <Key className="w-4 h-4" />
                              <span>Bắt Đầu Kết Nối YouTube (1-Click)</span>
                            </>
                          )}
                        </button>
                      </div>
                    ) : (
                      <div className="flex flex-col gap-3 p-4 bg-secondary/30 border border-primary/40 rounded-xl">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-foreground">Bước 1: Sao chép mã xác thực</span>
                          <span className="text-[10px] text-muted-foreground font-medium">Hết hạn sau 30 phút</span>
                        </div>

                        {/* Code Display */}
                        <div className="flex items-center justify-between p-3 bg-background border-2 border-dashed border-primary/60 rounded-xl">
                          <span className="text-lg font-extrabold font-mono tracking-widest text-primary">
                            {oauthFlowData.user_code}
                          </span>
                          <button
                            type="button"
                            onClick={handleCopyCode}
                            className="px-3 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary text-xs font-bold rounded-lg transition-all flex items-center gap-1.5 cursor-pointer"
                          >
                            {oauthCopied ? (
                              <>
                                <Check className="w-3.5 h-3.5 text-emerald-500" />
                                <span className="text-emerald-500">Đã chép!</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3.5 h-3.5" />
                                <span>Sao chép mã</span>
                              </>
                            )}
                          </button>
                        </div>

                        {/* Step 2 CTA */}
                        <div className="flex flex-col gap-2 pt-1">
                          <span className="text-xs font-bold text-foreground">Bước 2: Mở trang Google và dán mã</span>
                          <a
                            href={oauthFlowData.verification_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="w-full py-2.5 bg-primary hover:brightness-105 text-primary-foreground font-bold text-xs rounded-xl transition-all shadow-md flex items-center justify-center gap-2 cursor-pointer"
                          >
                            <span>Mở trang Google xác thực ({oauthFlowData.verification_url})</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </div>

                        {/* Live Waiting Status */}
                        <div className="p-3 bg-background/80 border border-border rounded-xl flex items-center gap-2.5 text-xs text-muted-foreground">
                          {oauthPolling ? (
                            <>
                              <Loader2 className="w-4 h-4 text-primary animate-spin" />
                              <span className="text-foreground font-medium">Đang chờ bạn bấm Cho phép trên Google... (Tự động nhận diện)</span>
                            </>
                          ) : oauthSuccessMsg ? (
                            <>
                              <ShieldCheck className="w-4 h-4 text-emerald-500" />
                              <span className="text-emerald-600 dark:text-emerald-400 font-bold">{oauthSuccessMsg}</span>
                            </>
                          ) : oauthError ? (
                            <>
                              <AlertCircle className="w-4 h-4 text-destructive" />
                              <span className="text-destructive font-medium">{oauthError}</span>
                            </>
                          ) : null}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}

            {/* TAB 2: COOKIES */}
            {activeModalTab === "cookies" && (
              <div className="flex flex-col gap-3">
                {/* Current Status */}
                <div className={`p-3 rounded-xl border flex items-center justify-between ${
                  cookieStatus?.has_cookies
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
                    : "bg-amber-500/10 border-amber-500/30 text-amber-600 dark:text-amber-400"
                }`}>
                  <div className="flex items-center gap-2 text-xs font-semibold">
                    {cookieStatus?.has_cookies ? (
                      <>
                        <ShieldCheck className="w-4 h-4" />
                        <span>Đã cài đặt file Cookies ({cookieStatus.size_bytes} bytes)</span>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-4 h-4" />
                        <span>Chưa có cookies</span>
                      </>
                    )}
                  </div>
                  {cookieStatus?.has_cookies && (
                    <button
                      type="button"
                      disabled={cookieUploading}
                      onClick={handleDeleteCookies}
                      className="px-2 py-1 bg-destructive/10 hover:bg-destructive/20 text-destructive text-[11px] font-bold rounded-lg transition-colors flex items-center gap-1 cursor-pointer"
                    >
                      <Trash2 className="w-3 h-3" />
                      <span>Xóa</span>
                    </button>
                  )}
                </div>

                {cookieMsg && (
                  <div className="p-2.5 bg-secondary/80 rounded-xl text-xs text-foreground font-medium border border-border">
                    {cookieMsg}
                  </div>
                )}

                {/* Upload Method 1: File */}
                <div className="flex flex-col gap-2">
                  <label className="text-xs font-bold text-foreground">Cách 1: Tải lên tệp cookies.txt</label>
                  <input
                    type="file"
                    accept=".txt"
                    onChange={handleUploadCookieFile}
                    disabled={cookieUploading}
                    className="block w-full text-xs text-muted-foreground file:mr-3 file:py-2 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:brightness-110 cursor-pointer border border-border rounded-xl p-1 bg-background"
                  />
                </div>

                {/* Upload Method 2: Textarea */}
                <div className="flex flex-col gap-2">
                  <label className="text-xs font-bold text-foreground">Cách 2: Dán nội dung Netscape Cookies</label>
                  <textarea
                    rows={3}
                    value={cookieText}
                    onChange={(e) => setCookieText(e.target.value)}
                    placeholder="# Netscape HTTP Cookie File&#10;.youtube.com TRUE / TRUE ... SID ..."
                    className="w-full bg-background border border-border rounded-xl p-2.5 text-[11px] font-mono text-foreground focus:outline-none focus:border-primary resize-none"
                  />
                  <button
                    type="button"
                    disabled={cookieUploading || !cookieText.trim()}
                    onClick={handleSaveCookieText}
                    className="self-end px-4 py-2 bg-primary hover:brightness-105 text-primary-foreground text-xs font-bold rounded-xl transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>{cookieUploading ? "Đang lưu..." : "Lưu Nội Dung Cookie"}</span>
                  </button>
                </div>
              </div>
            )}

            <div className="flex justify-end pt-2 border-t border-border">
              <button
                type="button"
                onClick={() => { setShowCookieModal(false); setCookieMsg(null); }}
                className="px-5 py-2 bg-secondary hover:bg-secondary/80 text-foreground font-bold text-xs rounded-xl border border-border transition-colors cursor-pointer"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
