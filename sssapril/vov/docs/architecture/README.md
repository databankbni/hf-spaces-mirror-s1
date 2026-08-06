# AgentFlow 架构设计文档

## 文档目录

```
docs/
├── v2-design.md                        # ★ 架构设计（权威文档）
├── requirements.md                     # 需求文档（v2 状态见文档头部）
├── DEVELOPMENT_PLAN.md                 # 当前执行计划（根目录）
│
├── architecture/                       # 技术细节
│   ├── README.md                       # 本文件
│   ├── 01-tech-stack.md               # 技术选型
│   ├── 02-database-design.md          # 数据库设计
│   ├── 04-api-design.md              # API设计
│   └── 05-pipeline-orchestration.md   # 流水线编排设计记录
│
├── templates/                          # 模板文档
│   └── novel-writing-template.md
│
└── assets/                             # 截图等资源
    └── screenshots/
```

---

## 快速概览

### 项目定位

AgentFlow是一个**多Agent群聊协作创作平台**，用户作为"导演"，通过创建项目、组织群聊、配置Agent，让多个AI Agent协作完成复杂创作任务。当前正在进行 v2 架构升级，详见 `docs/v2-design.md`。

### 核心架构

```
Frontend (React + TypeScript + Vite)
         │
         │ HTTP REST + WebSocket (SSE)
         ▼
Backend (Python + FastAPI)
         │
    ┌────┼──────────┐
    ▼    ▼          ▼
  PostgreSQL 15  agentflow SDK  LLM API (OpenAI 兼容)
```

### 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 18 + TypeScript + Vite + Tailwind + shadcn/ui |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy + Alembic |
| 数据库 | PostgreSQL 15 |
| Agent | agentflow SDK |
| 实时通信 | WebSocket + SSE |

---

## 设计原则

1. **代码层与流程层正交**：代码给通用原子能力，流程由 skill 命令式固定
2. **系统不硬编码**：不用 enum 锁死行为、不特化 agent 类型、不偷偷推进流程
3. **Agent 友好**：内容格式对 Agent 读写友好（Markdown + 元数据）
4. **用户控制**：用户有控制权，随时可介入
5. **分层架构**：API层 → Service层 → Repository层

---

## 核心概念

| 概念 | 说明 |
|------|------|
| Project | 项目，最顶层组织单元 |
| Group | 群聊，项目内的协作阶段 |
| Task | 任务，群聊内的具体工作 |
| Chain | 链，消息的 Packet 序列（树形结构） |
| Packet | 信息包，消息的最小存储单元 |
| Agent | 智能体，AI 角色 |
| Deliverable | 交付物，任务的产出 |
| Resource | 资料，树形文件夹结构 |
| Memory | 笔记，Agent 的个人积累 |

---

## 文档阅读顺序

1. **v2-design.md** → 了解 v2 架构设计哲学和核心原则
2. **requirements.md** → 了解完整功能需求
3. **DEVELOPMENT_PLAN.md** → 了解当前开发进度和计划
4. **01-tech-stack.md** → 了解技术选型和项目结构
5. **02-database-design.md** → 了解数据模型
6. **04-api-design.md** → 了解 API 规范
7. **05-pipeline-orchestration.md** → 了解流水线编排设计
