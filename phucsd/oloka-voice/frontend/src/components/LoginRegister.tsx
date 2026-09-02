import React, { useState, useEffect } from "react";
import { Radio, ShieldAlert, CheckCircle2, ArrowRight } from "lucide-react";
import { api } from "../api/client";

interface LoginRegisterProps {
  onLoginSuccess: (token: string) => void;
}

const GoogleIcon = ({ className = "w-5 h-5" }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
    <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z" />
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z" />
  </svg>
);

export const LoginRegister: React.FC<LoginRegisterProps> = ({ onLoginSuccess }) => {
  const apiBaseUrl = api.getApiBaseUrl();

  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Handle Google OAuth Callback (code exchange)
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get("code");
    if (code) {
      const redirectUri = window.location.origin + window.location.pathname;
      setLoading(true);
      setErrorMsg(null);
      // Clean query code from URL
      window.history.replaceState({}, document.title, window.location.pathname);
      
      api.oauthCallback("google", code, redirectUri)
        .then((res) => {
          localStorage.setItem("VITE_JWT_TOKEN", res.access_token);
          onLoginSuccess(res.access_token);
        })
        .catch((err: any) => {
          const msg = err.message || "";
          if (msg.includes("chưa được duyệt") || msg.includes("chưa xác thực")) {
            setErrorMsg("Tài khoản Google của bạn đã được đăng ký nhưng hiện đang ở trạng thái chờ Admin phê duyệt.");
          } else {
            setErrorMsg(msg || "Lỗi xác thực OAuth từ Google.");
          }
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [onLoginSuccess]);

  const handleGoogleLogin = async () => {
    setErrorMsg(null);
    setSuccessMsg(null);
    setLoading(true);

    const redirectUri = window.location.origin + window.location.pathname;
    try {
      // Direct redirect to real Google OAuth
      const res = await api.oauthLogin("google", redirectUri);
      if (res && res.auth_url) {
        window.location.href = res.auth_url;
        return;
      }
      setErrorMsg("Không thể nhận liên kết đăng nhập Google từ hệ thống.");
    } catch (err: any) {
      console.warn("Real Google OAuth error:", err);
      const msg = err.message || "";
      setErrorMsg(msg || "Không thể khởi tạo đăng nhập Google.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex items-center justify-center p-6 relative overflow-hidden font-sans">
      {/* Dynamic blurred background elements */}
      <div className="absolute top-1/4 left-1/4 w-[350px] h-[350px] bg-primary/10 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-[450px] h-[450px] bg-purple-600/10 rounded-full blur-[130px] pointer-events-none" />

      <div className="w-full max-w-md bg-card/70 backdrop-blur-md border border-border rounded-[32px] p-8 flex flex-col gap-6 shadow-[0_20px_50px_rgba(0,0,0,0.5)] relative z-10">
        
        {/* Header/Logo */}
        <div className="flex flex-col items-center gap-3 text-center select-none mb-1">
          <div className="bg-muted p-3 rounded-2xl border border-border shadow-md">
            <Radio className="w-8 h-8 text-primary" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-foreground mt-1">
            OmniVoice Gateway
          </h1>
          <p className="text-xs text-muted-foreground">
            Hệ thống quản lý và sinh giọng nói nhân bản AI (voice.oloka.net)
          </p>
        </div>

        {/* Main Google Login Banner & Button */}
        <div className="flex flex-col gap-5">
          {/* Info Banner */}
          <div className="p-4 bg-muted/50 border border-border/80 rounded-2xl text-xs leading-relaxed flex flex-col gap-1.5 text-muted-foreground">
            <div className="flex items-center gap-2 text-foreground font-bold">
              <ShieldAlert className="w-4 h-4 text-primary shrink-0" />
              <span>Chính sách xác thực mới</span>
            </div>
            <p className="text-[11px] text-muted-foreground">
              Hệ thống <strong>voice.oloka.net</strong> bắt buộc xác thực qua tài khoản Google. Tài khoản mới sau khi đăng ký bằng Google sẽ được đưa vào hàng chờ Admin phê duyệt.
            </p>
          </div>

          {/* Status messages */}
          {errorMsg && (
            <div className="p-3.5 bg-destructive/10 border border-destructive/20 text-destructive rounded-2xl text-xs leading-relaxed flex items-start gap-2 animate-fadeIn">
              <ShieldAlert className="w-4 h-4 text-destructive flex-shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}
          {successMsg && (
            <div className="p-3.5 bg-success/10 border border-success/20 text-success rounded-2xl text-xs leading-relaxed flex items-start gap-2 animate-fadeIn">
              <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* Exclusive Google Sign-In Button */}
          <button
            type="button"
            onClick={handleGoogleLogin}
            disabled={loading}
            className={`w-full py-4 px-6 rounded-full font-bold text-sm transition-all flex items-center justify-center gap-3 cursor-pointer shadow-lg active:scale-[0.99] border ${
              !loading
                ? "bg-white text-gray-900 border-gray-200 hover:bg-gray-50 shadow-white/10 hover:shadow-xl"
                : "bg-muted text-muted-foreground border-transparent cursor-not-allowed"
            }`}
          >
            <GoogleIcon className="w-5 h-5 shrink-0" />
            <span>{loading ? "Đang kết nối Google..." : "Đăng nhập bằng Google"}</span>
            <ArrowRight className="w-4 h-4 ml-auto text-gray-400" />
          </button>

          {/* Public Docs Link */}
          <div className="flex justify-center mt-1">
            <a
              href="#/docs"
              className="text-[11px] font-bold text-primary hover:text-primary-hover hover:underline flex items-center gap-1.5 transition-all"
            >
              <span>Xem tài liệu API công khai</span>
              <ArrowRight className="w-3 h-3" />
            </a>
          </div>

          {/* API URL Info */}
          <div className="mt-2 pt-4 border-t border-border flex items-center justify-between text-[10px] text-muted-foreground font-semibold select-none">
            <span>API Gateway</span>
            <span className="font-mono text-primary bg-background px-2.5 py-0.5 rounded-full select-all">
              {apiBaseUrl}
            </span>
          </div>
        </div>

      </div>
    </div>
  );
};
