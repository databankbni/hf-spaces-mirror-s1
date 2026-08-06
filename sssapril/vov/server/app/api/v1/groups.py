"""
群聊API路由模块

提供群聊相关的REST API端点。
"""

import json
from typing import List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.database import async_session_factory
from app.services.group_service import GroupService
from app.services.chat_service import ChatService
from app.schemas.group import (
    GroupCreate,
    GroupUpdate,
    GroupResponse,
    GroupListItem,
    GroupMemberCreate,
    GroupMemberResponse,
    ReorderGroupsRequest,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse


class ChatRequest(BaseModel):
    """聊天请求"""
    content: str = Field(..., min_length=1, description="消息内容")
    target_agent_id: Optional[str] = Field(None, description="指定响应的Agent ID")


class ChatMessageResponse(BaseModel):
    """聊天消息响应"""
    id: str
    chain_id: str
    sender_id: str
    sender_type: str
    sender_name: str
    content: str
    content_type: str
    metadata: dict = {}
    created_at: str | None = None


class ChatResponse(BaseModel):
    """聊天响应"""
    user_message: ChatMessageResponse
    agent_message: ChatMessageResponse

router = APIRouter(tags=["groups"])


# 项目群聊端点
@router.get("/projects/{project_id}/groups", response_model=ApiResponse[PaginatedResponse[GroupListItem]])
async def list_groups(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取项目的群聊列表

    返回项目中所有群聊。
    """
    service = GroupService(db)
    groups = await service.get_by_project(project_id)
    return ApiResponse(data=PaginatedResponse(items=groups, total=len(groups), skip=0, limit=100))


@router.post("/projects/{project_id}/groups", response_model=ApiResponse[GroupResponse], status_code=201)
async def create_group(
    project_id: str,
    data: GroupCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建群聊

    在项目中创建新群聊，可同时添加成员。
    """
    service = GroupService(db)
    group = await service.create_group(project_id, data.model_dump())
    return ApiResponse(data=group)


@router.post("/projects/{project_id}/groups/reorder", response_model=ApiResponse[StatusResponse])
async def reorder_groups(
    project_id: str,
    data: ReorderGroupsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    重新排序群聊

    更新项目中群聊的排序。
    """
    service = GroupService(db)
    await service.reorder(project_id, data.ordered_ids)
    return ApiResponse(data=StatusResponse(success=True, message="Groups reordered"))


# 群聊详情端点
@router.get("/groups/{group_id}", response_model=ApiResponse[GroupResponse])
async def get_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊详情

    返回群聊的详细信息。
    """
    service = GroupService(db)
    group = await service.get_detail(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return ApiResponse(data=group)


@router.put("/groups/{group_id}", response_model=ApiResponse[GroupResponse])
async def update_group(
    group_id: str,
    data: GroupUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新群聊

    更新群聊信息。
    """
    service = GroupService(db)
    group = await service.update_group(group_id, data.model_dump(exclude_unset=True))
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return ApiResponse(data=group)


@router.delete("/groups/{group_id}", response_model=ApiResponse[StatusResponse])
async def delete_group(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除群聊

    删除指定群聊（软删除）。
    """
    service = GroupService(db)
    success = await service.delete_group(group_id)
    if not success:
        raise HTTPException(status_code=404, detail="Group not found")
    return ApiResponse(data=StatusResponse(success=True, message="Group deleted"))


# 群聊成员端点
@router.get("/groups/{group_id}/members", response_model=ApiResponse[PaginatedResponse[GroupMemberResponse]])
async def list_members(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊成员列表

    返回群聊中所有成员。
    """
    service = GroupService(db)
    members = await service.get_members(group_id)
    return ApiResponse(data=PaginatedResponse(items=members, total=len(members), skip=0, limit=100))


@router.post("/groups/{group_id}/members", response_model=ApiResponse[GroupMemberResponse], status_code=201)
async def add_member(
    group_id: str,
    data: GroupMemberCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    添加群聊成员

    将Agent添加到群聊中。
    """
    service = GroupService(db)
    member = await service.add_member(group_id, data.project_agent_id, data.role)
    return ApiResponse(data=member)


@router.put("/groups/{group_id}/members/{agent_id}/role", response_model=ApiResponse[GroupMemberResponse])
async def update_member_role(
    group_id: str,
    agent_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    service = GroupService(db)
    try:
        member = await service.update_member_role(group_id, agent_id, data.get("role", "participant"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ApiResponse(data=member)


@router.delete("/groups/{group_id}/members/{agent_id}", response_model=ApiResponse[StatusResponse])
async def remove_member(
    group_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    移除群聊成员

    从群聊中移除指定Agent。
    """
    service = GroupService(db)
    success = await service.remove_member(group_id, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")
    return ApiResponse(data=StatusResponse(success=True, message="Member removed"))


@router.post("/groups/{group_id}/chat/stream")
async def chat_stream(
    group_id: str,
    data: ChatRequest,
):
    """
    发送消息并启动 Agent 响应 (v2: WebSocket 推送, 不再使用 SSE)。

    返回 JSON: {chain_id, packet_id, chain_type, parent_chain_id, agent_id, agent_name, user_message}
    后续 token/tool_call/tool_result/chain_end/done 事件通过 WebSocket 实时推送。
    """
    service = ChatService(async_session_factory)
    result = await service.send_message_stream(
        group_id, data.content, target_agent_id=data.target_agent_id
    )
    return ApiResponse(data=result)


class ChatStreamAttachRequest(BaseModel):
    """attach 到已有流式 session 的请求"""
    packet_id: Optional[str] = Field(None, description="指定要恢复的 packet ID")
    chain_id: Optional[str] = Field(None, description="指定 chain ID (fallback)")


@router.post("/groups/{group_id}/chat/stream/attach")
async def chat_stream_attach(
    group_id: str,
    data: ChatStreamAttachRequest,
):
    """
    查询正在进行的流的状态 (v2: 返回 snapshot dict, 不再使用 SSE)。

    返回 JSON: {active, chain_id, packet_id, content, metadata, chain_start}
    有活跃流时前端通过 WebSocket 接收后续事件; 无活跃流时前端走普通 chain view。
    """
    service = ChatService(async_session_factory)
    result = await service.resume_stream(
        group_id,
        packet_id=data.packet_id,
        chain_id=data.chain_id,
    )
    return ApiResponse(data=result)


class ChatStreamCancelRequest(BaseModel):
    """主动停止流式 session 的请求"""
    packet_id: Optional[str] = Field(None, description="指定 packet ID")
    chain_id: Optional[str] = Field(None, description="指定 chain ID (fallback)")


@router.post("/groups/{group_id}/chat/stream/cancel", response_model=ApiResponse[dict])
async def chat_stream_cancel(
    group_id: str,
    data: ChatStreamCancelRequest,
):
    """
    主动停止一个正在进行的流（用户点 Stop 按钮时调用）。

    Returns:
        {success: true, data: {cancelled: true/false}}
    """
    service = ChatService(async_session_factory)
    cancelled = await service.cancel_stream(
        packet_id=data.packet_id,
        chain_id=data.chain_id,
        group_id=group_id,
    )
    return ApiResponse(data={"cancelled": cancelled})


@router.get("/groups/{group_id}/chat/stream/status", response_model=ApiResponse[dict])
async def chat_stream_status(
    group_id: str,
    chain_id: Optional[str] = None,
    packet_id: Optional[str] = None,
):
    """
    查询 group / chain / packet 当前是否有活跃流。

    供前端在 page load 时快速检查 (无需建立 SSE 连接), 决定是否要 attach。
    """
    from app.services.stream_session import registry as stream_registry

    session = None
    if packet_id:
        session = stream_registry.get(packet_id)
    if session is None and chain_id:
        session = stream_registry.get_active_for_chain(chain_id)
    if session is None:
        session = stream_registry.get_any_active_for_group(group_id)

    if session is None:
        return ApiResponse(data={"active": False})

    return ApiResponse(data={
        "active": True,
        "chain_id": session.chain_id,
        "packet_id": session.packet_id,
        "is_streaming": session.is_streaming,
        "is_cancelled": session.is_cancelled,
        "content_length": len(session.latest_content),
    })


@router.post("/groups/{group_id}/chat", response_model=ApiResponse[ChatResponse])
async def chat(
    group_id: str,
    data: ChatRequest,
):
    """
    发送消息并获取Agent响应

    用户发送消息后，系统自动调用群聊主导Agent生成回复。
    支持通过target_agent_id指定响应Agent。
    """
    service = ChatService(async_session_factory)
    try:
        result = await service.send_message_and_get_response(
            group_id, data.content, target_agent_id=data.target_agent_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return ApiResponse(data=result)


@router.get("/groups/{group_id}/messages", response_model=ApiResponse[list[ChatMessageResponse]])
async def list_messages(
    group_id: str,
    limit: int = 50,
):
    """
    获取群聊历史消息

    返回群聊中最近的消息记录，默认50条。
    """
    service = ChatService(async_session_factory)
    messages = await service.get_history_messages(group_id, limit)
    return ApiResponse(data=messages)


@router.get("/groups/{group_id}/resolve-mention")
async def resolve_mention(
    group_id: str,
    content: str,
):
    """
    解析消息中的@mention，返回匹配的Agent ID

    用于前端在发送前确定目标Agent。
    """
    service = ChatService(async_session_factory)
    agent_id = await service.resolve_mentioned_agent(group_id, content)
    return ApiResponse(data={"agent_id": agent_id})


@router.post("/messages/cleanup")
async def cleanup_messages(
    retention_days: int = 30,
    keep_latest_per_chain: int = 20,
):
    """
    清理过期历史包

    对每个 chain 保留最近 keep_latest_per_chain 个包，
    超出部分且超过 retention_days 天的包会被软删除。
    """
    service = ChatService(async_session_factory)
    result = await service.cleanup_old_packets(
        retention_days=retention_days,
        keep_latest_per_chain=keep_latest_per_chain,
    )
    return {
        "success": True,
        "message": f"Cleaned up {result['packets_deleted']} packets across {result['chains_scanned']} chains",
        "data": result,
    }


@router.post("/chains/{chain_id}/query-memory")
async def query_chain_memory(
    chain_id: str,
    question: str,
    db: AsyncSession = Depends(get_db),
):
    """
    查询链记忆

    给定一个 chain_id 和问题，加载该链的完整历史，
    用 LLM 回答问题。用于 agent 回溯旧链上下文。
    """
    from app.services.chain_rollover_service import ChainRolloverService

    service = ChainRolloverService(db)
    result = await service.query_chain_memory(chain_id=chain_id, question=question)
    return {"success": True, "data": result}


class EventPayload(BaseModel):
    event_type: str = Field(..., description="事件类型，如 click, keypress, custom")
    target: str = Field("", description="事件目标元素描述")
    data: dict = Field(default_factory=dict, description="事件附加数据")


@router.post("/{group_id}/events")
async def post_group_event(
    group_id: str,
    body: EventPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    前端事件回传

    前端注入的 JS 可以通过此端点将用户操作事件发送回 Agent。
    事件会作为系统消息写入群聊，Agent 在下次响应时可以看到。
    """
    from app.models.chain import Chain, Packet
    from app.models.group import Group
    from sqlalchemy import select, and_
    from datetime import datetime, timezone
    import uuid

    # 获取群聊
    group = await db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    # 获取当前活跃的 chain
    result = await db.execute(
        select(Chain).where(and_(
            Chain.group_id == group_id,
            Chain.chain_type == "group",
            Chain.status == "active",
        )).order_by(Chain.created_at.desc()).limit(1)
    )
    chain = result.scalar_one_or_none()

    if not chain:
        raise HTTPException(status_code=404, detail="No active chain found")

    # 创建系统消息
    event_summary = f"[事件] {body.event_type}"
    if body.target:
        event_summary += f" on {body.target}"
    if body.data:
        event_summary += f" | {json.dumps(body.data, ensure_ascii=False)[:500]}"

    packet = Packet(
        id=str(uuid.uuid4()),
        chain_id=chain.id,
        packet_type="system",
        sender_type="system",
        sender_id="frontend_event",
        sender_name="页面事件",
        content=event_summary,
        content_type="text",
        metadata_json={"event_type": body.event_type, "event_target": body.target, "event_data": body.data},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(packet)
    await db.commit()

    return {"success": True, "message": "Event recorded"}
