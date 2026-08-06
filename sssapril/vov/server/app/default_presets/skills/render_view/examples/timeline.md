# timeline - 时间线视图

适用于：事件序列、剧情时间线、历史年表

## 基础示例

```json
{
  "view_type": "timeline",
  "title": "剧情时间线",
  "data": {
    "items": [
      {"created_at": "2024-01-15", "title": "案件发生"},
      {"created_at": "2024-01-16", "title": "林默接手调查"},
      {"created_at": "2024-01-20", "title": "发现关键线索"},
      {"created_at": "2024-01-25", "title": "真相大白"}
    ]
  },
  "options": {
    "time_field": "created_at",
    "event_field": "title"
  }
}
```

## 经验

- 按时间正序排列，最早的在最上面
- 适合 5-20 个事件，太多会很长
- 可以加 `description` 字段补充详情
