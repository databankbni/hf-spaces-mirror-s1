# 05 · 多 Agent 流水线编排设计记录

> 本文档记录 **2026-06-11** 关于"多 agent 流水线 / 跨群调度"的设计讨论要点,
> 含**核心设计原则、纠偏记录、当前 schema 通用化位、已落地决策、待定方向**。
> 目的是防遗忘——讨论中走偏的反思和未落地的方向不应丢失。

---

## 1. 核心设计原则 (重要程度 ★★★★★)

> 这些原则在讨论中反复出现, 是用户的设计哲学, 优先级最高。

### 1.1 "平台提供通用能力, 项目决定如何推进"

- **平台**只提供**通用原子能力** (创建群/agent、调工具、订阅事件、render_view)
- **项目模板 + project agent** 决定**具体怎么用**这些能力
- 平台**不**:
  - 在 agent system_prompt 里硬编码 "G1→G2→G3→…"
  - 在 orchestrator 里硬编码"上一群结束下个群开始"
  - 在 executor 里硬编码关键词触发行为
- 平台**可以**:
  - 提供 schema 字段 (`workflow_config` / `autonomy_hint`) 让项目**自己**填
  - 提供原子工具让 agent **自己**组合
  - 提供事件订阅让 agent **自己**决定怎么响应

### 1.2 不要硬编码 (尤其是流程)

- **代码层硬编码** = bug 隐患 (关键词匹配、按 agent 名字分发、按 role 分支)
- **提示词层硬编码** = 提示词优化范畴, **按需**做, 不在本原则强制范围
- 区分这两个层面:
  | 层面 | 例子 | 处理 |
  |---|---|---|
  | 代码 | `if "流程编排" in capabilities` | **禁止**, 用显式字段替代 |
  | 提示词 | "G1→G2→G3→…→G8" | 视项目需求, 可接受 |

### 1.3 第一性原理: 思考整个项目各个节点间的关系

- 改一处要**上下游都过一遍**: model ↔ schema ↔ service ↔ executor ↔ template
- 区分 **框架思考不合理** vs **场景考虑不周全**:
  - 框架不合理 → 改 framework (机制层)
  - 场景不全 → 改 schema / prompt (配置层)
- "加补丁"不如"修框架": 当同一个问题反复出现, 思考是不是 framework 缺机制

### 1.4 通用能力的优越性

- 通用设计 = 各种场景都能合理表达, **不**为每个场景写特化代码
- 平台提供"原子"而非"超级"工具——`create_group` 比 `advance_pipeline` 通用
- agent 自由组合原子工具 > 平台预编排流程

---

## 2. 纠偏记录 (讨论中走偏被纠正的)

### 2.1 ❌ 错把"通用化"当"新架构"

- **错**: 我提"动态 pipeline + 对话生成 + 可视化" → 称为"新架构"
- **正**: 现有 framework 已经有 `Project.workflow_config` / `autonomy_hint` /
  `Group.auto_advance` / 原子工具 / `render_view` —— **不用新加机制**, 只需要
  agent 学会用它们
- **教训**: 看到"通用化"先问"现有 schema/工具够不够", 别急着"新架构"

### 2.2 ❌ 误判 `map` view 适合画流程图

- **错**: 我说 "map view 支持 nodes/connections, 画流程图够用"
- **正**: map 是**空间地图/棋盘**风格 (`grid: {cols,rows}` + `territories` 占 `cells` +
  `connections` 路径) —— 适合画地图/航线/网络拓扑, **不适合**流程图
  - 缺 `level / depth / alignment` 概念
  - DAG 节点都平铺在 grid, 并行/合流画不出来
- **教训**: 引用 schema 前**真读** `render_processors.py:93-97`, 别凭印象判断
- **候选方案**:
  - 短期: `timeline` (线性) + `tree` (树形) 组合
  - 中期: 加 `view_type: "graph"` 真正支持 DAG
  - 临时: `document` view 的 `content` 字段嵌 Mermaid 字符串 (agent 写 Mermaid 不友好)

### 2.3 ❌ 提"超级工具" `advance_to_next_group`

- **错**: 我提议加 `advance_pipeline(current_id)` 这种封装完整流程的 tool
- **正**: 平台提供 `create_group` / `update_group` / `send_message` / `subscribe_event`
  等原子工具, **让 agent 自己组合**; coordinator 想推进流水线, 就
  `list_groups` → `update_group(next, active)` → `send_message(lead)` 三步调
- **教训**: 工具粒度——平台给**原子**, 编排**项目决定**; 别把"流程封装"塞进平台

### 2.4 ❌ 提"硬编码关键词"判断 `force_tool_choice`

- **错**: 在 `agent_executor.py` 里 `if "流程编排" in capabilities: force = True`
- **正**: Agent model 加 `force_tool_choice: bool` 字段, 模板里**显式声明**
  (`"force_tool_choice": true`), executor 读这个字段
- **教训**: 用 capability 文本"暗示"技术行为 = 把两件事错配, 该用显式字段

### 2.5 ❌ 误把"串行假设"当底层逻辑

- **错**: 默认"上一群结束 → 下一群开始"是平台假设
- **正**: 平台**不**做这个假设, 本质**支持并行**, 可退化为串行
- **教训**: 区分"平台机制"和"模板约定"; 模板选了串行, 平台不锁死

---

## 3. 当前 schema 已经为通用化留好位 (重要)

| 字段 | 模型 | 类型 | 用途 | 现状 |
|---|---|---|---|---|
| `Project.workflow_config` | Project | JSON | 工作流配置 (反馈机制、调度策略) | ✓ 已存在 |
| `Project.autonomy_hint` | Project | str | **自然语言** hint, agent 自己解读 | ✓ 已存在 |
| `Project.review_mode_hint` | Project | str | review 模式 hint | ✓ 已存在 |
| `Group.auto_advance` | Group | bool | 完成后自动推进 | ✓ 已存在 + `autonomy_controller` 在用 |
| `Group.workflow_config` | Group | JSON | 群级配置 | ⚠ context_builder 期望但 model 缺字段 (预留) |
| `Agent.force_tool_choice` | Agent | bool | 强制首轮 LLM 调工具 | ✓ 已加 (本次) |

注释原文 (`project.py:88`):
> "agent 自己解读" / "agent 自由选择"

**这正是用户"通用能力 + 项目决定"的设计** —— schema 已落地, 不需要新加。

---

## 4. 已落地的关键决策 (本轮)

### 4.1 跨群调度机制: 任务内"汇报"模式

- 每个群 `decomposition_rules` 末尾追加 "收尾必做: 开 task '汇报给项目总控'"
- lead 完成时调 `send_message` @ coordinator + `update_task_status(done)`
- **不**用新平台机制, 复用现有群任务/talk 工具

### 4.2 项目级 agent: `项目总控·编舟` (通用编排者, 非调度器)

- **v2 P2 重定位**: 不再是"项目内置调度器, 收汇报后按 G1→G2 推进", 而是"项目级对话+编排 agent", 跟用户聊收需求, 构造 pipeline, 渲染确认, 调原子工具搭建, 订阅 group_status_changed 推进
- system_prompt 详见 `app/default_presets/agent_templates/coordinator.json`
- `force_tool_choice: true` —— 强制 LLM 调工具 (不允许只回文本不动状态)

### 4.3 字段化机制: `Agent.force_tool_choice` (本次)

- **模型**: Agent 加 `force_tool_choice: bool` 默认 false
- **DB migration**: `ALTER TABLE agents ADD COLUMN force_tool_choice INTEGER NOT NULL DEFAULT 0`
- **template 同步**: `template_service._upsert_agents` 同步该字段
- **executor**: `agent_executor.py` 创建 `FlowAgent` 时读 `agent.force_tool_choice` 传入
- **删除**: 原硬编码关键词 `_FORCE_TOOL_CHOICE_KEYWORDS` 完全删除

### 4.4 空白项目 + 模板项目自动建出 coordinator (本次)

- 空白项目 (`POST /projects`): `ProjectService.create_project` 调用 `_ensure_project_coordinator`
- 模板项目 (`POST /templates/apply`): `TemplateService.apply_template` 在 step 6.6 同样调用
- **统一从 `default_presets/agent_templates/coordinator.json` 加载**, 不在每个模板里硬塞 coordinator 副本
- 幂等: 多次创建项目不会产生重复 agent / ProjectAgent
- 兜底: bootstrap 失败不阻断项目创建 (用户可手动建)
- novel-writing 模板中旧的 `项目总控·编舟` entry 替换为 `__placeholder_for_legacy_coordinator__` (skip=true) 占位, 避免和 default 重复维护

### 4.5 `view_type: "graph"` 通用 DAG (本次)

- `render_processors.py` 加入 `graph` 到 `VIEW_TYPES`
- 数据结构: `data.nodes=[{id, label, type, data}]` + `data.edges=[{source, target, label, style, condition}]`
- `options`: `layout` (lr/tb/td/radial), `directed`, `node_render` (按 type 查表), `edge_render` (按 style 查表)
- **通用性**: 不只项目流水线, 可用于任务依赖 / 知识图谱 / Agent 协作图 / 任何 DAG
- 文档+示例: `app/default_presets/skills/render_view/examples/graph.md` (新建)
- `tool_catalog.render_view` 描述更新 (8 → 9 视图类型)

### 4.6 Pipeline 文件: 渲染 + 阅读一套 (本次)

- **1 个文件 per pipeline** (运行时由 agent 创建, 项目资源 `Resource` 表, `content_type=json`, `resource_type=map`, `tags=[pipeline, orchestration]`)
- **同一份 content**:
  - 调 `read_resource(...)` 给 agent 读回作为流程指南
  - 调 `render_view(view_type="graph", data=<parsed>)` 给用户看
- **不冗余**: 没有第二份"pipeline spec 文件", 渲染 = 阅读 = 推进 = 同一份
- **不加专用 tool**: agent 用现有 `write_resource` / `read_resource` / `render_view`, 不开 `create_from_pipeline` 之类特化工具
- **schema 不在代码层强校验**: 由 coordinator system_prompt 描述 + graph view_type 结构文档共同约束, 保持通用性

---

## 5. 待定 / 未来方向 (未做, 别忘)

### 5.1 空白项目入口 — **已存在, 不需要改**

> 2026-06-11 纠错: 此节原写"待定, 需 API 加 template_id=null 字段", **错**.
> 查证后现状已支持, 两个独立入口:
>
> | 入口 | 行为 | 位置 |
> |---|---|---|
> | `POST /projects` | 直接建**纯空白**项目 (无 group/agent) | `app/api/v1/projects.py:42` |
> | `POST /templates/apply` | 走模板建完整项目 (含 group/agent/task) | `app/api/v1/templates.py:51` |
>
> schema 也无 `template_id` 字段 (`ProjectCreate` 只有 name/description/tags/...)
> 模板和空白已经是**两个分离的 API**, 不需要再合.

**v2 P2 进展**: 空白项目建出后**自动**建出 project agent (`ProjectService._ensure_project_coordinator`), 不再需要"用户自己建 coordinator". 详见 §4.4.

### 5.2 coordinator 重定位 — **✅ 已落地 (v2 P2)**

- system_prompt 删 "G1→G2→G3→…→G8" 硬编码
- 改为**通用编排协议**:
  1. 读 `project.workflow_config` 拿项目级策略
  2. 读 `project.autonomy_hint` / `review_mode_hint` (自然语言)
  3. 和用户对话收需求
  4. 构造 pipeline 结构 (nodes + edges, edges.from/to 支持数组 = 并行)
  5. 调 `render_view(view_type="graph", data=pipeline)` 可视化
  6. 用户确认后, 调原子工具 `create_group` / `create_agent` / `invite_agent` / `update_group`
  7. 群完成事件: 订阅 `group_status_changed`, 重渲染

**落地文件**:
- `app/default_presets/agent_templates/coordinator.json` (新建, **唯一 prompt 源**)
- `app/services/project_service.py:_ensure_project_coordinator` (空白项目 bootstrap)
- `app/services/template_service.py:apply_template` (step 6.6, 模板项目 bootstrap)
- `app/default_presets/project_templates/novel-writing/agents.json` (旧 coordinator 替换为 `__placeholder_for_legacy_coordinator__` skip=true)

### 5.3 pipeline 文档 schema — **✅ 已落地 (v2 P2, 1 文件/项目, 0 冗余 spec 文件)**

- **格式选 JSON** (实际是 `Resource.content` 存的 JSON 字符串, agent 直接构造/解析)
- **1 个文件 per pipeline**: `Resource` 表行, `title='项目流水线'`, `content_type=json`, `resource_type=map`, `tags=[pipeline, orchestration]`
- **同一份 content = 渲染源 = 阅读源 = 推进决策源**, 渲染+阅读+推进统一来源
- 完整 schema 文档:
  - coordinator system_prompt 描述 (`default_presets/agent_templates/coordinator.json`)
  - graph view_type 数据结构 (`app/default_presets/skills/render_view/examples/graph.md`)
- **不加 pydantic schema** (代码层强校验), agent 自由构造, 文档约束

**草案** (示例, 实际由 agent 自由构造):
```json
{
  "view_type": "graph",
  "title": "项目流水线",
  "data": {
    "version": 1,
    "nodes": [
      {"id": "g1", "label": "灵感孵化", "type": "group", "data": {"lead_agent": "灵感缪斯·启明", "description": "..."}},
      {"id": "g2", "label": "世界观设定", "type": "group", "data": {"lead_agent": "世界织者·经纬", "description": "..."}}
    ],
    "edges": [
      {"source": "g1", "target": "g2", "label": "完成后", "style": "solid"}
    ]
  }
}
```

### 5.4 加 `view_type: "graph"` — **✅ 已落地 (v2 P2)**

- `render_processors.py:VIEW_TYPES` 加入 `"graph"`
- 数据结构: `data.nodes=[{id, label, type, data}]` + `data.edges=[{source, target, label, style, condition}]`
- options: `layout` (lr/tb/td/radial), `directed`, `node_render` (按 type 查表), `edge_render` (按 style 查表)
- 通用 DAG, 不只项目流水线

### 5.5 补 Group.workflow_config 字段 — **✅ 已落地 (v2 P2)**

- `Group` model 加 `workflow_config: JSON` 默认 `{}` (同 `Project.workflow_config` 一致)
- DB migration: `ALTER TABLE groups ADD COLUMN workflow_config JSON NOT NULL DEFAULT '{}'`
- context_builder `format_for_llm` 用 `getattr(group, 'workflow_config', None) or {}` 安全读 → 现在能拿到真值 (之前 model 缺字段, 一直走空 dict fallback)
- 结构自由约定:
  ```json
  {
    "execution_variant": "A",          // ExecutionModeService A/B 测
    "pipeline_node_id": "g3",           // 关联项目 pipeline 资源
    "feedback_overrides": {...}         // 群级覆盖项目级 feedback
  }
  ```
- **不强校验 schema**, 由 agent / 模板 / 工具自由写

### 5.6 反馈机制配置化 — **✅ 已落地 (v2 P2, 无新平台机制)**

按"原子工具 + 项目决定"原则, **不加平台层推进逻辑**。3 种 mode 都用现有工具实现, agent 读 `project.workflow_config.feedback` 决定走哪条:

| mode | 机制 | 工具 | 适用 |
|---|---|---|---|
| `subscribe` (默认) | 订阅 `group_status_changed` → 系统唤醒 agent | `subscribe_event` | 大多数项目 |
| `report_task` | lead 主动 `send_message` @ coordinator, 消息含 `[群 X 汇报]` 触发 | `send_message` | 小项目 / 人工把关 |
| `auto` | subscribe + 静默 + 读 `group.auto_advance` | `subscribe_event` + `update_group` | `autonomy_hint='full_auto'` 项目 |

**落地**:
- coordinator.json §"反馈机制" 加 3 mode 详细文档 + 切换规则
- tool_catalog 补 `subscribe_event` / `unsubscribe_event` / `list_subscriptions` (processors 早就在, catalog 缺会让 LLM 发现不到)
- `project.workflow_config.feedback` 默认 `{mode: 'subscribe'}` 即可, 缺失时按 subscribe 处理

**关键设计**: **平台不锁死 mode**, `Group.auto_advance` 是 hint (agent 参考, 不强制); 群级 `workflow_config.feedback_overrides` 可覆盖项目级 feedback — 通用 + 灵活。

---

## 6. 关键术语 (防误用)

| 术语 | 含义 | 误用 |
|---|---|---|
| `advance_to_next_group` | 我之前提的**概念名**, **不是**已存在函数 | 当成 "现成 tool" 用 |
| coordinator | 当前: 项目内置调度器; 未来: 项目级对话+编排 agent | 混用两种定位 |
| pipeline | 群/任务编排的**结构化描述** (YAML) | 误以为是模板 JSON |
| `force_tool_choice` | Agent model bool 字段, 强制 LLM 调工具 | 误以为 cap 文本隐含 |
| 通用化 | 利用现有 schema/工具, agent 自由组合 | 误以为是"新架构" |
| 硬编码流程 | 平台层锁死流程 (代码或 schema) | 与"提示词优化"混淆 |

---

## 7. 一句话总结 (TL;DR)

> **平台给通用原子能力 + schema 留好配置位; project agent 用工具组合 + 自然语言 hint, 决定项目怎么跑。不在平台硬编码流程, 不用硬编码关键词触发行为, 不为每个场景写特化代码。**
>
> **v2 P2 进展**: 空白/模板项目都自动 bootstrap 通用 coordinator (项目总控·编舟, prompt 唯一源在 `default_presets/agent_templates/coordinator.json`); coordinator 通过原子工具 + `render_view(view_type="graph")` + 订阅 `group_status_changed` 编排任意 pipeline; pipeline data 存为项目资源, 渲染+阅读+推进统一来源。

### 7.1 v2 P2 落地的文件清单 (本轮)

| 类别 | 文件 | 变更类型 |
|---|---|---|
| 5.4 | `agentflow/render_processors.py` | 改: VIEW_TYPES + graph options 文档 |
| 5.4 | `agentflow/tool_catalog.py` | 改: render_view 描述 8→9 类型 |
| 5.4 | `app/default_presets/skills/render_view/SKILL.md` | 改: 速查表 8→9 |
| 5.4 | `app/default_presets/skills/render_view/examples/graph.md` | **新建** |
| 5.2 | `app/default_presets/agent_templates/coordinator.json` | **新建** (唯一 prompt 源) |
| 5.2 | `app/services/project_service.py` | 改: `_ensure_project_coordinator` + 调用 |
| 5.2 | `app/services/template_service.py` | 改: 跳过 skip=true, 6.6 调用 bootstrap |
| 5.2 | `app/default_presets/project_templates/novel-writing/agents.json` | 改: 旧 coordinator → placeholder skip=true |
| 5.5 | `app/models/group.py` | 改: 加 `workflow_config: JSON` 字段 |
| 5.6 | `agentflow/tool_catalog.py` | 改: 补 `subscribe_event` / `unsubscribe_event` / `list_subscriptions` |
| 5.6 | `app/default_presets/agent_templates/coordinator.json` | 改: §反馈机制 扩 3 mode 详细文档 |
| 5.5/5.6 | `app/services/project_service.py` | 改: bulk delete 修复 multi-session bootstrap bug |
| 记录 | `docs/architecture/05-pipeline-orchestration.md` | 改: §4.4-4.6 + §5.2-5.6 标 ✅ |
