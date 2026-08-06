// 数据渲染展示模块 - 统一导出入口
export { default as RenderEngine, registerView, getViewComponent } from './RenderEngine';
export type { RenderSpec, ViewType, ViewComponentProps, DataSourceConfig, TransformConfig, ViewOptions, ColumnDef, CellRenderConfig, MetricDef, ActionConfig, StyleConfig, MapConfig, GridConfig, Territory, TerritoryStyle, TerritoryInfo, MapConnection, MapBackground, MapLegend } from './types';
export { useRenderData } from './useRenderData';
export { applyTransform, extractDataByPath, resolveTemplate } from './DataTransform';
