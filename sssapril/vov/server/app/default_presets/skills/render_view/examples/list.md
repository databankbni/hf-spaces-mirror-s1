# list - 列表视图

适用于：卡片列表、成员列表、资源目录

## 基础示例

```json
{
  "view_type": "list",
  "title": "角色档案",
  "data": {
    "items": [
      {"name": "林默", "role": "主角", "desc": "沉默寡言的侦探"},
      {"name": "苏晴", "role": "搭档", "desc": "热情的记者"}
    ]
  },
  "options": {
    "layout": "grid",
    "card_fields": [
      {"field": "name", "label": "姓名"},
      {"field": "role", "label": "角色"},
      {"field": "desc", "label": "简介"}
    ],
    "show_avatar": true
  }
}
```

## 经验

- `layout: "grid"` 适合展示卡片，`list` 适合紧凑列表
- `show_avatar: true` 会取 name 首字作为头像
- 每项信息不宜过多，3-5 个字段为佳
