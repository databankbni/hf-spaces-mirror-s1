# map - 地图视图

适用于：空间布局、世界地图、场景关系图

## 基础示例

```json
{
  "view_type": "map",
  "title": "故事场景地图",
  "data": {},
  "options": {
    "map": {
      "grid": {"cols": 8, "rows": 6, "cell_shape": "square", "cell_size": 60},
      "territories": [
        {
          "id": "city", "name": "雾城",
          "cells": [[1,1],[2,1],[3,1],[1,2],[2,2],[3,2],[1,3],[2,3],[3,3]],
          "style": {"fill": "#3b82f6", "opacity": 0.3},
          "info": {"title": "雾城", "description": "故事主舞台", "stats": [{"label": "人口", "value": "200万"}]}
        },
        {
          "id": "harbor", "name": "旧港",
          "cells": [[5,1],[6,1],[5,2],[6,2]],
          "style": {"fill": "#f59e0b", "opacity": 0.3},
          "info": {"title": "旧港", "description": "案件发生地"}
        }
      ],
      "connections": [
        {"source": "city", "target": "harbor", "label": "5km", "style": "dashed", "directed": false}
      ],
      "legend": {"items": [{"label": "城区", "color": "#3b82f6"}, {"label": "港口", "color": "#f59e0b"}]}
    }
  }
}
```

## 核心概念

- **grid** — 网格定义，cols×rows 决定画布大小
- **territories** — 区域，每个区域占据若干 cells
- **connections** — 区域间的连线
- **legend** — 图例
- **sub_map** — 支持嵌套下钻（点击区域展开细节）

## cells 坐标

`[col, row]` 格式，从 0 开始。例如 `[1,2]` 表示第 2 列第 3 行。

## 经验

- 先规划好 grid 大小，再分配 territories
- cells 不要重叠，否则显示会冲突
- connections 的 source/target 是 territory 的 id
- `style: "dashed"` 虚线表示未连通，`"solid"` 实线表示已连通
- info.stats 可以展示该区域的关键数据
