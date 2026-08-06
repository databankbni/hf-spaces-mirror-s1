# stat - 统计视图

适用于：数据概览、指标面板、进度统计

## 基础示例

```json
{
  "view_type": "stat",
  "title": "创作统计",
  "data": {
    "metrics": [
      {"label": "总字数", "value": 12500, "suffix": "字", "icon": "file-text", "color": "blue"},
      {"label": "完成章节", "value": 3, "suffix": "/8", "icon": "list-checks", "color": "green"},
      {"label": "角色数", "value": 6, "icon": "users", "color": "violet"},
      {"label": "待办任务", "value": 5, "icon": "package", "color": "amber"}
    ]
  }
}
```

## 可用颜色

blue, green, violet, amber, red, cyan, pink, orange

## 经验

- 4 个指标是最佳展示数量
- `suffix` 用于单位（字、个、%等）
- 数字要有上下文才能有意义（同比、目标值）
