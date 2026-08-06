# graph（图谱）视图

通用 DAG（有向无环图）渲染。**不只用于项目流水线**，任何"节点 + 边"的关系都能用：
- 项目流水线（group 节点 + 完成关系边）
- 任务依赖（task 节点 + 阻塞关系边）
- 知识图谱（概念节点 + 引用关系边）
- Agent 协作图（agent 节点 + 通信关系边）
- 决策树（条件节点 + 判定关系边）

## 数据结构

```json
{
  "view_type": "graph",
  "title": "项目流水线",
  "description": "小说创作 8 阶段流程",
  "data": {
    "version": 1,
    "nodes": [
      {"id": "G1", "label": "灵感孵化", "type": "group", "data": {"description": "..."}},
      {"id": "G2", "label": "世界观",    "type": "group", "data": {"description": "..."}},
      {"id": "G3", "label": "人物档案",  "type": "group", "data": {"description": "..."}}
    ],
    "edges": [
      {"source": "G1", "target": "G2", "label": "完成后", "style": "solid"},
      {"source": "G2", "target": "G3", "label": "完成后", "style": "solid", "condition": "G2.completed"}
    ]
  },
  "options": {
    "layout": "td",
    "directed": true,
    "node_render": {
      "group":   {"icon": "💬", "color": "blue",   "shape": "rect"},
      "agent":   {"icon": "🤖", "color": "purple", "shape": "circle"},
      "task":    {"icon": "✅", "color": "green",  "shape": "rect"},
      "default": {"shape": "rect"}
    },
    "edge_render": {
      "default":  {"style": "solid", "arrow": true, "color": "gray"},
      "feedback": {"style": "dashed", "color": "orange"},
      "parallel": {"style": "dotted", "color": "green"}
    }
  }
}
```

## 字段说明

### data.nodes[]

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✓ | 节点唯一标识，edge.source / edge.target 引用此 id |
| `label` | ✓ | 节点显示文字 |
| `type` |  | 节点类型（如 `group` / `agent` / `task`），用于查 `options.node_render[type]` 表 |
| `data` |  | 节点的任意附加数据（agent 可读回，无渲染影响） |

### data.edges[]

| 字段 | 必填 | 说明 |
|------|------|------|
| `source` | ✓ | 起点 node id |
| `target` | ✓ | 终点 node id |
| `label` |  | 边上的文字 |
| `style` |  | 边的视觉样式 key（查 `options.edge_render[style]`），也用于 agent 自解释 |
| `condition` |  | agent 解释用：什么条件下此边触发（如 `"G1.completed"`） |

### options

| 字段 | 说明 |
|------|------|
| `layout` | `lr`（左→右）/ `tb` / `td`（上→下）/ `radial`（径向）。默认 `td` |
| `directed` | 是否显示箭头。默认 `true` |
| `node_render` | 按 `node.type` 查表，每项含 `icon` / `color` / `shape` / `size` / `badge_field` |
| `edge_render.default` | 默认边样式（含 `style` / `color` / `width` / `arrow`） |
| `edge_render[<style>]` | 按 `edge.style` 字段查表，覆盖默认 |

## 核心特性：渲染 + 阅读一套

**同一份 data 既用于渲染，也用于 agent 读回**。

**写入**（agent 编排后保存）:
```python
write_resource(
    title="项目流水线",
    content=json.dumps(graph_data, ensure_ascii=False, indent=2),
    content_type="json",
    resource_type="map",
    tags=["pipeline", "orchestration"]
)
```

**读回 + 渲染**（agent 重新进入项目时）:
```python
# 1. 读
res = read_resource(resource_id=pipeline_resource_id)
data = json.loads(res["content"])

# 2. 渲染（同一份 data）
render_view(
    view_type="graph",
    title=data.get("title", "项目流水线"),
    data=data
)
```

agent 可以直接从 `data.nodes` / `data.edges` 拿到完整流程结构，决定下一步推进哪个 group。

## 最小示例：3 节点直线

```json
{
  "view_type": "graph",
  "title": "最小示例",
  "data": {
    "nodes": [
      {"id": "A", "label": "开始", "type": "group"},
      {"id": "B", "label": "执行", "type": "group"},
      {"id": "C", "label": "结束", "type": "group"}
    ],
    "edges": [
      {"source": "A", "target": "B"},
      {"source": "B", "target": "C"}
    ]
  }
}
```

## 反例：不要这么用

- ❌ 把 graph 当 map 用（空间布局）—— 用 `view_type=map`
- ❌ 把 graph 当 tree 用（严格父子层级）—— 用 `view_type=tree`
- ❌ 把 nodes/edges 塞到 table 里（明明就是关系图）—— graph 更直观
- ❌ 把"流程"硬编码进 system_prompt（G1→G2→G3）—— 改用 graph data，渲染+阅读+推进统一来源
