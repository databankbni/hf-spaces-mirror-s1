# table - 表格视图

适用于：列表数据、对比数据、结构化记录

## 基础示例

```json
{
  "view_type": "table",
  "title": "任务进度",
  "data": {
    "items": [
      {"name": "第一章", "status": "done", "words": 3200},
      {"name": "第二章", "status": "in_progress", "words": 1500}
    ]
  },
  "options": {
    "columns": [
      {"field": "name", "label": "章节"},
      {"field": "status", "label": "状态", "render": {"type": "badge", "badge_map": {"done": {"label": "完成", "color": "green"}, "in_progress": {"label": "进行中", "color": "blue"}}}},
      {"field": "words", "label": "字数", "align": "right"}
    ],
    "sortable": true,
    "pagination": {"page_size": 10}
  }
}
```

## render 类型

- `badge` — 徽章，需要 `badge_map` 配置颜色映射
- `link` — 链接
- `progress` — 进度条
- `date` — 日期格式化

## 经验

- 列数控制在 5-7 列，太多用详情展开
- 状态字段用 badge 渲染比纯文字更直观
- 数字字段加 `align: "right"` 更整齐
- 数据量大时加 `pagination` 分页
