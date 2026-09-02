import React, { useState, useEffect } from "react";
import { Settings, X, HelpCircle } from "lucide-react";
import { api } from "../api/client";
import type { SystemSettings } from "../api/client";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onStatusChange?: (status: "unconfigured" | "connected" | "error") => void;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ isOpen, onClose, onStatusChange }) => {
  const [config, setConfig] = useState<SystemSettings | null>(null);
  const [username, setUsername] = useState("");
  const [key, setKey] = useState("");
  
  const [loading, setLoading] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [pushingNotebook, setPushingNotebook] = useState(false);

  const [connectionResult, setConnectionResult] = useState<{ success: boolean; message: string } | null>(null);
  const [pushResult, setPushResult] = useState<{ success: boolean; message: string; url?: string } | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const res = await api.getSettings();
      setConfig(res);
      setUsername(res.kaggle_username);
      
      // Determine status
      if (onStatusChange) {
        if (!res.kaggle_username || !res.kaggle_key_configured) {
          onStatusChange("unconfigured");
        } else {
          onStatusChange("connected");
        }
      }
    } catch (err: any) {
      console.error("Lỗi tải cấu hình:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchSettings();
    }
  }, [isOpen]);

  const handleAutoSave = async (field: "username" | "key", val: string) => {
    const payload: any = {};
    if (field === "username") {
      payload.kaggle_username = val.trim();
    } else {
      if (!val.trim()) return;
      payload.kaggle_key = val.trim();
    }

    try {
      await api.updateSettings(payload);
      // Reload configurations
      const res = await api.getSettings();
      setConfig(res);
      if (field === "key") setKey(""); // Clear key input value

      if (onStatusChange) {
        if (!res.kaggle_username || !res.kaggle_key_configured) {
          onStatusChange("unconfigured");
        } else {
          onStatusChange("connected");
        }
      }
    } catch (err: any) {
      console.error("Auto-save failed:", err);
    }
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setConnectionResult(null);
    try {
      const res = await api.testKaggleConnection();
      setConnectionResult(res);
      if (onStatusChange) {
        onStatusChange(res.success ? "connected" : "error");
      }
    } catch (err: any) {
      setConnectionResult({
        success: false,
        message: err.message || "Không thể kết nối đến máy chủ API hoặc lệnh kiểm tra thất bại.",
      });
      if (onStatusChange) {
        onStatusChange("error");
      }
    } finally {
      setTestingConnection(false);
    }
  };

  const handlePushNotebook = async () => {
    setPushingNotebook(true);
    setPushResult(null);
    setConnectionResult(null);
    try {
      const res = await api.pushNotebook();
      setPushResult(res);
      if (onStatusChange) {
        onStatusChange(res.success ? "connected" : "error");
      }
    } catch (err: any) {
      setPushResult({
        success: false,
        message: err.message || "Lỗi hệ thống khi đẩy notebook lên Kaggle.",
      });
      if (onStatusChange) {
        onStatusChange("error");
      }
    } finally {
      setPushingNotebook(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50 p-4 lg:pl-64 animate-fadeIn"
      onClick={onClose}
    >
      <div 
        className="bg-card border border-border rounded-3xl p-6 max-w-lg w-full flex flex-col gap-4 shadow-2xl relative animate-fadeIn max-h-[90vh] overflow-y-auto"
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
            <Settings className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-bold text-foreground text-sm">Cấu hình Kết nối Máy chủ Kaggle</h3>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              Tài khoản Kaggle Credentials được tự động lưu sau khi nhập để kích hoạt máy chủ dịch vụ GPU.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {/* Instructions */}
          <div className="bg-primary/15 border border-primary/25 rounded-xl p-3 flex flex-col gap-2.5 shadow-inner">
            <div className="flex items-center gap-2 text-primary">
              <HelpCircle className="w-4 h-4 flex-shrink-0" />
              <h4 className="font-semibold text-xs text-foreground">Cách lấy cấu hình kết nối Kaggle</h4>
            </div>
            <div className="text-[10px] text-muted-foreground space-y-1.5">
              <p className="leading-relaxed">
                1. Truy cập{" "}
                <a
                  href="https://www.kaggle.com/settings"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:text-primary/90 font-bold underline inline-flex items-center gap-0.5"
                >
                  Kaggle Settings
                </a>{" "}
                và bấm <strong>Create New Token</strong> trong mục API để tải về file <code className="text-warning font-mono">kaggle.json</code>.
              </p>
              <p className="leading-relaxed">
                2. Sao chép giá trị <code className="text-primary/90 font-mono">username</code> dán vào ô bên dưới.
              </p>
              <p className="leading-relaxed">
                3. Sao chép giá trị <code className="text-primary/90 font-mono">key</code> dán vào ô API Key.
              </p>
            </div>
          </div>

          {/* Form fields */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            {/* Username */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Kaggle Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onBlur={() => handleAutoSave("username", username)}
                placeholder="Nhập username..."
                className="bg-background border border-border rounded-lg p-2.5 text-xs text-foreground focus:outline-none focus:border-primary transition-colors"
                required
              />
            </div>

            {/* API Key */}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-muted-foreground">Kaggle API Key</label>
                {config?.kaggle_key_configured && (
                  <span className="text-[10px] text-success font-bold flex items-center gap-0.5">
                    ✓ Đã thiết lập
                  </span>
                )}
              </div>
              <input
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                onBlur={() => handleAutoSave("key", key)}
                placeholder={config?.kaggle_key_configured ? "•••••••••••••••• (Nhập mới tự lưu)" : "Nhập API Key..."}
                className="bg-background border border-border rounded-lg p-2.5 text-xs text-foreground focus:outline-none focus:border-primary transition-colors"
                required={!config?.kaggle_key_configured}
              />
            </div>
          </div>

          {connectionResult && (
            <div
              className={`p-3 rounded-lg text-xs border flex items-start gap-1.5 ${
                connectionResult.success
                  ? "bg-success/10 border-success/20 text-success"
                  : "bg-destructive/10 border-destructive/20 text-destructive"
              }`}
            >
              {connectionResult.success ? (
                <span className="text-success font-bold">✓</span>
              ) : (
                <span className="text-destructive font-bold">✗</span>
              )}
              <span className="break-all">{connectionResult.message}</span>
            </div>
          )}

          {pushResult && (
            <div
              className={`p-4 rounded-xl text-xs border flex flex-col gap-2.5 ${
                pushResult.success
                  ? "bg-primary/10 border-primary/20 text-primary/90"
                  : "bg-destructive/10 border-destructive/20 text-destructive"
              }`}
            >
              <div className="flex items-start gap-1.5">
                {pushResult.success ? (
                  <span className="text-success font-bold">✓</span>
                ) : (
                  <span className="text-destructive font-bold">✗</span>
                )}
                <span className="break-all font-medium">{pushResult.message}</span>
              </div>
              {pushResult.success && pushResult.url && (
                <p className="text-[10px] text-muted-foreground leading-relaxed bg-background p-2.5 border border-border rounded-lg">
                  Notebook đã được đẩy thành công lên Kaggle. Hệ thống tự động đẩy-và-chạy batch job khi bạn thực hiện TTS.
                </p>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center justify-between gap-3 mt-2 border-t border-border pt-3.5">
            <button
              type="button"
              onClick={handleTestConnection}
              disabled={testingConnection || loading || pushingNotebook}
              className="flex-grow flex items-center justify-center gap-1.5 bg-muted hover:bg-muted text-foreground hover:text-foreground font-bold text-xs px-4 py-2.5 rounded-lg transition-colors cursor-pointer border border-border/80 disabled:opacity-55 disabled:cursor-not-allowed"
            >
              {testingConnection ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Đang kết nối...</span>
                </>
              ) : (
                <span>Kiểm tra kết nối</span>
              )}
            </button>

            <button
              type="button"
              onClick={handlePushNotebook}
              disabled={pushingNotebook || loading || testingConnection}
              className="flex-grow flex items-center justify-center gap-1.5 bg-primary/20 hover:bg-primary/30 text-primary hover:text-primary/90 font-bold text-xs px-4 py-2.5 rounded-lg transition-colors cursor-pointer border border-primary/20 disabled:opacity-55 disabled:cursor-not-allowed"
            >
              {pushingNotebook ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Đang đẩy notebook...</span>
                </>
              ) : (
                <span>Đẩy Notebook lên Kaggle</span>
              )}
            </button>
          </div>
        </div>
      </div>
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
