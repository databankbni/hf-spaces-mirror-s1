import React, { useState, useEffect } from "react";
import { Clock, RefreshCw, Layers, Heart, Lock, Globe, X, ChevronDown, ChevronUp, AlertCircle, CheckCircle, Play, Pause, Zap, Copy, Check, Terminal, Settings, Tag, Trash2, Search, Filter, ChevronLeft, ChevronRight } from "lucide-react";
import { api, type JobStatusResponse } from "../api/client";

interface JobHistoryPanelProps {
  refreshTrigger: number;
  layout?: "classic" | "modern";
  currentPlayUrl: string | null;
  globalPlayerPlaying: boolean;
  onPlayAudio: (url: string, title: string) => void;
  onTogglePlay: () => void;
}

export const JobHistoryPanel: React.FC<JobHistoryPanelProps> = ({
  refreshTrigger,
  currentPlayUrl,
  globalPlayerPlaying,
  onPlayAudio,
  onTogglePlay,
}) => {
  const [jobs, setJobs] = useState<JobStatusResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  // Pagination & Filter states
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [totalJobs, setTotalJobs] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedStatus, setSelectedStatus] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");

  // Debounce search query (350ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Expanded job IDs state (for long texts)
  const [expandedJobs, setExpandedJobs] = useState<Record<string, boolean>>({});

  // Favorite Voices states
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [saveVoiceName, setSaveVoiceName] = useState("");
  const [saveVoiceRefText, setSaveVoiceRefText] = useState("");
  const [saveVoiceIsPublic, setSaveVoiceIsPublic] = useState(false);
  const [saveVoiceJobId, setSaveVoiceJobId] = useState<string | null>(null);
  const [isSavingVoice, setIsSavingVoice] = useState(false);
  const [saveVoiceStatus, setSaveVoiceStatus] = useState<string | null>(null);
  const [saveVoiceTags, setSaveVoiceTags] = useState<string[]>([]);

  // Expanded configs and tabs state
  const [expandedDetails, setExpandedDetails] = useState<Record<string, boolean>>({});
  const [activeTabs, setActiveTabs] = useState<Record<string, "params" | "json">>({});
  const [copiedJobId, setCopiedJobId] = useState<string | null>(null);

  const toggleDetails = (jobId: string) => {
    setExpandedDetails(prev => ({
      ...prev,
      [jobId]: !prev[jobId],
    }));
  };

  const isDetailsExpanded = (jobId: string) => !!expandedDetails[jobId];

  const getDetailsTab = (jobId: string) => activeTabs[jobId] || "params";

  const setDetailsTab = (jobId: string, tab: "params" | "json") => {
    setActiveTabs(prev => ({
      ...prev,
      [jobId]: tab,
    }));
  };

  const copyToClipboard = (jobId: string, text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedJobId(jobId);
      setTimeout(() => {
        setCopiedJobId(null);
      }, 2000);
    }).catch(err => {
      console.error("Lỗi khi sao chép: ", err);
    });
  };

  const loadJobs = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await api.listJobs({
        page,
        page_size: pageSize,
        job_type: selectedCategory,
        status_filter: selectedStatus,
        search: debouncedSearch
      });
      setJobs(res.items || []);
      setTotalJobs(res.total || 0);
      setTotalPages(res.total_pages || 1);
    } catch (err: any) {
      console.error("Lỗi lấy lịch sử công việc:", err);
      setErrorMsg(err.message || "Không thể tải danh sách lịch sử công việc.");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteJob = async (jobId: string) => {
    const isConfirmed = window.confirm("Bạn có chắc chắn muốn xóa tác vụ này không? Hành động này không thể hoàn tác.");
    if (!isConfirmed) return;
    
    try {
      await api.deleteJob(jobId);
      loadJobs();
    } catch (err: any) {
      console.error("Lỗi khi xóa tác vụ:", err);
      alert(`Không thể xóa tác vụ: ${err.message || "Lỗi không xác định"}`);
    }
  };

  useEffect(() => {
    loadJobs();
  }, [refreshTrigger, page, pageSize, selectedCategory, selectedStatus, debouncedSearch]);

  const toggleExpand = (jobId: string) => {
    setExpandedJobs(prev => ({
      ...prev,
      [jobId]: !prev[jobId],
    }));
  };

  const handleOpenSaveModal = (targetJobId: string, fullText: string) => {
    setSaveVoiceJobId(targetJobId);
    setSaveVoiceName(`Giọng Lưu - ${new Date().toLocaleDateString("vi-VN")} ${new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}`);
    
    // Suggest first 15 words of original text
    const words = fullText.trim().split(/\s+/);
    const suggestedText = words.slice(0, 15).join(" ") + (words.length > 15 ? "..." : "");
    setSaveVoiceRefText(suggestedText);
    
    setSaveVoiceIsPublic(false);
    setSaveVoiceTags([]);
    setSaveVoiceStatus(null);
    setIsSaveModalOpen(true);
  };

  const handleSaveVoiceSubmit = async () => {
    if (!saveVoiceJobId || !saveVoiceName || !saveVoiceRefText) return;
    setIsSavingVoice(true);
    setSaveVoiceStatus(null);

    try {
      await api.saveFavoriteVoice({
        job_id: saveVoiceJobId,
        name: saveVoiceName,
        is_public: saveVoiceIsPublic,
        ref_text: saveVoiceRefText,
        tags: saveVoiceTags.length > 0 ? saveVoiceTags : undefined,
      });
      setSaveVoiceStatus("Lưu giọng thành công vào Thư viện!");
      setTimeout(() => {
        setIsSaveModalOpen(false);
      }, 1500);
    } catch (err: any) {
      setSaveVoiceStatus(`Lỗi: ${err.message || "Không thể lưu giọng."}`);
    } finally {
      setIsSavingVoice(false);
    }
  };

  const getJobTypeLabel = (type?: string) => {
    switch (type) {
      case "clone_voice":
        return { label: "Clone Voice", color: "text-primary dark:text-primary border-primary/20 bg-primary/5" };
      case "auto_voice":
        return { label: "Auto Voice", color: "text-primary border-sky-550/20 bg-sky-500/5" };
      case "voice_design":
        return { label: "Voice Design Direct", color: "text-primary border-purple-550/20 bg-purple-500/5" };
      case "voice_design_preview":
        return { label: "Voice Design Preview", color: "text-primary border-pink-550/20 bg-pink-500/5" };
      default:
        return { label: "TTS Job", color: "text-muted-foreground dark:text-muted-foreground border-border/20 bg-muted/5" };
    }
  };

  const formatTime = (timeStr?: string) => {
    if (!timeStr) return "";
    try {
      const date = new Date(timeStr);
      return date.toLocaleString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "2-digit",
        year: "numeric"
      });
    } catch {
      return timeStr;
    }
  };

  return (
    <div className="bg-card/90 border border-border backdrop-blur-md rounded-3xl p-6 flex flex-col gap-5 shadow-xl w-full transition-all duration-300">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/60 pb-4 select-none">
        <div className="flex flex-col gap-1">
          <h2 className="text-lg font-bold text-foreground flex items-center gap-2">
            <Clock className="w-5 h-5 text-primary" />
            <span>Lịch sử tác vụ</span>
            <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 font-bold font-mono">
              {totalJobs} tác vụ
            </span>
          </h2>
          <p className="text-xs text-muted-foreground">
            Quản lý, nghe lại, tải về và lưu mẫu giọng đọc từ lịch sử sinh âm thanh.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Search Box */}
          <div className="relative flex-1 md:w-64">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Tìm theo Mã ID hoặc Nội dung..."
              className="w-full pl-9 pr-8 py-2 bg-background border border-border rounded-full text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary transition-all font-medium"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Refresh button */}
          <button
            onClick={loadJobs}
            disabled={loading}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-muted hover:bg-muted/80 text-foreground disabled:text-muted-foreground border border-border rounded-full text-xs font-bold transition-all cursor-pointer shadow-sm select-none flex-shrink-0"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-primary" : ""}`} />
            <span className="hidden sm:inline">Làm mới</span>
          </button>
        </div>
      </div>

      {/* Filter Toolbar & Category Tabs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-secondary/20 p-2 rounded-2xl border border-border/50">
        {/* Category Filter Pills */}
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-none pb-1 sm:pb-0">
          {[
            { id: "all", label: "Tất cả" },
            { id: "clone_voice", label: "🎙️ Clone Voice" },
            { id: "auto_voice", label: "⚡ Auto Voice" },
            { id: "voice_design", label: "✨ Voice Design" },
            { id: "video_dubbing", label: "🎬 Video Dubbing" }
          ].map((cat) => (
            <button
              key={cat.id}
              onClick={() => {
                setSelectedCategory(cat.id);
                setPage(1);
              }}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all whitespace-nowrap cursor-pointer ${
                selectedCategory === cat.id
                  ? "bg-primary text-primary-foreground shadow-sm shadow-primary/20"
                  : "text-muted-foreground hover:text-foreground hover:bg-card/50"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        {/* Status Filter */}
        <div className="flex items-center gap-2 self-end sm:self-auto">
          <Filter className="w-3.5 h-3.5 text-muted-foreground hidden sm:inline" />
          <select
            value={selectedStatus}
            onChange={(e) => {
              setSelectedStatus(e.target.value);
              setPage(1);
            }}
            className="bg-card border border-border rounded-xl px-2.5 py-1.5 text-xs text-foreground font-semibold focus:outline-none focus:border-primary cursor-pointer"
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="completed">Hoàn tất</option>
            <option value="running">Đang xử lý</option>
            <option value="failed">Thất bại</option>
          </select>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-destructive/10 border border-destructive/20 text-destructive text-xs font-semibold rounded-2xl flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Content Area */}
      {loading && jobs.length === 0 ? (
        /* Skeleton Shimmer Loading Cards */
        <div className="flex flex-col gap-3 my-2">
          {[1, 2, 3].map((n) => (
            <div key={n} className="p-4 bg-card border border-border/60 rounded-2xl animate-pulse flex flex-col gap-3">
              <div className="flex justify-between items-center">
                <div className="h-4 bg-muted rounded-md w-1/4"></div>
                <div className="h-4 bg-muted rounded-full w-16"></div>
              </div>
              <div className="h-10 bg-muted/60 rounded-xl w-full"></div>
            </div>
          ))}
        </div>
      ) : jobs.length === 0 ? (
        /* Empty State */
        <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground bg-background/20 rounded-3xl border border-dashed border-border">
          <Layers className="w-8 h-8 text-muted-foreground opacity-50" />
          <span className="text-xs font-bold text-muted-foreground">Không tìm thấy tác vụ nào khớp với bộ lọc.</span>
          {(searchQuery || selectedCategory !== "all" || selectedStatus !== "all") && (
            <button
              onClick={() => {
                setSearchQuery("");
                setSelectedCategory("all");
                setSelectedStatus("all");
                setPage(1);
              }}
              className="text-xs font-bold text-primary hover:underline cursor-pointer"
            >
              Xóa bộ lọc
            </button>
          )}
        </div>
      ) : (
        /* Jobs List */
        <div className="flex flex-col gap-4 max-h-[600px] overflow-y-auto pr-1 scrollbar-thin">
          {jobs.map((job) => {
            const { label, color } = getJobTypeLabel(job.job_type);
            const safeJobId = String(job.job_id || "unknown");
            const isCompleted = job.status === "completed";
            const isFailed = job.status === "failed";
            const isProcessing = !isCompleted && !isFailed;
            const fullText = job.text || "";
            const isLongText = fullText.length > 120;
            const isExpanded = !!expandedJobs[safeJobId];
            const displayedText = isLongText && !isExpanded 
              ? `${fullText.substring(0, 120)}...` 
              : fullText;

            const audioUrl = job.audio_url ? `${api.getApiBaseUrl()}${job.audio_url}` : "";
             return (
               <div 
                 key={safeJobId} 
                 className={`bg-muted/30 border rounded-3xl p-5 flex flex-col gap-4 transition-all duration-300 shadow-sm ${
                   currentPlayUrl && currentPlayUrl === audioUrl
                     ? "border-primary bg-primary/[0.02] shadow-md shadow-primary/5"
                     : "border-border hover:border-border/40 hover:bg-muted/50"
                 }`}
               >
                {/* Job Header */}
                <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-border/40 pb-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-[9px] font-bold px-2 py-0.5 border rounded-full uppercase tracking-wider ${color}`}>
                      {label}
                    </span>
                    <span className="text-[10px] text-muted-foreground font-semibold font-mono">
                      ID: {safeJobId.substring(0, 8)}...
                    </span>
                    <span className="text-[10px] text-muted-foreground font-semibold flex items-center gap-1 select-none">
                      <Clock className="w-3 h-3 text-muted-foreground" />
                      {formatTime(job.created_at)}
                    </span>
                    {typeof job.total_time === "number" && (
                      <span 
                        className="text-[10px] text-primary dark:text-primary font-semibold flex items-center gap-1 bg-primary/5 px-2 py-0.5 border border-primary/10 rounded-full cursor-help select-none"
                        title={`Hàng đợi: ${typeof job.queue_time === "number" ? job.queue_time.toFixed(1) : 0}s, Xử lý: ${typeof job.processing_time === "number" ? job.processing_time.toFixed(1) : 0}s`}
                      >
                        <Zap className="w-3 h-3 fill-current text-primary" />
                        <span>{job.total_time.toFixed(1)}s</span>
                      </span>
                    )}
                  </div>

                  {/* Status Badges & Delete Action */}
                  <div className="flex items-center gap-2">
                    {isCompleted && (
                      <span className="inline-flex items-center gap-1 text-[9px] font-bold px-2.5 py-0.5 bg-success/10 border border-success/20 text-success rounded-full select-none">
                        <CheckCircle className="w-3 h-3" />
                        <span>Thành công</span>
                      </span>
                    )}
                    {isFailed && (
                      <span className="inline-flex items-center gap-1 text-[9px] font-bold px-2.5 py-0.5 bg-destructive/10 border border-destructive/20 text-destructive rounded-full select-none" title={job.error_message || ""}>
                        <AlertCircle className="w-3 h-3" />
                        <span>Thất bại</span>
                      </span>
                    )}
                    {isProcessing && (
                      <span className="inline-flex items-center gap-1.5 text-[9px] font-bold px-2.5 py-0.5 bg-muted border border-border text-muted-foreground rounded-full animate-pulse select-none">
                        <RefreshCw className="w-3 h-3 animate-spin text-muted-foreground" />
                        <span>Đang chạy ({job.progress}%)</span>
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDeleteJob(job.job_id)}
                      className="p-1 hover:bg-destructive/10 border border-transparent hover:border-destructive/20 text-muted-foreground hover:text-destructive rounded-lg transition-colors cursor-pointer"
                      title={isProcessing ? "Hủy tác vụ khởi hàng chờ" : "Xóa tác vụ khỏi lịch sử"}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Job Text */}
                {fullText && (
                  <div className="text-xs text-foreground bg-card border border-border rounded-2xl p-3.5 leading-relaxed relative group shadow-inner">
                    <span className="whitespace-pre-wrap font-medium">{displayedText}</span>
                    {isLongText && (
                      <button
                        onClick={() => toggleExpand(job.job_id)}
                        className="text-[10px] text-muted-foreground hover:text-foreground font-bold ml-1.5 focus:outline-none inline-flex items-center gap-0.5 cursor-pointer align-bottom select-none"
                      >
                        {isExpanded ? (
                          <>
                            <span>Ẩn bớt</span>
                            <ChevronUp className="w-3 h-3" />
                          </>
                        ) : (
                          <>
                            <span>Xem thêm</span>
                            <ChevronDown className="w-3 h-3" />
                          </>
                        )}
                      </button>
                    )}
                  </div>
                )}

                {/* Accordion Toggle for parameters & Prompt JSON */}
                <div className="border-t border-border/20 pt-2 flex justify-between items-center select-none">
                  <button
                    onClick={() => toggleDetails(job.job_id)}
                    className="text-[11px] text-muted-foreground hover:text-foreground font-bold focus:outline-none inline-flex items-center gap-1 cursor-pointer"
                  >
                    {isDetailsExpanded(job.job_id) ? (
                      <>
                        <ChevronUp className="w-3.5 h-3.5" />
                        <span>Ẩn cấu hình & Prompt JSON</span>
                      </>
                    ) : (
                      <>
                        <ChevronDown className="w-3.5 h-3.5" />
                        <span>Xem cấu hình & Prompt JSON</span>
                      </>
                    )}
                  </button>
                  
                  {typeof job.total_time === "number" && (
                    <span className="text-[10px] text-muted-foreground">
                      Xử lý: <span className="font-mono font-bold text-foreground">{typeof job.processing_time === "number" ? job.processing_time.toFixed(1) : 0}s</span>
                      {typeof job.queue_time === "number" && (
                        <> (Chờ: <span className="font-mono font-bold text-foreground">{job.queue_time.toFixed(1)}s</span>)</>
                      )}
                    </span>
                  )}
                </div>

                {/* Collapsible details panel */}
                {isDetailsExpanded(job.job_id) && (
                  <div className="bg-card/40 border border-border/50 rounded-2xl p-4 flex flex-col gap-3 text-xs shadow-inner">
                    {/* Tabs header */}
                    <div className="flex border-b border-border/40 pb-1.5 gap-3 select-none">
                      <button
                        onClick={() => setDetailsTab(job.job_id, "params")}
                        className={`pb-1 text-[11px] font-bold border-b-2 transition-all cursor-pointer inline-flex items-center gap-1.5 ${
                          getDetailsTab(job.job_id) === "params"
                            ? "border-primary text-primary"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <Settings className="w-3.5 h-3.5" />
                        <span>Thông số đã gửi</span>
                      </button>
                      <button
                        onClick={() => setDetailsTab(job.job_id, "json")}
                        className={`pb-1 text-[11px] font-bold border-b-2 transition-all cursor-pointer inline-flex items-center gap-1.5 ${
                          getDetailsTab(job.job_id) === "json"
                            ? "border-primary text-primary"
                            : "border-transparent text-muted-foreground hover:text-foreground"
                        }`}
                      >
                        <Terminal className="w-3.5 h-3.5" />
                        <span>Prompt JSON</span>
                      </button>
                    </div>

                    {/* Tab 1: Params grid */}
                    {getDetailsTab(job.job_id) === "params" && (
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mt-1">
                        {Object.entries(job.params || {}).map(([key, val]) => {
                          if (key === "text") return null;
                          
                          let formattedVal = String(val);
                          if (typeof val === "boolean") {
                            formattedVal = val ? "Bật" : "Tắt";
                          } else if (key === "speed") {
                            formattedVal = `${val}x`;
                          }
                          
                          return (
                            <div key={key} className="bg-background/45 border border-border/30 rounded-xl px-3 py-1.5 flex flex-col gap-0.5 justify-center shadow-sm">
                              <span className="text-[10px] text-muted-foreground font-bold font-mono tracking-wide">{key}</span>
                              <span className="font-semibold text-foreground font-sans truncate" title={String(val)}>
                                {formattedVal}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Tab 2: Prompt JSON code block */}
                    {getDetailsTab(job.job_id) === "json" && (
                      <div className="relative mt-1 group">
                        <pre className="bg-background border border-border/60 rounded-xl p-3.5 overflow-x-auto text-[11px] font-mono leading-relaxed max-h-56 scrollbar-thin select-all">
                          {JSON.stringify(job.params || {}, null, 2)}
                        </pre>
                        <button
                          onClick={() => copyToClipboard(job.job_id, JSON.stringify(job.params || {}, null, 2))}
                          className="absolute top-2 right-2 p-1.5 bg-card hover:bg-muted border border-border rounded-lg text-muted-foreground hover:text-foreground transition-all cursor-pointer shadow-sm flex items-center justify-center"
                          title="Sao chép JSON"
                        >
                          {copiedJobId === job.job_id ? (
                            <Check className="w-3.5 h-3.5 text-success" />
                          ) : (
                            <Copy className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    )}
                  </div>
                )}


                {/* Job Output / Actions */}
                {isCompleted && (job.cdn_audio_url || job.audio_url) && (
                  <div className="flex gap-2 bg-card/20 p-2 rounded-2xl border border-border/50 mt-1 items-center select-none">
                    <button
                      onClick={() => {
                        const audioUrl = job.cdn_audio_url || `${api.getApiBaseUrl()}${job.audio_url}`;
                        if (currentPlayUrl === audioUrl) {
                          onTogglePlay();
                        } else {
                          onPlayAudio(audioUrl, `Job ${job.job_id.substring(0, 8)}`);
                        }
                      }}
                      className={`p-2.5 border rounded-full transition-all cursor-pointer flex items-center justify-center shrink-0 ${
                        currentPlayUrl === (job.cdn_audio_url || `${api.getApiBaseUrl()}${job.audio_url}`) && globalPlayerPlaying
                          ? "bg-primary text-white border-primary shadow-lg shadow-primary/20"
                          : "border-border hover:border-primary/40 hover:bg-muted text-foreground"
                      }`}
                      title={currentPlayUrl === (job.cdn_audio_url || `${api.getApiBaseUrl()}${job.audio_url}`) && globalPlayerPlaying ? "Tạm dừng" : "Nghe kết quả"}
                    >
                      {currentPlayUrl === (job.cdn_audio_url || `${api.getApiBaseUrl()}${job.audio_url}`) && globalPlayerPlaying ? (
                        <Pause className="w-4 h-4 fill-current" />
                      ) : (
                        <Play className="w-4 h-4 fill-current ml-0.5" />
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleOpenSaveModal(job.job_id, fullText)}
                      className="flex-grow py-2.5 px-4 bg-card/60 hover:bg-card border border-border text-foreground hover:text-foreground rounded-full font-bold text-xs flex items-center justify-center gap-1.5 transition-all cursor-pointer shadow-sm active:scale-[0.98]"
                    >
                      <Heart className="w-3.5 h-3.5 fill-slate-450 text-muted-foreground" />
                      <span>Lưu giọng vào Thư viện</span>
                    </button>
                  </div>
                )}

                {isFailed && job.error_message && (
                  <div className="text-xs text-destructive bg-destructive/5 border border-destructive/10 p-3.5 rounded-2xl font-mono leading-relaxed font-semibold">
                    <span className="font-bold">Lỗi chi tiết: </span>
                    {job.error_message}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination Footer */}
      {totalJobs > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 pt-3 border-t border-border/60 text-xs text-muted-foreground select-none">
          <div className="flex items-center gap-2">
            <span>Hiển thị <strong className="text-foreground">{Math.min((page - 1) * pageSize + 1, totalJobs)} - {Math.min(page * pageSize, totalJobs)}</strong> / <strong className="text-foreground">{totalJobs}</strong> tác vụ</span>
          </div>

          <div className="flex items-center gap-2">
            {/* Page Size selector */}
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="bg-card border border-border rounded-xl px-2.5 py-1.5 text-xs text-foreground focus:outline-none focus:border-primary cursor-pointer font-medium"
            >
              <option value={10}>10 tác vụ / trang</option>
              <option value={15}>15 tác vụ / trang</option>
              <option value={30}>30 tác vụ / trang</option>
              <option value={50}>50 tác vụ / trang</option>
            </select>

            {/* Prev / Next Buttons */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="p-1.5 rounded-lg bg-card border border-border text-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
                title="Trang trước"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>

              <span className="px-3 py-1 bg-secondary border border-border/60 rounded-lg font-bold text-foreground font-mono text-xs">
                {page} / {totalPages}
              </span>

              <button
                type="button"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || loading}
                className="p-1.5 rounded-lg bg-card border border-border text-foreground hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors"
                title="Trang tiếp"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Save Voice Modal Overlay */}
      {isSaveModalOpen && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 lg:pl-64 bg-background/80 backdrop-blur-md animate-fadeIn"
          onClick={() => setIsSaveModalOpen(false)}
        >
          <div 
            className="bg-card border border-border rounded-[32px] p-6 w-full max-w-md flex flex-col gap-4.5 shadow-2xl relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsSaveModalOpen(false)}
              className="absolute top-5 right-5 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
            
            <div className="flex items-center gap-3 border-b border-border/60 pb-3">
              <div className="p-2.5 bg-success/10 rounded-2xl text-success">
                <Heart className="w-5 h-5 fill-emerald-400" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-foreground">Lưu giọng nói yêu thích</h3>
                <p className="text-[10px] text-muted-foreground font-semibold">Cắt 8 giây đầu và lưu làm mẫu clone giọng</p>
              </div>
            </div>

            {saveVoiceStatus && (
              <div className={`p-3.5 rounded-2xl text-xs font-semibold border ${saveVoiceStatus.startsWith("Lỗi") ? "bg-destructive/10 border-destructive/20 text-destructive" : "bg-success/10 border-success/20 text-success"}`}>
                {saveVoiceStatus}
              </div>
            )}

            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Tên giọng mẫu</label>
                <input
                  type="text"
                  value={saveVoiceName}
                  onChange={(e) => setSaveVoiceName(e.target.value)}
                  placeholder="Ví dụ: Giọng nữ trầm ấm..."
                  className="bg-background border border-border focus:border-primary/50 rounded-2xl p-3 text-xs text-foreground focus:outline-none font-semibold transition-all duration-200"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Văn bản tham khảo (Phát âm trong 8s đầu)</label>
                <textarea
                  value={saveVoiceRefText}
                  onChange={(e) => setSaveVoiceRefText(e.target.value)}
                  placeholder="Nhập phần chữ tương ứng với đoạn nói đầu tiên..."
                  rows={2}
                  className="bg-background border border-border focus:border-primary/50 rounded-2xl p-3 text-xs text-foreground focus:outline-none resize-none font-semibold transition-all duration-200"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Chế độ chia sẻ</label>
                <div className="grid grid-cols-2 gap-2 bg-background p-1.5 rounded-2xl border border-border/60">
                  <button
                    type="button"
                    onClick={() => setSaveVoiceIsPublic(false)}
                    className={`py-2 px-1 text-center font-bold text-xs rounded-full transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                      !saveVoiceIsPublic
                        ? "bg-muted text-foreground border border-border shadow-sm"
                        : "text-muted-foreground hover:text-muted-foreground"
                    }`}
                  >
                    <Lock className="w-3.5 h-3.5" />
                    <span>Riêng tư (Private)</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setSaveVoiceIsPublic(true)}
                    className={`py-2 px-1 text-center font-bold text-xs rounded-full transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                      saveVoiceIsPublic
                        ? "bg-muted text-foreground border border-border shadow-sm"
                        : "text-muted-foreground hover:text-muted-foreground"
                    }`}
                  >
                    <Globe className="w-3.5 h-3.5" />
                    <span>Công khai (Public)</span>
                  </button>
                </div>
              </div>

              {/* Tags */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1">
                  <Tag className="w-2.5 h-2.5" /> Tags phân loại (Không bắt buộc)
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {["Miền Bắc", "Miền Nam", "Miền Trung", "Trẻ", "Trung niên", "Kể chuyện", "Quảng cáo", "Tin tức", "Podcast", "Audiobook"].map((tag) => (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => {
                        setSaveVoiceTags(prev =>
                          prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
                        );
                      }}
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold transition-all cursor-pointer border ${
                        saveVoiceTags.includes(tag)
                          ? "bg-primary text-white border-primary"
                          : "bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200/60 dark:border-zinc-700/60 text-zinc-600 dark:text-zinc-400 hover:brightness-95 dark:hover:brightness-110"
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="flex gap-2 justify-end mt-2 pt-3 border-t border-border">
              <button
                type="button"
                onClick={() => setIsSaveModalOpen(false)}
                className="px-5 py-2.5 bg-muted hover:bg-muted border border-border text-xs font-semibold text-foreground rounded-lg cursor-pointer transition-colors"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleSaveVoiceSubmit}
                disabled={isSavingVoice || !saveVoiceName || !saveVoiceRefText}
                className="px-5 py-2.5 bg-gradient-to-r from-primary to-accent hover:brightness-105 disabled:bg-muted disabled:text-muted-foreground text-xs font-bold text-white rounded-lg cursor-pointer transition-colors shadow-md shadow-primary/10 border-none"
              >
                {isSavingVoice ? "Đang lưu..." : "Xác nhận Lưu"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
