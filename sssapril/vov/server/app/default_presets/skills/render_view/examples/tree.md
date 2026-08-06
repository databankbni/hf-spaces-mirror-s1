# tree - 树形视图

适用于：目录结构、层级关系、组织架构

## 基础示例

```json
{
  "view_type": "tree",
  "title": "故事大纲",
  "data": {
    "children": [
      {
        "label": "第一幕：起", "kind": "section",
        "children": [
          {"label": "第1章：谜案", "kind": "task"},
          {"label": "第2章：线索", "kind": "task"}
        ]
      },
      {
        "label": "第二幕：承", "kind": "section",
        "children": [
          {"label": "第3章：追踪", "kind": "task"}
        ]
      }
    ]
  },
  "options": {
    "label_field": "label",
    "node_kind_field": "kind",
    "children_field": "children",
    "default_expand_depth": 3,
    "icon_map": {"section": "folder", "task": "file-text"}
  }
}
```

## 经验

- `default_expand_depth` 控制初始展开层级，3 是常用值
- `icon_map` 用 kind 字段映射图标，让层级更直观
- 适合 3-4 层深度，太深会难以浏览
