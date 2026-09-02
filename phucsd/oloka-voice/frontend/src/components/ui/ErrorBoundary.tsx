import { Component, type ReactNode, type ErrorInfo } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error caught by ErrorBoundary:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="w-full p-6 bg-destructive/10 border border-destructive/20 rounded-2xl flex flex-col gap-4 text-foreground shadow-sm">
          <div className="flex items-start gap-3">
            <div className="p-2 bg-destructive/20 text-destructive rounded-xl shrink-0">
              <AlertCircle className="w-6 h-6" />
            </div>
            <div className="flex flex-col gap-1">
              <h3 className="font-bold text-base text-destructive">
                {this.props.fallbackTitle || "Đã xảy ra lỗi khi hiển thị giao diện"}
              </h3>
              <p className="text-xs text-muted-foreground leading-relaxed">
                {this.state.error?.message || "Lỗi không xác định trong quá trình xử lý dữ liệu."}
              </p>
            </div>
          </div>
          
          <div className="flex justify-end gap-3 pt-2 border-t border-destructive/10">
            <button
              type="button"
              onClick={this.handleReset}
              className="px-4 py-2 bg-destructive text-white font-bold text-xs rounded-xl hover:bg-destructive/90 transition-colors flex items-center gap-2 cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Thử lại</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
