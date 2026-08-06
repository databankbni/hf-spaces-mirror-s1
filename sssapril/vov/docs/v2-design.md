# vov v2 Design Doc — 系统给通用能力，agent 灵活调控

> **Status**: Draft
> **Author**: AI 协作起草
> **Audience**: vov 项目维护者
> **Date**: 2026-06-07
> **Origin**: v1 demo 完成 50万字 小说前 3 章端到端测试后，用户提出架构升级诉求。

---

## 0. 一句话定位

把 vov 从「多 agent 群聊工具」重构为 **AI 操作系统**——一个按 URL 路由分发、agent 之间显式协作、用户可随时介入的"个人 AI 助理平台"。

---

## 0.3 产品形态（做什么）

1. **一句话定位**：个人 AI 助理平台——用户组建多 AI 团队，协作完成复杂任务。
2. **用户是"导演"**：组织 AI 角色、决定工作流节奏、随时介入审阅，不是被动使用者。
3. **AI 角色**：项目里有多个 AI 角色（写手、审稿、资料员、协调者等），按用户需要自由组合，不被系统类型化。
4. **协作载体**：项目 → 工作群 → 任务 → 资料 / 笔记 / 交付物。AI 角色之间用消息沟通，@ 谁就是点对点。
5. **典型体验**：用户丢需求 → AI 角色认领并协作 → 产出文档 / 设定 / 章节 → 用户审阅或继续推进；用户随时可介入、改要求、@ 某人单独聊。

---

## 0.5 设计哲学（最高指引）

**v2 的核心原则**——所有具体设计都应遵守：

### 原则 1：系统给通用原子能力，agent 灵活调控
- 系统**不**硬编码工作流
- 系统**不**规定"必须有什么角色"
- 系统只提供**原子能力**：
  - `send_message(to, content)` — 主动发消息
  - `read_resource(id)` / `list_resources` — 读数据
  - `update_task_status(id, status)` — 改 task 状态
  - `update_group(id, status)` — 改 group 状态
  - `ping(agent_id, reason)` — 系统给 agent 发"催促"（agent 自己决定要不要用）
  - `query_activity(project_id)` — 系统提供"查活跃度"原语
- 怎么用这些能力 → 由 agent 通过 **skill 提示**、**system_prompt**、**LLM 自主判断**决定

### 原则 2：硬编码"反模式"清单（**禁止**）
- ❌ enum 字段锁死行为模式（如 `review_strategy: "peer"`）
- ❌ 必填字段规定"必须有什么"（如 `task.reviewer_id: NOT NULL`）
- ❌ 特化 agent 类型（如 "群 Facilitator agent"）
- ❌ 系统层偷偷推进流程（如 `auto_continue` / `auto_track`）
- ❌ 触发条件硬编码"催谁"（如"催 reviewer" 写死）
- ❌ `requires_human_approval` 字段（硬编码"什么时候需要人"）

### 原则 3：能力 ≠ 角色 ≠ 行为
- **能力**（system 提供）：原子操作
- **角色**（agent 扮演）：lead / reviewer / facilitator... 都是 agent 自我认同
- **行为**（skill/prompt 约束）：通过自然语言告诉 agent 该怎么做

**关键区分**：agent 自主 ≠ agent 跳过/修改流程
- ✅ agent 自主 = **自由组合原子能力**实现 skill（怎么实现可以灵活）
- ❌ agent 自主 ≠ **跳过 / 修改 skill 描述的流程**（流程必须执行）
- 流程在 skill 里写好就**固定**，agent 必须按 skill 走
- 例外：流程优化 agent / 特殊设计

**Skill 描述应该是命令式、明确的**（不是开放讨论）：

**反例** ❌（开放讨论式，不建议写进运行 skill）：
```
本群约定：lead 写完产出后，可由群内其他 lead 帮忙把关。
你看到其他 lead 写完时，可以读产出 + 给评价 + 让作者修订。
```
> 这种"可" "可以" "建议"的描述太灵活, 实际运行容易变成"无流程"。

**正例** ✅（命令式明确, 适合写进运行 skill）：
```
你是 reviewer。
1. 当其他 lead 调 send_message 通知 task 完成时
2. 调 read_resource 读产出
3. 对照 task.acceptance_criteria 评估
4. 通过 → 调 update_task_status(task_id, 'done')
5. 不通过 → 调 send_message @对方（带具体评价 + 改进建议）

【重要】你必须按这个流程执行。不能跳过。
```
> 这种"你是 X"开头 + 1/2/3 步骤的描述, 明确、命令式、agent 必须执行。

**关键**：
- ❌ skill 不要写成"开放讨论"（"可以" "可" "建议" "灵活"）
- ✅ skill 要写成"明确指令"（"你是 X" + 步骤列表）
- ❌ 不要把"agent 必须按 skill 执行" 等价于"用开放描述"
- 代码层不锁死 ≠ skill 描述要软
- 软/硬指的是**代码层**（系统约束），不是**流程层**（skill 内容）

### 原则 4：用户给的例子 ≠ 系统设计要求
- 用户说"催 reviewer" → 例子
- 本质是"系统给 ping 能力，agent 决定 ping 谁" → 设计
- 不要把"用户的话"当"需求" — 要问"为什么这样，背后的本质是什么"

**更精确的区分**：
- 用户的"**流程描述**" → 写到 **skill** 里（清晰固定）
- 用户的"**系统能力举例**" → 实现成 **通用原语**（不锁死）
- 用户说"任务停止回调通知我" → 这是流程，写到 skill；系统提供"事件订阅"原语
- 用户说"群主自己订阅" → 这是流程，写到群主 skill；系统提供"订阅 + 通知"原语

### 原则 5：先给最小可行，逐步加约束
- P1 只做"系统给原子能力 + 删除系统层硬编码"
- 不在 P1 加新硬编码（reviewer 字段、strategy enum、trigger 矩阵）
- 由 agent 自由组合 + 用户/Skill 描述行为
- 真发现"agent 都做不对"时，才加软约束（不是 enum）

### 原则 6（新增）：代码层与流程层正交
- **代码层** = 系统代码，给通用原语，不锁死（**灵活**）
- **流程层** = skill / agent prompt，清晰固定（**可控**）
- 两者**正交** = 原语丰富 + skill 固定 = 灵活且可控

**典型架构**：

```
[系统代码]
  ├ send_message(to, content)
  ├ ping(agent_id, reason, context)
  ├ subscribe_event(event_type, callback)   ← 任务停止回调
  ├ create_agent(name, system_prompt, tools)  ← 创建新 agent
  ├ update_task_status(id, status)
  ├ ...

[Skill: 群主工作流] (命令式, 群主必须执行)
  你是群主, 你的工作流:
  1. 拆分 task, 分配给群内 lead
  2. 调 subscribe_event('task_status_changed', callback) 订阅 task 状态
  3. 收到 callback(task_id, 'in_progress') → 关注
  4. 收到 callback(task_id, 'done') → 调 read_resource(task.resource_id)
     a. 满意 → 调 update_task_status(task_id, 'confirmed_done')
     b. 不满意 → 调 send_message @<lead_name> 打回继续
  5. 如果你的 task 太重, 调 create_agent(...) 单独创建 reviewer agent
  6. 调 send_message @reviewer_agent, 指示它订阅 + 评估
  7. 你仍然订阅, 接收 reviewer 评价, 保留最终打回权

  【重要】你必须按以上步骤执行。不能跳过。

[Skill: reviewer agent] (命令式, reviewer 必须执行)
  你是 reviewer agent。
  1. 调 subscribe_event('task_status_changed', callback)
  2. 收到 callback(task_id, 'done') → 调 read_resource 读产出
  3. 对照 task.acceptance_criteria 评估
  4. 通过 → 调 update_task_status(task_id, 'done')
  5. 不通过 → 调 send_message @<lead_name> 打回

  【重要】你必须按以上步骤执行。
```

**关键**：
- 同一套系统代码（send_message / subscribe_event / update_task_status / create_agent）
- 不同 skill 描述不同工作流
- skill 是**命令式明确**指令, **不**是开放讨论
- agent 按 skill 执行，**不**自主跳过
- 用户想让流程更可控 → 改 skill（不改代码）
- 用户想给 agent 加能力 → 加原语（不改 skill）

---

## 1. v1 vs v2 对比

| 维度 | v1（当前） | v2（目标） |
|------|------------|------------|
| 数据存储 | DB + 本地双写 | **DB 单一数据源**，本地草稿只在 `.drafts/`（git ignore）|
| 资源组织 | 扁平 tag/title 搜索 | **树形文件夹**，parent_id 自引用 |
| 流程推进 | 系统层 `auto_continue` 硬编码 | **删除**——agent 自主决定续不续 |
| 任务状态 | agent 主动调 / 系统层 auto_track | **删除 auto_track**——agent 主动调 |
| 用户介入 | 必须手动触发每群 | **自然语言约定**——agent 看到 hint 决定何时 @ 用户 |
| Review 行为 | 不存在 | **Skill 描述**——不是特化 agent，是通用 lead 的可选行为 |
| 群聊模式 | 单 lead agent | **多 lead 自由协作**——可互评可不评 |
| 自动化级别 | 无 | **描述性 hint**（如 `"full"`）——agent 自己解读 |
| 路由 | 单 chat 页面 | **URL 路由 + 全局 Agent 空间** |

---

## 2. 4 期路线图

| 期 | 内容 | 工时 | 风险 | 依赖 |
|----|------|------|------|------|
| **P1** | 删 `auto_continue` / `auto_track` + 加原子能力 `ping` / `query_activity` + 项目资源文件夹骨架 + 50万字项目回归测试 | 2-3 周 | 低 | 无 |
| **P2** | 项目资源文件夹完善（parent_id + 树形 UI + 迁移脚本） | 1-2 周 | 中 | P1 |
| **P3** | 项目级 Orchestrator（监听事件 + 灵活调度）+ 健康监控后台任务 | 3-4 周 | 高 | P1, P2 |
| **P4** | 主页 Agent + Agent 世界 + URL 路由 + 全局快捷键 | 6-8 周 | 极高 | P1, P2, P3 |

**关键原则**：**P1 跑通前不动 P3/P4**。P1 是地基，地基不稳上面全塌。

---

## 3. 系统拓扑

```
                  [系统层：原子能力]
                       │
                       │  send_message / ping / read_resource
                       │  update_task_status / update_group
                       │  query_activity / ...
                       │
       ┌───────────────┼───────────────┐
       │               │               │
       ▼               ▼               ▼
  [群聊 A]         [群聊 B]         [群聊 C]
   织梦 (lead)      落笔 (lead)      较真 (lead)
   墨言 (lead)      墨言 (lead)      
   较真 (lead)      用户 (用户)
       │               │               │
       └───────────────┴───────────────┘
                       │
                  [lead 之间通过 send_message 灵活协作]
                  [可选：peer review / user approval / 跳过]
```

**关键**：
- 群聊里**多个 lead agent** 自由组合
- 没有"群 Facilitator agent"这种特化角色
- lead 通过 `send_message` 互发消息（可 @ 对方、@ 用户）
- review 是 lead 的**可选行为**（由 skill 提示）
- 用户也是"群成员"（可被 @）

---

## 4. P1 详细设计（核心）

### 4.1 数据模型变更

#### 4.1.1 Resource 增加文件夹支持

```python
class Resource(Base):
    __tablename__ = "resources"

    id: str
    project_id: str
    group_id: Optional[str]
    parent_id: Optional[str]  # ★ 新增：父资源 ID（文件夹）
    is_folder: bool  # ★ 新增：是否文件夹
    title: str
    content: str
    type: str
    content_type: str
    tags: List[str]
    is_required: bool
    created_by: str
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    children: List["Resource"]
    parent: Optional["Resource"]
```

#### 4.1.2 Task 增加**可选** hint 字段（不锁死行为）

```python
class Task(Base):
    __tablename__ = "tasks"

    id: str
    group_id: str
    title: str
    description: str
    acceptance_criteria: str  # 已有（agent 用作评估参考）
    order_index: int

    # ★ 可选 hint：都是 hint，不是约束
    # 字段值给 agent 参考，agent 可忽略
    verify_hint: Optional[str] = None
    # 例: "建议由群内 lead 互评 / 用户可指定"
    max_revisions_hint: Optional[int] = None
    # 例: 3, agent 可自行决定
    suggested_reviewer_id: Optional[str] = None
    # 例: 某个 agent id, 但 agent 可以决定换人

    status: str  # todo / in_progress / done / rejected
    last_status_change_at: Optional[datetime]
    # 谁都可以改 status -- agent / 系统 / 用户, 都不锁死
```

**关键**（按 §0.5 原则）：
- **没有 enum** 锁死 `verify_mode`
- **没有 NOT NULL** 强制 `reviewer_id`
- **没有"必须 review"** 的逻辑
- 字段都是 hint，agent 自己决定怎么用
- `requires_human_approval` 字段**取消**——这本身就是硬编码
  - 改为：用户在 system_prompt / 描述里说"这个 task 关键，请让用户过目"
  - agent 自己决定什么时候 @ 用户

#### 4.1.3 Project 增加**可选** hint 字段

```python
class Project(Base):
    __tablename__ = "projects"

    id: str
    name: str

    # ★ 可选 hint: agent 看到后会参考, 但不被强制
    autonomy_hint: Optional[str] = None
    # 例: "full（用户离线时全自动, agent 自主推进）"
    # 例: "semi（关键决策等用户, 常规全自动）"
    # 例: "manual（每步等用户）"
    # 描述性字符串, agent 自己解读

    review_mode_hint: Optional[str] = None
    # 例: "本项目用 peer review, 写手完成后由群内其他 lead 帮忙把关"
    # 例: "本项目跳过 review, 写完即 done"
    # 例: "本项目由用户核验关键 task"
    # 自然语言描述, agent 解读

    idle_threshold_seconds: int = 60  # 多久无活动视为"卡住"
```

**关键**：
- **没有 enum**——所有 hint 都是自然语言描述
- agent 看到 hint 后**自己判断**怎么用
- 系统**不强制**——agent 可以选择"我就用 lead 自评"（即使 hint 说"peer review"）

### 4.2 "Reviewer 行为模式"作为示例 Skill（不强制）

**关键认知**：没有"Reviewer Agent"这个特化 agent 类型。
- 任何 lead agent 都**可以**扮演 reviewer 角色
- reviewer 行为 = 读产出 + 给评价 + push 作者
- 这是**通用原子能力**的组合，**不是特化 agent**

**用户/项目可以选择**通过以下方式让 agent 走 reviewer 工作流：
- 群聊模板里挂的 skill 提示
- Lead 的 system_prompt 里的一段
- 项目配置里写明 review_mode_hint

**示例 1：群内 peer review 工作流**（作为 skill 描述——命令式明确，agent 必须执行）

```
Skill 名称: peer-review-mode

你是 reviewer。你的工作流:
1. 当其他 lead 调 send_message 通知 task 完成时（群内消息流里看到 @你）
2. 调 read_resource(resource_id) 读产出
3. 对照 task.acceptance_criteria 评估
4. 通过 → 调 update_task_status(task_id, 'done')
5. 不通过 → 调 send_message @<lead_name>（带具体评价 + 改进建议）

【重要】你必须按以上步骤执行。不能跳过任何 step。
- 不能因为"很忙"就跳过 review
- 不能因为"不熟悉领域"就跳过
- 如果你确实无法评估, 调 send_message @群主报告, 由群主决定
```

**示例 2：用户兜底 review 工作流**

```
Skill 名称: user-approval-mode

你是 lead 写手, 关键 task 需用户核验。你的工作流:
1. 写完 task 产出后, 调 send_message @用户（含产出链接 + 验收标准摘要）
2. 等用户回复
3. 用户 "通过" → 调 update_task_status(task_id, 'done')
4. 用户 "拒绝" + 评价 → 重新修订
5. 用户具体意见 → 按意见修改

【重要】你必须按以上步骤执行。
- 不能跳过用户核验直接 done
- 不能"觉得用户肯定同意"就跳过
```

**关键**（按 §0.5 原则 3 + 原则 6）：
- ❌ **没有**"Reviewer Agent 类型"（代码层不锁死）
- ❌ **没有**"群必须配 reviewer"（代码层不锁死）
- ❌ **没有**"必须走 review 才能 done"（代码层不锁死）
- ✅ **review 流程** = **skill 描述，agent 必须执行**（流程层清晰固定）
- ✅ 流程可控性 = 改 skill（不改代码）

**Lead 完成时按 skill 通知**（按 §0.5 原则 6）：
- 写完 task 后, **按 skill 决定通知谁**:
  - skill 写"通知 reviewer" → 调 send_message @reviewer
  - skill 写"不通知，直接 done" → 直接 update_task_status
  - skill 写"让用户过目" → 调 send_message @用户
- 这是 lead 的**执行**（按 skill），**不是**"自主决定"
- 改流程 = 改 skill（不改 lead 的代码）

### 4.3 用户核验流程（按 skill 决定）

**取消** `task.requires_human_approval` 字段——这是硬编码"什么时候需要人"。

**改为 skill 描述的流程**：
- 群聊 skill 写"关键 task 必须用户核验" → agent 必须 @ 用户
- 群聊 skill 写"task 完成后直接 done" → agent 直接 done
- 群聊 skill 写"用户过目后才 done" → agent 必须等用户

**用户核验 UI 反馈**（v1 chat 里）：

```
[验收] 任务 X：第 1 章正文
产出：[查看资源](d:/resources/xxx)
关键摘要：3 句话

✅ 通过 · ❌ 拒绝 · 📝 给评价
```

**用户回复分支**（agent 按 skill 响应）：
- `✅` / `通过` → skill 决定 agent 调 `update_task_status(done)`
- `❌` / `拒绝` + 评价 → skill 决定 agent 怎么处理（重做？归档？）
- `📝` / 评价 → skill 决定 agent 怎么响应

**关键**（按 §0.5 原则 6）：
- 代码层：用户输入"✅/❌/📝" 不触发任何系统自动动作
- 流程层：skill 决定"用户说✅时 agent 该做什么"
- agent 按 skill 执行，**不**自主跳过

### 4.4 健康监控（代码给原子能力，skill 决定流程）

#### 4.4.1 关键认知

按 §0.5 原则 6：**代码给原子能力，skill 决定流程**。

健康监控 = 代码**只**提供"查"原语（`query_activity` / `ping` / `subscribe_event`），流程**全部在 skill 里**。

#### 4.4.2 系统提供的原子能力（P1 加）

```python
# app/orchestrator/activity_primitives.py

async def query_activity(project_id: str) -> ActivityReport:
    """
    原子能力：查询项目活动状态。
    返回:
      - last_message_at: datetime
      - last_tool_call_at: datetime
      - pending_tool_calls: int
      - active_agent_ids: List[str]
      - idle_seconds: int
    """
    ...

async def ping(agent_id: str, reason: str, context: dict) -> None:
    """
    原子能力：系统发"催促"给指定 agent。
    reason 字段是结构化 hint（不是硬编码触发条件）。
    context 包含 task/group 信息。
    """
    ...
```

#### 4.4.3 调度示例（代码给原子能力，skill 决定流程）

**示例 1：项目级 Orchestrator 调度**（P3 引入，但 P1 留好接口）

```
# 关键：调度逻辑写在 Orchestrator 的 skill 描述里, 不在系统代码里
# 系统代码只提供 query_activity / ping / subscribe_event 原语

Orchestrator Skill (描述):
"你是项目编排者, 你的工作流:
 1. 每 30s 调 query_activity(project_id)
 2. 如果 idle_seconds > 60 且有 in_progress task:
    调 list_active_agents() 看谁在
    调 list_task_participants(task_id) 看 task 涉及谁
    按 skill 决定 ping 谁（lead? reviewer? 用户?）
 3. ping 时给 reason: 'task_idle' + task 上下文
 4. 同一 task 3 次 ping 都无响应 → ping 用户（升级）

【重要】本工作流必须执行, 不能跳过任何 step。"
```

**示例 2：完全不管（草稿型项目）**

```
Project.autonomy_hint = "no-orchestrator（不需要调度，让 agent 自由推进）"
→ 不创建 Orchestrator agent
→ 没有 ping 流程
→ agent 按各自 skill 工作
```

**示例 3：群主自管**（P1 推荐起步）

```
# 群主 lead 的 system_prompt 加:
"你是群主, 你订阅 task 状态变化事件。
 如果你 60s 内没收到任何 task 状态变化, 你可以调 query_activity() 看群里是否还有人。
 如果都 idle, 你可以 ping 用户告知进度。"
```

**关键**（按 §0.5 原则 6）：
- 代码层：系统**只给** query_activity / ping / subscribe_event **原子能力**
- 流程层：skill 决定"什么时候 ping、ping 谁、几次升级"
- 流程在 skill 里**写好就固定**，agent 必须按 skill 执行
- 项目可以**完全不 ping**（在 skill 里写"no-orchestrator"）
- 升级到用户**是 skill 规定的流程**，不是 agent 自主判断

#### 4.4.4 Agent 活动检测（基础查询原语）

```python
async def is_agent_active(self, project_id: str) -> bool:
    """
    查最近 60s 内项目是否有任何 agent 活动。
    "活动"包含: 发消息、调工具、等工具结果、等 LLM 响应。
    """
    recent_threshold = datetime.utcnow() - timedelta(seconds=60)
    
    # 1. 查 chain message 活动
    stmt = select(func.count(ChainMessage.id)).where(
        ChainMessage.project_id == project_id,
        ChainMessage.created_at > recent_threshold
    )
    if (await self.db.execute(stmt)).scalar() or 0:
        return True
    
    # 2. 查正在执行中的 agent 任务
    stmt = select(func.count(AgentExecution.id)).where(
        AgentExecution.project_id == project_id,
        AgentExecution.status.in_(["executing", "awaiting_tool", "awaiting_llm"]),
        AgentExecution.started_at > recent_threshold,
    )
    if (await self.db.execute(stmt)).scalar() or 0:
        return True
    
    # 3. 查等待中的 tool call
    stmt = select(func.count(PendingToolCall.id)).where(
        PendingToolCall.project_id == project_id,
        PendingToolCall.created_at > recent_threshold,
    )
    if (await self.db.execute(stmt)).scalar() or 0:
        return True
    
    return False
```

**注意**（用户强调过）：
- "活动"**不只是**发消息
- 工具调用、等待工具结果、等待 LLM 响应 = 算活动
- 只有**完全没动静**才视为卡住

#### 4.4.5 通用 ping 提示语模板

系统 ping agent 时，**通用模板**（不区分"催 reviewer"/"催 lead"/"催用户"）：

```
[系统 ping]
项目: <project.name>
触发原因: <reason>
上下文: <context>
空闲时长: <idle_seconds>s

参考信息:
- 当前 in_progress task: <task_id> <task.title>
- 群里活跃 agent: <active_agent_ids>
- 任务负责人（系统推荐）: <task.assigned_to>（仅参考）

请按你的 skill 决定如何响应。
```

**关键**：
- 系统**不规定**"这就是催 reviewer"
- 系统只给"原因 + 上下文 + 候选"
- agent 按**自己 skill**决定: 我要做什么? 我要不要 ping 谁? 我要更新 task 吗?
- skill 写"如果收到 ping 就 X" → agent 必须执行 X

---

## 5. 状态机

### 5.1 Task 状态转换（skill 决定的流程，agent 必须执行）

```
   todo ──Lead/Reviewer 调 update_task_status('in_progress')──→ in_progress
                              │
                              ├──按 skill 流程──→ done（自评 / peer pass / 用户过目 / reviewer 改）
                              │
                              └──按 skill 流程──→ in_progress（重做, 由谁驱动看 skill）
```

**关键**（按 §0.5 原则 6）：
- **代码层** 不锁死"必须 review 才能 done"（任何 lead 都可以调 update_task_status）
- **流程层** 由 skill 决定"谁有资格改 done 状态"（reviewer？群主？用户？）
- 状态机**只是数据模型**，不锁死流程
- 改流程 = 改 skill（不改代码）

### 5.2 Group 状态转换

```
   pending → active（按 skill 触发, 通常是 lead 主动 first message）
   active  → completed（按 skill 触发, 通常是最后一 task done 时）
   active  → paused（用户 /pause）
   completed → active（用户 /reopen）
```

**关键**：
- 代码层：任何 agent 都可以调 update_group
- 流程层：skill 规定"谁可以触发 completed"（群主？reviewer？用户？）

---

## 6. 事件流（skill 决定流程）

### 6.1 任务完成事件（按 skill 响应）

```
Lead A 写完 task (按 skill)
  │
  ├─ 按 skill 调 send_message @（按 skill 决定给谁）
  │
  ├─ 按 skill 调 update_task_status(task_id, 'done')（按 skill 决定谁调）
  │
  └─ 按 skill 调 update_group（按 skill 决定何时调）
```

**关键**（按 §0.5 原则 6）：
- 代码层：**不**触发任何自动事件
- 流程层：skill 决定 Lead 写完后**做什么**（必走流程）
- agent 必须按 skill 执行，**不**自主跳过

### 6.2 群聊推进（按 skill 决定）

```
Lead A 调 update_group(group_id, 'completed')（按 skill 决定）
  │
  └─ 不触发系统事件——是元数据更新
     按 skill 决定下一群推进（由 Orchestrator agent 调度？由群主推进？）
```

**关键**：
- 代码层：调 update_group 不触发任何自动事件
- 流程层：skill 决定"谁负责推进下一群"（Orchestrator？群主？用户？）
- agent 按 skill 执行

### 6.3 健康监控事件（agent 决定怎么用原子能力）

```
Agent X 调 query_activity(project_id)  ← 任何 agent 都可以调（按 skill 决定调不调）
  │
  └─ 拿到 ActivityReport
     │
     ├─ 按 skill 决定: 没事干, 我去写
     ├─ 按 skill 决定: ping Lead A
     └─ 按 skill 决定: ping 用户（升级）
```

**关键**：
- 代码层：系统**只**给 query_activity / ping 原子能力
- 流程层：skill 决定"什么时候 ping、ping 谁、几次升级"
- agent 按 skill 执行

---

## 7. Reviewer 行为 Skill 完整描述

### 7.1 通用认知

- 没有"Reviewer Agent"特化类型（代码层不锁死）
- Reviewer 角色 = **skill 描述的流程**（流程层清晰固定）
- 任何 lead 都可以**临时**扮演 reviewer 角色（在 skill 里规定）
- 角色转换通过**自然语言**完成, 不需要 enum 字段

### 7.2 Reviewer 工作流程（skill 命令式明确，agent 必须执行）

#### 模式 A: 群内 peer review

**Skill 描述** (命令式, 必须执行):

```
Skill 名称: peer-review-mode

你是 reviewer。你的工作流:
1. 当其他 lead 调 send_message 通知 task 完成时（群内消息流里看到 @你）
2. 调 read_resource(resource_id) 读产出
3. 对照 task.acceptance_criteria 评估
4. 通过 → 调 update_task_status(task_id, 'done')
5. 不通过 → 调 send_message @<lead_name>（带具体评价 + 改进建议）

【重要】你必须按以上步骤执行。不能跳过。
- 不能因为"很忙"就跳过 review
- 不能因为"不熟悉领域"就跳过
- 如果你无法评估, 调 send_message @群主报告, 由群主决定
```

#### 模式 B: 用户兜底 review

**Skill 描述** (命令式, 必须执行):

```
Skill 名称: user-approval-mode

你是 lead 写手, 关键 task 需用户核验。你的工作流:
1. 写完 task 产出后, 调 send_message @用户（含产出链接 + 验收标准摘要）
2. 等用户回复
3. 用户 "通过" → 调 update_task_status(task_id, 'done')
4. 用户 "拒绝" + 评价 → 重新修订
5. 用户具体意见 → 按意见修改

【重要】你必须按以上步骤执行。
- 不能跳过用户核验直接 done
- 不能"觉得用户肯定同意"就跳过
```

#### 模式 C: 群主统管（用户原话："群主拆分任务，每个任务他自己都要把关"）

**Skill 描述** (命令式, 必须执行):

```
Skill 名称: lead-self-review

你是群主, 你拆分任务, 每个 task 你自己把关。你的工作流:
1. 拆分 task, 调 update_task_status(task_id, 'todo') 创建
2. 调 subscribe_event('task_status_changed', callback) 订阅状态变化
3. 收到 callback(task_id, 'in_progress') → 关注, 等 lead 完成
4. 收到 callback(task_id, 'done') → 调 read_resource 读产出
   a. 满意 → 调 update_task_status(task_id, 'confirmed_done')
   b. 不满意 → 调 send_message @<lead_name> 打回继续
5. 如果你的任务很重:
   a. 调 create_agent(name='reviewer_<n>', system_prompt=...) 创建 reviewer
   b. 调 send_message @reviewer_<n>, 指示它订阅 + 评估
   c. 你仍然订阅, 接收 reviewer 评价
   d. 你保留最终打回权

【重要】你必须按以上步骤执行。
- 你对每个 task 都有最终决定权
- reviewer 是助手, 不是替代
- 用户可直接 send_message @你
```

#### 模式 D: 跨群 review

**Skill 描述** (命令式, 必须执行):

```
Skill 名称: cross-group-review

你是 cross-group reviewer, 关注 <other_group> 的产出。你的工作流:
1. 那个群有 lead 调 send_message @你 时
2. 调 read_resource(resource_id) 读产出
3. 按你的专业领域评估
4. 调 send_message 回原群 @<lead_name>, 给评价
5. 不调 update_task_status（那是原群 lead 的事, 评价权在原群）

【重要】你必须按以上步骤执行。
- 你只评价, 不替原群做决定
- 评价后必须 send_message 回原群
```

#### 模式 E: 不做 review

**Skill 描述** (命令式, 必须执行):

```
Skill 名称: no-review

你是 lead 写手, 本群不做 review。你的工作流:
1. 写完 task → 调 update_task_status(task_id, 'done')
2. 不需要等别人审
3. 如果用户后面要改, 用户自己 send_message @你

【重要】你必须按以上步骤执行。
- 本群没设 review 流程, 不要 send_message 给 reviewer
- 不要等用户核验
```

### 7.3 项目级 hint（参考用，不强制流程）

```python
Project.review_mode_hint = "本项目用 peer review, 写手完成后由群内其他 lead 帮忙把关"
# agent 看到后, 参考这个 hint 决定走哪个模式 (A-E)
# 不同群可以选择不同模式, 按 skill 描述执行
```

---

## 8. 用户可见的 UX 改进

### 8.1 Chat 页面顶部进度条

```
[主线大纲] ───[✓ 完成]───[✓ 完成]───[进行中]───[待办]
                          任务1       任务2       任务3
```

### 8.2 任务卡片

```
┌────────────────────────────────────┐
│ 任务 2：主线事件序列               │
│ 状态：in_progress  修订：0/3      │
│ Lead：故事架构师·织梦              │
│ (Reviewer：自由选择)               │
│                                    │
│ 验收标准：                          │
│ 1. 含 8 个核心节点                  │
│ 2. 每节点含因果链                   │
│ 3. 钩子递进合理                     │
│                                    │
│ [查看产出]  [查看进度报告]          │
└────────────────────────────────────┘
```

### 8.3 自然语言验收提示

用户进群时, agent 自由决定是否发:

```
[验收] 任务 X：第 1 章正文
产出：[查看资源](d:/resources/xxx)
关键摘要：3 句话

✅ 通过 · ❌ 拒绝 · 📝 给评价
```

**用户可以混用自然语言**:
- "写得不错" → agent 自己解读
- "再改改" → agent 自己决定下一步
- "直接发吧" → agent 调 update_task_status

---

## 9. URL 路由表（P3/P4 内容）

| URL | Agent | 用途 |
|-----|-------|------|
| `/` | 主页 Agent | 路由分发、最近项目、快速入口 |
| `/agents` | Agent 世界 Agent | agent 列表 / 创建 / 克隆 / 编辑 |
| `/skills` | Skill Agent | skill 列表 / 创建 / 调用 |
| `/tools` | 工具 Agent | 工具列表 / 元数据 |
| `/settings` | 设置 Agent | 偏好 / 记忆 / 系统配置 |
| `/search` | 搜索 Agent | 跨项目 / 全局搜索 |
| `/project/:id` | 项目 Agent（编排者, 可选） | 项目概览 / 资源库 / 群聊入口 |
| `/project/:id/group/:gid` | 群聊页（多 lead 自由组合） | 聊天 / 任务 / 进度 |
| `/project/:id/resources` | 资源库 | 树形文件夹浏览 |
| `/project/:id/timeline` | 时间线 | 群聊推进历史 / 事件流 |

---

## 10. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM 自由度过大, 行为不一致 | 中 | 中 | skill 描述 / system_prompt 引导（不是 enum 锁死）|
| Lead 互相推诿, 任务无人认领 | 中 | 中 | skill 提示"看到 task 是 todo, 想做就 send_message 认领" |
| 死锁: 全在等对方 | 低 | 高 | agent 自由调 ping 打破僵局（系统不强制） |
| LLM 服务 down | 中 | 高 | query_activity 返回 None, agent 自己决定暂停 |
| 资源文件夹重名 | 中 | 低 | title 唯一性约束（同名加后缀）|

---

## 11. 不在 v2 范围内

- 多用户 / 权限系统
- 商业化（订阅 / 付费）
- 移动端
- 离线模式
- 实时协作（多人同时编辑同一资源）

v2 仍是**单用户多 agent 协作平台**。

---

## 12. P1 实施清单（按 §0.5 原则：不硬编码）

按依赖顺序：

1. **数据模型迁移**（只加可选 hint 字段）
   - [x] `Resource` 加 `parent_id` + `is_folder`
   - [x] `Task` 加 `verify_hint` / `max_revisions_hint` / `suggested_reviewer_id`（**全部 Optional**）
   - [x] `Project` 加 `autonomy_hint` / `review_mode_hint` / `idle_threshold_seconds`
   - [x] **不**加 `requires_human_approval` / `verify_mode` / `review_strategy` / `reviewer_id` 必填
   - [x] alembic 迁移脚本 (`2026_06_07_0002-v2_p1_add_folders_and_hints.py`)

2. **删除系统层硬编码**
   - [x] 删 `chat_service.py` 的 `auto_continue` 循环
   - [x] 删 `tool_adapter.py` 的 `auto_track_task_status`（保留为 no-op 占位, 防止误调用）
   - [x] 不再写 `auto_complete_group`（v2 不需要）
   - [x] 保留 `tags 智能补全` / `group_id 自动注入` / `upsert`（这些是工具层保护）

3. **加原子能力（不写死触发）**
   - [x] `query_activity(project_id)` — 返回 ActivityReport（最近消息、活跃 agent、空闲时长）
   - [x] `ping(group_id, to_agent_id, reason, context)` — 系统/agent 给指定 agent 发"催促"消息
   - [x] `subscribe_event(event_type, subscriber_agent_id, project_id, group_id?)` — 事件订阅
   - [x] `list_subscriptions(subscriber_agent_id)` — 列出某 agent 的所有订阅
   - [x] 事件总线：`app/services/event_bus.py`（内存版, P3 升级为 Redis）

4. **资源文件夹骨架**
   - [x] 创建项目时预建 8 个文件夹（按群聊对应, `template_service._ensure_group_folder`）
   - [x] 群聊创建时预建 active chain（`template_service._ensure_group_chain`, 让 ping/send_message 可直接用）
   - [x] 资源写入时自动归入 group 文件夹（`tool_adapter._auto_locate_folder`）
   - [x] 资源 tags 智能补全（`_infer_tags_from_title`）
   - [x] UI 树形展示（P2 完善, P1 先建结构）

5. **回归测试**（`server/tests/test_v2_p1_regression.py`）
   - [x] 应用 novel-writing 模板创建项目 → 8 group + 27 task + 5 resource
   - [x] 验证 lead 现在**不靠** auto_continue 也能继续做事（lead 的 system_prompt 描述工作流）
   - [x] 验证 lead 现在**不靠** auto_track 也能自己调 update_task_status
   - [x] 验证 ping 原子能力不修改 task 状态（agent 自己决定）
   - [x] 验证 query_activity / subscribe_event / list_subscriptions 注册和调用
   - [x] 验证群聊预建 active chain（ping 可直接调）
   - [x] 验证系统层无 auto_continue / auto_track 硬编码

---

## 13. v2 P1 实现的额外约定（用户对话中提出，已落地）

### 13.1 事件订阅（subscribe_event）

**背景**：用户提"任务停止回调"是流程, 系统提供事件订阅原语。

**系统提供**（[tool_adapter.py](file:///d:/agents/vov/server/app/orchestrator/tool_adapter.py)）：

```python
async def subscribe_event(
    event_type: str,           # "task_status_changed" / "resource_created" / "resource_updated"
    subscriber_agent_id: str,
    project_id: str,
    group_id: Optional[str] = None,
) -> Dict[str, Any]
```

**实现**：[app/services/event_bus.py](file:///d:/agents/vov/server/app/services/event_bus.py) 内存版订阅（process 级别 dict）。
P3 升级：Redis 持久化 + 跨进程事件分发。

**流程层**（按 §0.5 原则 6：skill 决定怎么用）：

```
Skill: lead-self-review

你是群主。
1. 调 subscribe_event('task_status_changed', callback) 订阅状态变化
2. 收到 callback(task_id, 'in_progress') → 关注
3. 收到 callback(task_id, 'done') → 调 read_resource 读产出
4. 按你的判断: update_task_status(confirmed_done) / send_message 打回
```

### 13.2 群推动者（Facilitator）

**用户原话**："每个群可以有群推动者，负责群任务的全部完成"。

**v2 立场**（按 §0.5 原则 2 反模式清单）：
- ❌ **没有**"群 Facilitator Agent"特化 agent 类型（代码层不锁死）
- ✅ 推动群聊完成 = lead 自身的工作流（每个 lead 的 system_prompt 已写明）
- ✅ 群聊可以**临时**设一个 lead 当 facilitator（在 skill 里规定）

**Skill 示例**（lead 自管群聊, 不需要额外 facilitator）：

```
Skill: lead-facilitator

你是本群 lead（群主），你的工作流：
1. 拆任务：调 create_task 拆出子任务，分配给群内 lead
2. 订阅：调 subscribe_event('task_status_changed', callback)
3. 跟踪：收到 callback → 调 read_resource 看产出
4. 推动：
   - 任务卡住：调 ping(子 lead, reason="task_idle", context)
   - 本群完成：调 update_group(group_id, 'completed')
5. 同步用户：调 send_message @用户，告知本群完成情况
```

**关键**：
- 群主 = lead = facilitator 角色
- 不需要单独的"Facilitator Agent"
- 推动流程 = system_prompt / skill 描述的工作流（命令式明确）
- "群任务的全部完成" = lead 的 system_prompt 里写明的"本群所有任务 done → update_group=completed"

### 13.3 全局 Agent 空间（主页 / Agent 世界 / Skill / 工具 / 设置）

**用户原话**："可以搞一个特殊的全局群或 agent 对话空间，用户快捷键召唤，按 url 设定，比如可以有主页 agent，agent 世界 agent，skill agent，工具 agent，设置 agent 等"。

**P4 实现**（暂不实现, 先做其他页面 agent）：

| URL | Agent 类型 | 职责 |
|-----|-----------|------|
| `/` | 主页 Agent | 路由分发、最近项目、快速入口 |
| `/agents` | Agent 世界 Agent | agent 列表 / 创建 / 克隆 / 编辑 |
| `/skills` | Skill Agent | skill 列表 / 创建 / 调用 |
| `/tools` | 工具 Agent | 工具列表 / 元数据 |
| `/settings` | 设置 Agent | 偏好 / 记忆 / 系统配置 |
| `/search` | 搜索 Agent | 跨项目 / 全局搜索 |

**v2 立场**：
- 主页 Agent 可以是用户的"代理"（用户不在时按群顺序跑任务）
- 主页 Agent 可以订阅事件（任务停止回调等）
- 主页 Agent 本身**不**是特化角色, 是"用户代理", 通过 system_prompt 描述其职责
- 实现时复用同一套 agent 框架（tools + skill + system_prompt）

### 13.4 Chat Service 删除的硬编码

**`chat_service.py` 删除清单**（v2 P1）：
- `auto_continue` 循环（系统层偷偷继续对话）
- `auto_track`（系统层偷偷改 task 状态）
- 任何"卡住就自动 ping"的循环（改由 lead 按 skill 决定）

**保留**（v2 P1 仍需要）：
- `_get_or_create_chain`：lazy 创建 chain（chat 入口）
- `send_message_stream`：流式返回
- `resolve_mentioned_agent`：@ mention 解析

**关键**（按 §0.5 原则 2 反模式清单）：
- ❌ 系统层 auto_continue / auto_track
- ✅ 流程推进 = agent 主动调原子能力（按 skill 走）

### 13.5 群聊 Chain 预建

**问题**：`ping` / `send_message` 原子能力要求群下有 active chain。
- 之前依赖 chat 入口的 lazy create（`_get_or_create_chain`）
- 但 `ping` 是 system/agent 主动发起, 不走 chat 入口, 会遇到"无 active chain"

**v2 P1 修复**（[template_service.py](file:///d:/agents/vov/server/app/services/template_service.py)）：

```python
# 创建 group 后立即预建
await self._ensure_group_chain(project_id=project_id, group_id=group.id)
```

**关键**：
- chain 是工具层结构（消息容器）
- 预建 chain 不算"硬编码流程"（不是流程推进）
- 让所有"发消息"原子能力（ping / send_message）开箱即用

---

## 14. 写在最后

v2 不是"v1 + 几个 feature"，而是**架构升级**。核心变化：

| 维度 | v1 | v2 |
|------|-----|-----|
| 流程推进 | 系统层硬编码 | **agent 自主** |
| 角色 | 单 lead | **多 lead 自由协作** |
| Review | 不存在 | **skill 描述可选行为** |
| 自动化 | 系统兜底 | **agent 自由组合原子能力** |
| 路由 | 单 chat 页面 | **URL 路由 + 全局 agent 空间**（P4） |

**最大的认知升级**：
- **系统给能力，agent 决定怎么用**（不是系统给完整流程）
- **删除硬编码**优先于**加新功能**
- **用户给的例子是 hint，不是需求**

最大的风险是**"再加一点硬编码应该更稳"**的诱惑。P1 必须**克制**——只删 + 加原子能力, 不加新约束。

P1 跑通后, 用真实项目（50万字小说）反复验证, 再决定是否推 P3。
