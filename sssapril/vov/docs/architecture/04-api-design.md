# API设计文档

## 1. 通用约定

### 1.1 基础URL

```
http://localhost:8000/api/v1
```

### 1.2 请求格式

- Content-Type: application/json
- 字符编码: UTF-8
- 时间格式: ISO 8601 (UTC)

### 1.3 响应格式

**成功响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

**列表响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [ ... ],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

**错误响应**：
```json
{
  "code": 400,
  "message": "Validation error",
  "details": [
    { "field": "name", "message": "Name is required" }
  ]
}
```

### 1.4 HTTP状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 204 | 删除成功（无返回体） |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 2. 项目API

### 2.1 获取项目列表

```
GET /api/v1/projects
```

**Query参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 筛选状态 |
| page | int | 否 | 页码，默认1 |
| page_size | int | 否 | 每页数量，默认20 |

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "玄幻小说《星河破晓》",
        "description": "...",
        "cover_color": "from-violet-500 to-purple-600",
        "tags": ["小说", "玄幻"],
        "status": "active",
        "group_count": 4,
        "agent_count": 5,
        "created_at": "2024-01-10T00:00:00Z",
        "updated_at": "2024-01-15T00:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

### 2.2 创建项目

```
POST /api/v1/projects
```

**请求体**：
```json
{
  "name": "新项目",
  "description": "项目描述",
  "cover_color": "from-blue-500 to-cyan-600",
  "tags": ["标签1", "标签2"]
}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "name": "新项目",
    "status": "active",
    "created_at": "2024-01-10T00:00:00Z"
  }
}
```

### 2.3 获取项目详情

```
GET /api/v1/projects/{id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "name": "玄幻小说《星河破晓》",
    "description": "...",
    "cover_color": "from-violet-500 to-purple-600",
    "tags": ["小说", "玄幻"],
    "status": "active",
    "workflow_config": {
      "auto_advance": false
    },
    "groups": [ ... ],
    "agents": [ ... ],
    "resources": [ ... ],
    "created_at": "2024-01-10T00:00:00Z",
    "updated_at": "2024-01-15T00:00:00Z"
  }
}
```

### 2.4 更新项目

```
PUT /api/v1/projects/{id}
```

**请求体**：
```json
{
  "name": "更新后的名称",
  "description": "更新后的描述",
  "status": "paused"
}
```

### 2.5 删除项目

```
DELETE /api/v1/projects/{id}
```

**响应**：
```json
{
  "code": 0,
  "message": "Project deleted"
}
```

---

## 3. 群聊API

### 3.1 获取项目的群聊列表

```
GET /api/v1/projects/{project_id}/groups
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "大纲规划组",
        "description": "...",
        "status": "active",
        "order_index": 1,
        "autonomy_level": "semi_auto",
        "lead_agent": {
          "id": "uuid",
          "name": "策略师",
          "role": "planner"
        },
        "member_count": 3,
        "task_count": 2,
        "done_task_count": 2,
        "message_count": 10,
        "deliverable_count": 2,
        "auto_advance": false,
        "created_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 3.2 创建群聊

```
POST /api/v1/projects/{project_id}/groups
```

**请求体**：
```json
{
  "name": "新群聊",
  "description": "群聊描述",
  "autonomy_level": "semi_auto",
  "lead_agent_id": "uuid",
  "member_agent_ids": ["uuid1", "uuid2", "uuid3"],
  "auto_advance": false
}
```

### 3.3 获取群聊详情

```
GET /api/v1/groups/{id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "name": "大纲规划组",
    "description": "...",
    "status": "active",
    "order_index": 1,
    "autonomy_level": "semi_auto",
    "auto_advance": false,
    "lead_agent": { ... },
    "members": [ ... ],
    "tasks": [ ... ],
    "resources": [ ... ],
    "deliverables": [ ... ],
    "created_at": "2024-01-10T00:00:00Z",
    "updated_at": "2024-01-15T00:00:00Z"
  }
}
```

### 3.4 更新群聊

```
PUT /api/v1/groups/{id}
```

**请求体**：
```json
{
  "name": "更新后的名称",
  "autonomy_level": "full_auto",
  "auto_advance": true
}
```

### 3.5 删除群聊

```
DELETE /api/v1/groups/{id}
```

### 3.6 群聊排序

```
PUT /api/v1/projects/{project_id}/groups/reorder
```

**请求体**：
```json
{
  "ordered_ids": ["uuid1", "uuid2", "uuid3"]
}
```

---

## 4. 群聊成员API

### 4.1 获取群聊成员

```
GET /api/v1/groups/{group_id}/members
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "project_agent_id": "uuid",
        "agent": {
          "id": "uuid",
          "name": "策略师",
          "role": "planner",
          "avatar": "🧭",
          "description": "..."
        },
        "role": "lead",
        "joined_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 4.2 添加群聊成员

```
POST /api/v1/groups/{group_id}/members
```

**请求体**：
```json
{
  "project_agent_id": "uuid",
  "role": "participant"
}
```

### 4.3 移除群聊成员

```
DELETE /api/v1/groups/{group_id}/members/{agent_id}
```

---

## 5. 任务API

### 5.1 获取群聊任务列表

```
GET /api/v1/groups/{group_id}/tasks
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "title": "制定三幕式故事结构",
        "description": "...",
        "status": "done",
        "order_index": 1,
        "acceptance_criteria": "...",
        "lead_agent": { ... },
        "assignees": [ ... ],
        "chain_id": "uuid",
        "deliverable": { ... },
        "created_at": "2024-01-10T00:00:00Z",
        "started_at": "2024-01-11T00:00:00Z",
        "completed_at": "2024-01-12T00:00:00Z"
      }
    ]
  }
}
```

### 5.2 创建任务

```
POST /api/v1/groups/{group_id}/tasks
```

**请求体**：
```json
{
  "title": "新任务",
  "description": "任务描述",
  "acceptance_criteria": "验收标准",
  "lead_agent_id": "uuid",
  "assignee_ids": ["uuid1", "uuid2"]
}
```

### 5.3 获取任务详情

```
GET /api/v1/tasks/{id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "title": "制定三幕式故事结构",
    "description": "...",
    "status": "done",
    "order_index": 1,
    "acceptance_criteria": "...",
    "lead_agent": { ... },
    "assignees": [ ... ],
    "chain": {
      "id": "uuid",
      "status": "completed",
      "messages": [ ... ]
    },
    "deliverable": { ... },
    "created_at": "2024-01-10T00:00:00Z",
    "started_at": "2024-01-11T00:00:00Z",
    "completed_at": "2024-01-12T00:00:00Z"
  }
}
```

### 5.4 更新任务

```
PUT /api/v1/tasks/{id}
```

**请求体**：
```json
{
  "title": "更新后的标题",
  "description": "更新后的描述",
  "acceptance_criteria": "更新后的验收标准"
}
```

### 5.5 更新任务状态

```
PUT /api/v1/tasks/{id}/status
```

**请求体**：
```json
{
  "status": "in_progress"
}
```

**状态流转规则**：
- todo → in_progress（开始任务）
- in_progress → done（完成任务）
- done → reopened（重新打开）
- reopened → in_progress（重新开始）

### 5.6 删除任务

```
DELETE /api/v1/tasks/{id}
```

---

## 6. Agent API

### 6.1 获取全局Agent列表

```
GET /api/v1/agents
```

**Query参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| role | string | 否 | 按角色筛选 |
| search | string | 否 | 搜索名称/描述 |

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "梦笔生花",
        "role": "writer",
        "avatar": "✍️",
        "description": "专业创意写作Agent...",
        "capabilities": ["故事构建", "人物塑造"],
        "model_config": {
          "model": "gpt-4o",
          "temperature": 0.7
        },
        "tools": [ ... ],
        "skills": [ ... ],
        "is_active": true,
        "created_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 6.2 创建全局Agent

```
POST /api/v1/agents
```

**请求体**：
```json
{
  "name": "新Agent",
  "role": "writer",
  "avatar": "🤖",
  "description": "Agent描述",
  "system_prompt": "你是一个...",
  "model_config": {
    "model": "gpt-4o",
    "temperature": 0.7
  },
  "capabilities": ["能力1", "能力2"],
  "tools": [
    {
      "name": "search",
      "description": "搜索工具",
      "tool_type": "function",
      "config": { ... }
    }
  ],
  "skills": [
    {
      "name": "writing",
      "description": "写作技能",
      "skill_type": "prompt",
      "content": "..."
    }
  ]
}
```

### 6.3 获取Agent详情

```
GET /api/v1/agents/{id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "name": "梦笔生花",
    "role": "writer",
    "avatar": "✍️",
    "description": "...",
    "system_prompt": "...",
    "capabilities": [...],
    "model_config": {...},
    "tools": [...],
    "skills": [...],
    "is_active": true,
    "projects": [
      {
        "project_id": "uuid",
        "project_name": "星河破晓",
        "memory": { ... }
      }
    ],
    "created_at": "2024-01-10T00:00:00Z",
    "updated_at": "2024-01-15T00:00:00Z"
  }
}
```

### 6.4 更新Agent

```
PUT /api/v1/agents/{id}
```

### 6.5 删除Agent

```
DELETE /api/v1/agents/{id}
```

---

## 7. 项目Agent API

### 7.1 获取项目Agent列表

```
GET /api/v1/projects/{project_id}/agents
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "agent": { ... },
        "override_config": {},
        "memory": {
          "content": "...",
          "updated_at": "2024-01-15T00:00:00Z"
        },
        "created_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 7.2 添加Agent到项目

```
POST /api/v1/projects/{project_id}/agents
```

**请求体**：
```json
{
  "agent_id": "uuid",
  "override_config": {}
}
```

### 7.3 从项目移除Agent

```
DELETE /api/v1/projects/{project_id}/agents/{agent_id}
```

---

## 8. 交付物API

### 8.1 获取群聊交付物列表

```
GET /api/v1/groups/{group_id}/deliverables
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "title": "《星河破晓》故事大纲",
        "type": "outline",
        "tags": ["大纲", "三幕结构"],
        "scope": "project",
        "version": 2,
        "author": { ... },
        "chain_id": "uuid",
        "task_id": "uuid",
        "created_at": "2024-01-12T00:00:00Z",
        "updated_at": "2024-01-13T00:00:00Z"
      }
    ]
  }
}
```

### 8.2 获取项目交付物列表

```
GET /api/v1/projects/{project_id}/deliverables
```

### 8.3 创建交付物

```
POST /api/v1/deliverables
```

**请求体**：
```json
{
  "title": "新交付物",
  "content": "# 标题\n\n内容...",
  "type": "outline",
  "tags": ["标签1"],
  "scope": "group",
  "chain_id": "uuid",
  "group_id": "uuid",
  "task_id": "uuid",
  "author_id": "agent-uuid",
  "participant_ids": ["uuid1", "uuid2"]
}
```

### 8.4 获取交付物详情

```
GET /api/v1/deliverables/{id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "title": "《星河破晓》故事大纲",
    "content": "# 标题\n\n内容...",
    "content_type": "markdown",
    "type": "outline",
    "tags": ["大纲", "三幕结构"],
    "scope": "project",
    "version": 2,
    "author": { ... },
    "participants": [ ... ],
    "chain_id": "uuid",
    "task_id": "uuid",
    "group_id": "uuid",
    "versions": [
      {
        "version": 1,
        "change_summary": "初始版本",
        "created_at": "2024-01-12T00:00:00Z"
      },
      {
        "version": 2,
        "change_summary": "增加至暗时刻",
        "created_at": "2024-01-13T00:00:00Z"
      }
    ],
    "created_at": "2024-01-12T00:00:00Z",
    "updated_at": "2024-01-13T00:00:00Z"
  }
}
```

### 8.5 更新交付物

```
PUT /api/v1/deliverables/{id}
```

**请求体**：
```json
{
  "title": "更新后的标题",
  "content": "更新后的内容...",
  "change_summary": "变更说明"
}
```

### 8.6 获取交付物版本

```
GET /api/v1/deliverables/{id}/versions
```

### 8.7 获取特定版本内容

```
GET /api/v1/deliverables/{id}/versions/{version}
```

### 8.8 版本对比

```
GET /api/v1/deliverables/{id}/diff?v1=1&v2=2
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "v1": { "version": 1, "content": "..." },
    "v2": { "version": 2, "content": "..." },
    "diff": [
      { "type": "equal", "content": "..." },
      { "type": "delete", "content": "..." },
      { "type": "insert", "content": "..." }
    ]
  }
}
```

---

## 9. 资料API

### 9.1 获取项目全局资料

```
GET /api/v1/projects/{project_id}/resources
```

**Query参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 否 | 按类型筛选 |
| required | bool | 否 | 是否必读 |

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "title": "世界观核心设定",
        "content": "...",
        "content_type": "markdown",
        "type": "reference",
        "tags": ["世界观"],
        "is_required": true,
        "created_by": "user",
        "created_at": "2024-01-10T00:00:00Z",
        "updated_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 9.2 获取群聊资料

```
GET /api/v1/groups/{group_id}/resources
```

### 9.3 创建资料

```
POST /api/v1/resources
```

**请求体**：
```json
{
  "title": "新资料",
  "content": "# 资料内容...",
  "type": "note",
  "tags": ["标签1"],
  "is_required": false,
  "project_id": "uuid",
  "group_id": "uuid",  // 可选，不传表示全局资源
  "created_by": "user"
}
```

### 9.4 更新资料

```
PUT /api/v1/resources/{id}
```

### 9.5 删除资料

```
DELETE /api/v1/resources/{id}
```

---

## 10. Agent笔记API

### 10.1 获取Agent在项目中的笔记

```
GET /api/v1/agents/{agent_id}/memories/{project_id}
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "agent_id": "uuid",
    "project_id": "uuid",
    "content": "# 笔记内容...",
    "content_type": "markdown",
    "tags": ["世界观", "人物"],
    "created_at": "2024-01-10T00:00:00Z",
    "updated_at": "2024-01-15T00:00:00Z"
  }
}
```

### 10.2 获取项目所有Agent笔记

```
GET /api/v1/projects/{project_id}/memories
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "agent": { ... },
        "content": "...",
        "tags": [...],
        "updated_at": "2024-01-15T00:00:00Z"
      }
    ]
  }
}
```

### 10.3 更新Agent笔记

```
PUT /api/v1/agents/{agent_id}/memories/{project_id}
```

**请求体**：
```json
{
  "content": "更新后的笔记内容...",
  "tags": ["新标签"]
}
```

---

## 11. 标签API

### 11.1 获取项目标签列表

```
GET /api/v1/projects/{project_id}/tags
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "outline",
        "description": "故事大纲",
        "suggested_template": "# 大纲\n\n## 第一幕\n...",
        "color": "#3b82f6",
        "created_at": "2024-01-10T00:00:00Z"
      }
    ]
  }
}
```

### 11.2 创建标签

```
POST /api/v1/projects/{project_id}/tags
```

**请求体**：
```json
{
  "name": "新标签",
  "description": "标签说明",
  "suggested_template": "建议的模板...",
  "color": "#10b981"
}
```

### 11.3 更新标签

```
PUT /api/v1/tags/{id}
```

### 11.4 删除标签

```
DELETE /api/v1/tags/{id}
```

---

## 12. Chain与消息API

### 12.1 创建Chain（开始任务）

```
POST /api/v1/tasks/{task_id}/start
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "chain_id": "uuid",
    "status": "active"
  }
}
```

### 12.2 获取Chain消息

```
GET /api/v1/chains/{chain_id}/messages
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "uuid",
        "chain_id": "uuid",
        "sender_id": "agent-uuid",
        "sender_type": "agent",
        "sender_name": "策略师",
        "content": "我已经梳理了整体的故事框架...",
        "content_type": "text",
        "metadata": {},
        "created_at": "2024-01-11T09:30:00Z"
      }
    ]
  }
}
```

### 12.3 发送消息（用户）

```
POST /api/v1/chains/{chain_id}/messages
```

**请求体**：
```json
{
  "content": "用户的补充说明...",
  "sender_type": "user"
}
```

### 12.4 停止Agent

```
POST /api/v1/chains/{chain_id}/stop
```

**请求体**：
```json
{
  "mode": "wait_complete"  // wait_complete / wait_task / force
}
```

### 12.5 恢复讨论

```
POST /api/v1/chains/{chain_id}/resume
```

---

## 13. 导出导入API

### 13.1 导出项目

```
GET /api/v1/projects/{id}/export
```

**Query参数**：
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| include_agents | bool | 否 | 是否包含Agent配置 |
| include_deliverables | bool | 否 | 是否包含交付物 |
| include_resources | bool | 否 | 是否包含资料 |
| include_messages | bool | 否 | 是否包含聊天记录 |
| include_memories | bool | 否 | 是否包含笔记 |

**响应**：
```
Content-Type: application/zip
Content-Disposition: attachment; filename="project-export.zip"

[ZIP文件内容]
```

### 13.2 导入项目

```
POST /api/v1/projects/import
```

**请求**：
```
Content-Type: multipart/form-data

file: [ZIP文件]
mode: "create" | "merge"
```

---

## 14. WebSocket API

### 14.1 连接

```
ws://localhost:8000/ws/chat/{group_id}
```

### 14.2 客户端消息

**发送消息**：
```json
{
  "type": "send_message",
  "payload": {
    "content": "消息内容"
  }
}
```

**停止Agent**：
```json
{
  "type": "stop_agent",
  "payload": {
    "mode": "wait_complete"
  }
}
```

**恢复讨论**：
```json
{
  "type": "resume",
  "payload": {}
}
```

### 14.3 服务器消息

**Agent消息**：
```json
{
  "type": "agent_message",
  "payload": {
    "id": "uuid",
    "sender_id": "agent-uuid",
    "sender_name": "策略师",
    "sender_type": "agent",
    "content": "消息内容...",
    "is_streaming": false,
    "created_at": "2024-01-11T09:30:00Z"
  }
}
```

**Agent正在输入**：
```json
{
  "type": "agent_typing",
  "payload": {
    "agent_id": "uuid",
    "agent_name": "策略师"
  }
}
```

**系统消息**：
```json
{
  "type": "system_message",
  "payload": {
    "content": "Agent「梦笔生花」加入了群聊",
    "created_at": "2024-01-11T09:30:00Z"
  }
}
```

**任务状态更新**：
```json
{
  "type": "task_update",
  "payload": {
    "task_id": "uuid",
    "status": "done",
    "deliverable_id": "uuid"
  }
}
```

**错误**：
```json
{
  "type": "error",
  "payload": {
    "code": "AGENT_ERROR",
    "message": "Agent调用失败"
  }
}
```

---

## 15. 全局Agent世界API

### 15.1 获取统计数据

```
GET /api/v1/stats
```

**响应**：
```json
{
  "code": 0,
  "data": {
    "projects": {
      "total": 10,
      "active": 5,
      "completed": 3,
      "paused": 2
    },
    "agents": {
      "total": 8,
      "most_used": [
        { "id": "uuid", "name": "梦笔生花", "usage_count": 15 }
      ]
    },
    "groups": {
      "total": 25,
      "completed": 15
    },
    "tasks": {
      "total": 50,
      "completed": 30
    },
    "chains": {
      "total": 30,
      "avg_messages": 12.5
    },
    "deliverables": {
      "total": 30,
      "by_type": {
        "outline": 10,
        "character": 8,
        "chapter": 12
      }
    }
  }
}
```
