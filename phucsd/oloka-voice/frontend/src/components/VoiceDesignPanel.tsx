import React, { useState, useEffect, useRef } from "react";
import { Mic, Wand2, Check, Heart, Lock, Globe, X, Play, Pause } from "lucide-react";
import { api } from "../api/client";
import type { JobStatusResponse } from "../api/client";

import { JobStatusCard } from "./JobStatusCard";

interface VoiceDesignPanelProps {
  onAcceptSuccess: (voiceSampleId: string) => void;
  onJobCreatedOrUpdated?: () => void;
  layout?: "classic" | "modern";
  currentPlayUrl: string | null;
  globalPlayerPlaying: boolean;
  onPlayAudio: (url: string, title: string) => void;
  onTogglePlay: () => void;
}

export const VoiceDesignPanel: React.FC<VoiceDesignPanelProps> = ({
  onAcceptSuccess,
  onJobCreatedOrUpdated,
  layout = "classic",
  currentPlayUrl,
  globalPlayerPlaying,
  onPlayAudio,
  onTogglePlay,
}) => {
  const [voiceRequest, setVoiceRequest] = useState("Giọng nữ trẻ, trầm, nhẹ nhàng, tự nhiên");
  const [previewText, setPreviewText] = useState("Xin chào, đây là giọng nói thiết kế thử nghiệm của OmniVoice.");
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [speed, setSpeed] = useState(1.0);
  const [numStep, setNumStep] = useState(32);

  // Favorite Voices states
  const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
  const [saveVoiceName, setSaveVoiceName] = useState("");
  const [saveVoiceRefText, setSaveVoiceRefText] = useState("");
  const [saveVoiceCustomId, setSaveVoiceCustomId] = useState("");
  const [saveVoiceIsPublic, setSaveVoiceIsPublic] = useState(false);
  const [isSavingVoice, setIsSavingVoice] = useState(false);
  const [saveVoiceStatus, setSaveVoiceStatus] = useState<string | null>(null);

  // Advanced OmniVoice parameters state
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [denoise, setDenoise] = useState(true);
  const [guidanceScale, setGuidanceScale] = useState(2.0);
  const [tShift, setTShift] = useState(0.1);
  const [positionTemperature, setPositionTemperature] = useState(5.0);
  const [classTemperature, setClassTemperature] = useState(0.0);
  const [layerPenaltyFactor, setLayerPenaltyFactor] = useState(5.0);
  const [duration, setDuration] = useState("");
  const [preprocessPrompt, setPreprocessPrompt] = useState(true);
  const [postprocessOutput, setPostprocessOutput] = useState(true);
  const [audioChunkDuration, setAudioChunkDuration] = useState(15.0);
  const [audioChunkThreshold, setAudioChunkThreshold] = useState(30.0);

  const pollIntervalRef = useRef<number | null>(null);
  const timeoutRef = useRef<number | null>(null);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voiceRequest || !previewText) return;

    setLoading(true);
    setJobId(null);
    setPreviewId(null);
    setJobStatus(null);
    setErrorMsg(null);
    setSuccessMsg(null);

    const params = {
      denoise,
      guidance_scale: guidanceScale,
      t_shift: tShift,
      position_temperature: positionTemperature,
      class_temperature: classTemperature,
      layer_penalty_factor: layerPenaltyFactor,
      duration: duration ? parseFloat(duration) : undefined,
      preprocess_prompt: preprocessPrompt,
      postprocess_output: postprocessOutput,
      audio_chunk_duration: audioChunkDuration,
      audio_chunk_threshold: audioChunkThreshold
    };

    try {
      const res = await api.createVoiceDesignPreview(voiceRequest, previewText, speed, numStep, params);
      setJobId(res.job_id);
      setPreviewId(res.preview_id);
      localStorage.setItem("VITE_VOICE_DESIGN_JOB_ID", res.job_id);
      localStorage.setItem("VITE_VOICE_DESIGN_PREVIEW_ID", res.preview_id);
      setJobStatus({
        job_id: res.job_id,
        status: res.status,
        message: res.message,
        progress: 0,
        audio_url: null,
        error_message: null,
      });
      setIsPolling(true);
      onJobCreatedOrUpdated?.();
    } catch (err: any) {
      setErrorMsg(err.message || "Không thể gửi yêu cầu thiết kế giọng nói.");
      setLoading(false);
    }
  };

  const handleClearJob = () => {
    setJobId(null);
    setPreviewId(null);
    setJobStatus(null);
    localStorage.removeItem("VITE_VOICE_DESIGN_JOB_ID");
    localStorage.removeItem("VITE_VOICE_DESIGN_PREVIEW_ID");
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem("VITE_VOICE_DESIGN_JOB_ID");
    const savedPreviewId = localStorage.getItem("VITE_VOICE_DESIGN_PREVIEW_ID");
    if (savedJobId) {
      setJobId(savedJobId);
      if (savedPreviewId) setPreviewId(savedPreviewId);
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
          console.error("Lỗi khôi phục Voice Design job status:", err);
          setLoading(false);
        });
    }
  }, []);

  useEffect(() => {
    if (isPolling && jobId) {
      // Poll every 2 seconds
      pollIntervalRef.current = window.setInterval(async () => {
        try {
          const status = await api.getJobStatus(jobId);
          setJobStatus(status);

          if (status.status === "completed" || status.status === "failed") {
            stopPolling();
            onJobCreatedOrUpdated?.();
          }
        } catch (err: any) {
          setErrorMsg(`Lỗi khi thăm dò trạng thái: ${err.message}`);
          stopPolling();
        }
      }, 2000);

      // Set timeout after 15 minutes (900000 ms)
      timeoutRef.current = window.setTimeout(() => {
        setErrorMsg("Hết thời gian chờ xử lý (Timeout 15 phút).");
        stopPolling();
      }, 900000);
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [isPolling, jobId]);

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setIsPolling(false);
    setLoading(false);
  };

  const handleAccept = async () => {
    if (!previewId) return;
    setAccepting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const res = await api.acceptPreview(previewId);
      setSuccessMsg(`Đã lưu giọng thiết kế làm mẫu thành công! ID: ${res.voice_sample_id}`);
      onAcceptSuccess(res.voice_sample_id);
    } catch (err: any) {
      setErrorMsg(err.message || "Lỗi khi chấp nhận giọng thiết kế.");
    } finally {
      setAccepting(false);
    }
  };

  const handleOpenSaveModal = (fullText: string) => {
    setSaveVoiceName(`Giọng Lưu - ${new Date().toLocaleDateString("vi-VN")} ${new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}`);
    
    // Suggest first 15 words of original text
    const words = fullText.trim().split(/\s+/);
    const suggestedText = words.slice(0, 15).join(" ") + (words.length > 15 ? "..." : "");
    setSaveVoiceRefText(suggestedText);
    setSaveVoiceCustomId("");
    
    setSaveVoiceIsPublic(false);
    setSaveVoiceStatus(null);
    setIsSaveModalOpen(true);
  };

  const handleSaveVoiceSubmit = async () => {
    if (!previewId || !saveVoiceName || !saveVoiceRefText) return;
    setIsSavingVoice(true);
    setSaveVoiceStatus(null);

    try {
      await api.saveFavoriteVoice({
        preview_id: previewId,
        name: saveVoiceName,
        is_public: saveVoiceIsPublic,
        ref_text: saveVoiceRefText,
        custom_id: saveVoiceCustomId || undefined,
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

  return (
    <div className={`bg-card border border-border flex flex-col relative overflow-hidden transition-all duration-300 ${
      layout === "modern"
        ? "rounded-2xl p-4 gap-3.5 shadow-sm"
        : "rounded-3xl p-6 gap-6 shadow-xl"
    }`}>
      {/* Ambient background glow */}
      {layout !== "modern" && (
        <div className="absolute top-0 right-0 w-24 h-24 bg-purple-500/5 rounded-full blur-xl pointer-events-none" />
      )}

      <div className="flex flex-col gap-0.5 relative z-10">
        <h2 className="text-xs font-extrabold tracking-widest text-muted-foreground uppercase flex items-center gap-2">
          <Mic className="w-3.5 h-3.5 text-purple-400" />
          <span>Thiết kế giọng nói</span>
        </h2>
        {layout !== "modern" && (
          <p className="text-xs text-muted-foreground font-medium mt-1">
            Mô tả kiểu giọng nói bằng tiếng Việt để tạo bản nghe thử rồi lưu vào thư viện.
          </p>
        )}
      </div>

      <form onSubmit={handleGenerate} className="flex flex-col gap-3.5 relative z-10">
        {/* Voice request */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider">
            Mô tả giọng nói (Tiếng Việt hoặc English Tags)
          </label>
          <input
            type="text"
            value={voiceRequest}
            onChange={(e) => setVoiceRequest(e.target.value)}
            placeholder="Ví dụ: giọng nữ trẻ trầm thì thầm hoặc 'female, young adult, low pitch, whisper'..."
            className="bg-background border border-border/40 rounded-xl px-2.5 py-2 text-[11px] text-foreground focus:outline-none focus:border-primary/30 transition-all font-semibold w-full"
          />
          {layout !== "modern" && (
            <span className="text-[9px] text-muted-foreground font-medium leading-tight">
              * Tự động dịch mô tả tiếng Việt (nữ/nam, trẻ/già, trầm/cao, thì thầm, cười, giọng Mỹ/Anh) hoặc nhập chuỗi tags tiếng Anh chuẩn của OmniVoice.
            </span>
          )}
        </div>

        {/* Preview text */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[9px] font-bold text-muted-foreground uppercase tracking-wider">
            Nội dung nghe thử (Preview Text)
          </label>
          <textarea
            value={previewText}
            onChange={(e) => setPreviewText(e.target.value)}
            placeholder="Nhập nội dung ngắn để nghe thử giọng..."
            rows={layout === "modern" ? 1.5 : 2}
            className="bg-background border border-border/40 rounded-xl px-2.5 py-2 text-[11px] text-foreground focus:outline-none focus:border-primary/30 transition-all font-semibold w-full resize-none"
          />
        </div>

        {/* Advanced parameters: Speed and Steps */}
        <div className={`p-3 bg-background/40 border border-border/80 rounded-2xl shadow-inner ${
          layout === "modern" ? "flex flex-col gap-3.5" : "grid grid-cols-1 md:grid-cols-2 gap-5"
        }`}>
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between items-center text-[10px]">
              <label className="font-bold text-muted-foreground uppercase tracking-wider">Tốc độ: {speed.toFixed(1)}x</label>
              <span className="text-[9px] text-muted-foreground font-bold font-mono select-none">0.5x - 2.0x</span>
            </div>
            <input
              type="range"
              min="0.5"
              max="2.0"
              step="0.1"
              value={speed}
              onChange={(e) => setSpeed(parseFloat(e.target.value))}
              className="seekbar w-full"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between items-center text-[10px]">
              <label className="font-bold text-muted-foreground uppercase tracking-wider">Độ chính xác (Steps): {numStep}</label>
              <span className="text-[9px] text-muted-foreground font-bold font-mono select-none">10 - 64</span>
            </div>
            <input
              type="range"
              min="10"
              max="64"
              step="1"
              value={numStep}
              onChange={(e) => setNumStep(parseInt(e.target.value))}
              className="seekbar w-full"
            />
          </div>
        </div>

        {/* Toggle Advanced Settings */}
        <div className="border-t border-border/80 pt-2.5">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground font-extrabold transition-colors cursor-pointer select-none"
          >
            <span>{showAdvanced ? "Ẩn cấu hình nâng cao" : "Hiện cấu hình nâng cao (OmniVoice)"}</span>
          </button>
        </div>

        {showAdvanced && (
          <div className="flex flex-col gap-4 p-4 bg-background/40 border border-border/80 rounded-2xl shadow-inner">
            {/* Toggles Row */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={denoise}
                  onChange={(e) => setDenoise(e.target.checked)}
                  className="rounded border-border/60 bg-card text-foreground focus:ring-slate-700 w-4 h-4 cursor-pointer"
                />
                <span>Denoise (Lọc nhiễu)</span>
              </label>

              <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={preprocessPrompt}
                  onChange={(e) => setPreprocessPrompt(e.target.checked)}
                  className="rounded border-border/60 bg-card text-foreground focus:ring-slate-700 w-4 h-4 cursor-pointer"
                />
                <span>Tiền xử lý tham chiếu</span>
              </label>

              <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={postprocessOutput}
                  onChange={(e) => setPostprocessOutput(e.target.checked)}
                  className="rounded border-border/60 bg-card text-foreground focus:ring-slate-700 w-4 h-4 cursor-pointer"
                />
                <span>Hậu xử lý đầu ra</span>
              </label>
            </div>

            <div className="h-px bg-card/60 my-1" />

            {/* Sliders and text fields grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4.5">
              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Guidance Scale: {guidanceScale.toFixed(1)}</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">0.5 - 5.0</span>
                </div>
                <input
                  type="range" min="0.5" max="5.0" step="0.1"
                  value={guidanceScale}
                  onChange={(e) => setGuidanceScale(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Time-step Shift (t_shift): {tShift.toFixed(2)}</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">0.01 - 0.50</span>
                </div>
                <input
                  type="range" min="0.01" max="0.50" step="0.01"
                  value={tShift}
                  onChange={(e) => setTShift(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Position Temperature: {positionTemperature.toFixed(1)}</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">0.0 - 10.0</span>
                </div>
                <input
                  type="range" min="0.0" max="10.0" step="0.5"
                  value={positionTemperature}
                  onChange={(e) => setPositionTemperature(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Class Temperature: {classTemperature.toFixed(1)}</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">0.0 - 5.0</span>
                </div>
                <input
                  type="range" min="0.0" max="5.0" step="0.1"
                  value={classTemperature}
                  onChange={(e) => setClassTemperature(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Layer Penalty Factor: {layerPenaltyFactor.toFixed(1)}</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">0.0 - 10.0</span>
                </div>
                <input
                  type="range" min="0.0" max="10.0" step="0.5"
                  value={layerPenaltyFactor}
                  onChange={(e) => setLayerPenaltyFactor(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-bold text-muted-foreground uppercase tracking-wider">Thời lượng cố định (Duration - giây)</label>
                <input
                  type="number" step="0.1" min="0.1"
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  placeholder="Mặc định: Tự động tính theo văn bản"
                  className="bg-card/60 border border-border/80 rounded-xl px-3 py-2.5 text-xs text-foreground focus:outline-none focus:border-border transition-all font-semibold"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Đoạn cắt (Chunk Duration): {audioChunkDuration.toFixed(0)}s</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">5 - 60</span>
                </div>
                <input
                  type="range" min="5" max="60" step="1"
                  value={audioChunkDuration}
                  onChange={(e) => setAudioChunkDuration(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="font-bold text-muted-foreground">Ngưỡng cắt (Chunk Threshold): {audioChunkThreshold.toFixed(0)}s</span>
                  <span className="text-[10px] text-muted-foreground font-bold font-mono">10 - 120</span>
                </div>
                <input
                  type="range" min="10" max="120" step="5"
                  value={audioChunkThreshold}
                  onChange={(e) => setAudioChunkThreshold(parseFloat(e.target.value))}
                  className="seekbar w-full"
                />
              </div>
            </div>
          </div>
        )}

        {errorMsg && (
          <div className="p-3.5 bg-destructive/10 border border-destructive/20 text-destructive rounded-xl text-xs font-semibold">
            {errorMsg}
          </div>
        )}

        {successMsg && (
          <div className="p-3.5 bg-success/10 border border-success/20 text-success rounded-xl text-xs font-semibold flex items-center gap-1.5">
            <Check className="w-4 h-4 flex-shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !voiceRequest || !previewText}
          className={`w-full py-3 px-6 rounded-full font-bold text-sm transition-all duration-155 active:scale-[0.99] flex items-center justify-center gap-2 cursor-pointer shadow-md ${
            !loading && voiceRequest && previewText
              ? "bg-gradient-to-r from-primary to-accent text-white border-none shadow-lg shadow-primary/15 hover:brightness-105"
              : "bg-muted text-muted-foreground cursor-not-allowed"
          }`}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
              <span>Đang khởi tạo preview...</span>
            </>
          ) : (
            <>
              <Wand2 className="w-4 h-4 fill-current" />
              <span>Tạo bản nghe thử</span>
            </>
          )}
        </button>
      </form>

      {/* Progress display */}
      {jobId && jobStatus && (
        <div className="mt-2 flex flex-col gap-4">
          <div className="flex justify-between items-center px-1">
            <span className="text-[10px] text-muted-foreground font-bold uppercase">Tiến trình tạo file</span>
            {(jobStatus.status === "completed" || jobStatus.status === "failed") && (
              <button
                type="button"
                onClick={handleClearJob}
                className="text-[10px] text-muted-foreground hover:text-foreground underline cursor-pointer font-bold"
              >
                Xóa kết quả hiển thị
              </button>
            )}
          </div>
          <JobStatusCard
            jobId={jobStatus.job_id}
            status={jobStatus.status}
            message={jobStatus.message}
            progress={jobStatus.progress}
            errorMessage={jobStatus.error_message}
          />

          {jobStatus.status === "completed" && jobStatus.audio_url && (
            <div className={`flex flex-col gap-3 mt-1 p-3 rounded-2xl shadow-inner select-none border transition-all duration-300 ${
              currentPlayUrl === `${api.getApiBaseUrl()}${jobStatus.audio_url}`
                ? "border-primary bg-primary/[0.02]"
                : "border-border/80 bg-background/40"
            }`}>
              <button
                type="button"
                onClick={() => {
                  const audioUrl = `${api.getApiBaseUrl()}${jobStatus.audio_url}`;
                  if (currentPlayUrl === audioUrl) {
                    onTogglePlay();
                  } else {
                    onPlayAudio(audioUrl, "Bản thiết nghe thử");
                  }
                }}
                className={`w-full py-2.5 px-5 rounded-full font-bold text-xs transition-all flex items-center justify-center gap-1.5 cursor-pointer border shadow-sm ${
                  currentPlayUrl === `${api.getApiBaseUrl()}${jobStatus.audio_url}` && globalPlayerPlaying
                    ? "bg-primary text-white border-primary shadow-primary/10"
                    : "border-border hover:border-primary/40 hover:bg-muted text-foreground bg-card"
                }`}
              >
                {currentPlayUrl === `${api.getApiBaseUrl()}${jobStatus.audio_url}` && globalPlayerPlaying ? (
                  <>
                    <Pause className="w-3.5 h-3.5 fill-current" />
                    <span>Tạm dừng</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                    <span>Nghe bản thiết kế</span>
                  </>
                )}
              </button>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                <button
                  onClick={handleAccept}
                  disabled={accepting}
                  className="w-full bg-card hover:bg-muted border border-border text-foreground font-bold text-xs py-2.5 px-4 rounded-full transition-all flex items-center justify-center gap-1.5 cursor-pointer shadow-sm active:scale-[0.98]"
                >
                  {accepting ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      <span>Đang lưu...</span>
                    </>
                  ) : (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      <span>Dùng làm mẫu clone gốc</span>
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => handleOpenSaveModal(previewText)}
                  className="w-full bg-card hover:bg-muted border border-border text-foreground font-bold text-xs py-2.5 px-4 rounded-full transition-all flex items-center justify-center gap-1.5 cursor-pointer shadow-sm active:scale-[0.98]"
                >
                  <Heart className="w-3.5 h-3.5 fill-slate-400 text-muted-foreground" />
                  <span>Lưu giọng yêu thích</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Save Voice Modal Overlay */}
      {isSaveModalOpen && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center p-4 lg:pl-64 bg-background/85 backdrop-blur-sm animate-fadeIn"
          onClick={() => setIsSaveModalOpen(false)}
        >
          <div 
            className="bg-card border border-border rounded-3xl p-6 w-full max-w-md flex flex-col gap-4 shadow-2xl relative"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setIsSaveModalOpen(false)}
              className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
            
            <div className="flex items-center gap-3 border-b border-border pb-3">
              <div className="p-2 bg-success/10 rounded-xl text-success">
                <Heart className="w-5 h-5 fill-emerald-400" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-foreground">Lưu giọng nói yêu thích</h3>
                <p className="text-[10px] text-muted-foreground font-semibold">Cắt 8 giây đầu và lưu làm mẫu clone giọng</p>
              </div>
            </div>

            {saveVoiceStatus && (
              <div className={`p-3.5 rounded-xl text-xs font-semibold border ${saveVoiceStatus.startsWith("Lỗi") ? "bg-destructive/10 border-destructive/20 text-destructive" : "bg-success/10 border-success/20 text-success"}`}>
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
                  className="bg-background border border-border rounded-xl p-2.5 text-xs text-foreground focus:outline-none focus:border-primary font-semibold"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Mã ID giọng nói (slug - Không bắt buộc)</label>
                <input
                  type="text"
                  value={saveVoiceCustomId}
                  onChange={(e) => setSaveVoiceCustomId(e.target.value)}
                  placeholder="Ví dụ: giong_nu_tram"
                  className="bg-background border border-border rounded-xl p-2.5 text-xs text-foreground focus:outline-none focus:border-primary font-mono font-semibold"
                />
              </div>


              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Văn bản tham khảo (Phát âm trong 8s đầu)</label>
                <textarea
                  value={saveVoiceRefText}
                  onChange={(e) => setSaveVoiceRefText(e.target.value)}
                  placeholder="Nhập phần chữ tương ứng với đoạn nói đầu tiên..."
                  rows={2}
                  className="bg-background border border-border rounded-xl p-2.5 text-xs text-foreground focus:outline-none focus:border-primary resize-none font-semibold"
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Chế độ chia sẻ</label>
                <div className="grid grid-cols-2 gap-2 bg-background p-1 rounded-xl border border-border/60">
                  <button
                    type="button"
                    onClick={() => setSaveVoiceIsPublic(false)}
                    className={`py-2 px-1 text-center font-bold text-xs rounded-lg transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
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
                    className={`py-2 px-1 text-center font-bold text-xs rounded-lg transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
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
            </div>

            <div className="flex gap-2 justify-end mt-2 pt-3 border-t border-border">
              <button
                type="button"
                onClick={() => setIsSaveModalOpen(false)}
                className="px-4 py-2 bg-muted hover:bg-muted border border-border text-xs font-semibold text-foreground rounded-lg cursor-pointer transition-colors"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleSaveVoiceSubmit}
                disabled={isSavingVoice || !saveVoiceName || !saveVoiceRefText}
                className="px-4 py-2 bg-gradient-to-r from-primary to-accent hover:brightness-105 disabled:bg-muted disabled:text-muted-foreground text-xs font-bold text-white rounded-lg cursor-pointer transition-colors border-none shadow-md shadow-primary/10"
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

const Loader2 = ({ className }: { className?: string }) => (
  <svg
    className={`animate-spin ${className}`}
    xmlns="http://www.w3.org/2000/svg"
    fill="none"
    viewBox="0 0 24 24"
  >
    <circle
      className="opacity-25"
      cx="12"
      cy="12"
      r="10"
      stroke="currentColor"
      strokeWidth="4"
    ></circle>
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
    ></path>
  </svg>
);
