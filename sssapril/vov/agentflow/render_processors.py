"""
Render View Processor

Agent 通过此工具生成渲染配置 (RenderSpec)，
前端 RenderEngine 解析配置并动态渲染数据可视化视图。

Agent 决定"展示什么"和"怎么展示"，前端只负责执行渲染。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .builtin_processors import BuiltinProcessor, _function_schema, _extract_builtin_content
from .packet import InfoPacket, PacketType


# 支持的视图类型
# - table/list/tree/document/card/stat/timeline/map: 已稳定
# - graph (v2 P2): 通用 DAG, 既可作项目流水线, 也可作任意依赖/协作/知识图谱
VIEW_TYPES = ["table", "list", "tree", "document", "card", "stat", "timeline", "map", "graph"]

# render_view 工具的参数 Schema
_RENDER_VIEW_SCHEMA = _function_schema(
    "render_view",
    (
        "Render structured data visualization. "
        "Use this to present data as tables, trees, lists, documents, cards, stats, timelines, etc. "
        "You decide WHAT to show and HOW to show it. "
        "The rendered view will be displayed to the user in the chat or a dedicated data view area."
    ),
    {
        "view_type": {
            "type": "string",
            "enum": VIEW_TYPES,
            "description": "Type of visualization to render.",
        },
        "title": {
            "type": "string",
            "description": "Title for the rendered view.",
        },
        "description": {
            "type": "string",
            "description": "Brief description shown below the title.",
        },
        "data": {
            "type": "object",
            "description": (
                "Inline data to render. Use this when you already have the data available. "
                "For example: {\"metrics\": [{\"label\": \"Tasks\", \"value\": 12}]}"
            ),
        },
        "data_source": {
            "type": "object",
            "description": (
                "API data source config. Use this to lazy-load data from backend APIs. "
                "The frontend will call the specified API to fetch data on demand."
            ),
            "properties": {
                "api": {
                    "type": "string",
                    "description": "API endpoint path, e.g. '/groups/{group_id}/tasks'",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST"],
                    "description": "HTTP method, default GET.",
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters.",
                },
                "data_path": {
                    "type": "string",
                    "description": "Path to extract data from response, e.g. 'data.items'",
                },
                "transform": {
                    "type": "object",
                    "description": "Data transform rules: pick, rename, sort, filter, map.",
                },
            },
        },
        "options": {
            "type": "object",
            "description": (
                "View-specific options. "
                "For table: {columns: [{field, label, render: {type, badge_map}}], sortable, pagination}. "
                "For tree: {label_field, children_field, default_expand_depth, icon_map}. "
                "For document: {content_field, show_toc, compact}. "
                "For stat: {metrics: [{label, value_field, prefix, suffix, icon, color}]}. "
                "For list: {layout, item_template, card_fields}. "
                "For card: {card_fields, grid_cols}. "
                "For timeline: {time_field, event_field}. "
                "For map: {map: {grid: {cols, rows, cell_shape, cell_size}, territories: [{id, name, cells, style, info, sub_map}], connections, background, legend}}. "
                "Map cell_shape: 'square' or 'hex'. Territory cells: [[col, row], ...]. "
                "Territory info: {title, subtitle, description, avatar_url, icon, stats, badges}. "
                "Territory sub_map: nested MapConfig for drill-down. "
                "Connections: [{source, target, label, style, color, directed}]."
                "For graph (v2 P2, 通用 DAG): {layout: 'lr'|'tb'|'td'|'radial', directed: bool, "
                "node_render: {<node_type>: {icon, color, shape: 'rect'|'circle'|'diamond'|'hex', size, badge_field}}, "
                "edge_render: {default: {style: 'solid'|'dashed'|'dotted', color, width, arrow: bool}, "
                "<edge_style>: {...} (按 edges[].style 字段查表)}. "
                "Graph data 字段: data.nodes=[{id, label, type, data}]  data.edges=[{source, target, label, style, condition}]. "
                "Node id 唯一, edge source/target 引用 node id. 同一份 data 既是渲染源, 也是 agent 可读回的流程描述.}"
            ),
        },
        "style": {
            "type": "object",
            "description": "Style options: {bordered, compact, height, class_name}.",
        },
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["navigate", "open_detail", "trigger_tool"],
                    },
                    "label": {"type": "string"},
                    "route_template": {"type": "string"},
                },
            },
            "description": "Interactive actions for the rendered view.",
        },
        "render_target": {
            "type": "string",
            "description": (
                "CSS selector for the DOM element to render into (e.g. '#my-panel', '.data-area'). "
                "Defaults to rendering in the chat bubble if not specified or element not found."
            ),
        },
        "expandable": {
            "type": "boolean",
            "description": "If true, show a button to expand the view into a full-screen page.",
        },
    },
    required=["view_type"],
)


class RenderViewProcessor(BuiltinProcessor):
    """生成渲染配置的工具处理器

    Agent 调用此工具后，render_spec 会被存入 Message.metadata，
    前端从 metadata.render_spec 提取配置并使用 RenderEngine 渲染。
    """

    kind = "render_view"

    def __init__(self, name: str = "render_view"):
        super().__init__(
            name=name,
            description="Render structured data visualization for the user.",
        )

    def get_schema(self) -> Dict[str, Any]:
        return _RENDER_VIEW_SCHEMA

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        args = _extract_builtin_content(packet)
        view_type = args.get("view_type", "")

        if view_type not in VIEW_TYPES:
            return packet.create_child(
                content=f"Error: Unsupported view_type '{view_type}'. Supported: {', '.join(VIEW_TYPES)}",
                packet_type=PacketType.ERROR,
                inherit_metadata=False,
            )

        # 构建 RenderSpec
        render_spec = {
            "version": 1,
            "view_type": view_type,
            "title": args.get("title"),
            "description": args.get("description"),
            "data": args.get("data"),
            "data_source": args.get("data_source"),
            "options": args.get("options"),
            "style": args.get("style"),
            "actions": args.get("actions"),
            "render_target": args.get("render_target"),
            "expandable": args.get("expandable"),
        }

        # 清理 None 值
        render_spec = {k: v for k, v in render_spec.items() if v is not None}

        # 返回确认消息给 Agent，render_spec 通过 metadata 传递
        title = args.get("title", view_type)
        child = packet.create_child(
            content=f"Render view created: {view_type}" + (f" - {title}" if title != view_type else ""),
            packet_type=PacketType.RESPONSE,
        )
        # 将 render_spec 写入 RESPONSE 包的 metadata
        child.add_metadata("render_spec", render_spec)
        return child
