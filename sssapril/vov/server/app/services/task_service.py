"""
任务Service模块

提供任务(Task)的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.repositories.task_repo import TaskRepository, TaskAssigneeRepository
from .base import BaseService


class TaskService(BaseService[Task, TaskRepository]):
    """
    任务Service

    提供任务相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = TaskRepository(db)
        super().__init__(repo, db)
        self.assignee_repo = TaskAssigneeRepository(db)

    async def get_by_group(self, group_id: str) -> List[Task]:
        """
        获取群聊的任务列表

        Args:
            group_id: 群聊ID

        Returns:
            List[Task]: 任务列表
        """
        return await self.repo.get_by_group(group_id)

    async def get_detail(self, id: str) -> Optional[Task]:
        """
        获取任务详情

        Args:
            id: 任务ID

        Returns:
            Optional[Task]: 任务详情
        """
        return await self.repo.get_with_details(id)

    async def create_task(self, group_id: str, data: Dict[str, Any]) -> Task:
        """
        创建任务

        Args:
            group_id: 群聊ID
            data: 任务数据

        Returns:
            Task: 创建的任务
        """
        # 获取最大排序索引
        max_order = await self.repo.get_max_order(group_id)

        # 设置默认值
        data["group_id"] = group_id
        data["order_index"] = max_order + 1
        if "status" not in data:
            data["status"] = "todo"
        # v2 P2: inherit_main_chain 默认 1 (继承主链历史)
        if "inherit_main_chain" not in data:
            data["inherit_main_chain"] = 1
        # 转成 int (SQLite 没有 boolean)
        data["inherit_main_chain"] = 1 if data["inherit_main_chain"] else 0

        # 提取指派ID列表
        assignee_ids = data.pop("assignee_ids", [])

        # 创建任务
        task = await self.repo.create(data)

        # 添加指派
        for agent_id in assignee_ids:
            await self.add_assignee(task.id, agent_id)

        return task

    async def update_task(self, id: str, data: Dict[str, Any]) -> Optional[Task]:
        """
        更新任务

        Args:
            id: 任务ID
            data: 更新数据

        Returns:
            Optional[Task]: 更新后的任务
        """
        return await self.repo.update(id, data)

    async def update_status(self, id: str, status: str) -> Optional[Task]:
        """
        更新任务状态

        状态流转规则（宽松模式，支持跳级）：
        - todo -> in_progress / done
        - in_progress -> done
        - done -> reopened
        - reopened -> in_progress / done

        Args:
            id: 任务ID
            status: 新状态

        Returns:
            Optional[Task]: 更新后的任务

        Raises:
            ValueError: 状态流转不合法时抛出
        """
        task = await self.repo.get_by_id(id)
        if not task:
            return None

        # 验证状态流转（宽松模式：允许跳级前进，不允许倒退到之前的状态）
        valid_transitions = {
            "todo": ["in_progress", "done"],
            "in_progress": ["done"],
            "done": ["reopened"],
            "reopened": ["in_progress", "done"],
        }

        if status not in valid_transitions.get(task.status, []):
            raise ValueError(f"Invalid status transition: {task.status} -> {status}. Valid transitions from '{task.status}': {valid_transitions.get(task.status, [])}")

        # 更新状态和时间
        update_data = {"status": status}
        now = datetime.now(timezone.utc)

        if status == "in_progress":
            update_data["started_at"] = now
        elif status == "done":
            update_data["completed_at"] = now
        elif status == "reopened":
            update_data["completed_at"] = None

        return await self.repo.update(id, update_data)

    async def delete_task(self, id: str) -> bool:
        """
        删除任务

        Args:
            id: 任务ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)

    # 指派管理

    async def add_assignee(self, task_id: str, project_agent_id: str) -> None:
        """
        添加任务指派

        Args:
            task_id: 任务ID
            project_agent_id: 项目Agent ID
        """
        await self.assignee_repo.create({
            "task_id": task_id,
            "project_agent_id": project_agent_id,
        })

    async def clear_assignees(self, task_id: str) -> None:
        """
        清除任务的所有指派

        Args:
            task_id: 任务ID
        """
        await self.assignee_repo.delete_by_task(task_id)
