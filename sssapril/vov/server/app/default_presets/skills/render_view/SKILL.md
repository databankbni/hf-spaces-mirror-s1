# render_view 数据可视化指南

你可以使用 `render_view` 工具将结构化数据渲染为可视化视图，展示在聊天界面中。

## 基本调用格式

```json
{
  "view_type": "table",
  "title": "任务列表",
  "description": "当前群聊中的所有任务",
  "data": { "items": [...] },
  "options": { ... }
}
```

## 9 种视图类型速查

| 视图类型 | view_type | 适用场景 | 详细示例 |
|---------|-----------|---------|---------|
| 表格 | `table` | 列表数据、对比数据、结构化记录 | → examples/table.md |
| 列表 | `list` | 卡片列表、成员列表、资源目录 | → examples/list.md |
| 树形 | `tree` | 目录结构、层级关系、组织架构 | → examples/tree.md |
| 文档 | `document` | 长文内容、报告、故事正文 | → examples/document.md |
| 卡片 | `card` | 信息卡片、特性展示、对比 | → examples/card.md |
| 统计 | `stat` | 数据概览、指标面板、进度统计 | → examples/stat.md |
| 时间线 | `timeline` | 事件序列、剧情时间线、历史年表 | → examples/timeline.md |
| 地图 | `map` | 空间布局、世界地图、场景关系图 | → examples/map.md |
| 图谱 | `graph` | 项目流水线、任务依赖、知识图谱、Agent 协作图（DAG） | → examples/graph.md |

## 通用规则

1. `data` 中的 `items` 或 `children` 是数组，每项是一个对象
2. `options` 是可选的，不提供时使用默认渲染
3. 调用时只需传必要字段，不需要的字段可以省略
4. 表格的 `render` 支持 badge（徽章）、link（链接）、progress（进度条）、date（日期）
5. 地图的 `cells` 是 `[col, row]` 坐标数组，从 0 开始
6. 地图支持 `sub_map` 嵌套下钻
7. **图谱（graph）是通用 DAG**，可表达任何"节点 + 边"关系；同一份 data 既渲染给用户，也供 agent 读回作为流程描述

## 最佳实践

详见 → examples/tips.md
