"""
群聊Service模块

提供群聊(Group)的业务逻辑。
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group import Group, GroupMember
from app.repositories.group_repo import GroupRepository, GroupMemberRepository
from .base import BaseService


class GroupService(BaseService[Group, GroupRepository]):
    """
    群聊Service

    提供群聊相关的业务逻辑。
    """

    def __init__(self, db: AsyncSession):
        repo = GroupRepository(db)
        super().__init__(repo, db)
        self.member_repo = GroupMemberRepository(db)

    async def get_by_project(self, project_id: str) -> List[Dict[str, Any]]:
        """
        获取项目的群聊列表（含统计信息）

        Args:
            project_id: 项目ID

        Returns:
            List[Dict]: 群聊列表，含member_count/task_count
        """
        return await self.repo.get_by_project(project_id)

    async def get_detail(self, id: str) -> Optional[dict]:
        """
        获取群聊详情

        Args:
            id: 群聊ID

        Returns:
            Optional[dict]: 群聊详情
        """
        # Expire all cached objects to ensure fresh data
        self.db.expire_all()
        return await self.repo.get_with_details(id)

    async def create_group(self, project_id: str, data: Dict[str, Any]) -> Group:
        """
        创建群聊

        Args:
            project_id: 项目ID
            data: 群聊数据

        Returns:
            Group: 创建的群聊
        """
        # 获取最大排序索引
        max_order = await self.repo.get_max_order(project_id)

        # 设置默认值
        data["project_id"] = project_id
        data["order_index"] = max_order + 1
        if "status" not in data:
            data["status"] = "pending"
        if "autonomy_level" not in data:
            data["autonomy_level"] = "semi_auto"
        if "auto_advance" not in data:
            data["auto_advance"] = False

        # 提取成员ID列表
        member_ids = data.pop("member_agent_ids", [])

        # 创建群聊
        group = await self.repo.create(data)

        # 添加成员
        for agent_id in member_ids:
            await self.add_member(group.id, agent_id)

        # Return the group (members will be loaded when detail is fetched separately)
        return group

    async def update_group(self, id: str, data: Dict[str, Any]) -> Optional[Group]:
        """
        更新群聊

        Args:
            id: 群聊ID
            data: 更新数据

        Returns:
            Optional[Group]: 更新后的群聊
        """
        return await self.repo.update(id, data)

    async def delete_group(self, id: str) -> bool:
        """
        删除群聊

        Args:
            id: 群聊ID

        Returns:
            bool: 是否删除成功
        """
        return await self.repo.delete(id)

    async def reorder(self, project_id: str, ordered_ids: List[str]) -> None:
        """
        重新排序群聊

        Args:
            project_id: 项目ID
            ordered_ids: 排序后的群聊ID列表
        """
        await self.repo.reorder(project_id, ordered_ids)

    # 成员管理

    async def get_members(self, group_id: str) -> List[GroupMember]:
        """
        获取群聊成员列表

        Args:
            group_id: 群聊ID

        Returns:
            List[GroupMember]: 成员列表
        """
        return await self.member_repo.get_by_group(group_id)

    async def add_member(self, group_id: str, project_agent_id: str, role: str = "participant") -> GroupMember:
        """
        添加群聊成员

        Args:
            group_id: 群聊ID
            project_agent_id: 项目Agent ID
            role: 成员角色

        Returns:
            GroupMember: 添加的成员
        """
        return await self.member_repo.create({
            "group_id": group_id,
            "project_agent_id": project_agent_id,
            "role": role,
        })

    async def update_member_role(self, group_id: str, project_agent_id: str, role: str) -> GroupMember:
        member = await self.member_repo.get_by_group_and_agent(group_id, project_agent_id)
        if not member:
            raise ValueError("成员不存在")
        member.role = role
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def remove_member(self, group_id: str, project_agent_id: str) -> bool:
        """
        移除群聊成员

        Args:
            group_id: 群聊ID
            project_agent_id: 项目Agent ID

        Returns:
            bool: 是否移除成功
        """
        member = await self.member_repo.get_by_group_and_agent(group_id, project_agent_id)
        if not member:
            return False
        return await self.member_repo.hard_delete(member.id)

    async def is_member(self, group_id: str, project_agent_id: str) -> bool:
        """
        检查Agent是否是群聊成员

        Args:
            group_id: 群聊ID
            project_agent_id: 项目Agent ID

        Returns:
            bool: 是否是成员
        """
        return await self.member_repo.is_member(group_id, project_agent_id)
