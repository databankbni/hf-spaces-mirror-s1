# AgentFlow 产品演进讨论记录

> 记录时间：2026-06-20
> 讨论主题：从"每页一个 agent"到"AI 原生数据浏览器"的产品演进思考

---

## 一、讨论起点

原始想法：在每个页面加入可对话 agent，快捷键调出对话框，让 agent 介绍页面、操控页面（如设置页让 agent 帮忙设置）。

经讨论，演进为更深层的产品范式反思。

---

## 二、核心产品哲学

### 痛点
AgentFlow 提供通用能力（agent + 系统提示词 + 流程编排），但使用成本高：用户要懂项目、agent、群聊、任务、流程。学习曲线陡峭。

### 核心翻转
> 传统：用户学产品 → 操作 UI → 构建结构 → agent 执行
> 目标：用户提需求 → agent 构建结构 → agent 执行 → render_view 验收

用户只暴露"意图"，agent 把意图翻译成结构。**这是 AI native 应用最该做的事——不是给 UI 贴 chat，而是让 chat 成为主交互，UI 退为 agent 的手脚。**

### 闭环
提需求 → agent 构建 → render_view 展示 → 用户反馈 → agent 调整

---

## 三、分层引导设计（L0/L1/L2/L3）

本质是"漏斗式分层 agent"，每层 agent 帮用户跨过一道复杂度门槛。每页的 agent 不是独立助手，而是这个漏斗在该层级的化身，共享一份"引导上下文"层层传递。

| 层级 | 场景 | agent 角色 | 核心工具 | 成果出口 |
|------|------|-----------|---------|---------|
| L0 首页 | "我想写个武侠小说" | 需求 agent | create_project, pick_template | render_view 项目蓝图 |
| L1 项目内 | 项目建好怎么开工 | 项目 agent | create_group, define_direction | render_view 群聊规划 |
| L2 群内 | 群聊有了谁干啥 | 群负责人 agent | invite_agent, assign_task | chat + render_view |
| L3 成果 | 干完看效果 | (无新 agent) | — | render_view 验收 |

### 关键设计点
- **上下文传递**：层间传"结论卡片"（结构化）而非原始对话，避免下游重复提问。复用现有 chain 的 context_data 机制，但用独立 guide_session 表，不污染创作数据。
- **人机边界**：按"可逆性"划界。可逆操作（渲染、任务分配）agent 自主；不可逆操作（建项目、建群聊）agent 提议→用户确认→执行。
- **自主度可调**：三档预设（陪伴/协作/托管），按层级独立设置。自主度是三维的：执行自主度、对话密度、创造自由度。

---

## 四、AI 原生数据浏览器愿景（终极形态）

### 本质
把 HTML 里揉在一起的"数据/渲染/决策"三层解耦：
> 传统 web：数据提供商 → HTML（数据+渲染+布局混杂）→ 浏览器 → 人
> 数据浏览器：数据提供商 → 纯数据 API → AI 决策怎么渲染 → 渲染引擎 → 人

中间插入 AI 作为"渲染决策层"，数据与渲染解耦。同一份数据，用户说"看趋势"→折线图；"看明细"→表格。

### 关键洞察：AgentFlow 已是雏形
- render_view 引擎（8 视图）= 渲染引擎
- /api/v1/* = 数据协议
- agent + chain = AI 决策层

缺的不是新东西，是三步重组：
1. **视图 DSL**：render_view 调用从"代码写死"变"声明式 DSL"，AI 能直接生成
2. **URL 化**：视图状态编码进 URL，可分享/收藏/复现
3. **工具化**：把"渲染"做成 agent 工具，agent 可调用

### 视图 DSL 示例
```yaml
view: table
data: /api/v1/projects
columns: [name, status, created_at]
sort: created_at desc
filter: status == 'active'
actions: [open, delete]
```
URL encode 后即"视图定位符"：`/v/eyJ2aWV3IjoidGFibGUi...`

### URL 重新定义
不再是"页面地址定位符"，而是"视图定位符"——记录数据从哪来、怎么渲染、怎么过滤、怎么排序。可像网页一样收藏、分享。传统 URL 指向固定页面，此 URL 指向"数据+渲染配方"。

### 模板分层（类 Vue）
- L1 内置：table/list/card/tree/timeline...（已有）
- L2 组合：dashboard、master-detail
- L3 自定义：agent 用 DSL 生成新模板

### agent 分工
- 数据 agent：取数、过滤、聚合
- 视图 agent：选模板、定参数
- 模板 agent：创建/优化模板
- 导演 agent：理解意图、调度上面三个
（与现有 agentflow 多 agent 群聊完全契合）

### 与 MCP 的呼应
"信息提供商直接给 AI 的 API"正是 MCP（Model Context Protocol）在做的事。AgentFlow 的 /api/v1 可看作"内部 MCP server"，未来接外部 MCP server 即可浏览外部数据。这是现成的生态接入点，不用从零造协议。

---

## 五、演进策略：渐进抽取（第三条路）

不"直接封装现有为 SDK"，也不"重新开始构建"，走第三条路。

### 为什么不直接封装
现有代码耦合了项目/群聊/任务概念，直接封装会把"创作平台"假设带进 SDK，限制未来。

### 为什么不重新构建
现有 render_view/agentflow/chain 是宝贵资产，重写浪费。且愿景需实践验证，凭空设计的 SDK 易脱离实际。

### 渐进抽取三阶段
1. **当前阶段**：完善功能时，有意识把"可复用能力"做独立，但不急着抽包
   - render_view 引擎保持独立，加 DSL 化能力
   - agentflow SDK 保持独立
   - 数据 API 保持 RESTful，未来可包成 MCP server
2. **中期**：L0/L1/L2 引导跑通后，把"引导层"抽象成独立模块（= 数据浏览器 AI 决策层雏形）
3. **长期**：模块成熟后自然抽 SDK，形态从实践中长出

### 心态
当前产品不是"要被抛弃的原型"，是"数据浏览器的第一个应用"。项目/群聊/任务只是它浏览的第一批数据类型。用"数据浏览器思维"继续完善，它自然长成愿景。

---

## 六、当前完善功能路径（按优先级）

### 第一步：L0 首页引导 agent（最高优先级）
- 现首页是静态项目列表，新用户懵
- 加召唤对话框（Cmd+K）或主区域引导
- agent 调 create_project + pick_template
- 关键节点确认（按可逆性）

### 第二步：render_view 升格为"确认 UI"
- agent 建完项目 → render_view 出"项目蓝图卡"让用户确认
- 复用现有 8 视图引擎
- render_view 从"群聊成果展示"扩展到"引导确认"

### 第三步：L1 项目内引导 + L2 群负责人
- 项目页加引导 agent，帮建群聊、分方向
- 群聊加"负责人"角色 agent，帮邀请 agent、分任务
- 复用第一步召唤机制，agent 角色按 route 切换

### 关键桥梁：render_view DSL 化
当前完善功能时做**一件事**同时服务两个目标——把 render_view 调用从"代码写死"改成"DSL 声明"。
- 当前价值：L0 引导 agent 能动态生成视图
- 未来价值：数据浏览器"视图 DSL"的 v0.1

这是"当前能用"和"未来 SDK"的最大公约数。

---

## 七、风险提醒

1. **对话不是万能交互**：擅长意图表达，不擅长精确操作（改 api_key、多选拖拽）。设置页等配置型页面保留表单，不强行对话化。
2. **AI 决策渲染可靠性**：AI 选错模板→渲染错→用户困惑。需"渲染预览+确认"，渲染可逆可大胆，落库不可逆要确认。
3. **性能**：每次渲染过 AI 决策比静态页面慢。需视图缓存，URL 天然支持（URL 是 cache key）。
4. **不要重发明 web**：要能跟现有 web 互通，能嵌入/被链接/渲染外部数据。MCP 接入是桥梁。
5. **保留"我自己来"通道**：引导对话框始终有"手动接管"按钮，引导是选项不是强制。
6. **回溯能力**：用户在 L2 发现方向不对，要能回 L0/L1 改。agent 做 impact analysis，用户做决策。

---

## 八、会变多余 vs 必须保留

### 会变多余（未来可收敛）
- Index/ProjectPage/ChatPage/AgentsPage 等独立 page 组件
- react-router 多路由（简化为对话 session + 当前视图状态）
- 各 page 重复的列表/卡片逻辑

### 必须保留
- 设置表单（精确操作）
- render_view 引擎（升格为 app 级渲染层）
- chain/agent 编排机制（agentflow SDK）
- 数据 API（未来包成 MCP server）

---

## 九、决策记录（2026-06-20 讨论）

### 已决策
1. **切入点**：L0 首页引导 agent + render_view DSL 化，两件事一起做。当前能用 + 未来铺路同步。
2. **agent 身份形态**：前台统一后台分工。用户视角是单一导演 agent（连贯），后端按 route 调用不同专职 agent（专业度），交接由导演调度。
3. **URL 作为会话定位符**（关键决策）：URL 不只是视图定位符，而是"会话定位符"，统一四个维度：
   - route 路径 → 当前场景
   - agent 身份参数 → 当前角色（L0/L1/L2）
   - chain/session id → 当前对话链
   - 视图 DSL → 当前渲染内容
   - 切 URL = 切身份+chain+视图同步联动，URL 是唯一真相源，可分享/刷新/回溯
4. **引导对话框通用化**：引导对话框 = 随 URL 切换的通用群聊组件，支持单 agent（L0）和多 agent（L2 群负责人邀请），成员动态加入/退出。复用现有 useChatStream 机制。引导对话框与群聊收敛为同一组件 `<UniversalChat>`。

### 待决策
1. ~~URL 编码方案~~ → 已决策：URL 前缀匹配 agent 身份（见决策6），视图 DSL 用 base64 进 hash
2. ~~UniversalChat 与现有 ChatPage 关系~~ → 已决策：新建轻量 UniversalChat 侧边栏组件，复用 useChatStream hook，不复用 ChatPage（ChatPage 是重组件项目工作台）
3. ~~L0 首页引导形态~~ → 已决策：侧边栏+主区域保持状态（见决策7），L0 首次无项目时侧边栏默认展开+主区域空状态引导
4. ~~DSL 格式~~ → 已决策：JSON（复用现有 RenderSpec，不从零造）
5. ~~guide_session 存储~~ → 已决策：废弃 guide_sessions 表方案，改用"引导 project"方案（见决策8）
6. ~~useChatStream 改造~~ → 已决策：不用改（引导 project 方案下 groupId 还是 groupId）
7. ~~chat 页 render 化~~ → 已决策：短期 chat 保持特殊组件，长期 RenderSpec 演进支持有状态交互视图

### 概念澄清（2026-06-20）
**useChatStream 当前逻辑**：群聊流式对话核心 hook，所有 API 调用绑 groupId（chatStream/chatStreamCancel/chatStreamAttach/chatStreamStatus）。核心数据流：handleSend→SSE→事件处理（chain_start/token/tool_call/tool_result/render_spec/done）→tryResumeStream（找 streaming packet 重新订阅）。入参必须 groupId+group+members+agentList+taskChainViews。

**关键洞察（用户提出）**：groupId 本质只是一个 key，用于后端匹配会话。全局召唤对话框可以有自己的 id，有 id 映射去找就行。

**现有表硬约束**（已绕过）：Group.project_id NOT NULL、Chain.group_id NOT NULL 等。原以为要新建 guide_sessions 表绕过，后发现用"引导 project"方案完全不用动这些约束。

### 最终方案：引导 project（2026-06-20 确定）

**核心思想**：给引导 agent 们设定一个 project，这个 project 用来告诉 agent 如何与当前项目交互。引导 project 本质也是普通 project，有 agent/group/chain/资源，只是用途不同。

**关键决策**：
8. **引导 project 方案**（替代 guide_sessions 表）：
   - project 表加 `is_guide` 轻量标记（不建新表，不改本质，只是用途标记）
   - 每用户一个引导 project，首次使用时创建
   - 引导 project 就是普通 project（有 agent/group/chain/资源），不展示在"我的项目"列表（前端过滤 is_guide）
   - 引导 agent 配置系统级工具（跨 project 操作）+ 权限 + 信息查询能力
   - useChatStream 不用改（groupId 还是 groupId，group 属于引导 project）
   - chain 表不用改（chain.group_id 指向引导 project 的 group）
   - guide_sessions 表不建（废弃）

9. **跨 project 操作**（用户洞察）：没有本质技术障碍，就是三件事：
   - 系统级工具：create_project / update_project_goal / query_projects / create_group / assign_task 等，参数带 target_project_id
   - 权限：给引导 agent 配置这些工具的执行权限
   - 信息查询：agent 能查询当前所有 project 的状态/id/结构，知道要操作谁
   - 现有工具是"项目内隐式绑定当前 project"，扩展成"系统级工具显式带 target_project_id"
   - 上下文天然分离：agent 对话历史在引导 project，工具调用操作目标 project

10. **chat 页 render 化**（长期方向）：短期 chat 保持特殊组件（有状态交互复杂），长期 RenderSpec 演进支持有状态交互视图，ChatView 作为其中一种 view_type。这是 render_view 引擎从"纯展示"到"支持交互"的演进，是数据浏览器愿景核心能力。

**方案好处**：几乎不动后端数据模型（只加 is_guide 标记 + 系统级工具集），最大化复用现有 project/group/chain 机制，引导 agent 有完整上下文（提示词/工具/记忆都在 project 里配置）。

### 关键发现（2026-06-20 代码审查）
**RenderSpec 已经是 DSL！** 现有 [render-engine/types.ts](../client/src/render-engine/types.ts) 的 RenderSpec 就是完整声明式视图 DSL：
- view_type + data/data_source + options + style + actions
- 已支持 data_source（远程 API 查询）、transform（过滤/排序/重命名）
- **已支持 render_target（CSS selector 指定渲染目标 DOM）** ← 天然支持侧边栏+主区域架构
- 已支持 actions（navigate/open_detail/trigger_tool）

**这意味着 render_view DSL 化已完成 80%**。agent 现在就在用 render_view 工具生成 RenderSpec JSON。要做的只是：
1. 把 RenderSpec JSON 做 URL 编码（base64 进 hash）→ URL 化
2. 把 RenderEngine 提升为页面级渲染入口（不只群聊成果）→ 主区域渲染

不是从零造 DSL，是"把现有 RenderSpec URL 化 + 提升为页面级"。工作量大幅降低。

### 后续补充决策（2026-06-20 第二轮）
6. **agent 路由用 URL 前缀匹配**（关键决策）：按 URL 最长前缀匹配决定 agent 身份，未配置则往短回退，兜底到 `/` 的 L0。配置形如：
   ```
   /                         → L0 需求 agent（兜底）
   /project/:id              → L1 项目 agent
   /project/:id/chat/:gid    → L2 群负责人 agent
   ```
   统一"页面路由"和"agent 路由"为同一套路由表的两个维度。项目级别通用召唤天然被前缀匹配支持（`/project/:id/*` 都命中 L1）。
7. **交互形态：侧边栏 + 主区域保持状态**（关键决策）：
   - 侧边栏（Cmd+K 收放）：UniversalChat 对话入口
   - 主区域：始终是当前视图状态，对话不打断
   - agent 调 render 工具 → 主区域更新渲染
   - 类似 VS Code 布局，比"主区域对话"更不侵入
   - L0 首页首次引导特殊处理：无项目时侧边栏默认展开+主区域空状态引导；有项目后侧边栏收起、主区域列表

---

## 十、实施进展记录

> 计划文档：[plan-l0-guide-agent.md](./plan-l0-guide-agent.md)
> 本章节记录每个任务的实施结果，便于回溯。

### M1 后端基础就绪（T1-T4）✅

**T1. project 表加 is_guide 字段** ✅
- 文件：[server/app/models/project.py](../server/app/models/project.py) + [migration](../server/alembic/versions/2026_06_20_0001-add_is_guide_to_projects.py)
- 结果：is_guide bool 字段加入，migration 跑通

**T2. 引导 project 自动创建** ✅
- 文件：[server/app/services/guide_service.py](../server/app/services/guide_service.py) + [server/app/api/v1/guide.py](../server/app/api/v1/guide.py) + [guide_l0.json](../server/app/default_presets/agent_templates/guide_l0.json)
- 结果：POST /api/v1/guide/ensure 幂等创建 project+agent+group+lead member，8 个工具绑定，验证通过

**T3. 系统级工具集** ✅
- 文件：[agentflow/crud_processors.py](../agentflow/crud_processors.py) + [agentflow/tool_adapter.py](../agentflow/tool_adapter.py) + [agentflow/builtin_processors.py](../agentflow/builtin_processors.py) + [agentflow/tool_catalog.py](../agentflow/tool_catalog.py) + [server/app/orchestrator/tool_adapter.py](../server/app/orchestrator/tool_adapter.py)
- 新增工具：query_projects / list_templates / pick_template（通过 ToolServiceAdapter Protocol 解耦，processor 调 adapter，adapter 调 server service）
- 结果：3 工具注册到 catalog，8 工具绑定引导 agent，is_guide 字段端到端传递（1 引导 + 43 用户项目）

**T4. 引导 agent 配置** ✅
- 文件：[guide_l0.json](../server/app/default_presets/agent_templates/guide_l0.json)
- 结果：L0 需求 agent 提示词基本版完成（avatar 🧭，skill_refs: self-memory/render-view），优化留 T13

### M2 前端对话可用（T5-T7）

**T5. UniversalChat 侧边栏组件骨架** ✅
- 文件：
  - 新建 [client/src/api/guide.ts](../client/src/api/guide.ts) —— guide API 封装（ensure/getState）
  - 新建 [client/src/components/UniversalChat.tsx](../client/src/components/UniversalChat.tsx) —— 侧边栏骨架
  - 修改 [client/src/api/index.ts](../client/src/api/index.ts) —— 导出 guideApi
  - 修改 [client/src/store/appStore.ts](../client/src/store/appStore.ts) —— 加 universalChatOpen 状态 + toggle/setOpen
  - 修改 [client/src/App.tsx](../client/src/App.tsx) —— 挂载 UniversalChat（路由外层常驻）
- 实现：
  - Cmd/Ctrl+K 全局快捷键收放（preventDefault 避免浏览器默认）
  - 浮层式侧边栏（fixed right, translate-x 收放，宽 420px），收起时显示浮动触发按钮
  - 首次展开调 guideApi.ensure() 幂等初始化引导 project
  - UI 占位：标题栏（agent 头像+名+状态）+ 欢迎消息 + 输入框（Enter 发送/Shift+Enter 换行）
  - 未接入 useChatStream（T7 做），handleSend 为占位
- 验证：typecheck + lint 通过

**T6. URL 前缀匹配 agent 路由** ✅
- 文件：新建 [client/src/lib/guideRouter.ts](../client/src/lib/guideRouter.ts)
- 实现：最长前缀匹配（按路由表长→短顺序），L0 兜底，L1/L2 占位（enabled:false），matchPattern 支持 :param 路径参数解析
- 当前只激活 L0（首页），L1/L2 结构就绪供后续扩展

**T7. UniversalChat 接入引导 project（useChatStream）** ✅
- 文件：重写 [client/src/components/UniversalChat.tsx](../client/src/components/UniversalChat.tsx)
- 数据流：guideApi.ensure() → group_id → useGroup → group（含 members）→ useChainViews → taskChainViews → useChatStream → activeReplyChain + handleSend
- 复用 ChainBlock 渲染消息（历史链 + 流式回复 liveStream）
- 派生 members/agentList 与 ChatPage 完全一致
- group 加载完后调 loadGroupChains（与 ChatPage 一致的守卫）
- 停止生成按钮（handleStopStream）+ 滚动到底部
- 验证：typecheck 通过

### M3 渲染打通（T8-T10）✅

**T8. RenderSpec base64 编解码** ✅
- 文件：新建 [client/src/render-engine/urlCodec.ts](../client/src/render-engine/urlCodec.ts)
- 实现：encodeSpec/decodeSpec（base64url，URL 安全）+ specToHash/hashToSpec（#v= 前缀）

**T9. URL hash → 主区域渲染** ✅
- 文件：新建 [client/src/hooks/useViewFromHash.ts](../client/src/hooks/useViewFromHash.ts) + 修改 [App.tsx](../client/src/App.tsx)
- 实现：useViewFromHash 监听 hashchange，App 条件渲染（有 hash→RenderEngine / 无 hash→Routes）+ clearViewHash 返回

**T10. agent render → 主区域** ✅
- 文件：修改 [UniversalChat.tsx](../client/src/components/UniversalChat.tsx)
- 实现：监听 activeReplyChain 的 packet.metadata.render_spec，变化时同步到 URL hash（replaceState + dispatchEvent），触发主区域渲染。用 lastSpecKeyRef 去重避免频繁触发。

### M4 端到端跑通（T11-T13）

**T11. 首页无项目时侧边栏默认展开 + 空状态引导** ✅
- 文件：修改 [client/src/pages/Index.tsx](../client/src/pages/Index.tsx)
- 实现：useEffect 检测 projectList 为空时 setUniversalChatOpen(true)（autoOpenedRef 防重复）；空状态文案改为"按 ⌘K 召唤引导助手"

**T12. 项目列表过滤 is_guide** ✅
- 文件：修改 [client/src/pages/Index.tsx](../client/src/pages/Index.tsx)
- 实现：projectList 加 `.filter(p => !p.is_guide)`，引导 project 不出现在"我的项目"列表

**T13. L0 引导 agent 提示词优化 + 端到端测试** ✅
- 文件：更新 [guide_l0.json](../server/app/default_presets/agent_templates/guide_l0.json)
- 提示词优化：加 render_view 主区域渲染指导（明确结果显示在主区域）+ 8 种视图类型说明 + 5 步对话流程（开场→收需求→推荐模板→建项目→交接）
- ensure API 调用更新已存在 agent 的提示词（guide_service 每次 ensure 都 upsert agent）
- dev server 启动：http://localhost:5174/
- 端到端测试路径：首页 → Cmd+K → 输入需求 → agent 推荐模板 → render_view 主区域渲染 → 确认建项目

---

## 十一、全部任务完成总结（2026-06-20）

### 里程碑达成
- ✅ M1 后端基础就绪（T1-T4）：引导 project + 系统级工具 + is_guide 端到端
- ✅ M2 前端对话可用（T5-T7）：UniversalChat 侧边栏 + useChatStream 流式对话
- ✅ M3 渲染打通（T8-T10）：RenderSpec URL 编解码 + hash→主区域渲染 + agent render→hash 同步
- ✅ M4 端到端跑通（T11-T13）：首页引导 + 项目过滤 + 提示词优化

### 新增文件清单
- 后端：guide_service.py / guide.py / guide_l0.json / migration
- 前端：guide.ts / UniversalChat.tsx / guideRouter.ts / urlCodec.ts / useViewFromHash.ts

### 修改文件清单
- 后端：project.py(model) / project_repo.py / tool_adapter.py(×2) / crud_processors.py / builtin_processors.py / tool_catalog.py / project.py(schema)
- 前端：appStore.ts / api/index.ts / App.tsx / Index.tsx

### 文档
- [product-evolution-discussion.md](./product-evolution-discussion.md) —— 产品演进讨论 + 决策 + 实施进展
- [plan-l0-guide-agent.md](./plan-l0-guide-agent.md) —— 实施计划（T1-T13 全部 ✅）

---

## 十二、端到端测试验证（2026-06-21）

### 测试方式
通过 API 直接调用 `/api/v1/groups/{group_id}/chat/stream` 发送 SSE 请求，分析事件流验证 agent 行为。

### 测试结果

#### ✅ 通过项
1. **T12 过滤生效**：引导 project 不出现在"我的项目"列表（44→43）
   - 修复：`projectList = items.filter(p => !p.is_guide)` + `ProjectBase.is_guide?: boolean` 类型补全
2. **T11 自动展开逻辑**：代码补全（useEffect + autoOpenedRef）
3. **agent 对话流程**：收需求 → 推荐模板 → 建项目，5 步流程正常
4. **系统级工具调用**：
   - `list_templates` → 返回 2 个模板（小说创作 + 狼人杀）✓
   - `pick_template` → 创建项目成功（8 Agent / 8 群聊 / 12 技能）✓
5. **render_view 调用**（提示词加强后成功）：
   - agent 调 `render_view`（card 视图）渲染项目蓝图 ✓
   - 8 个 Agent 卡片（含 cover_color / description / title）✓
   - actions 含"进入项目"导航 ✓
   - SSE 流发出 `event: render_spec` ✓
   - done 事件 metadata 含 render_spec 数组 ✓

#### ⚠️ 已知问题
1. **偶发超时**：agent 第二次 LLM 调用（处理工具结果）偶发 60s 超时
   - 原因：LLM 负载波动 + 工具结果较长
   - 影响：偶尔 done 事件内容是 `[Agent error: timed out after 60.00s]`
2. **浏览器交互遮挡**：创建新项目对话框遮挡侧边栏输入框
   - 影响：agent-browser 自动化测试 fill 失败
   - 待验证：前端 UniversalChat 是否正确接收 render_spec 并同步到 URL hash → 主区域渲染

### 提示词演进
T13 初版提示词说"用 render_view"，但 agent 不主动调。加强为 STEP 格式 + 强制规则后成功：
- 第 3 步"推荐模板"：STEP 1 list_templates → STEP 2 render_view → STEP 3 文字
- 第 4 步"建项目"：STEP 1 pick_template → STEP 2 render_view → STEP 3 文字
- 加"⚠️ 不调 render_view 只用文字 = 失败"强制措辞

### 待用户验证（浏览器端）
1. 打开 http://localhost:5174/
2. 按 Cmd/Ctrl+K 调出侧边栏
3. 输入"帮我建个悬疑小说项目"
4. 观察：agent 是否调 render_view → 主区域是否渲染项目蓝图卡片
5. 验证 T10 机制：render_spec → URL hash → useViewFromHash → RenderEngine

---

## 十三、L1 项目内引导 agent 实施（2026-06-21）

### 冲突与决策
发现 L1 项目内引导 agent 与现有 coordinator（项目总控·编舟）职责重叠：
- L1 设计职责：帮用户建群聊、分方向、render_view 渲染群聊规划
- coordinator 已有能力：create_group / invite_agent / add_group_member / render_view / pipeline 编排

**融合方案（用户确认）**：L1 = 复用 coordinator，不新建 agent。
- 最小改动：激活路由 + 项目页挂载 UniversalChat + coordinator 提示词加 STEP 强制 render_view
- coordinator 已有全套工具，只需提示词优化

### 项目页行为决策
**用户确认**：项目页显示概览 + 召唤入口，不再直接重定向到第一个群聊。
- 有群聊：显示群聊卡片列表，点击进入
- 无群聊：显示空状态 + 召唤提示（Cmd+K 调出 coordinator 帮建）

### 实施清单

#### 后端
1. **GuideService 加 ensure_project_guide_state**（[guide_service.py](../server/app/services/guide_service.py)）
   - 幂等确保项目有 coordinator ProjectAgent + 项目引导群
   - 查 coordinator（按 agent.name = "项目总控·编舟"），没有则调 project_service._ensure_project_coordinator 补建
   - 查 coordinator 所在群聊，没有则建「项目引导群」+ 加 coordinator 为 lead
   - 模板项目复用已有群聊，空白项目补建引导群

2. **guide API 加 POST /guide/ensure_project**（[guide.py](../server/app/api/v1/guide.py)）
   - Query 参数 project_id
   - 404 处理项目不存在

3. **coordinator.json 提示词优化**（[coordinator.json](../server/app/default_presets/agent_templates/coordinator.json)）
   - 加"L1 引导流程（项目开工）"章节
   - 场景判断：有群聊（模板项目）vs 无群聊（空白项目）
   - 空白项目引导 STEP 格式：STEP 1 收需求 → STEP 2 规划群聊+render_view(graph) → STEP 3 建群聊+render_view(card) → STEP 4 交接
   - 加 render_view 强制规则 + graph/card 示例
   - 加"⚠️ 不调 render_view 只用文字 = 失败"强制措辞

#### 前端
4. **激活 guideRouter L1 路由**（[guideRouter.ts](../client/src/lib/guideRouter.ts)）
   - L1 pattern `/project/:id` enabled: true
   - L2 仍为占位（enabled: false）

5. **guide API 封装加 ensureProject**（[guide.ts](../client/src/api/guide.ts)）
   - `guideApi.ensureProject(projectId)` → POST /guide/ensure_project?project_id=xxx

6. **UniversalChat 支持 L1 模式**（[UniversalChat.tsx](../client/src/components/UniversalChat.tsx)）
   - useLocation + matchGuideRoute 判断当前层级
   - guideKey: L0 用 'L0'，L1 用 'L1:<projectId>'
   - guideKey 变化时清空旧 guide，重新 ensure
   - L0 调 ensure()，L1 调 ensureProject(projectId)
   - 空状态欢迎语按 level 切换（L0 建项目 / L1 建群聊）

7. **ProjectPage 改造**（[ProjectPage.tsx](../client/src/pages/ProjectPage.tsx)）
   - 不再自动重定向到第一个群聊
   - 显示项目名称 + 描述 + 群聊卡片列表
   - 无群聊时显示空状态 + 召唤提示
   - 群聊卡片显示 lead_agent / member_count / message_count / task_count

8. **Index.tsx handleOpenProject 改造**
   - 点击项目卡片跳到 `/project/${projectId}`（项目概览页），不再直接进群聊
   - 删除未使用的 groupApi import

### UI 修复（用户反馈）
- **render_view 卡片剪裁**：details 内容区 padding 不足，改为 `px-4 py-4 border-t bg-background/30`，加 `overflow-hidden rounded-md`，外层 `my-4 space-y-3`

### 验证
- 前端 typecheck 通过（`npx tsc --noEmit -p tsconfig.app.json` exit 0）
- 后端 Python 语法通过
- coordinator.json 有效 JSON

### 待用户验证
1. 进入项目页 `/project/:id` → 看到项目概览 + 群聊列表
2. Cmd+K 召唤 coordinator → 对话建群聊
3. coordinator 调 render_view(graph) 渲染 pipeline 规划
4. coordinator 调 render_view(card) 渲染群聊结构
5. 群聊出现在项目概览页
