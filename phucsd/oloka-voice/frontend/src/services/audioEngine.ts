// High-Performance Web Audio API Engine for Instant 0ms Playback

class AudioEngineService {
  private audioCtx: AudioContext | null = null;
  private bufferCache = new Map<string, AudioBuffer>();
  private activeSourceNode: AudioBufferSourceNode | null = null;
  private gainNode: GainNode | null = null;

  private currentUrl: string | null = null;
  private startTime: number = 0;
  private startOffset: number = 0;
  private isPlaying: boolean = false;
  private volume: number = 0.8;

  constructor() {
    // AudioContext will be initialized on first user gesture or preload
  }

  private getContext(): AudioContext {
    if (!this.audioCtx) {
      const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext;
      this.audioCtx = new AudioCtxClass();
      this.gainNode = this.audioCtx.createGain();
      this.gainNode.gain.value = this.volume;
      this.gainNode.connect(this.audioCtx.destination);
    }
    if (this.audioCtx.state === "suspended") {
      this.audioCtx.resume();
    }
    return this.audioCtx;
  }

  /**
   * Pre-fetches audio data over HTTPS and decodes it into an in-memory AudioBuffer.
   */
  async preload(url: string): Promise<AudioBuffer | null> {
    if (!url) return null;
    if (this.bufferCache.has(url)) {
      return this.bufferCache.get(url)!;
    }

    try {
      const ctx = this.getContext();
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      
      const arrayBuffer = await response.arrayBuffer();
      const decodedBuffer = await ctx.decodeAudioData(arrayBuffer);
      
      this.bufferCache.set(url, decodedBuffer);
      return decodedBuffer;
    } catch (err) {
      console.warn("[AudioEngine] Preload failed, fallback to native fetch:", err);
      return null;
    }
  }

  /**
   * Plays the specified audio URL instantly (0ms latency if preloaded).
   */
  async play(
    url: string, 
    offset: number = 0, 
    onEnded?: () => void
  ): Promise<boolean> {
    if (!url) return false;
    const ctx = this.getContext();

    // Stop current playing audio
    this.stop();

    let buffer = this.bufferCache.get(url);
    if (!buffer) {
      buffer = (await this.preload(url)) || undefined;
    }

    if (!buffer) {
      return false;
    }

    this.currentUrl = url;
    this.startOffset = offset;
    this.startTime = ctx.currentTime;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gainNode!);

    source.onended = () => {
      if (this.currentUrl === url && this.isPlaying) {
        this.isPlaying = false;
        if (onEnded) onEnded();
      }
    };

    source.start(0, offset);
    this.activeSourceNode = source;
    this.isPlaying = true;

    return true;
  }

  /**
   * Pauses the currently playing audio track.
   */
  pause(): number {
    if (!this.isPlaying || !this.audioCtx) return this.startOffset;

    const elapsed = this.audioCtx.currentTime - this.startTime;
    this.startOffset += elapsed;

    if (this.activeSourceNode) {
      try {
        this.activeSourceNode.stop();
      } catch {}
      this.activeSourceNode = null;
    }

    this.isPlaying = false;
    return this.startOffset;
  }

  /**
   * Stops audio playback and resets state.
   */
  stop(): void {
    if (this.activeSourceNode) {
      try {
        this.activeSourceNode.stop();
      } catch {}
      this.activeSourceNode = null;
    }
    this.isPlaying = false;
    this.startOffset = 0;
  }

  /**
   * Sets current output volume (0.0 to 1.0).
   */
  setVolume(vol: number): void {
    this.volume = Math.max(0, Math.min(1, vol));
    if (this.gainNode) {
      this.gainNode.gain.value = this.volume;
    }
  }

  /**
   * Returns whether audio is currently playing.
   */
  getIsPlaying(): boolean {
    return this.isPlaying;
  }

  /**
   * Returns total duration of preloaded buffer in seconds.
   */
  getDuration(url: string): number {
    const buf = this.bufferCache.get(url);
    return buf ? buf.duration : 0;
  }
}

export const audioEngine = new AudioEngineService();
