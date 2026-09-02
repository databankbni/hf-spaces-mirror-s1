# CS2 V3 Sonnet vs Gemini 3.5 Flash

十个相同的 81 帧 CS2 clip，按 frame 0 conditioning + 五个固定 16 帧窗口对照旧 Sonnet v3 与新的 Gemini 3.5 Flash v3 重跑。

- 配对数：10；固定窗口：50。
- Gemini schema clean：10/10；固定五段边界：10/10。
- 英文场景平均词数：Sonnet 149.4（折算每窗口 29.9），Gemini 475.1；Gemini 每窗口平均 95.0 词。
- 旧 Sonnet 结果的 segments 均为 whole-clip 单段（10/10）；网页明确标注此基线差异。
- Gemini 请求包含局部 chunk 图片：9/10；未包含：1/10（重试或网关限制）。

网页按五个固定 chunk 分行，显示局部证据图、Gemini 的中英文段落、Sonnet 的 legacy whole-clip 基线和动作时间重叠；总体场景文本提供差异高亮。
