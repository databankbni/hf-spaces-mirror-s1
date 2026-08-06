/**
 * 应用全局状态管理
 *
 * 使用Zustand管理客户端状态，包括：
 * - 当前选中的项目/群聊/交付物
 * - UI状态（侧边栏、面板等）
 * - 快捷键配置
 *
 * 注意：服务端状态（API数据）由TanStack Query管理，
 * 此store仅管理客户端本地状态。
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

/** 可选的召唤快捷键（均为 Cmd/Ctrl + key） */
export const CHAT_HOTKEY_OPTIONS = [
  { key: 'k', label: '⌘K' },
  { key: 'j', label: '⌘J' },
  { key: 'l', label: '⌘L' },
  { key: '\\', label: '⌘\\' },
] as const;

export type ChatHotkey = typeof CHAT_HOTKEY_OPTIONS[number]['key'];

/**
 * 应用状态接口
 */
interface AppState {
  // 当前选中的实体ID
  activeProjectId: string | null;
  activeGroupId: string | null;
  activeDeliverableId: string | null;

  // UI状态
  sidebarCollapsed: boolean;
  rightPanelOpen: boolean;
  /** UniversalChat 侧边栏是否展开 */
  universalChatOpen: boolean;
  /** 召唤侧边栏的快捷键（默认 'k'，可改为 j/l/\ 避免冲突） */
  chatHotkey: ChatHotkey;

  // 消息显示偏好（精简前端展示）
  /** 是否显示 think（思考）块 */
  showThink: boolean;
  /** 是否显示工具调用块 */
  showToolCalls: boolean;
  /** 是否显示系统消息（任务创建/完成通知等） */
  showSystemMessages: boolean;

  // 群级别可见性覆盖 —— 每个群可以单独覆盖系统级设置
  // undefined 字段 = 继承系统设置；true/false = 强制覆盖
  /** key: groupId, value: 该群的可见性覆盖（只含有覆盖的字段） */
  groupVisibilityOverrides: Record<string, GroupVisibilityOverride>;

  // Actions
  setActiveProjectId: (id: string | null) => void;
  setActiveGroupId: (id: string | null) => void;
  setActiveDeliverableId: (id: string | null) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleRightPanel: () => void;
  setRightPanelOpen: (open: boolean) => void;
  toggleUniversalChat: () => void;
  setUniversalChatOpen: (open: boolean) => void;
  setChatHotkey: (key: ChatHotkey) => void;
  setShowThink: (value: boolean) => void;
  setShowToolCalls: (value: boolean) => void;
  setShowSystemMessages: (value: boolean) => void;
  /** 设置某个群的可见性覆盖字段（传 undefined 表示继承系统设置） */
  setGroupVisibilityOverride: (groupId: string, key: VisibilityKey, value: boolean | undefined) => void;
  /** 重置某个群的所有可见性覆盖 */
  resetGroupVisibilityOverrides: (groupId: string) => void;
  resetActiveIds: () => void;
}

/** 群级别可见性覆盖字段 */
export type VisibilityKey = 'showThink' | 'showToolCalls' | 'showSystemMessages';
export type GroupVisibilityOverride = Partial<Record<VisibilityKey, boolean>>;

/**
 * 应用Store
 */
export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set) => ({
        // 初始状态
        activeProjectId: null,
        activeGroupId: null,
        activeDeliverableId: null,
        sidebarCollapsed: false,
        rightPanelOpen: true,
        universalChatOpen: false,
        chatHotkey: 'k',
        // 消息显示偏好默认全部开启（保持现有行为）
        showThink: true,
        showToolCalls: true,
        showSystemMessages: true,
        // 群级别覆盖：默认空对象，所有群都继承系统设置
        groupVisibilityOverrides: {},

        // Actions
        setActiveProjectId: (id) =>
          set(
            { activeProjectId: id, activeGroupId: null, activeDeliverableId: null },
            false,
            'setActiveProjectId'
          ),

        setActiveGroupId: (id) =>
          set(
            { activeGroupId: id, activeDeliverableId: null },
            false,
            'setActiveGroupId'
          ),

        setActiveDeliverableId: (id) =>
          set({ activeDeliverableId: id }, false, 'setActiveDeliverableId'),

        toggleSidebar: () =>
          set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed }), false, 'toggleSidebar'),

        setSidebarCollapsed: (collapsed) =>
          set({ sidebarCollapsed: collapsed }, false, 'setSidebarCollapsed'),

        toggleRightPanel: () =>
          set((state) => ({ rightPanelOpen: !state.rightPanelOpen }), false, 'toggleRightPanel'),

        setRightPanelOpen: (open) =>
          set({ rightPanelOpen: open }, false, 'setRightPanelOpen'),

        toggleUniversalChat: () =>
          set((state) => ({ universalChatOpen: !state.universalChatOpen }), false, 'toggleUniversalChat'),

        setUniversalChatOpen: (open) =>
          set({ universalChatOpen: open }, false, 'setUniversalChatOpen'),

        setChatHotkey: (key) =>
          set({ chatHotkey: key }, false, 'setChatHotkey'),

        setShowThink: (value) =>
          set({ showThink: value }, false, 'setShowThink'),

        setShowToolCalls: (value) =>
          set({ showToolCalls: value }, false, 'setShowToolCalls'),

        setShowSystemMessages: (value) =>
          set({ showSystemMessages: value }, false, 'setShowSystemMessages'),

        setGroupVisibilityOverride: (groupId, key, value) =>
          set(
            (state) => {
              const current = state.groupVisibilityOverrides[groupId] || {};
              const next: GroupVisibilityOverride = { ...current };
              if (value === undefined) {
                delete next[key];
              } else {
                next[key] = value;
              }
              // 如果该群覆盖为空对象，删除整个 key 避免 localStorage 膨胀
              const overrides = { ...state.groupVisibilityOverrides };
              if (Object.keys(next).length === 0) {
                delete overrides[groupId];
              } else {
                overrides[groupId] = next;
              }
              return { groupVisibilityOverrides: overrides };
            },
            false,
            'setGroupVisibilityOverride'
          ),

        resetGroupVisibilityOverrides: (groupId) =>
          set(
            (state) => {
              if (!(groupId in state.groupVisibilityOverrides)) return state;
              const overrides = { ...state.groupVisibilityOverrides };
              delete overrides[groupId];
              return { groupVisibilityOverrides: overrides };
            },
            false,
            'resetGroupVisibilityOverrides'
          ),

        resetActiveIds: () =>
          set(
            { activeProjectId: null, activeGroupId: null, activeDeliverableId: null },
            false,
            'resetActiveIds'
          ),
      }),
      {
        name: 'agentflow-app-store',
        // 只持久化这些字段
        partialize: (state) => ({
          activeProjectId: state.activeProjectId,
          sidebarCollapsed: state.sidebarCollapsed,
          chatHotkey: state.chatHotkey,
          showThink: state.showThink,
          showToolCalls: state.showToolCalls,
          showSystemMessages: state.showSystemMessages,
          groupVisibilityOverrides: state.groupVisibilityOverrides,
        }),
      }
    ),
    { name: 'AppStore', enabled: import.meta.env.DEV }
  )
);

export default useAppStore;
