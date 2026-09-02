import React, { useState, useEffect, useMemo } from "react";
import { Volume2, Lock, Globe, Trash2, Copy, Check, Search, Sparkles, Play, Pause, Pencil, X, Tag, ChevronDown, ChevronUp, Info } from "lucide-react";
import { api } from "../api/client";
import type { VoiceSampleResponse, VoiceSampleUpdateRequest } from "../api/client";

// Predefined tag categories for the filter bar
const PRESET_TAG_GROUPS: { label: string; tags: string[] }[] = [
  { label: "Khu vực", tags: ["Miền Bắc", "Miền Nam", "Miền Trung"] },
  { label: "Tuổi", tags: ["Trẻ", "Trung niên", "Cao tuổi"] },
  { label: "Phong cách", tags: ["Kể chuyện", "Quảng cáo", "Tin tức", "Podcast", "Audiobook"] },
];

const ALL_PRESET_TAGS = PRESET_TAG_GROUPS.flatMap(g => g.tags);

// Tag color mapping for visual variety
function getTagColor(tag: string): string {
  const regionTags = ["Miền Bắc", "Miền Nam", "Miền Trung"];
  const ageTags = ["Trẻ", "Trung niên", "Cao tuổi"];
  const styleTags = ["Kể chuyện", "Quảng cáo", "Tin tức", "Podcast", "Audiobook"];
  
  if (regionTags.includes(tag)) return "bg-sky-50 dark:bg-sky-950/40 border-sky-200/60 dark:border-sky-800/60 text-sky-700 dark:text-sky-400";
  if (ageTags.includes(tag)) return "bg-amber-50 dark:bg-amber-950/40 border-amber-200/60 dark:border-amber-800/60 text-amber-700 dark:text-amber-400";
  if (styleTags.includes(tag)) return "bg-violet-50 dark:bg-violet-950/40 border-violet-200/60 dark:border-violet-800/60 text-violet-700 dark:text-violet-400";
  return "bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200/60 dark:border-zinc-700/60 text-zinc-600 dark:text-zinc-400";
}

interface VoiceLibraryPanelProps {
  onUseVoice: (voiceId: string) => void;
  layout?: "classic" | "modern";
  currentPlayUrl: string | null;
  globalPlayerPlaying: boolean;
  onPlayAudio: (url: string, title: string) => void;
  onTogglePlay: () => void;
  activeVoiceSampleId?: string | null;
}

export const VoiceLibraryPanel: React.FC<VoiceLibraryPanelProps> = ({
  onUseVoice,
  currentPlayUrl,
  globalPlayerPlaying,
  onPlayAudio,
  onTogglePlay,
  activeVoiceSampleId,
}) => {
  const [voices, setVoices] = useState<VoiceSampleResponse[]>([]);
  const [filter, setFilter] = useState<"all" | "private" | "public">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  // Edit modal state
  const [editVoice, setEditVoice] = useState<VoiceSampleResponse | null>(null);
  const [editName, setEditName] = useState("");
  const [editRefText, setEditRefText] = useState("");
  const [editIsPublic, setEditIsPublic] = useState(false);
  const [editTags, setEditTags] = useState<string[]>([]);
  const [editTagInput, setEditTagInput] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editStatus, setEditStatus] = useState<string | null>(null);
  const [showSourceData, setShowSourceData] = useState(false);

  const fetchVoices = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const data = await api.listVoiceSamples();
      setVoices(data);
    } catch (err: any) {
      setErrorMsg(err.message || "Không thể tải danh sách giọng mẫu.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchVoices();
  }, []);

  const handleCopyId = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(id);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteVoiceSample(id);
      setVoices(prev => prev.filter(v => v.id !== id));
      setDeleteConfirmId(null);
    } catch (err: any) {
      alert(`Lỗi khi xóa giọng: ${err.message || "Vui lòng thử lại sau."}`);
    }
  };

  const handleToggleTag = (tag: string) => {
    setSelectedTags(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    );
  };

  // Collect custom tags from voice data that aren't in presets
  const customTagsFromData = useMemo(() => {
    const allTags = new Set<string>();
    voices.forEach(v => {
      if (v.tags) v.tags.forEach(t => allTags.add(t));
    });
    return Array.from(allTags).filter(t => !ALL_PRESET_TAGS.includes(t));
  }, [voices]);

  // Filter and search logic
  const filteredVoices = voices.filter((v) => {
    const matchesSearch =
      (v.name && v.name.toLowerCase().includes(searchQuery.toLowerCase())) ||
      v.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (v.ref_text && v.ref_text.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesTags = selectedTags.length === 0 || selectedTags.every(t => v.tags?.includes(t));

    if (filter === "private") return matchesSearch && matchesTags && !v.is_public;
    if (filter === "public") return matchesSearch && matchesTags && v.is_public;
    return matchesSearch && matchesTags;
  });

  // Edit modal handlers
  const openEditModal = (voice: VoiceSampleResponse) => {
    setEditVoice(voice);
    setEditName(voice.name || "");
    setEditRefText(voice.ref_text || "");
    setEditIsPublic(voice.is_public);
    setEditTags(voice.tags ? [...voice.tags] : []);
    setEditTagInput("");
    setEditStatus(null);
    setShowSourceData(false);
  };

  const closeEditModal = () => {
    setEditVoice(null);
    setEditStatus(null);
  };

  const handleAddEditTag = (tag: string) => {
    const trimmed = tag.trim();
    if (trimmed && !editTags.includes(trimmed)) {
      setEditTags(prev => [...prev, trimmed]);
    }
    setEditTagInput("");
  };

  const handleRemoveEditTag = (tag: string) => {
    setEditTags(prev => prev.filter(t => t !== tag));
  };

  const handleEditSubmit = async () => {
    if (!editVoice) return;
    setIsEditing(true);
    setEditStatus(null);

    try {
      const payload: VoiceSampleUpdateRequest = {
        name: editName,
        tags: editTags,
        ref_text: editRefText,
        is_public: editIsPublic,
      };
      const updated = await api.updateVoiceSample(editVoice.id, payload);
      setVoices(prev => prev.map(v => v.id === updated.id ? updated : v));
      setEditStatus("Cập nhật thành công!");
      setTimeout(() => closeEditModal(), 1200);
    } catch (err: any) {
      setEditStatus(`Lỗi: ${err.message || "Không thể cập nhật."}`);
    } finally {
      setIsEditing(false);
    }
  };

  return (
    <div className="bg-card/75 dark:bg-[#151618]/95 border border-border/80 dark:border-[#2a2b2f]/80 backdrop-blur-md rounded-[var(--radius-card)] p-fluid-card flex flex-col gap-fluid shadow-xl transition-all duration-300">
      {/* Header Info */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-border/60 pb-4">
        <div className="flex flex-col gap-1">
          <h2 className="text-fluid-lg font-bold text-foreground flex items-center gap-2.5">
            <Volume2 className="w-5 h-5 text-primary" />
            <span>Thư viện Giọng nói (Voice Library)</span>
          </h2>
          <p className="text-fluid-sm text-muted-foreground">
            Quản lý các giọng nói được tải lên hoặc sinh từ thiết kế để sử dụng làm mẫu clone giọng.
          </p>
        </div>
      </div>

      {/* Tag Filter Bar */}
      <div className="flex flex-col gap-2.5">
        <div className="flex items-center gap-2 text-[10px] font-bold text-muted-foreground uppercase tracking-wider">
          <Tag className="w-3 h-3" />
          <span>Lọc theo Tag</span>
          {selectedTags.length > 0 && (
            <button
              onClick={() => setSelectedTags([])}
              className="ml-2 px-2 py-0.5 bg-destructive/10 text-destructive rounded-full text-[9px] font-bold cursor-pointer hover:bg-destructive/20 transition-colors border border-destructive/20"
            >
              Xóa bộ lọc ({selectedTags.length})
            </button>
          )}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {PRESET_TAG_GROUPS.map((group) => (
            <React.Fragment key={group.label}>
              {group.tags.map((tag) => (
                <button
                  key={tag}
                  onClick={() => handleToggleTag(tag)}
                  className={`px-2.5 py-1 rounded-full text-[10px] font-bold transition-all cursor-pointer border ${
                    selectedTags.includes(tag)
                      ? `${getTagColor(tag)} border-current shadow-sm`
                      : "bg-secondary/40 border-border/70 text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                  }`}
                >
                  {tag}
                </button>
              ))}
              <div className="w-px bg-border/60 mx-0.5 self-stretch" />
            </React.Fragment>
          ))}
          {/* Custom tags from data */}
          {customTagsFromData.map((tag) => (
            <button
              key={tag}
              onClick={() => handleToggleTag(tag)}
              className={`px-2.5 py-1 rounded-full text-[10px] font-bold transition-all cursor-pointer border ${
                selectedTags.includes(tag)
                  ? "bg-zinc-200 dark:bg-zinc-700 border-zinc-400 dark:border-zinc-500 text-zinc-800 dark:text-zinc-200 shadow-sm"
                  : "bg-secondary/40 border-border/70 text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
              }`}
            >
              {tag}
            </button>
          ))}
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col lg:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-grow">
          <Search className="absolute left-3.5 top-3.5 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Tìm kiếm theo tên, ID, hoặc văn bản tham chiếu..."
            className="w-full pl-10 pr-4 h-10 bg-white dark:bg-[#131416] border border-border/80 dark:border-[#2a2b2f]/80 rounded-full text-fluid-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:border-primary/50 transition-colors font-semibold shadow-inner"
          />
        </div>

        {/* Tab Filters */}
        <div className="flex bg-background/85 dark:bg-[#131416]/85 border border-border/80 dark:border-[#2a2b2f]/80 rounded-full p-1 shrink-0 self-start lg:self-auto">
          <button
            onClick={() => setFilter("all")}
            className={`px-4 py-1.5 rounded-full text-fluid-sm font-bold transition-all cursor-pointer ${
              filter === "all" ? "bg-card dark:bg-[#1f2023] text-foreground shadow-sm border border-border/80 dark:border-[#2d2e33]" : "text-muted-foreground hover:text-foreground border border-transparent"
            }`}
          >
            Tất cả ({voices.length})
          </button>
          <button
            onClick={() => setFilter("private")}
            className={`px-4 py-1.5 rounded-full text-fluid-sm font-bold transition-all cursor-pointer ${
              filter === "private" ? "bg-card dark:bg-[#1f2023] text-foreground shadow-sm border border-border/80 dark:border-[#2d2e33]" : "text-muted-foreground hover:text-foreground border border-transparent"
            }`}
          >
            Cá nhân ({voices.filter(v => !v.is_public).length})
          </button>
          <button
            onClick={() => setFilter("public")}
            className={`px-4 py-1.5 rounded-full text-fluid-sm font-bold transition-all cursor-pointer ${
              filter === "public" ? "bg-card dark:bg-[#1f2023] text-foreground shadow-sm border border-border/80 dark:border-[#2d2e33]" : "text-muted-foreground hover:text-foreground border border-transparent"
            }`}
          >
            Cộng đồng ({voices.filter(v => v.is_public).length})
          </button>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-destructive/10 border border-destructive/20 text-destructive text-xs font-semibold rounded-2xl">
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
          <span className="text-xs font-bold text-muted-foreground">Đang tải danh sách giọng mẫu...</span>
        </div>
      ) : filteredVoices.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-border rounded-3xl text-muted-foreground text-xs font-semibold">
          {searchQuery || selectedTags.length > 0 ? "Không tìm thấy giọng nói khớp với điều kiện tìm kiếm." : "Thư viện giọng nói trống. Hãy tải lên hoặc thiết kế giọng nói để bắt đầu!"}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-fluid">
          {filteredVoices.map((voice) => {
            const audioUrl = `${api.getApiBaseUrl()}/v1/voice-samples/${voice.id}/audio`;
            return (
              <div
                key={voice.id}
                className={`bg-card dark:bg-[#1f2023] border rounded-[var(--radius-card)] p-fluid-card flex flex-col justify-between gap-4 transition-all duration-300 group relative shadow-[0_2px_8px_-3px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_12px_-3px_rgba(0,0,0,0.08)] ${
                  activeVoiceSampleId === voice.id
                    ? "border-primary/60 dark:border-primary/50 shadow-md shadow-primary/5 ring-1 ring-primary/20"
                    : "border-border/80 dark:border-[#2d2e33] hover:border-border/40 dark:hover:border-[#3d3e45]"
                }`}
              >
                {/* Delete Confirm Overlay */}
                {deleteConfirmId === voice.id && (
                  <div className="absolute inset-0 bg-card/98 rounded-[var(--radius-card)] p-fluid-card flex flex-col justify-center items-center gap-3.5 z-10 animate-fadeIn border border-border">
                    <span className="text-fluid-sm font-bold text-center text-foreground leading-normal">
                      Bạn có chắc chắn muốn xóa giọng mẫu "{voice.name || voice.id}"?
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setDeleteConfirmId(null)}
                        className="px-3.5 h-9 bg-muted hover:bg-muted border border-border text-fluid-sm font-bold text-foreground rounded-full cursor-pointer transition-all flex items-center justify-center"
                      >
                        Hủy
                      </button>
                      <button
                        onClick={() => handleDelete(voice.id)}
                        className="px-3.5 h-9 bg-destructive hover:bg-destructive/90 text-fluid-sm font-bold text-white rounded-full cursor-pointer transition-all flex items-center justify-center"
                      >
                        Đồng ý Xóa
                      </button>
                    </div>
                  </div>
                )}

                {/* Top Info */}
                <div className="flex flex-col gap-3">
                  <div className="flex justify-between items-start gap-2">
                    <div className="flex flex-col min-w-0">
                      <span className="font-bold text-fluid-sm text-foreground truncate group-hover:text-foreground transition-colors">
                        {voice.name || "Giọng không tên"}
                      </span>
                      {activeVoiceSampleId === voice.id && (
                        <span className="bg-primary/10 border border-primary/20 text-[9px] font-bold text-primary px-2 py-0.5 rounded-full flex items-center gap-1 mt-1 w-max animate-pulse">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-ping" />
                          <span>Đang dùng</span>
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                      {/* Visibility Badge */}
                      {voice.is_public ? (
                        <span className="bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200/60 dark:border-emerald-800/60 text-[10px] font-bold text-emerald-700 dark:text-emerald-400 px-2 py-0.5 rounded-full flex items-center gap-1 select-none">
                          <Globe className="w-2.5 h-2.5 text-emerald-600 dark:text-emerald-400" />
                          <span>Công khai</span>
                        </span>
                      ) : (
                        <span className="bg-zinc-100 dark:bg-zinc-800/60 border border-zinc-200/80 dark:border-zinc-700/80 text-[10px] font-bold text-zinc-600 dark:text-zinc-300 px-2 py-0.5 rounded-full flex items-center gap-1 select-none">
                          <Lock className="w-2.5 h-2.5 text-zinc-500 dark:text-zinc-400" />
                          <span>Riêng tư</span>
                        </span>
                      )}

                      {/* Source Type Badge */}
                      {voice.source_type === "uploaded" && (
                        <span className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200/60 dark:border-blue-800/60 text-[10px] font-bold text-blue-700 dark:text-blue-400 px-2 py-0.5 rounded-full select-none">
                          Tải lên
                        </span>
                      )}
                      {voice.source_type === "saved_favorite" && (
                        <span className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200/60 dark:border-rose-800/60 text-[10px] font-bold text-rose-700 dark:text-rose-400 px-2 py-0.5 rounded-full select-none">
                          Yêu thích
                        </span>
                      )}
                      {voice.source_type !== "uploaded" && voice.source_type !== "saved_favorite" && (
                        <span className="bg-purple-50 dark:bg-purple-950/40 border border-purple-200/60 dark:border-purple-800/60 text-[10px] font-bold text-purple-700 dark:text-purple-400 px-2 py-0.5 rounded-full select-none">
                          Thiết kế
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Tags */}
                  {voice.tags && voice.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {voice.tags.map((tag) => (
                        <span
                          key={tag}
                          className={`${getTagColor(tag)} border text-[9px] font-bold px-2 py-0.5 rounded-full select-none`}
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* ID row with copy capability */}
                  <div className="flex items-center gap-1.5 text-fluid-xs text-muted-foreground font-mono">
                    <span className="font-bold text-muted-foreground">ID:</span>
                    <span className="truncate max-w-[130px] select-all bg-card border border-border px-2 py-0.5 rounded-md font-bold text-muted-foreground">
                      {voice.id}
                    </span>
                    <button
                      onClick={(e) => handleCopyId(voice.id, e)}
                      className="p-1 hover:bg-muted rounded-md transition-colors text-muted-foreground hover:text-muted-foreground cursor-pointer"
                      title="Sao chép ID"
                    >
                      {copiedId === voice.id ? (
                        <Check className="w-3.5 h-3.5 text-success" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>

                  {/* Ref text section */}
                  {voice.ref_text && (
                    <div className="bg-background/80 dark:bg-[#131416]/90 border border-border/80 dark:border-[#2d2e33]/80 rounded-2xl p-3 max-h-[100px] overflow-y-auto text-fluid-sm text-foreground leading-normal scrollbar-thin">
                      <p className="font-bold text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Văn bản tham khảo</p>
                      {voice.ref_text}
                    </div>
                  )}

                  {voice.duration && (
                    <span className="text-fluid-xs font-bold text-muted-foreground">
                      Thời lượng: {voice.duration.toFixed(1)} giây
                    </span>
                  )}
                </div>

                {/* Bottom Actions */}
                <div className="flex flex-col gap-3 pt-3 border-t border-border">
                  <div className="flex gap-2 mt-1">
                    <button
                      onClick={() => {
                        if (currentPlayUrl === audioUrl) {
                          onTogglePlay();
                        } else {
                          onPlayAudio(audioUrl, voice.name || voice.id);
                        }
                      }}
                      className={`p-2 border rounded-full transition-all cursor-pointer flex items-center justify-center shrink-0 ${
                        currentPlayUrl === audioUrl && globalPlayerPlaying
                          ? "bg-primary text-white border-primary shadow-lg shadow-primary/20"
                          : "border-border hover:border-primary/40 hover:bg-muted text-foreground"
                      }`}
                      title={currentPlayUrl === audioUrl && globalPlayerPlaying ? "Tạm dừng" : "Nghe thử"}
                    >
                      {currentPlayUrl === audioUrl && globalPlayerPlaying ? (
                        <Pause className="w-3.5 h-3.5 fill-current" />
                      ) : (
                        <Play className="w-3.5 h-3.5 fill-current ml-0.5" />
                      )}
                    </button>

                    <button
                      onClick={() => onUseVoice(voice.id)}
                      className="flex-grow h-10 bg-gradient-to-r from-primary to-accent text-white hover:brightness-105 font-bold text-fluid-sm rounded-full transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-md shadow-primary/10 active:scale-[0.98]"
                    >
                      <Sparkles className="w-3.5 h-3.5 fill-current" />
                      <span>Sử dụng giọng này</span>
                    </button>

                    {/* Edit button for user owned voices */}
                    {!voice.is_public && (
                      <button
                        onClick={() => openEditModal(voice)}
                        className="p-2 border border-border hover:border-primary/35 hover:bg-primary/5 text-muted-foreground hover:text-primary rounded-full transition-all cursor-pointer shrink-0"
                        title="Chỉnh sửa"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                    )}

                    {/* Only show delete button for user owned voices */}
                    {!voice.is_public && (
                      <button
                        onClick={() => setDeleteConfirmId(voice.id)}
                        className="p-2 border border-border hover:border-destructive/35 hover:bg-destructive/5 text-muted-foreground hover:text-destructive rounded-full transition-all cursor-pointer shrink-0"
                        title="Xóa khỏi thư viện"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Edit Voice Modal */}
      {editVoice && (
        <div 
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fadeIn p-4 lg:pl-64"
          onClick={closeEditModal}
        >
          <div 
            className="bg-card dark:bg-[#1a1b1e] border border-border/80 dark:border-[#2d2e33] rounded-[var(--radius-card)] p-6 w-full max-w-lg flex flex-col gap-4 relative shadow-2xl max-h-[90vh] overflow-y-auto scrollbar-thin"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={closeEditModal}
              className="absolute top-4 right-4 p-1.5 hover:bg-muted rounded-full text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center gap-3 border-b border-border/60 pb-3">
              <div className="p-2.5 bg-primary/10 rounded-2xl text-primary">
                <Pencil className="w-5 h-5" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-foreground">Chỉnh sửa Giọng mẫu</h3>
                <p className="text-[10px] text-muted-foreground font-semibold">Cập nhật tên, tags, văn bản tham khảo và chế độ chia sẻ</p>
              </div>
            </div>

            {editStatus && (
              <div className={`p-3.5 rounded-2xl text-xs font-semibold border ${editStatus.startsWith("Lỗi") ? "bg-destructive/10 border-destructive/20 text-destructive" : "bg-success/10 border-success/20 text-success"}`}>
                {editStatus}
              </div>
            )}

            <div className="flex flex-col gap-3">
              {/* Name */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Tên giọng mẫu</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Ví dụ: Giọng nữ trầm ấm..."
                  className="bg-background border border-border focus:border-primary/50 rounded-2xl p-3 text-xs text-foreground focus:outline-none font-semibold transition-all duration-200"
                />
              </div>

              {/* Tags */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Tags phân loại</label>
                {/* Preset tag pills */}
                <div className="flex flex-wrap gap-1.5">
                  {ALL_PRESET_TAGS.map((tag) => (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => {
                        if (editTags.includes(tag)) {
                          handleRemoveEditTag(tag);
                        } else {
                          handleAddEditTag(tag);
                        }
                      }}
                      className={`px-2 py-0.5 rounded-full text-[10px] font-bold transition-all cursor-pointer border ${
                        editTags.includes(tag)
                          ? `${getTagColor(tag)} border-current shadow-sm`
                          : "bg-secondary/40 border-border/70 text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
                {/* Current custom tags */}
                {editTags.filter(t => !ALL_PRESET_TAGS.includes(t)).length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {editTags.filter(t => !ALL_PRESET_TAGS.includes(t)).map((tag) => (
                      <span
                        key={tag}
                        className="bg-zinc-100 dark:bg-zinc-800 border border-zinc-300 dark:border-zinc-600 text-[10px] font-bold text-foreground px-2 py-0.5 rounded-full flex items-center gap-1"
                      >
                        {tag}
                        <button
                          onClick={() => handleRemoveEditTag(tag)}
                          className="hover:text-destructive cursor-pointer"
                        >
                          <X className="w-2.5 h-2.5" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                {/* Custom tag input */}
                <div className="flex gap-2 mt-1">
                  <input
                    type="text"
                    value={editTagInput}
                    onChange={(e) => setEditTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddEditTag(editTagInput);
                      }
                    }}
                    placeholder="Thêm tag tùy chỉnh, nhấn Enter..."
                    className="flex-grow bg-background border border-border focus:border-primary/50 rounded-full px-3 py-1.5 text-[10px] text-foreground focus:outline-none font-semibold transition-all"
                  />
                  <button
                    type="button"
                    onClick={() => handleAddEditTag(editTagInput)}
                    disabled={!editTagInput.trim()}
                    className="px-3 py-1.5 bg-muted hover:bg-muted/80 border border-border text-[10px] font-bold text-foreground rounded-full cursor-pointer transition-colors disabled:opacity-50"
                  >
                    Thêm
                  </button>
                </div>
              </div>

              {/* Ref Text */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Văn bản tham khảo</label>
                <textarea
                  value={editRefText}
                  onChange={(e) => setEditRefText(e.target.value)}
                  placeholder="Nhập phần chữ tương ứng với đoạn nói đầu tiên..."
                  rows={2}
                  className="bg-background border border-border focus:border-primary/50 rounded-2xl p-3 text-xs text-foreground focus:outline-none resize-none font-semibold transition-all duration-200"
                />
              </div>

              {/* Visibility */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Chế độ chia sẻ</label>
                <div className="grid grid-cols-2 gap-2 bg-background p-1.5 rounded-2xl border border-border/60">
                  <button
                    type="button"
                    onClick={() => setEditIsPublic(false)}
                    className={`py-2 px-1 text-center font-bold text-xs rounded-full transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                      !editIsPublic
                        ? "bg-muted text-foreground border border-border shadow-sm"
                        : "text-muted-foreground hover:text-muted-foreground"
                    }`}
                  >
                    <Lock className="w-3.5 h-3.5" />
                    <span>Riêng tư</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditIsPublic(true)}
                    className={`py-2 px-1 text-center font-bold text-xs rounded-full transition-all cursor-pointer flex items-center justify-center gap-1.5 ${
                      editIsPublic
                        ? "bg-muted text-foreground border border-border shadow-sm"
                        : "text-muted-foreground hover:text-muted-foreground"
                    }`}
                  >
                    <Globe className="w-3.5 h-3.5" />
                    <span>Công khai</span>
                  </button>
                </div>
              </div>

              {/* Source Job Data (read-only, collapsible) */}
              {editVoice.source_job_data && (
                <div className="flex flex-col gap-1.5">
                  <button
                    type="button"
                    onClick={() => setShowSourceData(!showSourceData)}
                    className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground uppercase tracking-wider cursor-pointer hover:text-foreground transition-colors"
                  >
                    <Info className="w-3 h-3" />
                    <span>Thông số gốc từ OmniVoice</span>
                    {showSourceData ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showSourceData && (
                    <div className="bg-background/80 dark:bg-[#131416]/90 border border-border/80 dark:border-[#2d2e33]/80 rounded-2xl p-3 text-[10px] font-mono text-muted-foreground overflow-x-auto max-h-[200px] overflow-y-auto scrollbar-thin">
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                        {Object.entries(editVoice.source_job_data).map(([key, value]) => (
                          <React.Fragment key={key}>
                            <span className="font-bold text-foreground/60 truncate">{key}</span>
                            <span className="text-foreground truncate" title={String(value ?? "—")}>
                              {value !== null && value !== undefined ? String(value) : "—"}
                            </span>
                          </React.Fragment>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex gap-2 justify-end mt-2 pt-3 border-t border-border">
              <button
                type="button"
                onClick={closeEditModal}
                className="px-5 py-2.5 bg-muted hover:bg-muted border border-border text-xs font-semibold text-foreground rounded-lg cursor-pointer transition-colors"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleEditSubmit}
                disabled={isEditing || !editName}
                className="px-5 py-2.5 bg-gradient-to-r from-primary to-accent hover:brightness-105 disabled:bg-muted disabled:text-muted-foreground text-xs font-bold text-white rounded-lg cursor-pointer transition-colors shadow-md shadow-primary/10 border-none"
              >
                {isEditing ? "Đang lưu..." : "Lưu thay đổi"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
