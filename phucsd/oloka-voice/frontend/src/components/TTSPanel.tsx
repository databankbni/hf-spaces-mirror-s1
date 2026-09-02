import React, { useState, useEffect, useRef } from "react";
import { Play, Pause, Loader2, Sparkles, Settings2, CheckCircle2 } from "lucide-react";
import { api } from "../api/client";
import type { JobStatusResponse, VoiceSampleResponse } from "../api/client";

import { JobStatusCard } from "./JobStatusCard";
import { PageHeader } from "./ui/PageHeader";
import { SectionCard } from "./ui/SectionCard";

interface TTSPanelProps {
  activeVoiceSampleId: string | null;
  onJobCreatedOrUpdated?: () => void;
  layout?: "classic" | "modern";
  currentPlayUrl: string | null;
  globalPlayerPlaying: boolean;
  onPlayAudio: (url: string, title: string) => void;
  onTogglePlay: () => void;
}

export const TTSPanel: React.FC<TTSPanelProps> = ({
  activeVoiceSampleId,
  onJobCreatedOrUpdated,
  currentPlayUrl,
  globalPlayerPlaying,
  onPlayAudio,
  onTogglePlay,
}) => {
  const [mode, setMode] = useState<"clone_voice" | "auto_voice" | "voice_design">("clone_voice");
  const [text, setText] = useState("Học sinh hôm nay được nghỉ học do thời tiết xấu. Xin nhắc lại, học sinh được nghỉ học.");
  const [customVoiceSampleId, setCustomVoiceSampleId] = useState("");
  const [refText, setRefText] = useState("");
  
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  const [speed, setSpeed] = useState(1.0);
  const [numStep, setNumStep] = useState(32);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [denoise, setDenoise] = useState(true);
  const [guidanceScale, setGuidanceScale] = useState(2.0);
  const [tShift, setTShift] = useState<number>(0.1);

  const [positionTemperature, setPositionTemperature] = useState(5.0);
  const [classTemperature, setClassTemperature] = useState(0.0);
  const [layerPenaltyFactor, setLayerPenaltyFactor] = useState<number>(5.0);
  const [duration] = useState<number | null>(null);
  const [preprocessPrompt] = useState<boolean>(true);
  const [postprocessOutput] = useState<boolean>(true);
  const [audioChunkDuration] = useState(15.0);
  const [audioChunkThreshold] = useState(30.0);
  const [language, setLanguage] = useState("");
  const [padDuration, setPadDuration] = useState<string>("");
  const [fadeDuration, setFadeDuration] = useState<string>("");
  
  const [activePreset, setActivePreset] = useState("Tự nhiên");

  const applyPreset = (presetName: string) => {
    setActivePreset(presetName);
    switch (presetName) {
      case "Tự nhiên":
        setSpeed(1.0); setNumStep(32); setGuidanceScale(2.0); setPositionTemperature(5.0); setClassTemperature(0.0); setDenoise(true); setTShift(0.1); setLayerPenaltyFactor(5.0);
        break;
      case "Kể chuyện":
        setSpeed(0.9); setNumStep(40); setGuidanceScale(2.0); setPositionTemperature(4.0); setClassTemperature(0.1); setDenoise(true); setTShift(0.1); setLayerPenaltyFactor(5.0);
        break;
      case "Quảng cáo":
        setSpeed(1.1); setNumStep(32); setGuidanceScale(2.5); setPositionTemperature(6.0); setClassTemperature(0.2); setDenoise(true); setTShift(0.15); setLayerPenaltyFactor(5.0);
        break;
      case "Tin tức":
        setSpeed(1.05); setNumStep(32); setGuidanceScale(3.0); setPositionTemperature(5.0); setClassTemperature(0.0); setDenoise(true); setTShift(0.1); setLayerPenaltyFactor(5.0);
        break;
      case "Chậm rõ":
        setSpeed(0.8); setNumStep(40); setGuidanceScale(2.5); setPositionTemperature(4.0); setClassTemperature(0.0); setDenoise(true); setTShift(0.1); setLayerPenaltyFactor(5.0);
        break;
      case "Nhanh gọn":
        setSpeed(1.3); setNumStep(20); setGuidanceScale(1.5); setPositionTemperature(6.0); setClassTemperature(0.0); setDenoise(false); setTShift(0.05); setLayerPenaltyFactor(5.0);
        break;
    }
  };

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollIntervalRef = useRef<number | null>(null);
  const timeoutRef = useRef<number | null>(null);

  const [voiceSamples, setVoiceSamples] = useState<VoiceSampleResponse[]>([]);

  const fetchVoiceSamples = async () => {
    try {
      const samples = await api.listVoiceSamples();
      setVoiceSamples(samples);
    } catch (err) {
      console.error("Lỗi lấy danh sách mẫu giọng:", err);
    }
  };

  useEffect(() => {
    fetchVoiceSamples();
  }, []);

  useEffect(() => {
    if (activeVoiceSampleId) {
      setCustomVoiceSampleId(activeVoiceSampleId);
      setMode("clone_voice");
      fetchVoiceSamples();
    }
  }, [activeVoiceSampleId]);

  const handleGenerate = async () => {
    if (!text) return;
    setLoading(true);
    setJobId(null);
    setJobStatus(null);
    setErrorMsg(null);

    const voiceSampleId = mode === "clone_voice" ? customVoiceSampleId : undefined;
    const refTextParam = mode === "clone_voice" && refText ? refText : undefined;

    if (mode === "clone_voice" && !voiceSampleId) {
      setErrorMsg("Vui lòng chọn mẫu giọng.");
      setLoading(false);
      return;
    }

    const params = {
      denoise,
      guidance_scale: guidanceScale,
      t_shift: tShift,
      position_temperature: positionTemperature,
      class_temperature: classTemperature,
      layer_penalty_factor: layerPenaltyFactor,
      duration: duration !== null ? duration : undefined,
      preprocess_prompt: preprocessPrompt,
      postprocess_output: postprocessOutput,
      audio_chunk_duration: audioChunkDuration,
      audio_chunk_threshold: audioChunkThreshold,
      language: language || undefined,
      pad_duration: padDuration !== "" ? parseFloat(padDuration) : undefined,
      fade_duration: fadeDuration !== "" ? parseFloat(fadeDuration) : undefined
    };

    try {
      const res = await api.createTTSJob(mode, text, voiceSampleId, undefined, speed, numStep, params, refTextParam);
      setJobId(res.job_id);
      localStorage.setItem("VITE_TTS_JOB_ID", res.job_id);
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
      setErrorMsg(err.message || "Không thể khởi tạo tiến trình TTS.");
      setLoading(false);
    }
  };

  useEffect(() => {
    const savedJobId = localStorage.getItem("VITE_TTS_JOB_ID");
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
          console.error("Lỗi khôi phục TTS job status:", err);
          setLoading(false);
        });
    }
  }, []);

  useEffect(() => {
    if (isPolling && jobId) {
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

      timeoutRef.current = window.setTimeout(() => {
        setErrorMsg("Hết thời gian chờ xử lý (Timeout 15 phút).");
        stopPolling();
      }, 900000);
    }

    return () => stopPolling();
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

  const handleClearJob = () => {
    setJobId(null);
    setJobStatus(null);
    localStorage.removeItem("VITE_TTS_JOB_ID");
  };

  return (
    <div className="w-full flex flex-col gap-6">
      <PageHeader 
        title="Tạo giọng đọc" 
        description="Tạo audio từ văn bản theo 3 bước đơn giản."
        icon={<Sparkles className="w-6 h-6" />}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        <div className="lg:col-span-2 flex flex-col gap-6">
          {/* Step 1: Select Voice */}
          <SectionCard title="1. Chọn giọng đọc">
            <div className="flex flex-col gap-4">
              {activeVoiceSampleId && customVoiceSampleId === activeVoiceSampleId && (
                <div className="bg-primary/10 border border-primary/30 p-3 rounded-lg flex items-center gap-3">
                  <CheckCircle2 className="w-5 h-5 text-primary shrink-0" />
                  <div className="flex flex-col">
                    <span className="text-xs font-bold text-primary">Giọng đang chọn</span>
                    <span className="text-sm font-medium">{activeVoiceSampleId.substring(0, 15)}...</span>
                  </div>
                </div>
              )}
              <select
                value={customVoiceSampleId}
                onChange={(e) => {
                  setCustomVoiceSampleId(e.target.value);
                  const found = voiceSamples.find(s => s.id === e.target.value);
                  if (found && found.ref_text) setRefText(found.ref_text);
                }}
                className="bg-secondary/50 border border-border/70 hover:border-border rounded-xl px-4 h-12 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20 w-full"
              >
                <option value="">-- Chọn một mẫu giọng --</option>
                <optgroup label="Giọng cá nhân (Private)">
                  {voiceSamples.filter(s => !s.is_public).map(s => (
                    <option key={s.id} value={s.id}>
                      {s.name || s.id.substring(0, 10)} {s.duration ? `[${s.duration.toFixed(1)}s]` : ""}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Giọng cộng đồng (Public)">
                  {voiceSamples.filter(s => s.is_public).map(s => (
                    <option key={s.id} value={s.id}>
                      {s.name || s.id.substring(0, 10)} {s.duration ? `[${s.duration.toFixed(1)}s]` : ""}
                    </option>
                  ))}
                </optgroup>
              </select>
            </div>
          </SectionCard>

          {/* Step 2: Enter Text */}
          <SectionCard title="2. Nhập văn bản">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Nhập nội dung cần đọc..."
              className="w-full bg-secondary/30 rounded-xl p-4 min-h-[200px] border border-border/60 focus:border-primary/50 focus:outline-none resize-y"
            />
            <div className="text-xs text-muted-foreground mt-2 text-right">
              {text.length} / 5000 ký tự
            </div>
          </SectionCard>

          {/* Step 3: Result & Progress */}
          {jobId && jobStatus && (
            <SectionCard title="3. Kết quả">
              <JobStatusCard
                jobId={jobStatus.job_id}
                status={jobStatus.status}
                message={jobStatus.message}
                progress={jobStatus.progress}
                errorMessage={jobStatus.error_message}
              />
              {jobStatus.status === "completed" && jobStatus.audio_url && (
                <div className="mt-4 flex gap-3">
                  <button
                    onClick={() => {
                      const url = `${api.getApiBaseUrl()}${jobStatus.audio_url}`;
                      if (currentPlayUrl === url) onTogglePlay();
                      else onPlayAudio(url, "TTS Output");
                    }}
                    className="flex-1 bg-primary text-primary-foreground hover:bg-primary-hover h-10 rounded-xl flex items-center justify-center gap-2 text-sm font-semibold transition-colors"
                  >
                    {currentPlayUrl === `${api.getApiBaseUrl()}${jobStatus.audio_url}` && globalPlayerPlaying ? (
                      <><Pause className="w-4 h-4" /> Tạm dừng</>
                    ) : (
                      <><Play className="w-4 h-4" /> Nghe thử</>
                    )}
                  </button>
                  <button onClick={handleClearJob} className="px-4 bg-secondary text-foreground hover:bg-secondary/80 h-10 rounded-xl text-sm font-semibold">
                    Xóa kết quả
                  </button>
                </div>
              )}
            </SectionCard>
          )}
        </div>

        {/* Right column: Config & Generate */}
        <div className="lg:col-span-1 flex flex-col gap-6">
           <button
              onClick={handleGenerate}
              disabled={loading || !text || !customVoiceSampleId}
              className={`w-full h-14 rounded-xl font-bold text-base transition-all flex items-center justify-center gap-2 shadow-lg ${
                !loading && text && customVoiceSampleId
                  ? "bg-primary text-primary-foreground hover:bg-primary-hover shadow-primary/20"
                  : "bg-secondary text-muted-foreground cursor-not-allowed"
              }`}
            >
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Play className="w-5 h-5 fill-current" />}
              <span>{loading ? "Đang xử lý..." : "Tạo Audio"}</span>
            </button>

            {errorMsg && (
              <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive rounded-xl text-sm font-semibold">
                {errorMsg}
              </div>
            )}

          <SectionCard title="Cấu hình giọng đọc">
            <div className="flex flex-col gap-5">
              <div>
                <label className="text-xs font-bold text-muted-foreground uppercase mb-2 block">Cảm xúc & Nhịp điệu (Presets)</label>
                <div className="flex flex-wrap gap-2">
                  {["Tự nhiên", "Kể chuyện", "Quảng cáo", "Tin tức", "Chậm rõ", "Nhanh gọn"].map(p => (
                    <button
                      key={p}
                      onClick={() => applyPreset(p)}
                      className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                        activePreset === p ? "bg-primary/10 border-primary text-primary" : "bg-secondary/40 border-border hover:border-primary/50 text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <button
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase hover:text-foreground w-full text-left"
                >
                  <Settings2 className="w-4 h-4" />
                  Tham số kỹ thuật (Advanced) {showAdvanced ? "▲" : "▼"}
                </button>

                {showAdvanced && (
                  <div className="flex flex-col gap-4 mt-4 p-4 bg-secondary/20 rounded-xl border border-border/50">
                    <label className="flex items-center gap-2 text-xs font-semibold text-muted-foreground cursor-pointer">
                      <input type="checkbox" checked={denoise} onChange={e => setDenoise(e.target.checked)} className="rounded border-border text-primary focus:ring-primary" />
                      Lọc nhiễu (Denoise)
                    </label>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Tốc độ (Speed): {speed.toFixed(1)}x</span>
                      <input type="range" min="0.5" max="2.0" step="0.1" value={speed} onChange={e => setSpeed(parseFloat(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Steps: {numStep}</span>
                      <input type="range" min="10" max="64" step="1" value={numStep} onChange={e => setNumStep(parseInt(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Guidance Scale: {guidanceScale.toFixed(1)}</span>
                      <input type="range" min="0.5" max="5.0" step="0.1" value={guidanceScale} onChange={e => setGuidanceScale(parseFloat(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">t_shift: {tShift.toFixed(2)}</span>
                      <input type="range" min="0.01" max="0.50" step="0.01" value={tShift} onChange={e => setTShift(parseFloat(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Position Temp: {positionTemperature.toFixed(1)}</span>
                      <input type="range" min="0.0" max="10.0" step="0.5" value={positionTemperature} onChange={e => setPositionTemperature(parseFloat(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Layer Penalty: {layerPenaltyFactor.toFixed(1)}</span>
                      <input type="range" min="0.0" max="10.0" step="0.5" value={layerPenaltyFactor} onChange={e => setLayerPenaltyFactor(parseFloat(e.target.value))} className="w-full" />
                    </div>
                    <div className="flex flex-col gap-1">
                      <span className="text-[10px] font-bold text-muted-foreground uppercase">Ngôn ngữ (Language)</span>
                      <select
                        value={language}
                        onChange={e => setLanguage(e.target.value)}
                        className="w-full bg-background border border-border rounded-lg text-xs p-2 focus:outline-none focus:ring-1 focus:ring-primary text-foreground"
                      >
                        <option value="">Tự động nhận diện (Mặc định)</option>
                        <option value="vi">Tiếng Việt (vi)</option>
                        <option value="en">Tiếng Anh (en)</option>
                        <option value="zh">Tiếng Trung (zh)</option>
                        <option value="ja">Tiếng Nhật (ja)</option>
                        <option value="ko">Tiếng Hàn (ko)</option>
                        <option value="fr">Tiếng Pháp (fr)</option>
                        <option value="de">Tiếng Đức (de)</option>
                        <option value="es">Tiếng Tây Ban Nha (es)</option>
                      </select>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] font-bold text-muted-foreground uppercase">Pad Duration (Độ đệm)</span>
                        <input
                          type="number" min="0" max="2.0" step="0.05" placeholder="Mặc định" value={padDuration}
                          onChange={e => setPadDuration(e.target.value)}
                          className="bg-background border border-border rounded-lg text-xs p-2 focus:outline-none focus:ring-1 focus:ring-primary text-foreground w-full"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-[10px] font-bold text-muted-foreground uppercase">Fade Duration (Làm mượt)</span>
                        <input
                          type="number" min="0" max="1.0" step="0.05" placeholder="Mặc định" value={fadeDuration}
                          onChange={e => setFadeDuration(e.target.value)}
                          className="bg-background border border-border rounded-lg text-xs p-2 focus:outline-none focus:ring-1 focus:ring-primary text-foreground w-full"
                        />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </div>
  );
};
