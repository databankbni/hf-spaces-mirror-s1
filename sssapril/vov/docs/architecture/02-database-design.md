# 数据库设计文档

## 1. 设计原则

- **主键**：使用UUID，避免ID冲突和信息泄露
- **时间戳**：使用UTC时区，ISO 8601格式
- **软删除**：通过`deleted_at`字段实现软删除
- **审计字段**：`created_at`、`updated_at`自动维护
- **JSON字段**：使用PostgreSQL JSONB存储灵活数据
- **索引**：常用查询字段建立索引

---

## 2. ER图概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AgentFlow 数据库                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐            │
│  │   projects   │       │    agents    │       │  agent_tags  │            │
│  │              │       │  (global)    │       │              │            │
│  └──────┬───────┘       └──────┬───────┘       └──────────────┘            │
│         │                      │                                           │
│         │ 1:N                  │ 1:N                                       │
│         ▼                      ▼                                           │
│  ┌──────────────┐       ┌──────────────┐                                   │
│  │project_agents│◄──────│  agent_tools │                                   │
│  │  (project    │       │agent_skills  │                                   │
│  │   level)     │       └──────────────┘                                   │
│  └──────┬───────┘                                                          │
│         │                                                                  │
│         │ 1:N                                                              │
│         ▼                                                                  │
│  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐           │
│  │    groups    │──────▶│ group_members│       │    tasks     │           │
│  │              │       │              │       │              │           │
│  └──────┬───────┘       └──────────────┘       └──────┬───────┘           │
│         │                                              │                   │
│         │ 1:N                                          │ 1:1               │
│         ▼                                              ▼                   │
│  ┌──────────────┐                              ┌──────────────┐           │
│  │    chains    │◄─────────────────────────────│   messages   │           │
│  │              │           1:N                │              │           │
│  └──────┬───────┘                              └──────────────┘           │
│         │                                                                  │
│         │ 1:N                                                              │
│         ▼                                                                  │
│  ┌──────────────┐       ┌──────────────┐       ┌──────────────┐           │
│  │ deliverables │       │  resources   │       │   memories   │           │
│  │              │       │              │       │              │           │
│  └──────────────┘       └──────────────┘       └──────────────┘           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 表结构定义

### 3.1 projects（项目表）

```sql
CREATE TABLE projects (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 基本信息
    name VARCHAR(255) NOT NULL,
    description TEXT,
    cover_color VARCHAR(100),              -- 渐变色定义
    tags JSONB DEFAULT '[]',               -- 项目标签
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active/paused/completed/archived
    
    -- 工作流配置
    workflow_config JSONB DEFAULT '{}',    -- 工作流配置（自动推进等）
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,   -- 软删除
    
    -- 约束
    CONSTRAINT projects_status_check CHECK (status IN ('active', 'paused', 'completed', 'archived'))
);

-- 索引
CREATE INDEX idx_projects_status ON projects(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_created_at ON projects(created_at);
CREATE INDEX idx_projects_tags ON projects USING GIN(tags);
```

### 3.2 agents（全局Agent表）

```sql
CREATE TABLE agents (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 基本信息
    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,             -- writer/critic/researcher/planner/editor/custom
    avatar VARCHAR(255),                   -- 头像URL或emoji
    description TEXT,                      -- 描述（给其他Agent和用户看）
    
    -- 配置
    system_prompt TEXT NOT NULL,           -- 系统提示词
    model_config JSONB DEFAULT '{}',       -- 模型配置（model、temperature等）
    capabilities JSONB DEFAULT '[]',       -- 能力描述列表
    
    -- 状态
    is_active BOOLEAN NOT NULL DEFAULT true,
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT agents_role_check CHECK (role IN ('writer', 'critic', 'researcher', 'planner', 'editor', 'coder', 'designer', 'custom'))
);

-- 索引
CREATE INDEX idx_agents_role ON agents(role) WHERE deleted_at IS NULL;
CREATE INDEX idx_agents_name ON agents(name);
```

### 3.3 agent_tools（Agent工具绑定表）

```sql
CREATE TABLE agent_tools (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- 工具信息
    name VARCHAR(100) NOT NULL,            -- 工具名称
    description TEXT,                      -- 工具描述
    tool_type VARCHAR(50) NOT NULL,        -- 工具类型（builtin/function/api）
    config JSONB DEFAULT '{}',             -- 工具配置
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT agent_tools_unique UNIQUE (agent_id, name)
);

-- 索引
CREATE INDEX idx_agent_tools_agent_id ON agent_tools(agent_id);
```

### 3.4 agent_skills（Agent技能绑定表）

```sql
CREATE TABLE agent_skills (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- 技能信息
    name VARCHAR(100) NOT NULL,
    description TEXT,
    skill_type VARCHAR(50) NOT NULL,       -- prompt/template/function
    content TEXT,                          -- 技能内容（提示词模板等）
    config JSONB DEFAULT '{}',
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT agent_skills_unique UNIQUE (agent_id, name)
);

-- 索引
CREATE INDEX idx_agent_skills_agent_id ON agent_skills(agent_id);
```

### 3.5 project_agents（项目级Agent表）

```sql
CREATE TABLE project_agents (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    
    -- 项目内覆盖配置（可选）
    override_config JSONB DEFAULT '{}',    -- 覆盖全局Agent配置
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT project_agents_unique UNIQUE (project_id, agent_id)
);

-- 索引
CREATE INDEX idx_project_agents_project_id ON project_agents(project_id);
CREATE INDEX idx_project_agents_agent_id ON project_agents(agent_id);
```

### 3.6 groups（群聊表）

```sql
CREATE TABLE groups (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    lead_agent_id UUID REFERENCES project_agents(id),  -- 主导Agent
    
    -- 基本信息
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- 状态与配置
    status VARCHAR(20) NOT NULL DEFAULT 'pending',     -- pending/active/completed
    order_index INTEGER NOT NULL DEFAULT 0,            -- 排序
    autonomy_level VARCHAR(20) NOT NULL DEFAULT 'semi_auto',  -- full_auto/semi_auto/manual
    
    -- 工作流
    auto_advance BOOLEAN NOT NULL DEFAULT false,       -- 完成后是否自动推进
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT groups_status_check CHECK (status IN ('pending', 'active', 'completed')),
    CONSTRAINT groups_autonomy_check CHECK (autonomy_level IN ('full_auto', 'semi_auto', 'manual'))
);

-- 索引
CREATE INDEX idx_groups_project_id ON groups(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_groups_status ON groups(status);
CREATE INDEX idx_groups_order ON groups(project_id, order_index);
```

### 3.7 group_members（群聊成员表）

```sql
CREATE TABLE group_members (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    project_agent_id UUID NOT NULL REFERENCES project_agents(id) ON DELETE CASCADE,
    
    -- 成员信息
    role VARCHAR(20) NOT NULL DEFAULT 'participant',  -- lead/participant
    
    -- 审计字段
    joined_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT group_members_unique UNIQUE (group_id, project_agent_id)
);

-- 索引
CREATE INDEX idx_group_members_group_id ON group_members(group_id);
CREATE INDEX idx_group_members_agent_id ON group_members(project_agent_id);
```

### 3.8 tasks（任务表）

```sql
CREATE TABLE tasks (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    lead_agent_id UUID REFERENCES project_agents(id),  -- 任务主导Agent
    
    -- 基本信息
    title VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'todo',  -- todo/in_progress/done/reopened
    order_index INTEGER NOT NULL DEFAULT 0,
    
    -- 验收标准
    acceptance_criteria TEXT,
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT tasks_status_check CHECK (status IN ('todo', 'in_progress', 'done', 'reopened'))
);

-- 索引
CREATE INDEX idx_tasks_group_id ON tasks(group_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_order ON tasks(group_id, order_index);
```

### 3.9 task_assignees（任务指派表）

```sql
CREATE TABLE task_assignees (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    project_agent_id UUID NOT NULL REFERENCES project_agents(id) ON DELETE CASCADE,
    
    -- 审计字段
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT task_assignees_unique UNIQUE (task_id, project_agent_id)
);

-- 索引
CREATE INDEX idx_task_assignees_task_id ON task_assignees(task_id);
CREATE INDEX idx_task_assignees_agent_id ON task_assignees(project_agent_id);
```

### 3.10 chains（讨论链表）

```sql
CREATE TABLE chains (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id),
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active/completed
    
    -- 上下文快照
    context_snapshot JSONB DEFAULT '{}',
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT chains_status_check CHECK (status IN ('active', 'completed'))
);

-- 索引
CREATE INDEX idx_chains_task_id ON chains(task_id);
CREATE INDEX idx_chains_group_id ON chains(group_id);
CREATE INDEX idx_chains_status ON chains(status);
```

### 3.11 messages（消息表）

```sql
CREATE TABLE messages (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    chain_id UUID NOT NULL REFERENCES chains(id) ON DELETE CASCADE,
    
    -- 发送者信息
    sender_id VARCHAR(255) NOT NULL,       -- agent_id 或 'user' 或 'system'
    sender_type VARCHAR(20) NOT NULL,      -- agent/user/system
    sender_name VARCHAR(100),              -- 显示名称
    
    -- 内容
    content TEXT NOT NULL,
    content_type VARCHAR(20) NOT NULL DEFAULT 'text',  -- text/markdown/json
    
    -- 元数据
    metadata JSONB DEFAULT '{}',
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT messages_sender_type_check CHECK (sender_type IN ('agent', 'user', 'system'))
);

-- 索引
CREATE INDEX idx_messages_chain_id ON messages(chain_id);
CREATE INDEX idx_messages_sender_id ON messages(sender_id);
CREATE INDEX idx_messages_created_at ON messages(chain_id, created_at);
```

### 3.12 deliverables（交付物表）

```sql
CREATE TABLE deliverables (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    chain_id UUID REFERENCES chains(id),
    group_id UUID NOT NULL REFERENCES groups(id),
    task_id UUID REFERENCES tasks(id),
    
    -- 基本信息
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,                 -- Markdown内容
    content_type VARCHAR(20) NOT NULL DEFAULT 'markdown',
    
    -- 类型与标签
    type VARCHAR(50),                      -- 交付物类型（标签）
    tags JSONB DEFAULT '[]',               -- 额外标签
    
    -- 元数据
    author_id VARCHAR(255),                -- 主导Agent ID
    participant_ids JSONB DEFAULT '[]',    -- 参与Agent ID列表
    metadata JSONB DEFAULT '{}',
    
    -- 版本
    version INTEGER NOT NULL DEFAULT 1,
    
    -- 作用域
    scope VARCHAR(20) NOT NULL DEFAULT 'group',  -- group/project
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT deliverables_scope_check CHECK (scope IN ('group', 'project'))
);

-- 索引
CREATE INDEX idx_deliverables_group_id ON deliverables(group_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_deliverables_task_id ON deliverables(task_id);
CREATE INDEX idx_deliverables_chain_id ON deliverables(chain_id);
CREATE INDEX idx_deliverables_type ON deliverables(type);
CREATE INDEX idx_deliverables_tags ON deliverables USING GIN(tags);
CREATE INDEX idx_deliverables_scope ON deliverables(scope);
```

### 3.13 deliverable_versions（交付物版本表）

```sql
CREATE TABLE deliverable_versions (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    deliverable_id UUID NOT NULL REFERENCES deliverables(id) ON DELETE CASCADE,
    
    -- 版本信息
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    change_summary TEXT,                   -- 变更说明
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    created_by VARCHAR(255),               -- 修改者
    
    -- 约束
    CONSTRAINT deliverable_versions_unique UNIQUE (deliverable_id, version)
);

-- 索引
CREATE INDEX idx_deliverable_versions_deliverable_id ON deliverable_versions(deliverable_id);
```

### 3.14 resources（资料表）

```sql
CREATE TABLE resources (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    group_id UUID REFERENCES groups(id),   -- NULL表示全局资源
    
    -- 基本信息
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(20) NOT NULL DEFAULT 'markdown',
    
    -- 类型
    type VARCHAR(50) NOT NULL DEFAULT 'note',  -- note/reference/guideline/rule
    tags JSONB DEFAULT '[]',
    
    -- 属性
    is_required BOOLEAN NOT NULL DEFAULT false,  -- 是否必读
    
    -- 创建者
    created_by VARCHAR(255) NOT NULL,      -- user 或 agent_id
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT resources_type_check CHECK (type IN ('note', 'reference', 'guideline', 'rule', 'custom'))
);

-- 索引
CREATE INDEX idx_resources_project_id ON resources(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_resources_group_id ON resources(group_id);
CREATE INDEX idx_resources_type ON resources(type);
CREATE INDEX idx_resources_is_required ON resources(is_required);
CREATE INDEX idx_resources_tags ON resources USING GIN(tags);
```

### 3.15 memories（Agent个人笔记表）

```sql
CREATE TABLE memories (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- 内容
    content TEXT NOT NULL,
    content_type VARCHAR(20) NOT NULL DEFAULT 'markdown',
    tags JSONB DEFAULT '[]',
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    
    -- 约束
    CONSTRAINT memories_unique UNIQUE (agent_id, project_id)
);

-- 索引
CREATE INDEX idx_memories_agent_id ON memories(agent_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_memories_project_id ON memories(project_id);
CREATE INDEX idx_memories_tags ON memories USING GIN(tags);
```

### 3.16 tags（项目标签定义表）

```sql
CREATE TABLE tags (
    -- 主键
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- 关联
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- 标签信息
    name VARCHAR(100) NOT NULL,
    description TEXT,
    suggested_template TEXT,               -- 建议的格式/模板
    color VARCHAR(50),                     -- 标签颜色
    
    -- 审计字段
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    -- 约束
    CONSTRAINT tags_unique UNIQUE (project_id, name)
);

-- 索引
CREATE INDEX idx_tags_project_id ON tags(project_id);
```

---

## 4. 数据库函数

### 4.1 自动更新updated_at

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 应用到各表
CREATE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_agents_updated_at BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_deliverables_updated_at BEFORE UPDATE ON deliverables
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_resources_updated_at BEFORE UPDATE ON resources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_memories_updated_at BEFORE UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

---

## 5. 示例查询

### 5.1 获取项目的群聊列表（按顺序）

```sql
SELECT g.*, 
       COUNT(DISTINCT t.id) as task_count,
       COUNT(DISTINCT CASE WHEN t.status = 'done' THEN t.id END) as done_count
FROM groups g
LEFT JOIN tasks t ON t.group_id = g.id AND t.deleted_at IS NULL
WHERE g.project_id = :project_id AND g.deleted_at IS NULL
GROUP BY g.id
ORDER BY g.order_index;
```

### 5.2 获取群聊的消息列表

```sql
SELECT m.*
FROM messages m
JOIN chains c ON c.id = m.chain_id
WHERE c.group_id = :group_id
ORDER BY m.created_at;
```

### 5.3 获取Agent在项目中的笔记

```sql
SELECT m.*
FROM memories m
WHERE m.agent_id = :agent_id 
  AND m.project_id = :project_id
  AND m.deleted_at IS NULL;
```

### 5.4 获取项目的必读资源

```sql
SELECT r.*
FROM resources r
WHERE r.project_id = :project_id 
  AND r.is_required = true
  AND r.deleted_at IS NULL
ORDER BY r.created_at;
```
