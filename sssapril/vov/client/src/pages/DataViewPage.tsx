import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeftIcon, ExpandIcon, ShrinkIcon } from 'lucide-react';
import RenderEngine from '../render-engine/RenderEngine';
import type { RenderSpec } from '../render-engine/types';

/**
 * 独立数据展示页面
 *
 * 提供大片空白画布用于展示 RenderEngine 渲染的数据视图。
 * 通过 URL search params 传递 render_spec 配置，
 * 或从 sessionStorage 中读取由聊天区传递的渲染配置。
 */
export default function DataViewPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [spec, setSpec] = useState<RenderSpec | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    // 优先从 URL params 读取（base64 编码的 render_spec）
    const specParam = searchParams.get('spec');
    if (specParam) {
      try {
        const decoded = JSON.parse(atob(specParam));
        setSpec(decoded);
        return;
      } catch {
        // 解码失败，尝试其他方式
      }
    }

    // 从 sessionStorage 读取
    const stored = sessionStorage.getItem('data_view_spec');
    if (stored) {
      try {
        setSpec(JSON.parse(stored));
        sessionStorage.removeItem('data_view_spec');
        return;
      } catch {
        // 解析失败
      }
    }
  }, [searchParams]);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  };

  if (!spec) {
    return (
      <div className="min-h-screen newspaper-bg font-newspaper flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground mb-3">未指定数据展示配置</p>
          <button
            onClick={() => navigate(-1)}
            className="text-primary text-sm hover:underline"
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen newspaper-bg font-newspaper">
      {/* 顶部导航 */}
      <header className="sticky top-0 z-10 newspaper-bg border-b-2 border-double border-current">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate(-1)}
              className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeftIcon className="w-4 h-4" />
              返回
            </button>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm font-bold font-newspaper truncate max-w-64">
              {spec.title || '数据展示'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleFullscreen}
              className="flex items-center gap-1.5 border border-current px-3 py-1.5 text-xs transition-opacity hover:opacity-80"
            >
              {isFullscreen ? <ShrinkIcon className="w-3.5 h-3.5" /> : <ExpandIcon className="w-3.5 h-3.5" />}
              {isFullscreen ? '退出全屏' : '全屏'}
            </button>
          </div>
        </div>
      </header>

      {/* 主内容区 - 大片空白画布 */}
      <main className="max-w-[1600px] mx-auto px-6 py-6">
        <RenderEngine spec={spec} className="min-h-[calc(100vh-120px)]" />
      </main>
    </div>
  );
}

/**
 * 工具函数：从聊天区跳转到数据展示页
 * 在 ChatPage 或其他地方调用此函数，将 render_spec 传递到独立页面
 */
export function navigateToDataView(spec: RenderSpec) {
  sessionStorage.setItem('data_view_spec', JSON.stringify(spec));
  window.open('/data-view', '_blank');
}
