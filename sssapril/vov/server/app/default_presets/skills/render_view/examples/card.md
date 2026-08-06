# card - 卡片视图

适用于：信息卡片、特性展示、对比

## 基础示例

```json
{
  "view_type": "card",
  "title": "角色对比",
  "data": {
    "items": [
      {"name": "林默", "strength": "逻辑推理", "weakness": "社交", "status": "主角"},
      {"name": "苏晴", "strength": "信息搜集", "weakness": "冲动", "status": "搭档"}
    ]
  },
  "options": {
    "card_fields": [
      {"field": "name", "label": "姓名"},
      {"field": "strength", "label": "优势"},
      {"field": "weakness", "label": "弱点"},
      {"field": "status", "label": "定位"}
    ],
    "grid_cols": 2
  }
}
```

## 经验

- `grid_cols` 控制每行列数，2-3 列最佳
- 适合 3-8 个项目的对比展示
- 比表格更视觉化，适合给人看而非数据分析
