"""
任务API路由模块

提供任务相关的REST API端点。
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.services.task_service import TaskService
from app.schemas.task import (
    TaskCreate,
    TaskUpdate,
    TaskUpdateStatus,
    TaskResponse,
    TaskListItem,
)
from app.schemas.common import ApiResponse, PaginatedResponse, StatusResponse

router = APIRouter(tags=["tasks"])


# 群聊任务端点
@router.get("/groups/{group_id}/tasks", response_model=ApiResponse[PaginatedResponse[TaskListItem]])
async def list_tasks(
    group_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取群聊的任务列表

    返回群聊中所有任务。
    """
    from sqlalchemy import select, and_, func
    from app.models.resource import Resource

    service = TaskService(db)
    tasks = await service.get_by_group(group_id)

    # v2 P2: 批量预计算 resources_by_task, 避免 from_task 内 N+1
    # 仅统计非文件夹的 resource 数量, 作为 has_deliverable 判定
    task_ids = [t.id for t in tasks]
    resources_by_task: dict = {}
    if task_ids:
        r_q = (
            select(Resource.task_id, func.count(Resource.id))
            .where(and_(
                Resource.task_id.in_(task_ids),
                Resource.is_folder == False,
                Resource.deleted_at.is_(None),
            ))
            .group_by(Resource.task_id)
        )
        rows = (await db.execute(r_q)).all()
        resources_by_task = {row[0]: row[1] for row in rows}

    # v2 P2: 显式构造 TaskListItem 以正确计算 assignee_count/has_chain/has_deliverable
    items = [TaskListItem.from_task(t, resources_by_task=resources_by_task) for t in tasks]
    return ApiResponse(data=PaginatedResponse(items=items, total=len(items), skip=0, limit=100))


@router.post("/groups/{group_id}/tasks", response_model=ApiResponse[TaskResponse], status_code=201)
async def create_task(
    group_id: str,
    data: TaskCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    创建任务

    在群聊中创建新任务，同时创建任务链并在群聊级链中插入请求节点。
    """
    from app.services.chat_service import ChatService
    from app.models.group import Group
    from app.core.database import async_session_factory
    from sqlalchemy import select

    service = TaskService(db)
    task = await service.create_task(group_id, data.model_dump())

    # 创建任务链
    try:
        chat_service = ChatService(async_session_factory)
        group_result = await db.execute(select(Group).where(Group.id == group_id))
        group = group_result.scalar_one_or_none()
        if group:
            await chat_service.create_task_chain(
                db, group, task.id,
                request_content=f"创建任务: {task.title}",
            )
            await db.commit()
    except Exception as e:
        # 任务链创建失败不影响任务创建
        import logging
        logging.getLogger(__name__).warning(f"Failed to create task chain: {e}")

    # 广播任务创建事件, 让前端通过 WebSocket 实时看到新任务
    try:
        from app.orchestrator.websocket_manager import ws_manager
        await ws_manager.broadcast(str(group_id), {
            "type": "task_update",
            "payload": {
                "task_id": str(task.id),
                "action": "created",
                "group_id": str(group_id),
            },
        })
    except Exception:
        pass

    return ApiResponse(data=task)


# 任务详情端点
@router.get("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取任务详情

    返回任务的详细信息。
    """
    service = TaskService(db)
    task = await service.get_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(data=task)


@router.put("/tasks/{task_id}", response_model=ApiResponse[TaskResponse])
async def update_task(
    task_id: str,
    data: TaskUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    更新任务

    更新任务信息。
    """
    service = TaskService(db)

    # 提取指派ID列表
    update_data = data.model_dump(exclude_unset=True)
    assignee_ids = update_data.pop("assignee_ids", None)

    # 更新任务基本信息
    task = await service.update_task(task_id, update_data)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 更新指派
    if assignee_ids is not None:
        await service.clear_assignees(task_id)
        for agent_id in assignee_ids:
            await service.add_assignee(task_id, agent_id)

    return ApiResponse(data=task)


@router.patch("/tasks/{task_id}/status", response_model=ApiResponse[TaskResponse])
async def update_task_status(
    task_id: str,
    data: TaskUpdateStatus,
    db: AsyncSession = Depends(get_db),
):
    """
    更新任务状态

    根据状态流转规则更新任务状态。

    v2 P2 群内串行守卫:
      - 群内任务必须串行（同一时刻只允许 1 个 in_progress）
      - 工具层（tool_adapter）和 API 层（这里）都做兜底
    """
    from app.models.task import Task as TaskModel
    from sqlalchemy import select, and_

    service = TaskService(db)

    # 1) 群内串行守卫: 标 in_progress 前, 检查同群是否已有其他 in_progress
    if data.status == "in_progress":
        target = await service.get_detail(task_id)
        if target is None:
            raise HTTPException(status_code=404, detail="Task not found")
        other_q = (
            select(TaskModel)
            .where(and_(
                TaskModel.group_id == target.group_id,
                TaskModel.id != task_id,
                TaskModel.status == "in_progress",
                TaskModel.deleted_at.is_(None),
            ))
        )
        others = (await db.execute(other_q)).scalars().all()
        if others:
            titles = " / ".join(t.title for t in others[:3])
            raise HTTPException(
                status_code=409,
                detail=(
                    f"群内任务必须串行, 同一时刻只允许 1 个 in_progress。"
                    f"当前群内还有 in_progress 任务: [{titles}]。"
                    f"请先把它 done（或让它回到 todo），再标本 task 为 in_progress。"
                ),
            )

    try:
        task = await service.update_status(task_id, data.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # v2 P2+ 统一服务路径: chain 流转 + 事件发布 与 agent 工具 (tool_adapter) 共用
    #   ChainHandoverService.apply_task_status_transition
    #   修复: 此前 UI 启动任务不触发 handover (主链不 paused、task chain 不 active),
    #         导致消息进不到任务块、任务块里看不到对话记录。现在 UI 与 agent 走同一条路径。
    try:
        from app.services.chain_handover_service import ChainHandoverService
        handover_svc = ChainHandoverService(db)
        await handover_svc.apply_task_status_transition(
            task, data.status, result=getattr(data, "result", "") or "",
        )
        await db.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to apply task chain transition: {e}")

    return ApiResponse(data=task)


@router.delete("/tasks/{task_id}", response_model=ApiResponse[StatusResponse])
async def delete_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除任务

    删除指定任务（软删除）。
    """
    service = TaskService(db)
    success = await service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(data=StatusResponse(success=True, message="Task deleted"))
