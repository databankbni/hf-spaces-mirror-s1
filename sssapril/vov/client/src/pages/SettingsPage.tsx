/**
 * 设置页面 — 报纸风格
 *
 * LLM 配置、数据存储、关于信息。
 * 首次使用时作为 Onboarding 引导页。
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { ArrowLeftIcon, EyeIcon, EyeOffIcon, Loader2Icon, CheckCircleIcon, PaletteIcon, MessageSquareIcon } from 'lucide-react';
import { useLLMSettings, useUpdateLLMSettings, useTestLLM, useSystemStatus } from '../hooks/useSettings';
import { useAppStore } from '../store/appStore';
import ThemePicker from '../components/ThemePicker';

const PROVIDER_PRESETS: Record<string, { base_url: string; model: string }> = {
  openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4o' },
  minimax: { base_url: 'https://api.minimaxi.com/v1', model: 'MiniMax-M2.7' },
  deepseek: { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  custom: { base_url: '', model: '' },
};

export default function SettingsPage() {
  const navigate = useNavigate();

  const { data: status } = useSystemStatus();
  const { data: llmSettings, isLoading } = useLLMSettings();
  const updateMutation = useUpdateLLMSettings();
  const testMutation = useTestLLM();

  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [defaultModel, setDefaultModel] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [provider, setProvider] = useState('custom');
  const [testModels, setTestModels] = useState<string[]>([]);

  // 从已有配置初始化表单
  useEffect(() => {
    if (llmSettings) {
      if (llmSettings.base_url) setBaseUrl(llmSettings.base_url);
      if (llmSettings.default_model) setDefaultModel(llmSettings.default_model);
      // 自动识别 provider
      if (llmSettings.base_url?.includes('openai.com')) setProvider('openai');
      else if (llmSettings.base_url?.includes('minimaxi.com')) setProvider('minimax');
      else if (llmSettings.base_url?.includes('deepseek.com')) setProvider('deepseek');
    }
  }, [llmSettings]);

  const handleProviderChange = (p: string) => {
    setProvider(p);
    const preset = PROVIDER_PRESETS[p];
    if (preset) {
      if (preset.base_url) setBaseUrl(preset.base_url);
      if (preset.model) setDefaultModel(preset.model);
    }
  };

  const handleTest = async () => {
    if (!apiKey) {
      toast.error('请先输入 API Key');
      return;
    }
    setTestModels([]);
    try {
      const result = await testMutation.mutateAsync({ api_key: apiKey, base_url: baseUrl || undefined });
      if (result.success) {
        toast.success(result.message);
        setTestModels(result.models);
      } else {
        toast.error(result.message);
      }
    } catch {
      toast.error('测试连接失败');
    }
  };

  const handleSave = async () => {
    const updates: Record<string, string> = {};
    if (apiKey) updates.api_key = apiKey;
    if (baseUrl) updates.base_url = baseUrl;
    if (defaultModel) updates.default_model = defaultModel;

    if (Object.keys(updates).length === 0) {
      toast.error('请至少填写 API Key');
      return;
    }

    try {
      await updateMutation.mutateAsync(updates);
      toast.success('配置已保存');
      setApiKey(''); // 清空输入框（安全考虑）
    } catch {
      toast.error('保存失败');
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen newspaper-bg flex items-center justify-center">
        <Loader2Icon className="w-6 h-6 animate-spin opacity-40" />
      </div>
    );
  }

  return (
    <div className="min-h-screen newspaper-bg font-newspaper">
      {/* Header */}
      <div className="border-b border-foreground/15 sticky top-0 z-10">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <button onClick={() => navigate(-1)} className="opacity-40 hover:opacity-80 transition-opacity">
            <ArrowLeftIcon className="w-4 h-4" />
          </button>
          <h1 className="text-lg font-newspaper-bold">设置</h1>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* LLM 配置 */}
        <div className="border border-foreground/15 p-5">
          <h2 className="text-base font-newspaper-bold mb-1">LLM 配置</h2>
          <p className="text-sm opacity-50 mb-4">
            配置大语言模型的 API 连接信息。配置保存在本地数据库中，无需编辑文件。
          </p>

          {/* 当前状态 */}
          {llmSettings?.api_key_set && (
            <div className="flex items-center gap-2 text-sm opacity-60 border border-foreground/10 px-3 py-2 mb-4">
              <CheckCircleIcon className="w-4 h-4 opacity-70" />
              <span>当前 API Key: {llmSettings.api_key_masked}</span>
            </div>
          )}

          {/* Provider 选择 */}
          <div className="space-y-1.5 mb-4">
            <label className="text-sm opacity-60 font-newspaper">Provider</label>
            <div className="flex gap-3 flex-wrap">
              {Object.entries({ openai: 'OpenAI', minimax: 'MiniMax', deepseek: 'DeepSeek', custom: '自定义' }).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => handleProviderChange(key)}
                  className={`px-3 py-1.5 text-sm border border-foreground/15 transition-all ${
                    provider === key
                      ? 'font-newspaper-bold border-b-2 border-b-foreground/60'
                      : 'opacity-50 hover:opacity-80'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* API Key */}
          <div className="space-y-1.5 mb-4">
            <label className="text-sm opacity-60 font-newspaper">API Key</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={llmSettings?.api_key_set ? '留空则保持现有 Key 不变' : '输入你的 API Key'}
                  className="w-full border-b border-foreground/20 bg-transparent px-1 py-1.5 text-sm font-newspaper focus:outline-none focus:border-foreground/50 transition-colors placeholder:opacity-30"
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-1 top-1/2 -translate-y-1/2 p-1 opacity-30 hover:opacity-70 transition-opacity"
                >
                  {showKey ? <EyeOffIcon className="w-4 h-4" /> : <EyeIcon className="w-4 h-4" />}
                </button>
              </div>
              <button
                onClick={handleTest}
                disabled={testMutation.isPending || !apiKey}
                className="text-sm font-newspaper underline underline-offset-4 opacity-60 hover:opacity-100 disabled:opacity-30 transition-opacity whitespace-nowrap"
              >
                {testMutation.isPending ? <Loader2Icon className="w-4 h-4 animate-spin inline" /> : '测试连接'}
              </button>
            </div>
          </div>

          {/* Base URL */}
          <div className="space-y-1.5 mb-4">
            <label className="text-sm opacity-60 font-newspaper">Base URL</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="w-full border-b border-foreground/20 bg-transparent px-1 py-1.5 text-sm font-newspaper focus:outline-none focus:border-foreground/50 transition-colors placeholder:opacity-30"
            />
          </div>

          {/* 默认模型 */}
          <div className="space-y-1.5 mb-4">
            <label className="text-sm opacity-60 font-newspaper">默认模型</label>
            <input
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder="gpt-4o"
              className="w-full border-b border-foreground/20 bg-transparent px-1 py-1.5 text-sm font-newspaper focus:outline-none focus:border-foreground/50 transition-colors placeholder:opacity-30"
            />
            {testModels.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {testModels.slice(0, 15).map((m) => (
                  <button
                    key={m}
                    onClick={() => setDefaultModel(m)}
                    className={`px-2 py-0.5 text-xs border border-foreground/15 transition-all ${
                      defaultModel === m
                        ? 'font-newspaper-bold border-b-2 border-b-foreground/60'
                        : 'opacity-40 hover:opacity-70'
                    }`}
                  >
                    {m}
                  </button>
                ))}
                {testModels.length > 15 && (
                  <span className="text-xs opacity-30 self-center">+{testModels.length - 15} 更多</span>
                )}
              </div>
            )}
          </div>

          {/* 保存按钮 */}
          <div className="h-px bg-foreground/15 my-4" />
          <div className="flex justify-end gap-4">
            <button onClick={() => navigate(-1)} className="text-sm opacity-50 hover:opacity-80 transition-opacity">
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="text-sm font-newspaper-bold underline underline-offset-4 opacity-80 hover:opacity-100 disabled:opacity-30 transition-opacity"
            >
              {updateMutation.isPending ? <Loader2Icon className="w-4 h-4 animate-spin inline mr-1.5" /> : null}
              保存
            </button>
          </div>
        </div>

        {/* 外观主题 */}
        <div className="border border-foreground/15 p-5">
          <h2 className="text-base font-newspaper-bold mb-1 flex items-center gap-2">
            <PaletteIcon className="w-4 h-4 opacity-60" />
            外观主题
          </h2>
          <p className="text-sm opacity-50 mb-4">
            自定义界面色系、风格和显示模式
          </p>
          <ThemePicker />
        </div>

        {/* 消息显示偏好 */}
        <MessageVisibilityPrefs />

        {/* 数据存储 */}
        <div className="border border-foreground/15 p-5">
          <h2 className="text-base font-newspaper-bold mb-1">数据存储</h2>
          <p className="text-sm opacity-50 mb-3">应用数据存储位置</p>
          <div className="space-y-2 text-sm opacity-60">
            <div className="flex items-center justify-between">
              <span>数据库类型</span>
              <span className="font-mono">{status?.db_driver === 'sqlite' ? 'SQLite' : 'PostgreSQL'}</span>
            </div>
            {status?.db_driver === 'sqlite' && (
              <div className="flex items-center justify-between">
                <span>数据目录</span>
                <span className="font-mono text-xs">~/AgentFlow/data/</span>
              </div>
            )}
          </div>
        </div>

        {/* 关于 */}
        <div className="border border-foreground/15 p-5">
          <h2 className="text-base font-newspaper-bold mb-1">关于</h2>
          <div className="flex items-center justify-between text-sm opacity-60 mt-3">
            <span>版本</span>
            <span className="font-mono">{status?.app_version || '—'}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 消息显示偏好 — 控制工具调用/思考/系统消息是否在前端可见
 *
 * 用户在狼人杀等复杂 agent 流程中, 工具调用/思考/系统通知会淹没正文.
 * 这里提供 3 个独立开关, 让用户精简前端展示. 设置持久化到 localStorage
 * (appStore partialize), 跨会话保持.
 */
function MessageVisibilityPrefs() {
  const showThink = useAppStore((s) => s.showThink);
  const showToolCalls = useAppStore((s) => s.showToolCalls);
  const showSystemMessages = useAppStore((s) => s.showSystemMessages);
  const setShowThink = useAppStore((s) => s.setShowThink);
  const setShowToolCalls = useAppStore((s) => s.setShowToolCalls);
  const setShowSystemMessages = useAppStore((s) => s.setShowSystemMessages);

  const items: Array<{
    label: string;
    description: string;
    value: boolean;
    onChange: (v: boolean) => void;
  }> = [
    {
      label: '思考过程',
      description: '显示 LLM 的 <think> 推理块（reasoning）',
      value: showThink,
      onChange: setShowThink,
    },
    {
      label: '工具调用',
      description: '显示工具调用与工具结果块',
      value: showToolCalls,
      onChange: setShowToolCalls,
    },
    {
      label: '系统消息',
      description: '显示任务创建/完成等系统通知',
      value: showSystemMessages,
      onChange: setShowSystemMessages,
    },
  ];

  return (
    <div className="border border-foreground/15 p-5">
      <h2 className="text-base font-newspaper-bold mb-1 flex items-center gap-2">
        <MessageSquareIcon className="w-4 h-4 opacity-60" />
        消息显示偏好
      </h2>
      <p className="text-sm opacity-50 mb-4">
        控制聊天界面中各类辅助内容的可见性，关闭可精简展示
      </p>
      <div className="space-y-3">
        {items.map((item) => (
          <label
            key={item.label}
            className="flex items-center justify-between gap-3 cursor-pointer select-none group"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-newspaper">{item.label}</div>
              <div className="text-xs opacity-40 group-hover:opacity-60 transition-opacity">
                {item.description}
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={item.value}
              onClick={() => item.onChange(!item.value)}
              className={`relative w-9 h-5 rounded-full border transition-colors flex-shrink-0 ${
                item.value
                  ? 'bg-foreground/80 border-foreground/80'
                  : 'bg-transparent border-foreground/30'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-3.5 h-3.5 rounded-full bg-background transition-transform ${
                  item.value ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </label>
        ))}
      </div>
    </div>
  );
}
