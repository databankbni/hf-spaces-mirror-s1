# 技术选型文档

## 1. 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client (Frontend)                        │
│                     React + TypeScript + Vite                    │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP REST + WebSocket
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                         Server (Backend)                         │
│                        Python + FastAPI                          │
│                                                                 │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐│
│   │  API Layer  │  │  WebSocket  │  │   Agent Orchestrator    ││
│   │  (REST)     │  │   Layer     │  │   (核心业务逻辑)         ││
│   └─────────────┘  └─────────────┘  └─────────────────────────┘│
│                                                                 │
│   ┌─────────────────────────────────────────────────────────────│
│   │                    Service Layer                            ││
│   │  (业务逻辑：Project/Group/Task/Agent/Deliverable/Memory)   ││
│   └─────────────────────────────────────────────────────────────│
│                                                                 │
│   ┌─────────────────────────────────────────────────────────────│
│   │                   Repository Layer                          ││
│   │                  (数据访问抽象层)                            ││
│   └─────────────────────────────────────────────────────────────│
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │PostgreSQL│   │ agentflow│   │ LLM API  │
        │          │   │   SDK    │   │(OpenAI等)│
        └──────────┘   └──────────┘   └──────────┘
```

---

## 2. 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18+ | UI框架 |
| TypeScript | 5+ | 类型安全 |
| Vite | 5+ | 构建工具 |
| React Router | 6+ | 路由管理 |
| TanStack Query | 5+ | 服务端状态管理 |
| Zustand | 4+ | 客户端状态管理 |
| Tailwind CSS | 3+ | 样式框架 |
| shadcn/ui | - | UI组件库 |
| react-markdown | - | Markdown渲染 |
| rehype-highlight | - | 代码高亮 |
| react-syntax-highlighter | - | 代码块渲染 |
| dnd-kit | - | 拖拽排序 |
| sonner | - | Toast通知 |

### 2.1 前端目录结构

```
client/
├── public/
├── src/
│   ├── api/                    # API调用封装
│   │   ├── client.ts           # HTTP客户端配置
│   │   ├── projects.ts         # 项目相关API
│   │   ├── groups.ts           # 群聊相关API
│   │   ├── tasks.ts            # 任务相关API
│   │   ├── agents.ts           # Agent相关API
│   │   ├── deliverables.ts     # 交付物相关API
│   │   ├── resources.ts        # 资料相关API
│   │   └── memories.ts         # 笔记相关API
│   │
│   ├── components/             # 通用组件
│   │   ├── ui/                 # shadcn/ui组件
│   │   ├── layout/             # 布局组件
│   │   ├── markdown/           # Markdown渲染组件
│   │   └── common/             # 业务通用组件
│   │
│   ├── features/               # 功能模块
│   │   ├── projects/           # 项目管理
│   │   ├── groups/             # 群聊管理
│   │   ├── tasks/              # 任务管理
│   │   ├── agents/             # Agent管理
│   │   ├── deliverables/       # 交付物
│   │   ├── resources/          # 资料库
│   │   └── memories/           # 笔记
│   │
│   ├── hooks/                  # 自定义Hooks
│   │   ├── useWebSocket.ts     # WebSocket连接
│   │   ├── useStore.ts         # 状态管理
│   │   └── useApi.ts           # API调用Hook
│   │
│   ├── lib/                    # 工具库
│   │   ├── utils.ts            # 通用工具函数
│   │   └── constants.ts        # 常量定义
│   │
│   ├── pages/                  # 页面组件
│   │   ├── HomePage.tsx        # 首页/项目列表
│   │   ├── AgentWorld.tsx      # Agent世界
│   │   ├── ProjectPage.tsx     # 项目详情
│   │   ├── ChatPage.tsx        # 群聊页面
│   │   ├── DeliverablePage.tsx # 交付物查看
│   │   └── AgentDetailPage.tsx # Agent详情
│   │
│   ├── stores/                 # Zustand状态
│   │   ├── appStore.ts         # 全局状态
│   │   └── chatStore.ts        # 聊天状态
│   │
│   ├── types/                  # TypeScript类型定义
│   │   ├── project.ts
│   │   ├── group.ts
│   │   ├── task.ts
│   │   ├── agent.ts
│   │   ├── deliverable.ts
│   │   ├── resource.ts
│   │   └── memory.ts
│   │
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
│
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

---

## 3. 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行环境 |
| FastAPI | 0.110+ | Web框架 |
| Uvicorn | 0.29+ | ASGI服务器 |
| SQLAlchemy | 2.0+ | ORM |
| Alembic | 1.13+ | 数据库迁移 |
| asyncpg | 0.29+ | PostgreSQL异步驱动 |
| Pydantic | 2.6+ | 数据验证 |
| python-jose | 0.3+ | JWT认证（预留） |
| websockets | 12+ | WebSocket支持 |
| agentflow | - | Agent框架 |

### 3.1 后端目录结构

```
server/
├── alembic/                    # 数据库迁移
│   ├── versions/
│   └── env.py
│
├── app/
│   ├── api/                    # API路由层
│   │   ├── v1/                 # API版本
│   │   │   ├── __init__.py
│   │   │   ├── projects.py     # 项目API
│   │   │   ├── groups.py       # 群聊API
│   │   │   ├── tasks.py        # 任务API
│   │   │   ├── agents.py       # Agent API
│   │   │   ├── deliverables.py # 交付物API
│   │   │   ├── resources.py    # 资料API
│   │   │   ├── memories.py     # 笔记API
│   │   │   └── websocket.py    # WebSocket
│   │   └── deps.py             # 依赖注入
│   │
│   ├── core/                   # 核心配置
│   │   ├── config.py           # 配置管理
│   │   ├── database.py         # 数据库连接
│   │   └── security.py         # 安全相关
│   │
│   ├── models/                 # SQLAlchemy模型
│   │   ├── __init__.py
│   │   ├── base.py             # 基础模型
│   │   ├── project.py
│   │   ├── group.py
│   │   ├── task.py
│   │   ├── agent.py
│   │   ├── chain.py
│   │   ├── message.py
│   │   ├── deliverable.py
│   │   ├── resource.py
│   │   └── memory.py
│   │
│   ├── schemas/                # Pydantic Schema
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── group.py
│   │   ├── task.py
│   │   ├── agent.py
│   │   ├── deliverable.py
│   │   ├── resource.py
│   │   └── memory.py
│   │
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── project_service.py
│   │   ├── group_service.py
│   │   ├── task_service.py
│   │   ├── agent_service.py
│   │   ├── deliverable_service.py
│   │   ├── resource_service.py
│   │   ├── memory_service.py
│   │   └── export_service.py
│   │
│   ├── repositories/           # 数据访问层
│   │   ├── __init__.py
│   │   ├── base.py             # 基础Repository
│   │   ├── project_repo.py
│   │   ├── group_repo.py
│   │   ├── task_repo.py
│   │   ├── agent_repo.py
│   │   ├── deliverable_repo.py
│   │   ├── resource_repo.py
│   │   └── memory_repo.py
│   │
│   ├── orchestrator/           # Agent编排层（核心）
│   │   ├── __init__.py
│   │   ├── chain_manager.py    # Chain生命周期管理
│   │   ├── context_builder.py  # Agent上下文组装
│   │   ├── autonomy_controller.py # 自主级别控制
│   │   ├── message_dispatcher.py  # 消息分发
│   │   └── deliverable_generator.py # 交付物生成
│   │
│   ├── websocket/              # WebSocket管理
│   │   ├── __init__.py
│   │   ├── manager.py          # 连接管理
│   │   └── events.py           # 事件定义
│   │
│   └── main.py                 # FastAPI应用入口
│
├── tests/                      # 测试
│   ├── unit/
│   └── integration/
│
├── requirements.txt
├── pyproject.toml
└── alembic.ini
```

---

## 4. 数据库选型

**PostgreSQL 15+**

选择理由：
1. **JSON支持**：JSONB类型适合存储灵活的元数据、配置
2. **全文搜索**：内置全文搜索能力，方便资料检索
3. **扩展性**：支持数组类型、自定义类型
4. **成熟稳定**：生产级数据库，适合长期项目
5. **异步支持**：asyncpg提供高性能异步访问

### 4.1 数据库设计原则

- 使用UUID作为主键
- 时间戳使用UTC
- 软删除（deleted_at字段）
- JSON字段存储灵活数据
- 适当建立索引

---

## 5. API设计原则

### 5.1 RESTful规范

```
GET    /api/v1/projects              # 获取项目列表
POST   /api/v1/projects              # 创建项目
GET    /api/v1/projects/{id}         # 获取项目详情
PUT    /api/v1/projects/{id}         # 更新项目
DELETE /api/v1/projects/{id}         # 删除项目

GET    /api/v1/projects/{id}/groups  # 获取项目的群聊列表
POST   /api/v1/projects/{id}/groups  # 创建群聊
...
```

### 5.2 响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

### 5.3 错误处理

```json
{
  "code": 400,
  "message": "Validation error",
  "details": [
    { "field": "name", "message": "Name is required" }
  ]
}
```

---

## 6. WebSocket设计

### 6.1 连接路径

```
ws://localhost:8000/ws/chat/{group_id}
```

### 6.2 消息类型

```typescript
// 客户端 → 服务器
interface ClientMessage {
  type: 'send_message' | 'stop_agent' | 'resume';
  payload: any;
}

// 服务器 → 客户端
interface ServerMessage {
  type: 'agent_message' | 'agent_typing' | 'system_message' | 'task_update' | 'error';
  payload: any;
}
```

---

## 7. Agent集成方案

### 7.1 与agentflow SDK集成

```python
# Agent配置映射
class AgentConfig:
    def to_agentflow_spec(self) -> AgentSpec:
        """将数据库Agent配置转换为agentflow AgentSpec"""
        return AgentSpec(
            name=self.name,
            system_prompt=self.system_prompt,
            llm_config=self.llm_config,
            plugins=self.plugins,
            builtin_tools=self.tools,
        )
```

### 7.2 上下文组装

```python
class ContextBuilder:
    def build(self, agent: Agent, chain: Chain, task: Task) -> List[Dict]:
        """
        组装Agent执行上下文
        
        上下文层级：
        1. Agent自我设定
        2. 项目全局资源（必读）
        3. 群聊共享资源
        4. Agent个人笔记
        5. 当前链历史
        6. 任务约束
        """
        context = []
        context.append(self._build_agent_self(agent))
        context.append(self._build_project_resources(agent.project_id))
        context.append(self._build_group_resources(chain.group_id))
        context.append(self._build_agent_memory(agent.id, agent.project_id))
        context.append(self._build_chain_history(chain.id))
        context.append(self._build_task_constraint(task))
        return context
```

---

## 8. 开发环境

### 8.1 前端

```bash
# 安装依赖
cd client && bun install

# 开发服务器
bun run dev

# 构建
bun run build
```

### 8.2 后端

```bash
# 安装依赖
cd server && pip install -r requirements.txt

# 数据库迁移
alembic upgrade head

# 启动服务器
uvicorn app.main:app --reload
```

### 8.3 Docker（可选）

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: agentflow
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  server:
    build: ./server
    ports:
      - "8000:8000"
    depends_on:
      - postgres
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/agentflow

  client:
    build: ./client
    ports:
      - "3000:3000"
    depends_on:
      - server

volumes:
  postgres_data:
```
