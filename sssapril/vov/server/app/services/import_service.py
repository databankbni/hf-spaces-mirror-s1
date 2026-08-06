"""
导入服务模块

负责从ZIP文件导入项目数据。
"""

import json
import zipfile
import io
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.agent import Agent, ProjectAgent
from app.models.group import Group, GroupMember
from app.models.task import Task
from app.models.deliverable import Deliverable
from app.models.resource import Resource
from app.models.memory import Memory
from app.models.tag import Tag
from app.repositories.project_repo import ProjectRepository
from app.repositories.agent_repo import AgentRepository, ProjectAgentRepository
from app.repositories.group_repo import GroupRepository, GroupMemberRepository
from app.repositories.task_repo import TaskRepository
from app.repositories.deliverable_repo import DeliverableRepository
from app.repositories.resource_repo import ResourceRepository, TagRepository
from app.repositories.agent_repo import MemoryRepository


class ImportService:
    """
    导入服务

    从ZIP文件导入项目数据，支持：
    - 完整项目导入
    - 增量导入（可选）

    Example:
        service = ImportService(db)
        project = await service.import_project(zip_bytes)
    """

    def __init__(self, db: AsyncSession):
        """
        初始化导入服务

        Args:
            db: 数据库会话
        """
        self.db = db

    async def import_project(
        self,
        zip_bytes: bytes,
        name_suffix: str = " (imported)",
    ) -> Project:
        """
        从ZIP文件导入项目

        Args:
            zip_bytes: ZIP文件内容
            name_suffix: 项目名称后缀

        Returns:
            Project: 导入的项目

        Raises:
            ValueError: 文件格式错误时抛出
        """
        # 解析ZIP文件
        manifest, files = self._parse_zip(zip_bytes)

        # 验证manifest
        self._validate_manifest(manifest)

        # 创建项目
        project = await self._create_project(manifest, name_suffix)

        # 创建ID映射（旧ID -> 新ID）
        id_map = {}

        # 导入Agent
        await self._import_agents(project.id, manifest, id_map)

        # 导入群聊
        await self._import_groups(project.id, manifest, id_map)

        # 导入任务
        await self._import_tasks(project.id, manifest, id_map)

        # 导入交付物
        await self._import_deliverables(project.id, manifest, files, id_map)

        # 导入资源
        await self._import_resources(project.id, manifest, files, id_map)

        # 导入笔记
        await self._import_memories(project.id, manifest, files, id_map)

        # 导入标签
        await self._import_tags(project.id, manifest, id_map)

        return project

    def _parse_zip(self, zip_bytes: bytes) -> tuple:
        """
        解析ZIP文件

        Args:
            zip_bytes: ZIP文件内容

        Returns:
            tuple: (manifest, files)
        """
        buffer = io.BytesIO(zip_bytes)

        try:
            with zipfile.ZipFile(buffer, 'r') as zf:
                # 读取manifest.json
                if "manifest.json" not in zf.namelist():
                    raise ValueError("Invalid ZIP file: manifest.json not found")

                manifest = json.loads(zf.read("manifest.json"))

                # 读取所有文件
                files = {}
                for name in zf.namelist():
                    if name != "manifest.json":
                        files[name] = zf.read(name).decode("utf-8")

                return manifest, files

        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file format")

    def _validate_manifest(self, manifest: Dict[str, Any]) -> None:
        """
        验证manifest格式

        Args:
            manifest: manifest内容

        Raises:
            ValueError: 格式错误时抛出
        """
        required_fields = ["version", "project", "structure"]
        for field in required_fields:
            if field not in manifest:
                raise ValueError(f"Missing required field: {field}")

        # 验证版本
        version = manifest.get("version")
        if version != "1.0":
            raise ValueError(f"Unsupported version: {version}")

    async def _create_project(
        self,
        manifest: Dict[str, Any],
        name_suffix: str,
    ) -> Project:
        """
        创建项目

        Args:
            manifest: manifest内容
            name_suffix: 名称后缀

        Returns:
            Project: 创建的项目
        """
        project_data = manifest["project"]
        repo = ProjectRepository(self.db)

        # 生成新项目数据
        new_project_data = {
            "name": project_data["name"] + name_suffix,
            "description": project_data.get("description"),
            "cover_color": project_data.get("cover_color"),
            "tags": project_data.get("tags", []),
            "status": "active",
            "workflow_config": project_data.get("workflow_config", {}),
        }

        return await repo.create(new_project_data)

    async def _import_agents(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入Agent

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            id_map: ID映射
        """
        agents = manifest.get("structure", {}).get("agents", [])
        repo = ProjectAgentRepository(self.db)

        for agent_data in agents:
            old_id = agent_data["id"]

            # 检查Agent是否存在
            agent_repo = AgentRepository(self.db)
            agent = await agent_repo.get_by_id(agent_data.get("agent_id"))

            if agent:
                # 添加到项目
                pa = await repo.create({
                    "project_id": project_id,
                    "agent_id": agent.id,
                    "override_config": {},
                })
                id_map[old_id] = pa.id

    async def _import_groups(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入群聊

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            id_map: ID映射
        """
        groups = manifest.get("structure", {}).get("groups", [])
        repo = GroupRepository(self.db)

        for group_data in groups:
            old_id = group_data["id"]

            # 创建群聊
            new_group = await repo.create({
                "project_id": project_id,
                "name": group_data["name"],
                "order_index": group_data.get("order_index", 0),
                "status": "pending",  # 重置状态
                "autonomy_level": "semi_auto",
                "auto_advance": False,
            })
            id_map[old_id] = new_group.id

    async def _import_tasks(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入任务

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            id_map: ID映射
        """
        tasks = manifest.get("structure", {}).get("tasks", [])
        repo = TaskRepository(self.db)

        for task_data in tasks:
            old_id = task_data["id"]
            old_group_id = task_data["group_id"]

            # 映射到新群聊ID
            new_group_id = id_map.get(old_group_id)
            if not new_group_id:
                continue

            # 创建任务
            new_task = await repo.create({
                "group_id": new_group_id,
                "title": task_data["title"],
                "status": "todo",  # 重置状态
                "order_index": task_data.get("order_index", 0),
            })
            id_map[old_id] = new_task.id

    async def _import_deliverables(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        files: Dict[str, str],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入交付物

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            files: 文件内容
            id_map: ID映射
        """
        # 从manifest获取交付物信息
        deliverables_info = manifest.get("files", {}).get("deliverables", [])
        repo = DeliverableRepository(self.db)

        for filename in deliverables_info:
            # 读取文件内容
            content = files.get(filename, "")

            # 解析文件名获取ID
            old_id = filename.replace("deliverables/", "").replace(".md", "")

            # 查找对应的群聊ID
            # 这里简化处理，实际需要根据manifest中的映射关系
            group_id = None
            for group in manifest.get("structure", {}).get("groups", []):
                new_group_id = id_map.get(group["id"])
                if new_group_id:
                    group_id = new_group_id
                    break

            if not group_id:
                continue

            # 创建交付物
            await repo.create({
                "group_id": group_id,
                "title": f"Imported deliverable",
                "content": content,
                "content_type": "markdown",
                "scope": "group",
                "version": 1,
            })

    async def _import_resources(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        files: Dict[str, str],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入资源

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            files: 文件内容
            id_map: ID映射
        """
        resources_info = manifest.get("files", {}).get("resources", [])
        repo = ResourceRepository(self.db)

        for filename in resources_info:
            content = files.get(filename, "")

            # 创建资源
            await repo.create({
                "project_id": project_id,
                "title": f"Imported resource",
                "content": content,
                "content_type": "markdown",
                "type": "note",
                "is_required": False,
                "created_by": "import",
            })

    async def _import_memories(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        files: Dict[str, str],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入Agent笔记

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            files: 文件内容
            id_map: ID映射
        """
        memories_info = manifest.get("files", {}).get("memories", [])
        repo = MemoryRepository(self.db)

        for filename in memories_info:
            content = files.get(filename, "")

            # 解析文件名获取Agent信息
            old_id = filename.replace("memories/", "").replace(".md", "")

            # 创建笔记
            # 注意：需要找到对应的Agent ID
            # 这里简化处理
            await repo.create({
                "agent_id": "unknown",  # 需要映射
                "project_id": project_id,
                "content": content,
                "tags": [],
            })

    async def _import_tags(
        self,
        project_id: str,
        manifest: Dict[str, Any],
        id_map: Dict[str, str],
    ) -> None:
        """
        导入标签

        Args:
            project_id: 新项目ID
            manifest: manifest内容
            id_map: ID映射
        """
        tags = manifest.get("tags", [])
        repo = TagRepository(self.db)

        for tag_data in tags:
            await repo.create({
                "project_id": project_id,
                "name": tag_data["name"],
                "description": tag_data.get("description"),
                "suggested_template": tag_data.get("suggested_template"),
                "color": tag_data.get("color"),
            })
