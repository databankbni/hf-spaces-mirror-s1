# Agentflow 核心概念

## 概览

Agentflow 是一个基于信息包（InfoPacket）流转的 agent 执行框架。所有信息处理 — 用户输入、LLM 调用、工具调用、工具结果、错误 — 都以 InfoPacket 为载体，在 Processor 构成的管线中流转。

---

## 1. InfoPacket（信息包）

信息包是 agentflow 中信息流动的最小单元。每一次消息、每一次工具调用、每一次结果返回，都是一个 InfoPacket。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 唯一标识，不可变 |
| `sender_id` | str | 发送者 ID（agent_id / processor_id），不可变 |
| `parent_id` | Optional[str] | 父包 ID，用于追溯因果关系，不可变 |
| `chain_id` | str | 所属链 ID，不可变 |
| `content` | str/dict/bytes | 包内容，不可变 |
| `type` | PacketType | 包类型，不可变 |
| `timestamp` | datetime | 创建时间，不可变 |
| `_metadata` | dict | 元数据（追加式，不可修改已有 key） |

### PacketType（包类型）

| 类型 | 含义 | 典型场景 |
|------|------|----------|
| `NORMAL` | 普通消息 | 用户输入、Agent 回复、子链返回的最终结果 |
| `CALL` | 工具调用请求 | Agent 决定调用某个工具/子 Agent |
| `RESPONSE` | 工具调用结果 | 工具/子 Agent 执行完毕，返回结果给调用者 |
| `ERROR` | 错误 | 工具执行失败、LLM 调用异常 |
| `STREAM` | 流式片段 | LLM 流式输出的 token 片段（不参与历史） |
| `INTERRUPT` | 中断 | 流程被中断（如 stop_agent） |

### 关键特性

- **不可变**：核心字段（id, sender_id, parent_id, chain_id, content, type, timestamp）创建后不可修改
- **metadata 追加式**：`add_metadata()` 只能添加新 key，不能修改已有 key
- **`create_child()`**：创建子包，自动继承 chain_id 和 parent_id

---

## 2. Chain（链）

链是一个需求从产生到满足的完整信息包序列。

### 定义

一个 chain 由同一个 `chain_id` 标识，包含从需求产生（用户消息或 CALL 包）到最终满足（最终回复或 RESPONSE 包）的所有 InfoPacket。

### 链的生命周期

```
链开始：用户消息 / 收到 CALL 包
  ↓
处理过程：LLM 调用、工具调用、子 Agent 调用...
  ↓
链结束：最终回复 / 产出 RESPONSE 包
```

### 子链（Sub-chain）

当链中的 Agent 调用工具或子 Agent 时，会产生一条**子链**：

```
A 链 (chain_id=A1)
  ├── packet_1: 用户消息 (chain=A1)
  ├── packet_2: Agent A 的 LLM 回复 (chain=A1)
  ├── packet_3: CALL 包 — 调用 Agent B (chain=A1)     ← A 链上的工具调用
  │
  │   [Agent B 开始处理，创建子链 A2]
  │   B 子链 (chain_id=A2, parent_chain_id=A1)
  │     ├── packet_4: 收到的 CALL 包 (chain=A2)        ← B 接收时重建为 A2 的包
  │     ├── packet_5: B 的 LLM 调用 (chain=A2)
  │     ├── packet_6: B 调用子工具 (chain=A2)
  │     ├── packet_7: 子工具结果 (chain=A2)
  │     ├── packet_8: B 的最终 LLM 回复 (chain=A2)
  │     └── packet_9: RESPONSE 包 (chain=A2)           ← B 产出结果
  │
  ├── packet_10: 收到的 RESPONSE (chain=A1)            ← CallbackPlugin 重建为 A1 的包
  ├── packet_11: Agent A 继续 LLM 处理 (chain=A1)
  └── packet_12: Agent A 最终回复 (chain=A1)
```

### chain_id 隔离原则

**A 链的 LLM 只能看到 A 链的包。B 子链的内部处理过程（packet_4~9）对 A 不可见。**

A 看到的历史：
```
packet_1: 用户消息
packet_2: Agent A 的回复
packet_3: [Tool Call] Agent B
packet_10: [Tool Result] Agent B result=...
packet_11: Agent A 的回复
packet_12: Agent A 最终回复
```

B 子链的历史（仅 B 自己可见）：
```
packet_4: 收到的 CALL
packet_5: B 的 LLM 调用
packet_6: [Tool Call] 子工具
packet_7: [Tool Result] 子工具
packet_8: B 的 LLM 回复
packet_9: RESPONSE（最终结果）
```

### parent_chain_id

子链通过 `parent_chain_id` 元数据指向父链。这使得：
- 可以追溯一个工具调用的完整执行路径
- 可以构建链的树结构
- 可以在需要时展开子链的详细历史

### 子链隔离的实现机制

子链隔离由 `CallbackPlugin` 在工具处理器的 `pre_process` / `post_process` 中自动完成：

**pre_process（CALL 包到达工具处理器时）：**
1. 检测到 `PacketType.CALL`
2. 保存原始 `chain_id`（调用者链 ID）到 `call_info['original_chain_id']`
3. 生成新的 `sub_chain_id`，替换 CALL 包的 `chain_id`
4. 后续工具处理器产出的所有包自动继承 `sub_chain_id`（通过 `create_child()`）

**post_process（工具处理完成时）：**
1. 检测到工具输出包关联的 CALL 记录
2. 从 `call_info['original_chain_id']` 取回调用者链 ID
3. 创建 RESPONSE 包时使用 `original_chain_id`，而非当前包的 `chain_id`
4. RESPONSE 包路由回调用者 Agent

```
Agent A (chain A1)                    Tool B (CallbackPlugin)
    │                                      │
    ├─ CALL (chain=A1) ──────────────────→ │
    │                                      ├─ pre_process: 
    │                                      │   original_chain_id = A1
    │                                      │   sub_chain_id = S1
    │                                      │   packet.chain_id = S1
    │                                      │
    │                                      ├─ core_process (chain=S1)
    │                                      │   所有中间包 chain_id=S1
    │                                      │
    │                                      ├─ post_process:
    │                                      │   RESPONSE.chain_id = A1
    │                                      │   (使用 original_chain_id)
    │                                      │
    │ ←── RESPONSE (chain=A1) ──────────── │
```

**关键保证：**
- 工具处理器的中间包（chain=S1）不会出现在调用者链（A1）的历史中
- MemoryPlugin 按 chain_id 查询历史，天然实现链间隔离
- 子链可嵌套：工具 A 调用工具 B 时，B 也会获得自己的子链

---

## 3. Tree（树）

树是由父子链关系构成的层级结构。

### 结构

```
Project Tree
  ├── Chain A（群聊讨论）
  │    ├── Sub-chain A.1（任务执行）
  │    │    └── Sub-chain A.1.1（子任务）
  │    └── Sub-chain A.2（另一个工具调用）
  ├── Chain B（另一个群聊讨论）
  │    └── Sub-chain B.1（工具调用）
  └── Chain C（独立任务）
```

### 用途

- **项目级视角**：查看整棵树，了解项目的完整讨论和执行过程
- **调试追踪**：从父链的工具调用出发，追踪子链的完整执行路径
- **上下文回溯**：子链可以引用父链的上下文（通过 rollover summary）

### Tree 与当前项目的映射

| 项目概念 | agentflow 概念 |
|----------|---------------|
| Project | Tree 的根 |
| Group（群聊） | Tree 下的一个 Chain |
| Task（任务） | Group Chain 下的子 Chain |
| Agent 讨论 | Chain 上的 InfoPacket 序列 |
| 工具调用 | CALL 包 → 子 Chain → RESPONSE 包 |
| 消息历史 | Chain 上的 InfoPacket 查询 |

---

## 4. Processor（处理器）

处理器是对信息包进行处理的最小单位。

### 定义

Processor 接收 InfoPacket，处理后产出新的 InfoPacket。它是 agentflow 管线的基本构建块。

### 接口

```python
class Processor:
    def core_process(self, packet: InfoPacket) -> InfoPacket | List[InfoPacket]:
        """核心处理逻辑，可以是 async"""
        ...

    def input(self, packet: InfoPacket) -> None:
        """接收信息包（非阻塞，提交到线程池）"""
        ...
```

### 处理流程

```
input(packet)
  → submit_process 到 ThreadPoolExecutor（非阻塞）
  → _process(packet):
      → pre_process（插件钩子）
      → core_process（核心逻辑）
      → post_process（插件钩子）
      → _output_to_list（发往下游处理器）
```

### 关键特性

- **非阻塞输入**：`input()` 提交到线程池后立即返回
- **内部可 await**：`core_process()` 可以是 async，在线程池内通过 `asyncio.run()` 执行
- **包不可变**：Processor 不能修改输入包，只能创建新包

---

## 5. Agent（智能体）

Agent 是以 LLM 作为核心处理单元的 Processor。

### 定义

Agent 拥有 LLM、系统提示词、工具列表（_call_targets）、插件列表。它接收用户消息或工具结果，调用 LLM，产出回复或工具调用请求。

### 处理流程

```
收到 InfoPacket
  → _build_messages(): 从 chain 历史构建 LLM 消息列表
  → self.llm.chat(messages, tools=schemas)
  → 如果有 tool_calls:
      → 创建 CALL 包（每个 tool_call 一个）
      → 返回 [text_packet?, *call_packets]
  → 否则:
      → 返回 NORMAL response_packet
```

### 工具调用流程

```
Agent.core_process() 产出 CALL 包
  → post_process: _route_call_packet 路由到目标 Processor
  → _output_to_list: 目标 Processor.input(call_packet)
  → 目标 Processor 执行 core_process()
  → 目标 post_process: CallbackPlugin 将结果转为 RESPONSE 包，回流给 Agent
  → Agent.input(response_packet)
  → Agent._process(): _build_messages 包含 CALL + RESPONSE，再次调 LLM
```

### chain 上的消息构建

`_build_messages()` 从 MemoryPlugin 获取 chain 历史，按类型转换为 LLM 消息：

| PacketType | LLM Role | 格式 |
|------------|----------|------|
| NORMAL（自己发的） | ASSISTANT | 直接用 content |
| NORMAL（别人发的） | USER | 直接用 content |
| CALL（自己发出的） | ASSISTANT | `[Tool Call] name arguments=...` |
| RESPONSE（工具返回） | USER | `[Tool Result] name result=...` |
| ERROR | USER | `[Tool Error] name error=...` |

---

## 6. Plugin（插件）

插件是 Processor 的可复用组件，用于扩展处理流程。

### 定义

Plugin 通过 `pre_process()` 和 `post_process()` 钩子介入 Processor 的处理流程。

### 接口

```python
class Plugin:
    def pre_process(self, packet: InfoPacket) -> InfoPacket:
        """在 core_process 之前执行"""
        return packet

    def post_process(self, packet: InfoPacket, output_list: List[Processor]) -> Tuple[InfoPacket, List[Processor]]:
        """在 core_process 之后执行，可以修改 output_list"""
        return packet, output_list

    def build_system_message(self, packet: InfoPacket) -> Optional[str]:
        """构建系统消息（Agent 专用）"""
        return None
```

### 内置插件

| 插件 | 功能 |
|------|------|
| `MemoryPlugin` | 记忆管理：保存包到 InfoManager，加载 chain 历史 |
| `CallbackPlugin` | 工具结果回流：将工具结果包转为 RESPONSE 回流给调用者 Agent |
| `SkillPlugin` | 技能注入：根据消息内容自动选择相关 skill 注入系统提示词 |
| `ContextRolloverPlugin` | 上下文换链：chain 过长时自动总结并创建新 chain |
| `AllModelPlugin` | 并行工具调用：管理多个工具调用的 batch |
| `ReasoningFilterPlugin` | 推理过滤：从历史消息中剥离 reasoning 内容 |

### 插件组合

```python
agent = Agent(name="writer", llm=llm, system_prompt="...")
agent.add_plugin(MemoryPlugin(manager=info_manager))      # 记忆
agent.add_plugin(SkillPlugin(skill_roots=[...]))           # 技能
agent.add_plugin(ContextRolloverPlugin(max_chars=12000))   # 换链

# 工具注册时自动添加 CallbackPlugin
agent.register_call_target(tool_processor)  # 自动挂载 CallbackPlugin
```

---

## 7. Workspace（工作区）

Workspace 是 Processor 和 Agent 的注册中心。

### 职责

- **注册表**：存储所有 Processor 和 Agent 实例
- **资源共享**：共享 InfoManager（包存储）、全局插件
- **依赖注入**：通过 `tool_adapter` 注入外部服务能力

### 使用

```python
workspace = Workspace("my_project")
workspace.register(agent_a)
workspace.register(tool_processor)
workspace.tool_adapter = my_adapter  # 注入服务适配器

# Agent 创建时从 workspace 获取工具
agent = Agent.from_spec(spec, workspace=workspace)
```

---

## 8. Rollover（换链）

当一个 chain 的上下文过长时，自动总结并创建新 chain。

### 触发条件

Chain 上所有包的总字符数超过阈值（默认 12000 * 0.7 = 8400 字符）。

### 执行过程

1. 收集 chain 上所有包
2. 调 LLM 生成摘要（核心需求、已完成工作、待办、关键决策）
3. 在旧 chain 上创建 handoff 包（`rollover_handoff=True`）
4. 在新 chain 上创建 summary 包（`rollover_summary=True`）
5. 后续消息进入新 chain

### 对 LLM 的影响

- handoff 包被排除出消息列表
- summary 包作为 SYSTEM 消息注入：`[Previous Chain Summary from {chain_id}]\n{摘要内容}`
- Agent 看到前链摘要，保持上下文连续性
