import React, { useState, useEffect } from "react";
import { KeyRound, Copy, Trash2, Eye, EyeOff, Check, RefreshCw, ShieldCheck, X, BookOpen } from "lucide-react";
import { api } from "../api/client";
import type { ApiKeyResponse } from "../api/client";

interface ApiKeyPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigateToDocs: () => void;
}

export const ApiKeyPanel: React.FC<ApiKeyPanelProps> = ({ isOpen, onClose, onNavigateToDocs }) => {
  const [apiKeys, setApiKeys] = useState<ApiKeyResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [creatingKey, setCreatingKey] = useState(false);
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null);

  const fetchApiKeys = async () => {
    setLoading(true);
    try {
      const res = await api.getUserApiKeys();
      setApiKeys(res);
    } catch (err) {
      console.error("Lỗi lấy danh sách API Keys:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchApiKeys();
    }
  }, [isOpen]);

  const handleCreateApiKey = async () => {
    setCreatingKey(true);
    try {
      // Auto-generate name based on date-time
      const now = new Date();
      const formattedDate = `${String(now.getDate()).padStart(2, "0")}/${String(now.getMonth() + 1).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
      const autoName = `Khóa API - ${formattedDate}`;
      
      const newKey = await api.createUserApiKey(autoName);
      // Automatically make it visible so they can copy it immediately
      setVisibleKeys((prev) => ({ ...prev, [newKey.id]: true }));
      await fetchApiKeys();
    } catch (err: any) {
      alert("Lỗi tạo API Key: " + err.message);
    } finally {
      setCreatingKey(false);
    }
  };

  const handleDeleteApiKey = async (keyId: string) => {
    if (!window.confirm("Bạn có chắc chắn muốn xóa API Key này không? Mọi tích hợp bên ngoài dùng key này sẽ ngừng hoạt động.")) return;
    try {
      await api.deleteUserApiKey(keyId);
      await fetchApiKeys();
    } catch (err: any) {
      alert("Lỗi xóa API Key: " + err.message);
    }
  };

  const handleCopyKey = (keyId: string, keyValue: string) => {
    navigator.clipboard.writeText(keyValue);
    setCopiedKeyId(keyId);
    setTimeout(() => setCopiedKeyId(null), 2000);
  };



  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 lg:pl-64 animate-fadeIn"
      onClick={onClose}
    >
      <div 
        className="bg-card border border-border rounded-3xl p-6 max-w-2xl w-full flex flex-col gap-4 shadow-2xl relative animate-fadeIn max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute right-5 top-5 text-muted-foreground hover:text-foreground cursor-pointer"
          title="Đóng"
        >
          <X className="w-4.5 h-4.5" />
        </button>

        <div className="flex items-center gap-3 border-b border-border pb-3">
          <div className="bg-primary/10 p-2 rounded-xl text-primary">
            <KeyRound className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-foreground text-sm">Quản lý API Keys &amp; Tài liệu Tích hợp</h3>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Tạo tự động các khóa API và xem hướng dẫn chi tiết cách nhúng giọng nói nhân bản AI.
            </p>
          </div>
        </div>

        {/* API Keys Table & Generation Card */}
        <div className="bg-background border border-border rounded-xl p-4 flex flex-col gap-3.5 shadow-inner">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-primary">
              <ShieldCheck className="w-4.5 h-4.5" />
              <h4 className="font-bold text-xs text-foreground">Danh sách mã API Key của bạn</h4>
            </div>
            <button
              type="button"
              onClick={handleCreateApiKey}
              disabled={creatingKey}
              className="bg-gradient-to-r from-primary to-accent hover:brightness-105 text-white font-bold text-xs px-4 py-2 rounded-lg cursor-pointer transition-colors shadow-md shadow-primary/10 disabled:opacity-50 flex items-center gap-1.5"
            >
              <PlusIcon className="w-3.5 h-3.5" />
              <span>{creatingKey ? "Đang sinh khóa..." : "Tạo API Key mới"}</span>
            </button>
          </div>
          
          <p className="text-[11px] text-muted-foreground leading-relaxed -mt-1.5">
            API Key được cấp quyền truy cập đầy đủ các endpoint tạo âm thanh nhân bản. Vui lòng bảo mật các khóa này, không chia sẻ lên mã nguồn công khai.
          </p>

          <div className="overflow-x-auto">
            {loading && apiKeys.length === 0 ? (
              <div className="text-center py-4 text-muted-foreground text-xs flex items-center justify-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-primary" />
                <span>Đang tải các khóa...</span>
              </div>
            ) : apiKeys.length > 0 ? (
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-border text-muted-foreground text-[10px] uppercase font-semibold">
                    <th className="py-2 px-1">Tên khóa</th>
                    <th className="py-2 px-1">Mã khóa API</th>
                    <th className="py-2 px-1">Ngày tạo</th>
                    <th className="py-2 px-1">Sử dụng cuối</th>
                    <th className="py-2 px-1 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody>
                  {apiKeys.map((k) => (
                    <tr key={k.id} className="border-b border-border/60 hover:bg-card/20">
                      <td className="py-2.5 px-1 font-bold text-foreground truncate max-w-[140px]">{k.name}</td>
                      <td className="py-2.5 px-1 font-mono text-[11px] text-primary/90">
                        <div className="flex items-center gap-1.5">
                          <span className="max-w-[180px] truncate block select-all" title={k.key}>
                            {visibleKeys[k.id] ? k.key : (k.key.length > 12 ? `${k.key.substring(0, 8)}••••${k.key.substring(k.key.length - 4)}` : k.key)}
                          </span>
                          <button
                            type="button"
                            onClick={() => setVisibleKeys({ ...visibleKeys, [k.id]: !visibleKeys[k.id] })}
                            className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
                            title={visibleKeys[k.id] ? "Ẩn" : "Hiện"}
                          >
                            {visibleKeys[k.id] ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                          </button>
                        </div>
                      </td>
                      <td className="py-2.5 px-1 text-muted-foreground text-[11px]">
                        {new Date(k.created_at).toLocaleDateString("vi-VN")}
                      </td>
                      <td className="py-2.5 px-1 text-muted-foreground text-[11px]">
                        {k.last_used_at ? new Date(k.last_used_at).toLocaleDateString("vi-VN") : "Chưa hoạt động"}
                      </td>
                      <td className="py-2.5 px-1 text-right">
                        <div className="flex justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => handleCopyKey(k.id, k.key)}
                            className="p-1.5 hover:bg-muted text-muted-foreground hover:text-foreground rounded-lg cursor-pointer transition-colors"
                            title="Sao chép API Key"
                          >
                            {copiedKeyId === k.id ? (
                              <Check className="w-3.5 h-3.5 text-success" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteApiKey(k.id)}
                            className="p-1.5 hover:bg-destructive/10 text-muted-foreground hover:text-destructive rounded-lg cursor-pointer transition-colors"
                            title="Thu hồi khóa"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-6 text-muted-foreground text-[11px]">
                Bạn chưa có API Key nào. Bấm nút "Tạo API Key mới" ở góc phải để tạo tự động.
              </div>
            )}
          </div>
        </div>

        {/* Integration Documentation Card Redirect */}
        <div className="bg-background border border-border rounded-xl p-4 flex items-center justify-between gap-4 animate-fadeIn">
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-xs font-bold text-foreground truncate">Bạn muốn nhúng giọng nói AI vào hệ thống?</span>
            <span className="text-[11px] text-muted-foreground">
              Hãy xem tài liệu tích hợp chi tiết có kèm mã nguồn mẫu cURL, Python, NodeJS.
            </span>
          </div>
          <button
            type="button"
            onClick={onNavigateToDocs}
            className="bg-gradient-to-r from-primary to-accent hover:brightness-105 text-white font-bold text-xs px-4 py-2 rounded-lg cursor-pointer transition-colors shrink-0 flex items-center gap-1 shadow-md shadow-primary/10"
          >
            <BookOpen className="w-3.5 h-3.5" />
            <span>Xem Tài liệu</span>
          </button>
        </div>
      </div>
    </div>
  );
};

const PlusIcon = ({ className }: { className?: string }) => (
  <svg
    className={className}
    fill="none"
    stroke="currentColor"
    viewBox="0 0 24 24"
    xmlns="http://www.w3.org/2050/svg"
  >
    <path
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      d="M12 4v16m8-8H4"
    ></path>
  </svg>
);
