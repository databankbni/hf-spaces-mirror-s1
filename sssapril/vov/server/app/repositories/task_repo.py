"""
任务Repository模块

提供任务(Task)和任务指派(TaskAssignee)的数据访问操作。
"""

from typing import Optional, List
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.task import Task, TaskAssignee
from .base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """
    任务Repository

    提供任务相关的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(Task, db)

    async def get_by_group(self, group_id: str) -> List[Task]:
        """
        获取群聊的任务列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Task]: 任务列表，按order_index排序
        """
        query = (
            select(Task)
            .where(and_(
                Task.group_id == group_id,
                Task.deleted_at.is_(None)
            ))
            .options(
                selectinload(Task.assignees),
                selectinload(Task.chain),
            )
            .order_by(Task.order_index)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_with_details(self, id: str) -> Optional[Task]:
        """
        获取任务详情（包含关联数据）

        Args:
            id: 任务ID

        Returns:
            Optional[Task]: 任务详情
        """
        # ⚠️ 必须显式 selectinload 所有可能被访问的关系, 异步 ORM 不预加载访问会触发
        # MissingGreenlet 静默失败 (常见关联: group/assignees/chain, 任何一处遗漏都可能导致
        # 后续访问 NPE 或异常被外层 except 吞掉). 这里全量预加载, 一次搞定.
        query = (
            select(Task)
            .where(and_(Task.id == id, Task.deleted_at.is_(None)))
            .options(
                selectinload(Task.group),
                selectinload(Task.assignees),
                selectinload(Task.chain),
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_max_order(self, group_id: str) -> int:
        """
        获取群聊中任务的最大排序索引

        Args:
            group_id: 群聊ID

        Returns:
            int: 最大排序索引
        """
        from sqlalchemy import func
        query = (
            select(func.max(Task.order_index))
            .where(and_(
                Task.group_id == group_id,
                Task.deleted_at.is_(None)
            ))
        )
        result = await self.db.execute(query)
        return result.scalar() or 0


class TaskAssigneeRepository(BaseRepository[TaskAssignee]):
    """
    任务指派Repository

    提供任务指派的数据访问操作。
    """

    def __init__(self, db: AsyncSession):
        super().__init__(TaskAssignee, db)

    async def get_by_task(self, task_id: str) -> List[TaskAssignee]:
        """
        获取任务的指派列表

        Args:
            task_id: 任务ID

        Returns:
            List[TaskAssignee]: 指派列表
        """
        query = (
            select(TaskAssignee)
            .where(TaskAssignee.task_id == task_id)
            .options(selectinload(TaskAssignee.project_agent))
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def delete_by_task(self, task_id: str) -> None:
        """
        删除任务的所有指派

        Args:
            task_id: 任务ID
        """
        assignees = await self.get_by_task(task_id)
        for assignee in assignees:
            await self.db.delete(assignee)
        await self.db.flush()
