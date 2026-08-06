# document - 文档视图

适用于：长文内容、报告、故事正文

## 基础示例

```json
{
  "view_type": "document",
  "title": "世界观设定",
  "data": {
    "content": "# 世界观\n\n## 地理\n大陆分为五块...\n\n## 历史\n千年之前..."
  },
  "options": {
    "content_field": "content",
    "show_toc": true,
    "compact": false
  }
}
```

## 经验

- `show_toc: true` 会根据标题自动生成目录
- `compact: true` 适合短文档，减少留白
- content 支持完整 Markdown 语法
- 适合展示超过 500 字的长文本，短文本用其他视图更合适
