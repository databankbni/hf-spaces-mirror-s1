# L0 首页引导 agent + RenderSpec URL 化 实施计划

> 基于 [product-evolution-discussion.md](./product-evolution-discussion.md) 的决策
> 范围：只计划第一步（L0 首页引导 + RenderSpec URL 化），跑通后再计划后续

---

## 目标

新用户进入首页 → Cmd+K 调出侧边栏引导 agent → 对话"我想写个武侠小说" → agent 调系统级工具创建项目 → render_view 在主区域渲染项目蓝图确认卡 → 用户确认 → 项目出现在列表。

核心验证：**用户不学产品，只提需求，agent 帮忙建项目**。

---

## 前置决策（已确定）

- 引导 project 方案：每用户一个引导 project（is_guide 标记），引导 agent 在其中工作
- 系统级工具：跨 project 操作，带 target_project_id
- useChatStream 不改：groupId 还是 groupId（引导 project 的 group）
- UniversalChat：新建轻量侧边栏组件，复用 useChatStream
- RenderSpec URL 化：base64 进 hash
- 交互形态：侧边栏对话 + 主区域保持状态

---

## 任务拆解

### 阶段1：后端基础（引导 project 基础设施）

**T1. project 表加 is_guide 字段** ✅
- 文件：[server/app/models/project.py](../server/app/models/project.py) + 新 migration
- 改动：加 `is_guide: bool = False` 字段
- 验证：migration 跑通，字段存在

**T2. 引导 project 自动创建逻辑** ✅
- 文件：[server/app/services/guide_service.py](../server/app/services/guide_service.py) + [server/app/api/v1/guide.py](../server/app/api/v1/guide.py) + [server/app/default_presets/agent_templates/guide_l0.json](../server/app/default_presets/agent_templates/guide_l0.json)
- 逻辑：POST /api/v1/guide/ensure 幂等创建引导 project + agent + group
- 验证：API 调用成功，DB 验证 is_guide=1, 7→8 个工具绑定, lead member 就位, 幂等性通过

**T3. 系统级工具集实现** ✅
- 文件：[agentflow/crud_processors.py](../agentflow/crud_processors.py) + [agentflow/tool_adapter.py](../agentflow/tool_adapter.py) + [agentflow/builtin_processors.py](../agentflow/builtin_processors.py) + [agentflow/tool_catalog.py](../agentflow/tool_catalog.py) + [server/app/orchestrator/tool_adapter.py](../server/app/orchestrator/tool_adapter.py)
- 工具：query_projects（排除 is_guide）/ list_templates / pick_template（create_project 已存在）
- 验证：3 个新工具在 catalog 注册, 8 个工具全部绑定到引导 agent, is_guide 字段正确返回(1引导+43用户)

**T4. 引导 agent 配置** ✅
- 文件：[server/app/default_presets/agent_templates/guide_l0.json](../server/app/default_presets/agent_templates/guide_l0.json)
- 内容：L0 需求 agent 的系统提示词 + 8 个工具绑定（4 已有 + 4 系统级）
- 验证：提示词基本版完成, 优化留到 T13 端到端测试

### 阶段2：前端 UniversalChat 框架

**T5. UniversalChat 侧边栏组件骨架**
- 文件：[client/src/components/](../client/src/components/) 新建 UniversalChat.tsx
- 功能：
  - 侧边栏布局（右侧或左侧，可配置）
  - Cmd/Ctrl+K 收放
  - 消息列表 + 输入框（复用 ChatPanel 的渲染逻辑，但轻量）
  - 接入 useChatStream
- 验证：Cmd+K 能调出/收起侧边栏，能看到消息列表和输入框

**T6. URL 前缀匹配 agent 路由**
- 文件：[client/src/](../client/src/) 新建 lib/guideRouter.ts + 挂载到 [App.tsx](../client/src/App.tsx)
- 逻辑：
  - 配置 agent 路由表：`/` → L0 引导 agent，`/project/:id` → L1（后续），`/project/:id/chat/:gid` → L2（后续）
  - 最长前缀匹配，未匹配回退到 `/` 的 L0
  - 根据当前 URL 返回应使用的 agent 身份 + groupId（引导 project 的 group）
- 验证：首页 URL 返回 L0 引导 agent 配置

**T7. UniversalChat 接入引导 project**
- 文件：UniversalChat.tsx + guideRouter.ts
- 逻辑：
  - 根据 URL 路由得到引导 agent 的 groupId
  - 调 useChatStream({ groupId, group, members, agentList, ... })
  - group/members/agentList 从引导 project 查询
- 验证：首页 Cmd+K 调出侧边栏，能跟 L0 引导 agent 流式对话

### 阶段3：RenderSpec URL 化 + 主区域渲染

**T8. RenderSpec base64 编码/解码工具**
- 文件：[client/src/render-engine/](../client/src/render-engine/) 新建 urlCodec.ts
- 功能：
  - `encodeSpec(spec: RenderSpec): string` → JSON.stringify + base64
  - `decodeSpec(encoded: string): RenderSpec` → base64 decode + JSON.parse
- 验证：编码解码往返一致

**T9. URL hash 解析 → 主区域渲染**
- 文件：[client/src/](../client/src/) 新建 hooks/useViewFromHash.ts + 修改 [App.tsx](../client/src/App.tsx)
- 逻辑：
  - 监听 URL hash 变化
  - hash 解析出 RenderSpec
  - 主区域渲染 `<RenderEngine spec={spec} />`
  - 无 hash 时主区域显示默认内容（首页项目列表）
- 验证：手动改 URL hash 带 base64 RenderSpec，主区域渲染对应视图

**T10. agent render 工具支持渲染到主区域**
- 文件：后端 render_view 工具 + 前端 useChatStream 事件处理
- 逻辑：
  - agent 调 render_view 工具时，tool_result 事件带 render_spec
  - useChatStream 已处理 render_spec 事件（[useChatStream.ts#L144](../client/src/hooks/useChatStream.ts) applyRenderSpec）
  - 新增：将 render_spec 同步到 URL hash（触发主区域更新）
  - render_target 字段已存在，支持指定渲染目标
- 验证：agent 调 render_view → 主区域更新视图

### 阶段4：L0 首页引导体验

**T11. 首页无项目时侧边栏默认展开 + 空状态引导**
- 文件：[client/src/pages/Index.tsx](../client/src/pages/Index.tsx) + UniversalChat.tsx
- 逻辑：
  - 检测用户无项目（且非引导 project）→ 侧边栏默认展开
  - 主区域显示空状态引导（"按 Cmd+K 跟我聊聊你想做什么"）
  - 有项目后侧边栏收起，主区域显示项目列表
- 验证：新用户首次进入 → 侧边栏展开 + 空状态引导

**T12. 项目列表过滤 is_guide**
- 文件：[client/src/hooks/useProjects.ts](../client/src/hooks/useProjects.ts) + 后端 projects API
- 逻辑：查询项目列表时过滤 is_guide=True 的引导 project
- 验证：引导 project 不出现在"我的项目"列表

**T13. L0 引导 agent 提示词优化 + 端到端测试**
- 文件：guide_l0.json（T4 创建）
- 优化：根据实际对话效果调整提示词
- 端到端验证：
  1. 新用户进入首页 → 侧边栏展开
  2. 输入"我想写个武侠小说"
  3. agent 理解需求，推荐模板
  4. agent 调 create_project 创建项目
  5. agent 调 render_view 展示项目蓝图
  6. 主区域渲染项目蓝图确认卡
  7. 项目出现在列表

---

## 依赖关系

```
T1 (is_guide 字段)
  ↓
T2 (引导 project 创建) ← T3 (系统级工具，独立)
  ↓                      ↓
T4 (引导 agent 配置) ←───┘
  ↓
T7 (UniversalChat 接入) ← T5 (侧边栏骨架，独立)
  ↓                       T6 (URL 路由，独立)
T11 (首页引导体验)
  ↓
T13 (端到端测试)

T8 (RenderSpec 编解码，独立)
  ↓
T9 (URL hash → 主区域渲染)
  ↓
T10 (agent render → 主区域) ← T7
  ↓
T11 (首页引导体验)

T12 (过滤 is_guide) ← T1
```

**可并行**：
- T3、T5、T6、T8 互相独立，可并行
- T1 完成后 T2、T12 可并行

---

## 验证点（里程碑）

| 里程碑 | 验证内容 | 依赖任务 |
|--------|---------|---------|
| M1 后端基础就绪 | 引导 project 能创建，系统级工具能调用 | T1-T4 |
| M2 前端对话可用 | 首页 Cmd+K 能跟引导 agent 流式对话 | T5-T7 |
| M3 渲染打通 | agent 调 render_view → 主区域更新 | T8-T10 |
| M4 端到端跑通 | 新用户对话建项目完整流程 | T11-T13 |

---

## 风险与应对

1. **引导 agent 理解需求不准**：提示词迭代，关键节点（建项目）让用户确认
2. **系统级工具权限管控**：引导 agent 只配必要工具，不配危险操作
3. **RenderSpec URL 过长**：base64 可能长，监控 URL 长度，必要时压缩或存后端只传 id
4. **useChatStream 复用兼容**：引导 project 的 group 结构要跟普通 group 一致（members/agent_list），确保 useChatStream 无缝复用

---

## 不在本次范围（后续计划）

- L1 项目内引导 agent（进入项目后帮建群聊）
- L2 群负责人 agent（群内帮分配任务）
- render_view DSL 模板分层（L2 组合模板、L3 自定义）
- chat 页 render 化（长期）
- 数据浏览器愿景的外部数据接入（MCP）
- 自主度可调（陪伴/协作/托管三档）
- 回溯能力（L2 回 L0 修改）
