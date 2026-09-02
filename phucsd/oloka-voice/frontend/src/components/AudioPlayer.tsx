import React, { useState, useEffect, useRef } from "react";
import { Download, Play, Pause, Volume1, Volume2, VolumeX, X, RotateCcw, RotateCw, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { audioEngine } from "../services/audioEngine";

interface AudioPlayerProps {
  url: string;
  title: string;
  isPlayingGlobal: boolean;
  onPlayingGlobalChange: (playing: boolean) => void;
  onClose: () => void;
}

export const AudioPlayer: React.FC<AudioPlayerProps> = ({
  url,
  title,
  isPlayingGlobal,
  onPlayingGlobalChange,
  onClose,
}) => {
  const token = localStorage.getItem("VITE_JWT_TOKEN");
  const isCdnUrl = url.includes("cdn") || url.includes("huggingface.co/datasets") || url.startsWith("blob:") || url.startsWith("data:");
  const authenticatedUrl = url ? (isCdnUrl ? url : `${url}${url.includes("?") ? "&" : "?"}token=${token || ""}`) : "";

  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [volumeVal, setVolumeVal] = useState(0.8);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);
  
  // Loading and Error States
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  // In-memory Blob URL & Web Audio API Preload for instant 0ms playback
  const [blobUrl, setBlobUrl] = useState<string>("");

  useEffect(() => {
    if (!authenticatedUrl) {
      setBlobUrl("");
      return;
    }

    // Instantly stop previous track when switching audio
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }

    let isCancelled = false;
    setIsLoading(true);

    // Preload via Web Audio Engine
    audioEngine.preload(authenticatedUrl);

    fetch(authenticatedUrl)
      .then(res => res.blob())
      .then(blob => {
        if (!isCancelled) {
          const objectUrl = URL.createObjectURL(blob);
          setBlobUrl(objectUrl);
          setIsLoading(false);
        }
      })
      .catch(err => {
        console.warn("Pre-fetch audio blob failed, falling back to direct URL", err);
        if (!isCancelled) {
          setBlobUrl(authenticatedUrl);
          setIsLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [authenticatedUrl]);

  // Auto play when blobUrl changes
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (blobUrl || authenticatedUrl) {
      setHasError(false);
      audio.play()
        .then(() => {
          setIsPlaying(true);
          onPlayingGlobalChange(true);
        })
        .catch(() => {
          // Play abort is normal when loading a new track fast
        });
    }
  }, [blobUrl]);

  // Sync state with HTML5 Audio Element
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handlePlay = () => {
      setIsPlaying(true);
      onPlayingGlobalChange(true);
    };
    const handlePause = () => {
      setIsPlaying(false);
      onPlayingGlobalChange(false);
    };
    const handleTimeUpdate = () => setCurrentTime(audio.currentTime);
    const handleLoadedMetadata = () => {
      setDuration(audio.duration);
      setIsLoading(false);
      setHasError(false);
    };
    const handleEnded = () => {
      setIsPlaying(false);
      onPlayingGlobalChange(false);
      setCurrentTime(0);
    };
    const handleWaiting = () => setIsLoading(true);
    const handlePlaying = () => {
      setIsLoading(false);
      setHasError(false);
    };
    const handleCanPlay = () => {
      setIsLoading(false);
      setHasError(false);
    };
    const handleError = () => {
      setIsLoading(false);
      setHasError(true);
    };

    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("waiting", handleWaiting);
    audio.addEventListener("playing", handlePlaying);
    audio.addEventListener("canplay", handleCanPlay);
    audio.addEventListener("error", handleError);

    if (audio.duration) {
      setDuration(audio.duration);
    }

    return () => {
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("waiting", handleWaiting);
      audio.removeEventListener("playing", handlePlaying);
      audio.removeEventListener("canplay", handleCanPlay);
      audio.removeEventListener("error", handleError);
    };
  }, [authenticatedUrl]);

  // Sync HTML5 play state when parent changes isPlayingGlobal
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlayingGlobal) {
      if (audio.paused) {
        audio.play().catch(err => console.error("Global play error:", err));
      }
    } else {
      if (!audio.paused) {
        audio.pause();
      }
    }
  }, [isPlayingGlobal]);

  // Adjust volume/mute
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.volume = isMuted ? 0 : volumeVal;
    }
  }, [volumeVal, isMuted]);

  // Adjust playback speed
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play().catch(err => console.error("Audio playback error:", err));
    }
  };

  const handleSeekChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const newTime = parseFloat(e.target.value);
    audio.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const toggleMute = () => {
    setIsMuted(!isMuted);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newVal = parseFloat(e.target.value);
    setVolumeVal(newVal);
    if (newVal > 0 && isMuted) {
      setIsMuted(false);
    }
  };

  const handleDownload = (e: React.MouseEvent) => {
    e.preventDefault();
    const link = document.createElement("a");
    link.href = authenticatedUrl;
    link.download = title ? `${title.replace(/\s+/g, "_")}.wav` : "audio.wav";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleRewind = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, audio.currentTime - 10);
    setCurrentTime(audio.currentTime);
  };

  const handleForward = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.min(duration, audio.currentTime + 10);
    setCurrentTime(audio.currentTime);
  };

  const formatTime = (time: number) => {
    if (isNaN(time)) return "00:00";
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    const mm = minutes < 10 ? `0${minutes}` : `${minutes}`;
    const ss = seconds < 10 ? `0${seconds}` : `${seconds}`;
    return `${mm}:${ss}`;
  };

  const speeds = [0.75, 1.0, 1.25, 1.5, 2.0];
  const percentage = duration ? (currentTime / duration) * 100 : 0;

  // Choose correct volume icon
  const renderVolumeIcon = () => {
    if (isMuted || volumeVal === 0) {
      return <VolumeX className="w-4 h-4" />;
    }
    if (volumeVal < 0.5) {
      return <Volume1 className="w-4 h-4" />;
    }
    return <Volume2 className="w-4 h-4" />;
  };

  if (!url) {
    return (
      <div className="w-full h-full flex items-center justify-center text-fluid-sm text-muted-foreground/50 select-none font-semibold relative">
        <div className="absolute inset-0 bg-card/65 backdrop-blur-md transition-colors duration-300 dark:bg-[#151922]/75 -z-10" />
        <div className="flex items-center gap-2">
          <Volume2 className="w-4 h-4 text-muted-foreground/35 animate-pulse" />
          <span>Chưa có audio được tạo. Nhập văn bản và chọn giọng để bắt đầu.</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full relative select-none animate-player-in">
      {/* Liquid Animated Blobs Background */}
      <div className="absolute inset-0 -z-10 overflow-hidden pointer-events-none">
        {/* Glass Layer */}
        <div className="absolute inset-0 bg-card/65 backdrop-blur-2xl transition-colors duration-300 dark:bg-[#151922]/75" />
        
        {/* Fluid blobs */}
        <div className={`absolute -inset-10 opacity-70 transition-opacity duration-1000 ${isPlaying ? 'opacity-90' : 'opacity-40'}`}>
          <div className="absolute top-1/4 left-1/4 w-32 h-32 rounded-full bg-primary/20 blur-[20px] animate-liquid-1" />
          <div className="absolute bottom-1/4 right-1/4 w-36 h-36 rounded-full bg-accent/25 blur-[25px] animate-liquid-2" />
          <div className="absolute top-1/3 right-1/3 w-28 h-28 rounded-full bg-pink-500/10 blur-[22px] animate-liquid-3" />
        </div>
      </div>

      <div className="h-full px-6 flex items-center justify-between gap-4 relative z-10">
        <audio ref={audioRef} src={blobUrl || authenticatedUrl} preload="auto" />

        {/* Left: SkipBack, Play, SkipForward & Metadata & Equalizer */}
        <div className="flex items-center gap-3.5 min-w-0">
          {/* Controls button group */}
          <div className="flex items-center gap-1 shrink-0">
            {/* Rewind 10s */}
            <button
              onClick={handleRewind}
              className="p-2 hover:bg-secondary rounded-full text-muted-foreground hover:text-foreground transition-all cursor-pointer hidden xs:flex items-center justify-center shrink-0"
              title="Tua lại 10 giây"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            {/* Play/Pause/Loader */}
            <button
              onClick={togglePlay}
              className="w-10 h-10 rounded-full bg-gradient-to-tr from-primary to-accent hover:brightness-105 text-white flex items-center justify-center cursor-pointer shrink-0 shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 duration-300 btn-squishy"
              title={isPlaying ? "Tạm dừng" : "Phát"}
              disabled={hasError}
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin text-white" />
              ) : isPlaying ? (
                <Pause className="w-4 h-4 fill-current text-white" />
              ) : (
                <Play className="w-4 h-4 fill-current text-white ml-0.5" />
              )}
            </button>

            {/* Forward 10s */}
            <button
              onClick={handleForward}
              className="p-2 hover:bg-secondary rounded-full text-muted-foreground hover:text-foreground transition-all cursor-pointer hidden xs:flex items-center justify-center shrink-0"
              title="Tua tới 10 giây"
            >
              <RotateCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Sound Metadata */}
          <div className="flex flex-col min-w-0 leading-tight">
            <div className="flex items-center gap-2">
              <span className="text-fluid-sm font-bold text-foreground truncate max-w-[100px] sm:max-w-[130px] md:max-w-[180px]" title={title}>
                {title}
              </span>
              
              {/* Mini Liquid Equalizer */}
              {!hasError && (
                <div className="flex items-end gap-0.5 h-3 shrink-0 select-none" title={isPlaying ? "Đang phát" : "Tạm dừng"}>
                  <span className={`w-[2px] bg-primary rounded-full transition-all duration-300 ${isPlaying ? 'h-3 animate-wave-bar-1' : 'h-[3px]'}`} />
                  <span className={`w-[2px] bg-accent rounded-full transition-all duration-300 ${isPlaying ? 'h-4.5 animate-wave-bar-2' : 'h-[3px]'}`} />
                  <span className={`w-[2px] bg-primary rounded-full transition-all duration-300 ${isPlaying ? 'h-2.5 animate-wave-bar-3' : 'h-[3px]'}`} />
                  <span className={`w-[2px] bg-accent rounded-full transition-all duration-300 ${isPlaying ? 'h-4 animate-wave-bar-4' : 'h-[3px]'}`} />
                </div>
              )}
            </div>
            
            {hasError ? (
              <span className="text-fluid-xs text-destructive font-bold flex items-center gap-0.5">
                <AlertCircle className="w-3.5 h-3.5" />
                <span>Lỗi phát âm thanh</span>
              </span>
            ) : (
              <span className="text-fluid-xs font-mono font-medium text-muted-foreground mt-0.5 tabular-nums select-none">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            )}
          </div>
        </div>

        {/* Center: Fluid Seekbar Slider */}
        <div className="flex-grow max-w-[400px] hidden sm:flex items-center">
          <input
            type="range"
            min={0}
            max={duration || 100}
            value={currentTime}
            onChange={handleSeekChange}
            className="seekbar w-full"
            disabled={hasError}
            style={{
              background: `linear-gradient(to right, var(--primary) 0%, var(--accent) ${percentage}%, var(--slider-track) ${percentage}%, var(--slider-track) 100%)`
            }}
          />
        </div>

        {/* Right: Tools & Dismiss */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Playback Speed Selector */}
          <div className="relative flex items-center">
            <button
              onClick={() => setShowSpeedMenu(!showSpeedMenu)}
              className="px-2.5 py-1.5 bg-background/50 hover:bg-secondary border border-border/80 hover:border-border rounded-lg text-fluid-xs font-bold text-muted-foreground hover:text-foreground transition-all cursor-pointer select-none"
            >
              {playbackRate.toFixed(2)}x
            </button>
            
            {showSpeedMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowSpeedMenu(false)} />
                <div className="absolute bottom-full right-0 mb-2.5 z-25 bg-card/95 border border-border/80 rounded-2xl p-1.5 shadow-2xl flex flex-col gap-0.5 min-w-[75px] animate-speed-menu backdrop-blur-md">
                  {speeds.map(s => (
                    <button
                      key={s}
                      onClick={() => {
                        setPlaybackRate(s);
                        setShowSpeedMenu(false);
                      }}
                      className={`px-3 py-1.5 text-left rounded-xl text-fluid-xs font-bold transition-all cursor-pointer w-full ${
                        playbackRate === s
                          ? "bg-gradient-to-tr from-primary to-accent text-white"
                          : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                      }`}
                    >
                      {s.toFixed(2)}x
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Volume Control Group (Speaker + Hover Slider) */}
          <div className="flex items-center gap-1.5 group/volume relative py-1">
            <button
              onClick={toggleMute}
              className="text-muted-foreground hover:text-foreground hover:bg-secondary rounded-full p-2 transition-all cursor-pointer shrink-0"
              title={isMuted ? "Bật âm thanh" : "Tắt âm thanh"}
            >
              {renderVolumeIcon()}
            </button>
            
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={isMuted ? 0 : volumeVal}
              onChange={handleVolumeChange}
              className="w-0 opacity-0 group-hover/volume:w-16 group-hover/volume:opacity-100 focus:w-16 focus:opacity-100 transition-all duration-300 h-1 bg-slider-track/50 rounded-full appearance-none cursor-pointer range-xs accent-primary pointer-events-none group-hover/volume:pointer-events-auto focus:pointer-events-auto"
              style={{
                background: `linear-gradient(to right, var(--primary) 0%, var(--accent) ${(isMuted ? 0 : volumeVal) * 100}%, var(--slider-track) ${(isMuted ? 0 : volumeVal) * 100}%, var(--slider-track) 100%)`
              }}
            />
          </div>

          {/* Download Button */}
          <button
            onClick={handleDownload}
            className="text-muted-foreground hover:text-foreground hover:bg-secondary rounded-full p-2 transition-all cursor-pointer shrink-0"
            title="Tải xuống tệp WAV"
          >
            <Download className="w-4 h-4" />
          </button>

          {/* Regenerate Button */}
          <button
            onClick={() => {
              window.dispatchEvent(new CustomEvent("omnivoice:regenerate"));
            }}
            className="text-muted-foreground hover:text-foreground hover:bg-secondary rounded-full p-2 transition-all cursor-pointer shrink-0"
            title="Tạo lại âm thanh (Regenerate)"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {/* Divider */}
          <div className="h-5 w-[1px] bg-border/85 mx-0.5 shrink-0" />

          {/* Dismiss Player Button */}
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded-full p-2 transition-all cursor-pointer shrink-0"
            title="Đóng trình phát"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
};
