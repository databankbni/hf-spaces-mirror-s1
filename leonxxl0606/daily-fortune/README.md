---
title: Daily Fortune
emoji: 🏮
colorFrom: red
colorTo: yellow
sdk: static
pinned: false
license: mit
---
# 每日运势 Web 应用

个人每日运势页面——根据八字与干支自动生成每天的宜、忌以及两人相处建议。

**设计风格**：老上海 Art Deco 装饰主义黄历——米色羊皮纸 + 深酒红 + 烫金，像一本 1920 年代上海限量版月份牌。

**在线访问**：https://leonxxl0606-daily-fortune.static.hf.space

## 特性

- **完全自包含**：单个 HTML 文件，无需后端、无需数据库
- **自动计算**：根据当天日期自动计算干支，结合八字生成宜忌
- **每日更新**：无需手动更新，打开即是当天运势
- **关系建议**：分别给 Leon 和星星提供针对性的相处建议
- **响应式设计**：手机优先，可添加到主屏幕像原生 App 一样使用
- **完全离线**：所有计算在浏览器本地完成，零网络请求

## 技术原理

1. **日柱计算**：以 2026年1月1日（乙亥日）为锚点，按 UTC 天数差推算当天干支
2. **八字比对**：将日柱与 Leon（庚辰/辛巳/乙亥/乙酉）和星星（甲申/癸酉/丙午/辛卯）的八字比对
3. **关系检测**：检测伏吟（地支相同）、相冲（六冲）、相合（六合）
4. **十神分析**：按五行生克与阴阳异同，计算流日天干相对日主的十神（比劫/食伤/财/官杀/印），确定宜忌方向
5. **场景组合**：根据两人当天的敏感度组合，生成不同的关系建议

## 本地运行

```bash
# 方法一：直接打开
# 双击 index.html 即可在浏览器中打开

# 方法二：本地服务器
python -m http.server 8000
# 然后访问 http://localhost:8000/index.html
```

## 部署到 Hugging Face Spaces

1. 打开 https://huggingface.co/spaces
2. 点击 **Create new Space**（新建 Space）
3. 填写：
   - **Space name**（名称）: `daily-fortune`（或你喜欢的名字）
   - **License**（许可证）: MIT
   - **Space SDK**: 选择 **Static**（静态站点）
4. 点击 **Create Space**
5. 上传 `index.html`

> **注意**：Space 中的 `README.md` 顶部必须保留 Hugging Face 的 YAML 配置头（`sdk: static` 等字段），否则 Space 会报 `CONFIG_ERROR` 并无法访问。

## 添加到手机主屏幕

- **iPhone**：Safari 打开 → 点击分享按钮 → "添加到主屏幕"
- **Android**：Chrome 打开 → 点击菜单 → "添加到主屏幕"

## 项目结构

```
daily-fortune/
├── index.html      # 主页面（包含所有 CSS 和 JavaScript）
├── LICENSE         # MIT 许可证
└── README.md       # 本文件
```

## 数据来源

- 八字数据：Leon 和星星的真实八字
- 干支历：基于万年历算法自动计算
- 节气：按常见公历日期近似显示（前后可能有一天误差，仅作展示）

## 许可证

MIT
