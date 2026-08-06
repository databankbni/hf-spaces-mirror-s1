"""
讨论链API路由模块

提供讨论链相关的REST API端点。
"""

from typing import List, Optional
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.repositories.base import BaseRepository
from app.models.chain import Chain, Packet
from app.services.chain_query_service import ChainQueryService
from app.schemas.chain import (
    ChainCreate,
    ChainUpdate,
    ChainResponse,
    ChainActionRequest,
    PacketCreate,
)
from app.schemas.common import ApiResponse, StatusResponse

router = APIRouter(tags=["chains"])
logger = logging.getLogger(__name__)


class ChainRepository(BaseRepository[Chain]):
    """讨论链Repository"""

    def __init__(self, db: AsyncSession):
        super().__init__(Chain, db)



# 讨论链端点
@router.get("/tasks/{task_id}/chain", response_model=ApiResponse[ChainResponse])
async def get_task_chain(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取任务的讨论链

    返回任务关联的讨论链。
    """
    repo = ChainRepository(db)
    from sqlalchemy import select, and_
    query = select(Chain).where(and_(
        Chain.task_id == task_id,
        Chain.deleted_at.is_(None)
    ))
    result = await db.execute(query)
    chain = result.scalar_one_or_none()

    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")
    return ApiResponse(data=chain)


@router.post("/chains", response_model=ApiResponse[ChainResponse], status_code=201)
async def create_chain(
    data: ChainCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建讨论链

    为任务创建讨论链。
    """
    repo = ChainRepository(db)
    chain = await repo.create(data.model_dump())
    return ApiResponse(data=chain)


@router.post("/chains/{chain_id}/action", response_model=ApiResponse[StatusResponse])
async def chain_action(
    chain_id: str,
    data: ChainActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    讨论链操作

    对讨论链执行操作（暂停/恢复/完成/取消）。
    """
    repo = ChainRepository(db)
    chain = await repo.get_by_id(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # 状态映射
    status_map = {
        "pause": "paused",
        "resume": "active",
        "complete": "completed",
        "cancel": "cancelled",
    }

    new_status = status_map.get(data.action)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Invalid action: {data.action}")

    update_data = {"status": new_status}
    if new_status == "completed":
        from datetime import datetime, timezone
        update_data["completed_at"] = datetime.now(timezone.utc)

    await repo.update(chain_id, update_data)
    return ApiResponse(data=StatusResponse(success=True, message=f"Chain {data.action}"))



@router.get("/chains/{chain_id}/messages")
async def list_messages(
    chain_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = Query(None, description="游标分页：获取此消息ID之前的消息"),
    db: AsyncSession = Depends(get_db),
):
    # 收集所有需要查询的链 ID（当前链 + rollover 历史链）
    chain_service = ChainQueryService(db)
    chain_ids = await chain_service.collect_chain_ids_with_rollover(chain_id)

    query = (
        select(Packet)
        .where(and_(Packet.chain_id.in_(chain_ids), Packet.deleted_at.is_(None)))
        .order_by(Packet.created_at.desc())
        .offset(skip)
        .limit(limit + 1)
    )
    if before:
        query = query.where(Packet.id < before)

    result = await db.execute(query)
    packets = list(result.scalars().all())

    has_more = len(packets) > limit
    if has_more:
        packets = packets[:limit]

    return ApiResponse(data={
        "items": [ChainQueryService.serialize_packet(p) for p in packets],
        "total": len(packets),
        "has_more": has_more,
    })


@router.post("/chains/{chain_id}/messages", status_code=201)
async def create_message(
    chain_id: str,
    data: PacketCreate,
    sender_id: Optional[str] = Query(None, description="发送者ID"),
    sender_type: str = Query("user", description="发送者类型"),
    sender_name: Optional[str] = Query(None, description="发送者名称"),
    db: AsyncSession = Depends(get_db),
):
    chain_result = await db.execute(
        select(Chain).where(and_(Chain.id == chain_id, Chain.deleted_at.is_(None)))
    )
    chain = chain_result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    packet_type_map = {"user": "user_input", "agent": "agent_text", "system": "system", "tool": "tool_result"}
    packet_type = packet_type_map.get(sender_type, "user_input")

    prev_result = await db.execute(
        select(Packet)
        .where(and_(Packet.chain_id == chain_id, Packet.deleted_at.is_(None)))
        .order_by(Packet.created_at.desc())
        .limit(1)
    )
    last_packet = prev_result.scalar_one_or_none()

    packet = Packet(
        chain_id=chain_id,
        prev_packet_id=last_packet.id if last_packet else None,
        packet_type=packet_type,
        sender_type=sender_type,
        sender_id=sender_id or sender_type,
        sender_name=sender_name or "unknown",
        content=data.content,
        content_type=data.content_type or "text",
        metadata_json=data.metadata or {},
    )
    db.add(packet)

    if not chain.head_packet_id:
        chain.head_packet_id = packet.id
    chain.tail_packet_id = packet.id
    chain.packet_count = (chain.packet_count or 0) + 1

    await db.commit()
    await db.refresh(packet)

    return ApiResponse(data=ChainQueryService.serialize_packet(packet))


@router.get("/chains/{chain_id}/view")
async def get_chain_view(
    chain_id: str,
    depth: int = Query(1, ge=0, le=3, description="子链展开深度"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取链视图

    返回链的包列表和子链摘要。
    depth=0: 只返回链信息和包列表
    depth=1: 返回子链的 head/tail 摘要
    depth=2+: 递归展开子链
    """
    # 查询链
    chain_result = await db.execute(
        select(Chain)
        .where(and_(Chain.id == chain_id, Chain.deleted_at.is_(None)))
    )
    chain = chain_result.scalar_one_or_none()
    if not chain:
        raise HTTPException(status_code=404, detail="Chain not found")

    # 收集所有需要查询的链 ID（当前链 + rollover 历史链）
    chain_service = ChainQueryService(db)
    chain_ids = await chain_service.collect_chain_ids_with_rollover(chain_id)

    # 查询包（包含 rollover 历史链的包）
    packets_result = await db.execute(
        select(Packet)
        .where(and_(Packet.chain_id.in_(chain_ids), Packet.deleted_at.is_(None)))
        .order_by(Packet.created_at)
    )
    packets = list(packets_result.scalars().all())



    # 构建子链摘要
    sub_chain_summaries = []
    if depth > 0:
        # 收集所有包引用的子链ID
        sub_chain_ids = [p.sub_chain_id for p in packets if p.sub_chain_id]
        if sub_chain_ids:
            sub_chains_result = await db.execute(
                select(Chain)
                .where(and_(
                    Chain.id.in_(sub_chain_ids),
                    Chain.deleted_at.is_(None),
                ))
            )
            sub_chains = list(sub_chains_result.scalars().all())

            for sc in sub_chains:
                chain_info = ChainQueryService.serialize_chain(sc)
                if depth > 1:
                    # 递归获取子链视图
                    sub_view = await _get_sub_chain_view(db, sc, depth - 1)
                    sub_chain_summaries.append({
                        "chain": chain_info,
                        "packets": sub_view["packets"],
                        "sub_chains": sub_view["sub_chains"],
                    })
                else:
                    # 只返回 head/tail 包
                    sub_chain_summaries.append({
                        "chain": chain_info,
                        "packets": await _get_head_tail_packets(db, sc),
                        "sub_chains": [],
                    })

    return ApiResponse(data={
        "chain": ChainQueryService.serialize_chain(chain),
        "packets": [ChainQueryService.serialize_packet(p) for p in packets],
        "sub_chains": sub_chain_summaries,
    })


async def _get_sub_chain_view(db: AsyncSession, chain: Chain, depth: int) -> dict:
    """递归获取子链视图（含 rollover 链包）"""
    # 收集所有需要查询的链 ID（当前链 + rollover 历史链）
    chain_service = ChainQueryService(db)
    chain_ids = await chain_service.collect_chain_ids_with_rollover(chain.id)

    packets_result = await db.execute(
        select(Packet)
        .where(and_(Packet.chain_id.in_(chain_ids), Packet.deleted_at.is_(None)))
        .order_by(Packet.created_at)
    )
    packets = list(packets_result.scalars().all())

    sub_chain_summaries = []
    if depth > 0:
        sub_chain_ids = [p.sub_chain_id for p in packets if p.sub_chain_id]
        if sub_chain_ids:
            sub_chains_result = await db.execute(
                select(Chain)
                .where(and_(
                    Chain.id.in_(sub_chain_ids),
                    Chain.deleted_at.is_(None),
                ))
            )
            sub_chains = list(sub_chains_result.scalars().all())
            for sc in sub_chains:
                chain_info = ChainQueryService.serialize_chain(sc)
                if depth > 1:
                    sub_view = await _get_sub_chain_view(db, sc, depth - 1)
                    sub_chain_summaries.append({
                        "chain": chain_info,
                        "packets": sub_view["packets"],
                        "sub_chains": sub_view["sub_chains"],
                    })
                else:
                    sub_chain_summaries.append({
                        "chain": chain_info,
                        "packets": await _get_head_tail_packets(db, sc),
                        "sub_chains": [],
                    })

    return {
        "packets": [ChainQueryService.serialize_packet(p) for p in packets],
        "sub_chains": sub_chain_summaries,
    }


async def _get_head_tail_packets(db: AsyncSession, chain: Chain) -> list[dict]:
    """获取链的头尾包摘要"""
    packet_ids = []
    if chain.head_packet_id:
        packet_ids.append(chain.head_packet_id)
    if chain.tail_packet_id and chain.tail_packet_id != chain.head_packet_id:
        packet_ids.append(chain.tail_packet_id)

    if not packet_ids:
        return []

    result = await db.execute(
        select(Packet).where(Packet.id.in_(packet_ids))
    )
    packets = list(result.scalars().all())
    return [ChainQueryService.serialize_packet(p) for p in packets]


@router.get("/groups/{group_id}/chains")
async def get_group_chains(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊的链树

    返回群链及其所有子链的树形结构。
    如果群链不存在，回退查找该群聊的所有任务链。

    v2 P2 链交接修复：按 created_at DESC 排序取最新活跃链，
    兼容链交接后同时存在 active/completed 多根链的场景。
    """
    # 查找群链（优先 active，兜底取最新创建）
    # v2 P2 修复：优先查找 active 状态的链，如果没有 active 链，则取最新创建的链
    group_chain_result = await db.execute(
        select(Chain)
        .where(and_(
            Chain.group_id == group_id,
            Chain.chain_type == "group",
            Chain.deleted_at.is_(None),
        ))
        .order_by(
            # 优先选择 active 状态的链
            Chain.status == "active",
            Chain.created_at.desc()
        )
        .limit(1)
    )
    group_chain = group_chain_result.scalar_one_or_none()

    if group_chain:
        # 收集所有群链 ID（当前 + rollover 历史链），以获取完整的任务链列表
        chain_service = ChainQueryService(db)
        group_chain_ids = await chain_service.collect_chain_ids_with_rollover(group_chain.id)

        # 标准路径：群链存在，查找其下（含 rollover 历史链下）的任务链
        task_chains_result = await db.execute(
            select(Chain)
            .where(and_(
                Chain.parent_chain_id.in_(group_chain_ids),
                Chain.chain_type == "task",
                Chain.deleted_at.is_(None),
            ))
            .order_by(Chain.created_at)
        )
        task_chains = list(task_chains_result.scalars().all())

        result = {
            "chain": ChainQueryService.serialize_chain(group_chain),
            "sub_chains": [ChainQueryService.serialize_chain(tc) for tc in task_chains],
        }
    else:
        # 兼容路径：群链不存在，直接查找该群聊的所有任务链
        task_chains_result = await db.execute(
            select(Chain)
            .where(and_(
                Chain.group_id == group_id,
                Chain.chain_type == "task",
                Chain.deleted_at.is_(None),
            ))
            .order_by(Chain.created_at)
        )
        task_chains = list(task_chains_result.scalars().all())

        result = {
            "chain": None,
            "sub_chains": [ChainQueryService.serialize_chain(tc) for tc in task_chains],
        }

    return ApiResponse(data=result)
