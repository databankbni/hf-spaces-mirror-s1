import { useState } from 'react';
import { ArrowLeftIcon, TableIcon, ListIcon, NetworkIcon, FileTextIcon, BarChart2Icon, LayoutGridIcon, ClockIcon, MapIcon } from 'lucide-react';
import RenderEngine from '../render-engine/RenderEngine';
import type { RenderSpec, ViewType } from '../render-engine/types';

// ── 演示数据 ──

const DEMO_SPECS: { type: ViewType; label: string; icon: typeof TableIcon; spec: RenderSpec }[] = [
  {
    type: 'table',
    label: '表格',
    icon: TableIcon,
    spec: {
      version: 1,
      view_type: 'table',
      title: '项目任务列表',
      description: '当前项目的所有任务概览',
      data: {
        items: [
          { id: '1', title: '需求分析', status: 'done', priority: 'high', assignee: 'Alice', created_at: '2025-01-15T10:00:00Z' },
          { id: '2', title: '系统设计', status: 'done', priority: 'high', assignee: 'Bob', created_at: '2025-01-20T14:00:00Z' },
          { id: '3', title: '前端开发', status: 'in_progress', priority: 'medium', assignee: 'Charlie', created_at: '2025-02-01T09:00:00Z' },
          { id: '4', title: '后端开发', status: 'in_progress', priority: 'medium', assignee: 'Diana', created_at: '2025-02-01T09:00:00Z' },
          { id: '5', title: '接口联调', status: 'todo', priority: 'medium', assignee: 'Charlie', created_at: '2025-02-15T10:00:00Z' },
          { id: '6', title: '性能优化', status: 'todo', priority: 'low', assignee: 'Eve', created_at: '2025-03-01T10:00:00Z' },
          { id: '7', title: '测试验收', status: 'todo', priority: 'high', assignee: 'Frank', created_at: '2025-03-10T10:00:00Z' },
        ],
      },
      data_source: { api: '', data_path: 'items' },
      options: {
        columns: [
          { field: 'title', label: '任务名称', width: '2fr', render: { type: 'link', href_template: '/tasks/{id}' } },
          { field: 'status', label: '状态', width: '100px', render: { type: 'badge', badge_map: {
            todo: { label: '待办', color: 'gray' },
            in_progress: { label: '进行中', color: 'blue' },
            done: { label: '已完成', color: 'green' },
          }}},
          { field: 'priority', label: '优先级', width: '90px', render: { type: 'badge', badge_map: {
            high: { label: '高', color: 'red' },
            medium: { label: '中', color: 'amber' },
            low: { label: '低', color: 'gray' },
          }}},
          { field: 'assignee', label: '负责人', width: '100px' },
          { field: 'created_at', label: '创建时间', width: '120px', render: { type: 'date', format: 'YYYY-MM-DD' } },
        ],
        sortable: true,
        pagination: { page_size: 5 },
      },
      style: { bordered: true },
    },
  },
  {
    type: 'stat',
    label: '统计',
    icon: BarChart2Icon,
    spec: {
      version: 1,
      view_type: 'stat',
      title: '项目概览',
      data: {
        total_tasks: 7,
        completed: 2,
        in_progress: 2,
        completion_rate: 29,
        agents: 4,
        deliverables: 3,
      },
      options: {
        metrics: [
          { label: '任务总数', value_field: 'total_tasks', suffix: '个', icon: 'list-checks', color: 'blue' },
          { label: '已完成', value_field: 'completed', suffix: '个', icon: 'trending-up', color: 'green' },
          { label: '完成率', value_field: 'completion_rate', suffix: '%', icon: 'bar-chart', color: 'amber' },
          { label: 'Agent数', value_field: 'agents', suffix: '个', icon: 'bot', color: 'violet' },
        ],
      },
    },
  },
  {
    type: 'tree',
    label: '树形',
    icon: NetworkIcon,
    spec: {
      version: 1,
      view_type: 'tree',
      title: '项目结构',
      data: {
        children: [
          { id: 'agents', kind: 'section', label: 'Agents', badge: '4', children: [
            { id: 'a1', kind: 'agent', label: 'Alice - 项目经理', description: '负责需求分析和项目管理' },
            { id: 'a2', kind: 'agent', label: 'Bob - 架构师', description: '负责系统设计和技术决策' },
            { id: 'a3', kind: 'agent', label: 'Charlie - 前端开发', description: '负责前端界面开发' },
            { id: 'a4', kind: 'agent', label: 'Diana - 后端开发', description: '负责后端服务开发' },
          ]},
          { id: 'tasks', kind: 'section', label: '任务', badge: '7', children: [
            { id: 't1', kind: 'task', label: '需求分析', description: '已完成' },
            { id: 't2', kind: 'task', label: '系统设计', description: '已完成' },
            { id: 't3', kind: 'task', label: '前端开发', description: '进行中' },
            { id: 't4', kind: 'task', label: '后端开发', description: '进行中' },
          ]},
          { id: 'deliverables', kind: 'section', label: '交付物', badge: '3', children: [
            { id: 'd1', kind: 'deliverable', label: '需求规格说明书', description: 'v2.1' },
            { id: 'd2', kind: 'deliverable', label: '系统架构设计', description: 'v1.3' },
            { id: 'd3', kind: 'deliverable', label: 'API接口文档', description: 'v1.0' },
          ]},
          { id: 'resources', kind: 'section', label: '资料库', badge: '5', children: [
            { id: 'r1', kind: 'resource', label: '项目规范' },
            { id: 'r2', kind: 'resource', label: '技术栈指南' },
          ]},
        ],
      },
      data_source: { api: '', data_path: 'children' },
      options: {
        default_expand_depth: 2,
        icon_map: {
          section: 'folder',
          agent: 'agent',
          task: 'task',
          deliverable: 'deliverable',
          resource: 'resource',
        },
      },
      style: { bordered: true },
    },
  },
  {
    type: 'card',
    label: '卡片',
    icon: LayoutGridIcon,
    spec: {
      version: 1,
      view_type: 'card',
      title: '交付物列表',
      data: {
        items: [
          { id: 'd1', title: '需求规格说明书', type: 'document', version: 'v2.1', author: 'Alice', updated: '2025-02-10' },
          { id: 'd2', title: '系统架构设计', type: 'design', version: 'v1.3', author: 'Bob', updated: '2025-02-15' },
          { id: 'd3', title: 'API接口文档', type: 'document', version: 'v1.0', author: 'Diana', updated: '2025-02-20' },
        ],
      },
      data_source: { api: '', data_path: 'items' },
      options: {
        grid_cols: 3,
        card_fields: [
          { field: 'title', label: '名称', render: { type: 'link', href_template: '/deliverable/{id}' } },
          { field: 'type', label: '类型', render: { type: 'badge', badge_map: {
            document: { label: '文档', color: 'blue' },
            design: { label: '设计', color: 'violet' },
            code: { label: '代码', color: 'green' },
          }}},
          { field: 'version', label: '版本' },
          { field: 'author', label: '作者' },
          { field: 'updated', label: '更新时间', render: { type: 'date', format: 'YYYY-MM-DD' } },
        ],
      },
    },
  },
  {
    type: 'list',
    label: '列表',
    icon: ListIcon,
    spec: {
      version: 1,
      view_type: 'list',
      title: 'Agent 列表',
      data: {
        items: [
          { id: 'a1', name: 'Alice', role: '项目经理', status: 'active', tasks: 3 },
          { id: 'a2', name: 'Bob', role: '架构师', status: 'active', tasks: 2 },
          { id: 'a3', name: 'Charlie', role: '前端开发', status: 'busy', tasks: 5 },
          { id: 'a4', name: 'Diana', role: '后端开发', status: 'active', tasks: 4 },
        ],
      },
      data_source: { api: '', data_path: 'items' },
      options: {
        layout: 'vertical',
        card_fields: [
          { field: 'name', label: '名称' },
          { field: 'role', label: '角色', render: { type: 'badge', badge_map: {
            '项目经理': { label: '项目经理', color: 'violet' },
            '架构师': { label: '架构师', color: 'blue' },
            '前端开发': { label: '前端开发', color: 'green' },
            '后端开发': { label: '后端开发', color: 'amber' },
          }}},
          { field: 'status', label: '状态', render: { type: 'badge', badge_map: {
            active: { label: '在线', color: 'green' },
            busy: { label: '忙碌', color: 'amber' },
          }}},
          { field: 'tasks', label: '任务数' },
        ],
      },
    },
  },
  {
    type: 'document',
    label: '文档',
    icon: FileTextIcon,
    spec: {
      version: 1,
      view_type: 'document',
      title: '需求规格说明书',
      data: {
        content: `# 需求规格说明书 v2.1

## 1. 项目概述

本项目旨在构建一个**智能协作平台**，支持 AI Agent 与人类用户的高效协作。

### 1.1 核心目标

- 提供多 Agent 协作的工作流编排能力
- 支持任务分配、进度跟踪和交付物管理
- 实现数据驱动的可视化展示模块

### 1.2 技术栈

| 技术 | 用途 |
|------|------|
| React + TypeScript | 前端框架 |
| FastAPI | 后端服务 |
| PostgreSQL | 数据存储 |
| agentflow | Agent 执行引擎 |

## 2. 功能需求

### 2.1 数据渲染展示模块

该模块支持以下视图类型：

1. **表格视图** - 展示结构化数据
2. **树形视图** - 展示层级关系
3. **文档视图** - 渲染 Markdown 内容
4. **统计视图** - 展示关键指标
5. **卡片视图** - 展示实体概览
6. **时间线视图** - 展示事件流

> Agent 可以通过 \`render_view\` 工具动态生成渲染配置，前端自动解析并渲染。

### 2.2 Agent 集成

\`\`\`json
{
  "name": "render_view",
  "arguments": {
    "view_type": "table",
    "title": "任务列表",
    "data_source": {
      "api": "/groups/{group_id}/tasks"
    }
  }
}
\`\`\`

## 3. 非功能需求

- 页面加载时间 < 2s
- 支持 100+ 并发用户
- 数据渲染延迟 < 500ms`,
      },
      data_source: { api: '', data_path: 'content' },
      options: {
        content_field: 'content',
        show_toc: true,
      },
      style: { bordered: true },
    },
  },
  {
    type: 'timeline',
    label: '时间线',
    icon: ClockIcon,
    spec: {
      version: 1,
      view_type: 'timeline',
      title: '项目进展',
      data: {
        items: [
          { id: 'e1', title: '项目启动', description: '确定项目目标和团队组成', created_at: '2025-01-10T10:00:00Z' },
          { id: 'e2', title: '需求分析完成', description: '完成需求规格说明书 v2.1', created_at: '2025-01-25T14:00:00Z' },
          { id: 'e3', title: '系统设计评审', description: '通过架构设计方案', created_at: '2025-02-05T09:00:00Z' },
          { id: 'e4', title: '前端开发启动', description: '开始前端界面开发', created_at: '2025-02-10T10:00:00Z' },
          { id: 'e5', title: '后端开发启动', description: '开始后端服务开发', created_at: '2025-02-12T10:00:00Z' },
          { id: 'e6', title: '数据渲染模块上线', description: '独立数据渲染展示模块开发完成', created_at: '2025-02-20T16:00:00Z' },
        ],
      },
      data_source: { api: '', data_path: 'items' },
      options: {
        time_field: 'created_at',
        event_field: 'title',
      },
    },
  },
  {
    type: 'map',
    label: '地图',
    icon: MapIcon,
    spec: {
      version: 1,
      view_type: 'map',
      title: '大陆势力分布图',
      description: '点击领地查看详情，右键展开子地图',
      data: {},
      options: {
        map: {
          grid: { cols: 10, rows: 8, cell_shape: 'hex', cell_size: 36 },
          background: { color: '#f8fafc', grid_lines: false },
          legend: {
            items: [
              { label: '星辉帝国', color: '#6366f1' },
              { label: '碧海联盟', color: '#0891b2' },
              { label: '赤焰部落', color: '#dc2626' },
              { label: '中立区域', color: '#94a3b8' },
            ],
            position: 'bottom-right',
          },
          territories: [
            {
              id: 'star_empire',
              name: '星辉帝国',
              cells: [[0,1],[0,2],[0,3],[1,1],[1,2],[1,3],[1,4],[2,1],[2,2],[2,3],[3,1],[3,2]],
              style: { fill: '#6366f1', stroke: '#4f46e5' },
              info: {
                title: '星辉帝国',
                subtitle: '人口 1200万 | 面积 12格',
                description: '大陆北方的古老帝国，以魔法与科技并重闻名于世。帝国拥有大陆最强的魔法学院和最先进的机械工坊。',
                icon: '👑',
                stats: { 人口: '1200万', 军力: '85', 经济: '92', 魔力: '98' },
                badges: [{ label: '强国', color: '#6366f1' }, { label: '魔法', color: '#8b5cf6' }, { label: '科技', color: '#3b82f6' }],
              },
              sub_map: {
                grid: { cols: 6, rows: 4, cell_shape: 'hex', cell_size: 40 },
                background: { color: '#f8fafc', grid_lines: false },
                territories: [
                  { id: 'capital', name: '帝都', cells: [[1,2],[1,3],[2,2],[2,3]], style: { fill: '#818cf8', stroke: '#6366f1' }, info: { title: '帝都·星辰城', subtitle: '帝国首都', icon: '🏰', stats: { 人口: '300万' }, badges: [{ label: '首都', color: '#818cf8' }] } },
                  { id: 'north_province', name: '北境省', cells: [[0,0],[0,1],[1,0]], style: { fill: '#6366f1', stroke: '#4f46e5' }, info: { title: '北境省', subtitle: '边防重地', icon: '⚔️', stats: { 驻军: '5万' } } },
                  { id: 'east_province', name: '东岭省', cells: [[0,4],[0,5],[1,4],[1,5]], style: { fill: '#6366f1', stroke: '#4f46e5' }, info: { title: '东岭省', subtitle: '矿业中心', icon: '⛏️', stats: { 矿产: '丰富' } } },
                  { id: 'south_province', name: '南风省', cells: [[3,0],[3,1],[2,0]], style: { fill: '#a5b4fc', stroke: '#818cf8' }, info: { title: '南风省', subtitle: '农业腹地', icon: '🌾', stats: { 粮产: '自给' } } },
                  { id: 'west_province', name: '西澜省', cells: [[3,4],[3,5],[2,4],[2,5]], style: { fill: '#a5b4fc', stroke: '#818cf8' }, info: { title: '西澜省', subtitle: '贸易港口', icon: '⚓', stats: { 贸易额: '极高' } } },
                ],
              },
            },
            {
              id: 'ocean_alliance',
              name: '碧海联盟',
              cells: [[0,7],[0,8],[0,9],[1,7],[1,8],[1,9],[2,7],[2,8],[2,9],[3,8],[3,9]],
              style: { fill: '#0891b2', stroke: '#0e7490' },
              info: {
                title: '碧海联盟',
                subtitle: '人口 800万 | 面积 11格',
                description: '东部沿海的城邦联盟，以航海贸易立国。联盟拥有大陆最强大的舰队和最繁忙的港口。',
                icon: '⚓',
                stats: { 人口: '800万', 军力: '65', 经济: '95', 航海: '99' },
                badges: [{ label: '商贸', color: '#0891b2' }, { label: '航海', color: '#0284c7' }],
              },
            },
            {
              id: 'flame_tribe',
              name: '赤焰部落',
              cells: [[4,0],[4,1],[5,0],[5,1],[5,2],[5,3],[6,0],[6,1],[6,2],[7,0],[7,1],[7,2]],
              style: { fill: '#dc2626', stroke: '#b91c1c', pattern: 'striped' },
              info: {
                title: '赤焰部落',
                subtitle: '人口 500万 | 面积 12格',
                description: '南方荒原的游牧部落联盟，崇尚武力与自由。部落战士以勇猛著称，经济虽不发达但军事力量不可小觑。',
                icon: '🔥',
                stats: { 人口: '500万', 军力: '90', 经济: '45', 士气: '95' },
                badges: [{ label: '好战', color: '#dc2626' }, { label: '游牧', color: '#f97316' }],
              },
            },
            {
              id: 'neutral_north',
              name: '北方荒原',
              cells: [[0,0],[0,4],[0,5],[0,6]],
              style: { fill: '#94a3b8', stroke: '#64748b' },
              info: { title: '北方荒原', subtitle: '无人区', icon: '❄️', stats: { 温度: '-30°C' } },
            },
            {
              id: 'neutral_mid',
              name: '中部平原',
              cells: [[3,3],[3,4],[3,5],[3,6],[3,7],[4,2],[4,3],[4,4],[4,5],[4,6],[4,7],[4,8],[4,9],[5,4],[5,5],[5,6],[5,7],[5,8],[5,9]],
              style: { fill: '#94a3b8', stroke: '#64748b' },
              info: { title: '中部平原', subtitle: '争议地区', icon: '⚔️', description: '三国交界的战略要地，常年纷争不断', stats: { 危险度: '高' } },
            },
            {
              id: 'neutral_south',
              name: '南方沼泽',
              cells: [[6,3],[6,4],[6,5],[6,6],[6,7],[6,8],[6,9],[7,3],[7,4],[7,5],[7,6],[7,7],[7,8],[7,9]],
              style: { fill: '#94a3b8', stroke: '#64748b', pattern: 'dotted' },
              info: { title: '南方沼泽', subtitle: '危险区域', icon: '🐊', description: '瘴气弥漫的沼泽地带，传说中远古遗迹的所在', stats: { 危险度: '极高' } },
            },
          ],
          connections: [
            { source: 'star_empire', target: 'ocean_alliance', label: '贸易', style: 'dashed', color: '#6366f1' },
            { source: 'star_empire', target: 'flame_tribe', label: '对峙', style: 'solid', color: '#dc2626', directed: true },
            { source: 'ocean_alliance', target: 'flame_tribe', label: '封锁', style: 'dotted', color: '#0891b2' },
          ],
        },
      },
      style: { bordered: true },
    },
  },
];

export default function RenderDemoPage() {
  const [activeType, setActiveType] = useState<ViewType>('stat');

  const currentDemo = DEMO_SPECS.find(d => d.type === activeType);

  return (
    <div className="min-h-screen bg-background">
      {/* 顶部导航 */}
      <header className="sticky top-0 z-10 bg-card border-b border-border">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-4">
          <h1 className="text-base font-bold text-foreground">数据渲染展示模块 - 演示</h1>
          <span className="text-xs text-muted-foreground">RenderEngine Demo</span>
        </div>
      </header>

      <div className="max-w-[1600px] mx-auto px-6 py-6 flex gap-6">
        {/* 左侧：视图类型选择 */}
        <aside className="w-48 flex-shrink-0">
          <div className="sticky top-20 rounded-xl border border-border bg-card p-3">
            <div className="text-xs font-semibold text-muted-foreground mb-3">视图类型</div>
            <div className="flex flex-col gap-1">
              {DEMO_SPECS.map(({ type, label, icon: Icon }) => (
                <button
                  key={type}
                  onClick={() => setActiveType(type)}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors ${
                    activeType === type
                      ? 'bg-primary/10 text-primary font-medium'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* 中间：渲染效果预览 */}
        <main className="flex-1 min-w-0">
          {currentDemo && <RenderEngine spec={currentDemo.spec} />}
        </main>

        {/* 右侧：配置 JSON 预览 */}
        <aside className="w-80 flex-shrink-0 hidden xl:block">
          <div className="sticky top-20 rounded-xl border border-border bg-card p-3">
            <div className="text-xs font-semibold text-muted-foreground mb-3">RenderSpec 配置</div>
            <pre className="text-[11px] text-muted-foreground overflow-auto max-h-[calc(100vh-200px)] whitespace-pre-wrap break-all">
              {currentDemo ? JSON.stringify(currentDemo.spec, null, 2) : ''}
            </pre>
          </div>
        </aside>
      </div>
    </div>
  );
}
