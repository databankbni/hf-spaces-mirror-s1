# 项目模板：小说创作工作流（Novel Writing Workflow）

> 一份"开箱即用"的小说协作项目模板。
> 用户新建项目时选择"小说创作" → 自动铺设好 8 个 Agent、8 个 Skill、8 个群聊（阶段）、27 个初始任务，
> 用户只需填入自己的题材、字数目标，AI 团队即可按流程推进。

---

## 0. 设计原则

1. **流水线思维**：把小说创作拆成可串行/并行的"工序"，每道工序对应一个**群聊**。
2. **角色专精**：每个 Agent 只做自己最擅长的事（不混用），通过**群聊 + 任务指派**完成协作。
3. **可裁剪**：所有阶段、任务都可以让用户改、删、加；模板是"起手式"，不是束缚。
4. **可复盘**：每个阶段都产出**可交付物**（大纲、人物卡、章节稿），并落到项目资源里。
5. **类型无关**：模板不绑定玄幻/言情/悬情等具体类型，由用户在阶段 1 里确定类型后，再让"风格润色师"载入对应风格。

---

## 1. 项目元信息

```json
{
  "template_id": "novel-writing",
  "name": "小说创作工作流",
  "description": "8 阶段流水线，从灵感孵化到出版准备，配备 8 名专属 Agent 与全套 Skill。",
  "cover_color": "from-amber-500 to-orange-600",
  "tags": ["writing", "novel", "long-form", "creative"],
  "config": {
    "expected_artifacts": ["一句话简介", "世界观设定", "人物档案", "主线大纲", "章节细纲", "章节正文", "审校报告", "出版物料"],
    "supported_genres": ["玄幻", "都市", "言情", "悬疑", "科幻", "历史", "武侠", "其他"],
    "default_length": { "min_chapters": 30, "max_chapters": 200, "words_per_chapter": 3000 }
  }
}
```

---

## 2. Agents（8 名）

> 全用 `role: "custom"` 避免占用内置 writer/critic 槽位，方便用户按需调整。

### 2.1 总览

| # | 名称 | role | 头像 | 主要职责 |
|---|---|---|---|---|
| A1 | 主编·墨言 | planner | 📋 | 全流程把控、阶段验收、对外定调 |
| A2 | 世界观架构师·筑界 | custom | 🌍 | 时代/地理/力量体系/历史/文化 |
| A3 | 人物设定师·塑魂 | custom | 👤 | 主角/配角/反派/人物弧光/关系网 |
| A4 | 故事架构师·织梦 | planner | 🏗️ | 主题/结构/三幕/章纲/伏笔 |
| A5 | 主笔作家·落笔 | writer | ✍️ | 章节正文、场景、对话 |
| A6 | 风格润色师·点墨 | editor | 🎨 | 文笔润色、风格统一、节奏调整 |
| A7 | 逻辑审校·较真 | critic | 🔍 | 设定冲突、时间线、剧情漏洞 |
| A8 | 读者代理·灯下 | critic | 📖 | 模拟读者反馈、节奏评估、市场视角 |

### 2.2 系统提示词（精简版）

> 完整版在 `default_presets/agents/novel-writing/*.md` 里引用，每个 agent 的 `system_prompt` 字段填 markdown。

**A1 主编·墨言**
```
你是小说的主编与总策划。
你的职责：
1. 把控整体方向，验收每个阶段的交付物
2. 协调不同 Agent 的工作冲突（世界观 vs 人物 vs 故事）
3. 在阶段切换时决定是否推进（auto_advance 仍由你说了算）
4. 对外（用户）汇报进展，调用 send_message 保持沟通
工作风格：简洁、结构化、决断力强；偏好以列表/表格呈现方案；
倾向把任务拆解为可验收的小项；遇到重大抉择先抛 2-3 个方案让用户拍板。
禁止：不要替其他 Agent 做他们专业领域的事（如不要写正文）；不要在没有交付物的情况下推进。
```

**A2 世界观架构师·筑界**
```
你是世界观/设定的架构师。
你的职责：把"故事的土壤"建立起来——时代、地理、力量体系、社会结构、历史脉络、文化习俗。
输出物偏好：地图（map 视图）、体系规则表（table 视图）、编年史（timeline 视图）。
要求：
- 内部自洽（先写规则、再用规则约束事件）
- 给后续 Agent 留接口（世界规则要标 ID，方便人物/剧情引用）
- 体系不能太复杂——30% 的体系被主笔用到已经足够
禁止：不要写人物，不要写剧情。
```

**A3 人物设定师·塑魂**
```
你是人物设定师。
你的职责：为主角、配角、反派建立"人物卡"——
  1. 基本信息（名字/年龄/身份/外表）
  2. 性格（不要"勇敢/善良"这种标签，给可观察的行为倾向）
  3. 动机（想要的 vs 需要的——这是人物弧光的核心）
  4. 人物弧光（起点状态 → 关键转折 → 终点状态）
  5. 人物关系（与其他角色的冲突/羁绊/对立）
输出物：人物卡（card 视图）、人物关系图（tree 或 map 视图）。
要求：每个主要人物必须有"一个可被读者记住"的细节癖好。
禁止：不要写剧情，不要预设结局。
```

**A4 故事架构师·织梦**
```
你是故事架构师。
你的职责：把"故事的骨架"立起来——
  1. 主题（一句话内核）
  2. 结构（三幕/起承转合/英雄之旅，按题材选）
  3. 主线关键事件序列（开端→激励事件→第一幕高潮→中点→第二幕高潮→高潮→结局）
  4. 副线与暗线（伏笔表、悬念表）
  5. 章节级大纲（每章钩子、POV、情绪曲线）
输出物：节拍表（timeline 视图）、伏笔表（table 视图）、章节目录（list 视图）。
要求：
- 主线事件必须能在 1-2 句话内说清
- 每章结尾必须有"钩子"（悬念/反转/情感波动）
- 伏笔与回收要成对登记
禁止：不要写正文（500 字以上的成文写作），不要写人物卡。
```

**A5 主笔作家·落笔**
```
你是一名小说作者。
你的职责：根据章节细纲写出成文章节。
风格：遵循项目"风格指南"资源；保持章节 2500-4000 字；场景切换清晰；对话占比 30-50%。
技术：
- 用"展示而非告诉"——角色通过动作/对话表达情绪，不要直接说"他很伤心"
- 节奏：动作场景短句快切；情绪场景多感官铺陈
- 章节开头承接上一章钩子；结尾抛出新钩子
- POV 严格遵守（除非明确切换）
- 持续追踪已有资源（人物卡、世界观、章纲）确保一致性
工具用法：每章写完后用 write_resource 存为 resource（type=note, tags=第N章），
  并用 render_view 的 document 视图在群里展示。
禁止：不要擅自改大纲；不要重写设定。
```

**A6 风格润色师·点墨**
```
你是文字润色师。
你的职责：在主笔完成初稿后，进行二轮加工——
  1. 修辞打磨：动词精确化、删除冗余副词、对话去翻译腔
  2. 节奏调整：长句拆短、短句间插入感官细节
  3. 风格统一：与项目风格指南（资源）保持一致
  4. 删除作者腔（"突然""竟然""不禁"等口水词）
输出：在原文基础上做最小修改——不重写结构，只改表达。
反馈方式：列出"修改点 + 理由"，方便用户/主笔 review。
工具：read_file 读原稿 → write_file 写新稿（保留版本号 v2/v3）→ 用 render_view 对比。
禁止：不要改情节，不要动人物弧光。
```

**A7 逻辑审校·较真**
```
你是逻辑/一致性审校。
你的职责：在每一阶段都做"较真"——
  - 大纲阶段：节拍表是否连贯、伏笔是否能回收、人物动机是否支撑行为
  - 章节阶段：人物前后言行是否一致、时间线是否冲突、设定规则是否被违反
  - 全文阶段：跨章一致性（人物年龄、季节、地理距离、力量体系限制）
输出：检查报告（table 视图：位置 | 问题 | 严重度 | 建议）
原则：先列问题，再给建议；不在群里争论；问题分级（致命/重要/小）。
禁止：不要润色文笔，不要替主笔重写。
```

**A8 读者代理·灯下**
```
你是模拟读者 + 市场视角。
你的职责：
  1. 代入目标读者（按项目类型设定）阅读大纲/章节
  2. 给出"代入反馈"——哪里猜到了、哪里被打动、哪里走神、哪里不解
  3. 评估节奏曲线（情绪点是否到位、高潮前是否有足够铺垫）
  4. 出版阶段：起书名、写简介、找卖点
输出：反馈报告（list 视图：章 | 反馈 | 评分 1-5）。
原则：诚实、不迎合；说出"作为读者我真的会 X"而不是"作者可能想表达 Y"。
禁止：不要给文学建议（那是润色师的事）；不要改稿。
```

### 2.3 Agent 工具配置

| Agent | 工具 | 备注 |
|---|---|---|
| A1 主编 | send_message, list_groups, get_group, update_group, list_tasks, create_task, update_task_status, list_deliverables, write_resource, render_view | 几乎全工具但只用"管理类" |
| A2 筑界 | write_file, read_file, write_resource, search_resources, render_view | 主要是写+展示 |
| A3 塑魂 | write_file, read_file, write_resource, search_resources, render_view | 同上 |
| A4 织梦 | write_file, read_file, write_resource, search_resources, render_view, query_history | 频繁回看世界观/人物 |
| A5 落笔 | write_file, read_file, write_resource, search_resources, query_history, create_memory, get_memory, render_view | 记忆系统最关键 |
| A6 点墨 | write_file, read_file, search_resources, render_view | 只读+写 |
| A7 较真 | write_file, read_file, search_resources, query_history, write_resource, render_view | 需要跨章搜索 |
| A8 灯下 | write_file, read_file, search_resources, web_search, fetch_url, write_resource, render_view | 出版阶段联网调研 |

### 2.4 Agent 绑定 Skill

| Agent | 绑定的 Skill |
|---|---|
| A1 主编 | story-structure, character-arc, pacing-rhythm |
| A2 筑界 | style-guide, continuity-check |
| A3 塑魂 | character-arc, style-guide |
| A4 织梦 | story-structure, pacing-rhythm, continuity-check |
| A5 落笔 | show-dont-tell, dialogue-craft, chapter-format, style-guide |
| A6 点墨 | show-dont-tell, dialogue-craft, style-guide, chapter-format |
| A7 较真 | continuity-check, pacing-rhythm |
| A8 灯下 | pacing-rhythm, style-guide |

---

## 3. Skills（8 个）

> `skill_type: "prompt"`，内容用 markdown 写"该如何做"。

### S1. `story-structure`（剧情结构）
**描述**：三幕结构、起承转合、英雄之旅、节拍表等结构工具速查。
**内容要点**：
- 8 种主流结构对比表
- 每种结构的关键节拍、转折点位置（百分比）
- 伏笔设计原则（契诃夫之枪、Fichtean curve）
- 何时用哪种结构（按题材给推荐）

### S2. `character-arc`（人物弧光）
**描述**：人物设计的核心方法论。
**内容要点**：
- 想要的 vs 需要的（人物成长核心）
- 4 种主要弧光类型（正向/负向/平直/转化）
- 人物卡 9 要素模板
- 人物关系网 6 类关系（盟友/对手/镜像/过去/诱饵/门槛）
- 配角工具箱（spanner in the works, yes-but, no-and）

### S3. `show-dont-tell`（展示而非告诉）
**描述**：小说写作最常用的修辞指导。
**内容要点**：
- 12 个常见"告诉"反模式（他很伤心/她很漂亮/他很勇敢…）
- 替代示例：动作替代、对话替代、感官替代
- 情绪词典：把"伤心"具体化为可观察行为
- 视角控制：通过 POV 角色滤镜展示

### S4. `style-guide`（风格指南）
**描述**：根据小说类型加载对应风格。
**内容要点**：
- 6 种主流文风对比（白描、华丽、冷硬、温情、悬疑、幽默）
- 每种文风的标志性手法、用词偏好、句式特征
- 如何在群里调用：润色师先 read_skill，再依此润色
- 用户可在项目资源里覆盖

### S5. `chapter-format`（章节格式）
**描述**：标准章节结构。
**内容要点**：
- 章节四段式：钩子承接 → 场景推进 → 转折/冲突 → 钩子抛出
- POV 切换规则（位置标记、密度）
- 章节信息密度曲线（开头松 → 中段密 → 结尾松）
- 章节标题/分隔符规范

### S6. `dialogue-craft`（对话技巧）
**描述**：写好对话的完整方法。
**内容要点**：
- 好的对话 5 标准：揭示性格 / 推进剧情 / 提供信息 / 制造冲突 / 潜台词
- 避免"说明对话"——别让角色念旁白
- 节奏：长对白与短对白交错
- 方言/口头禅设计

### S7. `pacing-rhythm`（节奏把控）
**描述**：把握全书的情绪与节奏。
**内容要点**：
- 5 种基本情绪曲线（上升/下降/V/W/楼梯）
- 张力与释放的交替（pumpkin coach 原理）
- 信息密度调节（紧张场景：短句+白描；情绪场景：长句+感官）
- 章节级与全书级两条节奏线

### S8. `continuity-check`（一致性检查）
**描述**：审校时该看哪些维度。
**内容要点**：
- 人物：外貌、年龄、能力、口头禅、人物关系
- 时间：季节、昼夜、节日、寿数
- 空间：地理距离、行程时间
- 设定：力量体系规则、社会规则
- 伏笔：是否被回收
- 跨章搜索关键词的方法（`search_files`）

---

## 4. 群聊 / 阶段（8 个）

> 顺序执行（`auto_advance=True`），用户可在任意阶段手动中断或跳回。

### G1 · 灵感孵化（Ideation）
- **描述**：把"想写个故事"变成"清晰的项目立项"。
- **主导 Agent**：A1 主编
- **参与者**：A1, A4, A8
- **自主级别**：semi_auto
- **任务**：
  - T1.1 主题与核心冲突（A4 主导）— 输出"主题陈述 + 核心冲突 + 类型 + 一句话简介"
  - T1.2 类型与受众分析（A8 主导）— 同类作品 3-5 部、受众画像、市场判断
  - T1.3 立项书（A1 主导）— 整合 T1.1 + T1.2，输出"项目立项书"（资源）
- **交付物**：项目立项书（type=reference, is_required=true）

### G2 · 世界观设定（World Building）
- **描述**：把"故事的土壤"立起来。
- **主导 Agent**：A2 筑界
- **参与者**：A1, A2, A8
- **自主级别**：semi_auto
- **任务**：
  - T2.1 时代与地理（A2）— 时代背景、版图、关键场景地图（map 视图）
  - T2.2 力量/科技体系（A2）— 体系规则表（table 视图），每条规则标 ID
  - T2.3 历史与文化（A2）— 编年史（timeline 视图）、社会结构、宗教习俗
  - T2.4 自检（A1）— 内部自洽性、可被主笔用到的占比 ≥ 30%
- **交付物**：世界观手册（type=guideline, is_required=true）

### G3 · 人物档案（Character Profiles）
- **描述**：立人。
- **主导 Agent**：A3 塑魂
- **参与者**：A1, A3, A4
- **自主级别**：semi_auto
- **任务**：
  - T3.1 主角卡（A3）— 主角 1-2 名，每人完整 9 要素 + 人物弧光
  - T3.2 配角与反派卡（A3）— 重要配角 3-5 名 + 反派 1-2 名
  - T3.3 关系图与冲突矩阵（A3）— 关系网（tree）+ 冲突表（table）
  - T3.4 大纲预对齐（A4）— 检验人物是否支撑主线事件
- **交付物**：人物卡集（type=reference, is_required=true）

### G4 · 主线大纲（Plot Outline）
- **描述**：立骨架。
- **主导 Agent**：A4 织梦
- **参与者**：A1, A4, A3
- **自主级别**：semi_auto
- **任务**：
  - T4.1 结构选型（A4）— 选定结构（三幕/起承转合/英雄之旅…），关键节拍表（timeline）
  - T4.2 主线事件序列（A4）— 8-12 个关键事件 + 因果链
  - T4.3 副线与暗线（A4）— 副线 1-2 条、伏笔表（table）
  - T4.4 逻辑自检（A7）— 因果链是否成立、伏笔是否能回收
- **交付物**：主线大纲（type=reference, is_required=true）

### G5 · 章节细纲（Chapter Breakdown）
- **描述**：把骨架拆成章节。
- **主导 Agent**：A4 织梦
- **参与者**：A1, A4, A5, A7
- **自主级别**：semi_auto
- **任务**：
  - T5.1 分卷（A4）— 分成 2-4 卷，每卷主题、节奏曲线
  - T5.2 章节目录（A4）— 30-200 章，每章：标题/POV/钩子/情绪曲线/字数
  - T5.3 重点章细纲（A4）— 高潮/转折/开场/结尾章的详细细纲
  - T5.4 大纲自检（A7）— 跨章人物/时间线一致性
- **交付物**：章节大纲集（type=reference, is_required=true）

### G6 · 章节正文（Chapter Drafting）
- **描述**：写正文。**这是动态任务群**——每章一个任务，由主笔发起。
- **主导 Agent**：A5 落笔
- **参与者**：A5, A6, A7
- **自主级别**：full_auto（可让主笔一气呵成）
- **任务（每章）**：
  - T6.x 章节写作（A5）— 写本章正文 2500-4000 字
  - T6.x+1 初稿自校（A5）— 写完后立即对照章纲、人物卡自检
  - T6.x+2 风格润色（A6）— 对初稿做最小化润色
  - T6.x+3 一致性检查（A7）— 跨章一致性
- **特殊机制**：主编在每 10 章后触发"中期评审"（召集 A4+A7+A8 一起回看节奏）
- **交付物**：每章正文稿（type=note, tags=第N章）

### G7 · 审校润色（Editing & Polishing）
- **描述**：全稿质量提升。
- **主导 Agent**：A6 点墨
- **参与者**：A1, A6, A7, A8
- **自主级别**：manual（每轮都要主编确认）
- **任务**：
  - T7.1 全文一致性检查（A7）— 输出问题清单（致命/重要/小）
  - T7.2 全文文笔润色（A6）— 风格统一、口水词清理
  - T7.3 读者反馈与节奏评估（A8）— 代入目标读者阅读、给反馈
  - T7.4 修订循环（A1 主导）— 根据 T7.1-7.3 决定是否回到 G6 修订
- **交付物**：审校报告 + 终稿

### G8 · 出版准备（Publishing Prep）
- **描述**：上架前的物料。
- **主导 Agent**：A1 主编
- **参与者**：A1, A8
- **自主级别**：semi_auto
- **任务**：
  - T8.1 书名与简介（A8）— 5 个备选书名 + 200/500/1000 字简介
  - T8.2 卖点与营销（A8）— 3-5 个卖点、目标平台分析（web_search）
  - T8.3 封面概念（A1）— 概念描述（颜色/意象/构图/推荐语）
- **交付物**：出版物料包（type=custom）

---

## 5. 项目级资源（5 个，模板自带的"地基"）

> 这些资源由模板创建，用户可改。

| 标题 | type | is_required | 用途 |
|---|---|---|---|
| 项目立项书 | reference | true | G1 完成后由 A1 写入；后续 Agent 必读 |
| 写作风格指南 | guideline | true | S4 style-guide 的具体化（用户可定制） |
| 人物卡片模板 | guideline | true | 9 要素卡片的 markdown 模板 |
| 章节格式模板 | guideline | true | 章节开头/结尾/POV 切换的统一格式 |
| 一致性检查清单 | rule | true | S8 的具体化——份维度清单 |

---

## 6. 群聊推进流程图

```
G1 灵感孵化 ─→ G2 世界观 ─→ G3 人物档案 ─→ G4 主线大纲 ─→ G5 章节细纲
                                                            ↓
                                                       G6 章节正文（循环）
                                                            ↓
                                                       G7 审校润色
                                                            ↓ (可回 G6 修订)
                                                       G8 出版准备
```

**自动推进规则**：
- G1-G5、G8：`auto_advance=True`（主编确认验收后自动到下一阶段）
- G6：`auto_advance=False`（每章都是独立任务，不由群聊自动推进）
- G7：`auto_advance=False`（审校需主编手动拍板）

**回退机制**：
- 任意阶段 A7 较真可触发"回退"——把群聊 status 重置为 active，让对应 Agent 重新工作

---

## 7. 实施建议（How to build）

### 7.1 数据来源

把模板定义为一份**项目资产包 JSON**（基于现有 `ProjectBundleMode=template` 模式）：

```
default_presets/project_templates/novel-writing/
├── template.json            # 元信息 + Agent 列表 + Skill 列表
├── agents/
│   ├── chief_editor.json    # 含 system_prompt
│   ├── world_architect.json
│   ├── ...
├── skills/
│   ├── story-structure.json
│   ├── ...
├── groups/
│   ├── G1_ideation.json     # 含任务列表
│   ├── G2_world.json
│   ├── ...
└── resources/
    ├── style_guide.md
    ├── character_template.md
    └── ...
```

### 7.2 触发入口

在 `CreateProjectModal` 增加"从模板创建"Tab，列出可用模板：
- 小说创作工作流
- （未来）市场调研报告
- （未来）产品 PRD 协作
- （未来）短剧/剧本
- （未来）课程设计

### 7.3 落库流程

```
1. 用户点"从模板创建"
2. 后端读 template.json → 解析 agents/skills/groups/tasks/resources
3. 事务内依次：
   a. 写入 Project
   b. 写入 Skills（按 name 查重，已存在则复用）
   c. 创建 ProjectAgent（关联 Agent → 绑定 Skill）
   d. 创建 Groups（按 order_index 排序）
   e. 在每个 Group 下创建 Tasks
   f. 创建项目级 Resources
4. 跳转到项目首页，用户可见完整的 8 阶段布局
```

### 7.4 复用策略

- Skills 是全局资源，**模板只引用，不复制**。
- Agents 是全局资源，模板也**只引用**（通过 `template_agent_refs` 数组），用户可对每个项目做 override_config。
- Groups / Tasks / Resources 才是项目级的，模板携带完整内容。

### 7.5 未来扩展

- **多模板商店**：模板放成可分享资产包（zip），用户可上传/下载社区模板
- **模板预览**：点击模板后显示"包含 8 个 Agent、27 个任务、5 份资源"的预览
- **模板派生**：用户改完模板后导出为自己的模板
- **AI 推荐**：根据用户填的"项目名"+"描述"让 LLM 推荐最合适的模板

---

## 8. 验收 Checklist（实施时自测）

- [ ] 模板 JSON 校验脚本（schema + 引用闭环）
- [ ] 一键创建项目 → 数据库中可见 8 Agent / 8 Skill / 8 Group / 25 Task / 5 Resource
- [ ] 每个群聊的 lead_agent / members 正确绑定
- [ ] 每个 Agent 的 tools / skills 正确绑定
- [ ] 项目首页按 order_index 顺序展示 8 个阶段
- [ ] 阶段 1-5、8 完成后可自动推进到下一阶段
- [ ] 阶段 6（章节正文）能按章循环创建任务
- [ ] 阶段 7（审校）触发"回退到 6"机制
- [ ] 模板中所有跨 Agent 引用（lead_agent_id → ProjectAgent）解析正确
- [ ] 模板版本号 + 升级机制（用户已用旧模板创建的项目能否升级）

---

## 9. 配套 UI 建议

- 项目首页：8 个群聊卡片按时间轴/流水线排版，每个卡片显示进度（x/y 任务完成）
- 阶段切换动效：进度条推进 + 顶部"当前阶段"高亮
- 任务面板：在每个群聊页内显示当前阶段的所有任务
- 全局资源侧栏：立项书/风格指南/人物卡可一键置顶
- "中期评审"按钮：在 G6 章节正文阶段，主编可一键召唤 A4+A7+A8 开评审会

---

## 10. 与现有系统的映射

| 设计元素 | 现有模型 | 字段 |
|---|---|---|
| 项目 | Project | name, description, cover_color, tags, workflow_config |
| Agent | ProjectAgent + Agent | system_prompt, llm_config, tools, skills |
| Skill | Skill | name, content, skill_type=prompt |
| 群聊 | Group | name, lead_agent_id, autonomy_level, auto_advance, order_index |
| 任务 | Task | title, description, lead_agent_id, status, order_index, acceptance_criteria |
| 资源 | Resource | title, content, type, tags, is_required |
| 阶段推进 | Group.status (pending→active→completed) + auto_advance | — |
| 任务指派 | TaskAssignee | project_agent_id |
| 记忆 | Memory (via create_memory tool) | agent_id, project_id, content |

> 模板落地**不需要新加表**，全部用现有 schema。
