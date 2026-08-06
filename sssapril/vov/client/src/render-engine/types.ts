/**
 * RenderSpec — 数据渲染展示模块的配置协议
 *
 * Agent 通过 render_view 工具生成此配置，前端 RenderEngine 解析并渲染。
 * 支持内联数据 (data) 和按需查询 (data_source) 两种数据通道。
 */

// ── 视图类型 ──

export type ViewType =
  | 'table'
  | 'list'
  | 'tree'
  | 'document'
  | 'card'
  | 'stat'
  | 'timeline'
  | 'chart'       // 预留
  | 'map'         // 非现实地图（六边形/方格网格、领地、连接线、子地图钻取）
  | 'flowchart'   // 预留
  | 'mindmap'     // 预留
  | 'custom';

// ── 顶层配置 ──

export interface RenderSpec {
  version: number;
  view_type: ViewType;
  title?: string;
  description?: string;
  data?: Record<string, unknown>;
  data_source?: DataSourceConfig;
  options?: ViewOptions;
  style?: StyleConfig;
  actions?: ActionConfig[];
  render_target?: string;  // CSS selector for target DOM element, e.g. '#my-panel', '.data-area'
  expandable?: boolean;    // Show expand-to-fullscreen button
}

// ── 数据源配置 ──

export interface DataSourceConfig {
  api: string;
  method?: 'GET' | 'POST';
  params?: Record<string, unknown>;
  body?: Record<string, unknown>;
  data_path?: string;
  transform?: TransformConfig;
  refresh_interval?: number;
}

// ── 数据转换 ──

export interface TransformConfig {
  pick?: string[];
  rename?: Record<string, string>;
  sort?: { field: string; order: 'asc' | 'desc' };
  filter?: FilterCondition[];
  map?: Record<string, FieldMapping>;
}

export interface FilterCondition {
  field: string;
  operator: 'eq' | 'neq' | 'contains' | 'gt' | 'lt' | 'in';
  value: unknown;
}

export interface FieldMapping {
  enum?: Record<string, string>;
  date_format?: string;
  truncate?: number;
}

// ── 视图选项 ──

export interface ViewOptions {
  // table
  columns?: ColumnDef[];
  sortable?: boolean;
  filterable?: boolean;
  pagination?: { page_size: number };

  // tree
  node_kind_field?: string;
  label_field?: string;
  children_field?: string;
  default_expand_depth?: number;
  icon_map?: Record<string, string>;

  // list
  layout?: 'vertical' | 'grid';
  item_template?: string;
  show_avatar?: boolean;

  // document
  content_field?: string;
  show_toc?: boolean;
  compact?: boolean;

  // card
  card_fields?: CardFieldDef[];
  grid_cols?: number;

  // stat
  metrics?: MetricDef[];

  // chart (预留)
  chart_type?: 'bar' | 'line' | 'pie' | 'radar';
  x_field?: string;
  y_field?: string;

  // timeline
  time_field?: string;
  event_field?: string;

  // map
  map?: MapConfig;

  // 通用
  empty_text?: string;
  loading_text?: string;
}

// ── 表格列定义 ──

export interface ColumnDef {
  field: string;
  label: string;
  width?: string;
  align?: 'left' | 'center' | 'right';
  sortable?: boolean;
  render?: CellRenderConfig;
}

export interface CellRenderConfig {
  type: 'text' | 'badge' | 'link' | 'progress' | 'avatar' | 'date' | 'custom';
  badge_map?: Record<string, { label: string; color: string }>;
  href_template?: string;
  max_field?: string;
  format?: string;
}

// ── 统计指标 ──

export interface MetricDef {
  label: string;
  value_field: string;
  prefix?: string;
  suffix?: string;
  trend_field?: string;
  icon?: string;
  color?: string;
}

// ── 卡片字段 ──

export interface CardFieldDef {
  field: string;
  label?: string;
  render?: CellRenderConfig;
}

// ── 样式配置 ──

export interface StyleConfig {
  class_name?: string;
  height?: string;
  bordered?: boolean;
  compact?: boolean;
  popup?: boolean;
}

// ── 交互动作 ──

export interface ActionConfig {
  type: 'navigate' | 'open_detail' | 'trigger_tool';
  label: string;
  route_template?: string;
  detail_source?: DataSourceConfig;
  tool_name?: string;
  tool_args_template?: Record<string, string>;
}

// ── 视图组件 Props ──

export interface ViewComponentProps {
  data: unknown;
  options?: ViewOptions;
  actions?: ActionConfig[];
  style?: StyleConfig;
}

// ── 地图类型定义 ──

export interface MapConfig {
  grid: GridConfig;
  territories: Territory[];
  connections?: MapConnection[];
  background?: MapBackground;
  legend?: MapLegend;
}

export interface GridConfig {
  cols: number;
  rows: number;
  cell_shape: 'square' | 'hex';
  cell_size?: number;
}

export interface Territory {
  id: string;
  name: string;
  cells: [number, number][];
  style?: TerritoryStyle;
  info?: TerritoryInfo;
  sub_map?: MapConfig;
}

export interface TerritoryStyle {
  fill?: string;
  stroke?: string;
  stroke_width?: number;
  opacity?: number;
  pattern?: 'solid' | 'striped' | 'dotted' | 'crosshatch';
  label_position?: 'center' | 'top';
}

export interface TerritoryInfo {
  title?: string;
  subtitle?: string;
  description?: string;
  avatar_url?: string;
  icon?: string;
  stats?: Record<string, string | number>;
  badges?: { label: string; color: string }[];
}

export interface MapConnection {
  source: string;
  target: string;
  label?: string;
  style?: 'solid' | 'dashed' | 'dotted';
  color?: string;
  directed?: boolean;
}

export interface MapBackground {
  color?: string;
  grid_lines?: boolean;
  grid_color?: string;
}

export interface MapLegend {
  items?: { label: string; color: string; pattern?: string }[];
  position?: 'top-right' | 'bottom-right' | 'top-left' | 'bottom-left';
}
