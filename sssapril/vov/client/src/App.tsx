import React, { Suspense, lazy } from 'react';
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster, toast } from 'sonner';
import ThemeInitializer from './components/ThemeInitializer';
import FontPreload from './components/FontPreload';
import { UniversalChat } from './components/UniversalChat';
import { useViewFromHash, clearViewHash } from './hooks/useViewFromHash';
import RenderEngine from './render-engine/RenderEngine';

// 路由懒加载
const Index = lazy(() => import("./pages/Index"));
const ProjectPage = lazy(() => import("./pages/ProjectPage"));
const ChatPage = lazy(() => import("./pages/ChatPage"));
const AgentsPage = lazy(() => import("./pages/AgentsPage"));
const ToolsPage = lazy(() => import("./pages/ToolsPage"));
const SkillsPage = lazy(() => import("./pages/SkillsPage"));
const DataViewPage = lazy(() => import("./pages/DataViewPage"));
const RenderDemoPage = lazy(() => import("./pages/RenderDemoPage"));
const MapEditorPage = lazy(() => import("./pages/MapEditorPage"));
const WorkbenchPage = lazy(() => import("./pages/WorkbenchPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const NotFound = lazy(() => import("./pages/NotFound"));

/**
 * 配置QueryClient
 *
 * 设置默认的查询选项：
 * - staleTime: 数据缓存时间（5分钟）
 * - retry: 失败重试次数（1次）
 * - refetchOnWindowFocus: 窗口聚焦时不自动刷新
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.log('[ErrorBoundary] caught:', error);
    toast.error(`页面发生错误，请刷新重试`);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-background flex items-center justify-center">
          <div className="text-center max-w-sm">
            <div className="text-4xl mb-4">⚠️</div>
            <p className="text-lg font-semibold text-foreground mb-2">出现了一点问题</p>
            <p className="text-sm text-muted-foreground mb-6">页面遇到了意外错误，请刷新页面重试</p>
            <button
              onClick={() => { this.setState({ hasError: false }); window.location.href = '/'; }}
              className="px-5 py-2 bg-primary text-primary-foreground rounded-xl text-sm font-medium hover:opacity-90 transition-opacity"
            >
              返回首页
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const PageLoader = () => (
  <div className="min-h-screen bg-background flex items-center justify-center">
    <div className="animate-pulse text-muted-foreground text-sm">加载中...</div>
  </div>
);

const App = () => {
  // URL hash 中的 RenderSpec —— 有值时主区域渲染 agent 生成的视图，无值时显示默认路由
  const viewSpec = useViewFromHash();

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ErrorBoundary>
          <ThemeInitializer />
          <FontPreload />
          {viewSpec ? (
            <main className="min-h-screen bg-background">
              <div className="flex items-center justify-between border-b px-4 py-2">
                <span className="text-xs text-muted-foreground">agent 渲染视图</span>
                <button
                  onClick={clearViewHash}
                  className="text-xs text-primary hover:underline"
                >
                  ← 返回
                </button>
              </div>
              <div className="p-4">
                <RenderEngine spec={viewSpec} />
              </div>
            </main>
          ) : (
            <Suspense fallback={<PageLoader />}>
              <Routes>
                <Route path="/" element={<Index />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/tools" element={<ToolsPage />} />
                <Route path="/skills" element={<SkillsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/project/:projectId" element={<ProjectPage />} />
                <Route path="/project/:projectId/chat/:groupId" element={<ChatPage />} />
                <Route path="/data-view" element={<DataViewPage />} />
                <Route path="/render-demo" element={<RenderDemoPage />} />
                <Route path="/map-editor" element={<MapEditorPage />} />
                <Route path="/workbench" element={<WorkbenchPage />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          )}
          {/* 全局召唤的通用对话侧边栏（Cmd+K 收放），挂在路由外层常驻 */}
          <UniversalChat />
        </ErrorBoundary>
      </BrowserRouter>
      <Toaster position="top-right" />
    </QueryClientProvider>
  );
};

export default App;
