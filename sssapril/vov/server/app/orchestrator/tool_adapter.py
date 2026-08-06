"""
ServerToolAdapter

实现 agentflow 的 ToolServiceAdapter 协议，
将 agentflow 工具处理器的调用桥接到 server 的各个 Service。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.project_service import ProjectService
from app.services.group_service import GroupService
from app.services.task_service import TaskService
from app.services.deliverable_service import DeliverableService
from app.services.resource_service import ResourceService
from app.services.agent_service import AgentService, ProjectAgentService, MemoryService
from app.services.template_service import TemplateService
from app.repositories.agent_repo import AgentSkillRepository

logger = logging.getLogger(__name__)


def _serialize(obj: Any, _depth: int = 0) -> Any:
    """将模型对象递归序列化为可 JSON 化的类型"""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (str, int, float)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _serialize(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_serialize(item, _depth + 1) for item in obj]
    if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
        try:
            return _serialize(obj.to_dict(), _depth + 1)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "_serialize: obj.to_dict() failed for type=%s at depth=%d: %s",
                type(obj).__name__, _depth, e
            )
            return str(obj)
    # 兜底：尝试转为字符串
    try:
        return str(obj)
    except Exception:
        return f"<unserializable:{type(obj).__name__}>"


# ── 智能标签补全 ──────────────────────────────────────────
# LLM 经常忘记传 tags 参数。基于 title 关键词 + 资源类型 + 内容启发式，
# 自动补全常用标签，让资源可被按 tag 检索/分组。
_TAG_RULES = [
    # (title_contains, [tags])
    ("1-50章", ["细纲", "1-50章", "卷一", "G5"]),
    ("51-100章", ["细纲", "51-100章", "卷二", "G5"]),
    ("101-150章", ["细纲", "101-150章", "卷三", "G5"]),
    ("151-200章", ["细纲", "151-200章", "卷四", "G5"]),
    ("分卷", ["细纲", "分卷", "G5"]),
    ("章节目录", ["细纲", "目录", "G5"]),
    ("重点章细纲", ["细纲", "重点章", "G5"]),
    ("大纲自检", ["细纲", "审校", "G5"]),
    ("大纲", ["大纲", "G4"]),
    ("架构", ["大纲", "G4"]),
    ("节拍表", ["大纲", "节拍", "G4"]),
    ("主线", ["大纲", "主线", "G4"]),
    ("世界观", ["世界观", "G2", "guideline"]),
    ("力量体系", ["世界观", "体系", "G2"]),
    ("编年史", ["世界观", "历史", "G2"]),
    ("立项", ["立项", "G1"]),
    ("项目立项", ["立项", "G1"]),
    ("主角卡", ["人物", "主角", "G3"]),
    ("配角", ["人物", "配角", "G3"]),
    ("反派", ["人物", "反派", "G3"]),
    ("关系图", ["人物", "关系", "G3"]),
    ("人物", ["人物", "G3"]),
    ("风格指南", ["风格", "guideline"]),
    ("风格", ["风格", "guideline"]),
    ("章节格式", ["章节", "格式", "guideline"]),
    ("第", ["章节"]),  # 章节正文：标题含"第N章"
    ("审校", ["审校", "rule"]),
    ("一致", ["审校", "rule"]),
    ("逻辑", ["审校", "rule"]),
    ("检查", ["审校", "rule"]),
    ("伏笔", ["大纲", "伏笔", "G4"]),
    ("副线", ["大纲", "副线", "G4"]),
    ("开篇", ["章节", "开篇"]),
    ("高潮", ["章节", "高潮"]),
    ("结尾", ["章节", "结尾"]),
    ("中点", ["章节", "中点"]),
]


def _infer_tags_from_title(
    title: str,
    resource_type: str = "note",
    content: str = "",
) -> List[str]:
    """
    基于 title 关键词 + 资源类型 + 内容启发式推断 tags。

    目的：LLM 经常忘记传 tags 参数。这里做"软兜底"——基于常见模板标题
    自动补标签，让资源可被按 tag 检索。

    规则：
    - 标题含 "1-50章" → 细纲 + 卷一 + G5
    - 标题含 "大纲" → 大纲 + G4
    - 资源类型 = guideline → 加 "guideline" 标签
    - 资源类型 = rule → 加 "rule" 标签
    - 章节正文（标题含"第N章"）→ 章节 + chapter_N
    - 兜底：基于 type 加至少一个标签

    Returns:
        List[str]: 推断的标签（去重 + 保序）
    """
    if not title:
        return []

    tags: List[str] = []
    seen: set = set()

    def add(tag: str):
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # 1. title 关键词匹配
    for keyword, matched_tags in _TAG_RULES:
        if keyword in title:
            for t in matched_tags:
                add(t)

    # 2. 资源类型补标签
    if resource_type == "guideline":
        add("guideline")
    elif resource_type == "rule":
        add("rule")
    elif resource_type == "reference":
        add("reference")

    # 3. 章节正文特殊处理（标题含"第N章"）
    import re
    m = re.search(r"第\s*(\d+)\s*章", title)
    if m:
        add("章节")
        add(f"第{m.group(1)}章")

    # 4. 兜底：什么都没有时至少一个标签
    if not tags:
        add(resource_type or "note")

    return tags


class ServerToolAdapter:
    """
    Server 端的 ToolServiceAdapter 实现

    每个方法创建独立的数据库 session（线程安全），
    调用对应的 Service 方法，返回序列化后的字典。

    重要：由于 agentflow 的 Processor 在 ThreadPoolExecutor 线程中执行，
    而 SQLAlchemy AsyncSession 绑定到主事件循环，所有 async 方法
    必须通过 run_coroutine_threadsafe 调度回主循环执行。
    """

    # v9: B2 串行守卫锁 - 类变量, 所有实例共享 (agent_executor._prepare 每次新建实例,
    # 实例级锁无法跨 agent 串行化 B2 检查)
    _task_lock: Optional["asyncio.Lock"] = None

    @classmethod
    def _get_task_lock(cls) -> "asyncio.Lock":
        """懒初始化类级 _task_lock, 绑定到首次调用时的事件循环"""
        if cls._task_lock is None:
            cls._task_lock = asyncio.Lock()
        return cls._task_lock

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        # 保存主事件循环引用，供子线程中调度协程
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._main_loop = None
        # v2 P2: 任务事件通知改走 EventDispatcher (经 event_bus)，
        # tool_adapter 不再保留 awake 回调钩子。旧 _on_task_in_progress_awake / _on_task_done_awake_lead 已废弃。
        # B2 串行守卫锁: 串行化 update_task_status, 防止 AllModelPlugin 并行工具调用
        # 导致多个 create_task(status="in_progress") 同时通过 B2 检查 (TOCTOU 竞态).
        # 注意: 锁绑定到首次 await 时所在的事件循环. 由于所有工具调用都通过
        # run_coroutine_threadsafe 调度回主循环执行, 这里创建的锁能正确串行化它们.
        # v9 修复: _task_lock 改为类变量. agent_executor._prepare 每次都新建
        # ServerToolAdapter 实例, 实例级锁无法跨 agent/execute 串行化, 导致
        # 法官 + 玩家在不同实例上各自获得"独占锁"→ B2 守卫失效, 出现多个 in_progress.
        # 类变量绑定到首次实例化时的事件循环, 主循环固定时安全共享.

    # ── Project ──

    async def create_project(self, name: str, description: str = "") -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = ProjectService(db)
            project = await svc.create_project({"name": name, "description": description})
            await db.commit()
            return _serialize(project.to_dict())

    async def list_projects(self) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = ProjectService(db)
            projects = await svc.get_list()
            return _serialize(projects)

    async def list_user_projects(self) -> List[Dict[str, Any]]:
        """列出所有用户项目（排除 is_guide=True 的引导 project）"""
        async with self._session_factory() as db:
            svc = ProjectService(db)
            projects = await svc.get_list()
            serialized = _serialize(projects)
            return [p for p in serialized if not p.get("is_guide", False)]

    async def get_project(self, project_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = ProjectService(db)
            project = await svc.get_detail(project_id)
            if project is None:
                raise ValueError(f"Project '{project_id}' not found")
            return _serialize(project.to_dict())

    # ── Group ──

    async def create_group(self, project_id: str, name: str, description: str = "") -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            group = await svc.create_group(project_id, {"name": name, "description": description})
            await db.commit()
            return _serialize(group.to_dict())

    async def list_groups(self, project_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            groups = await svc.get_by_project(project_id)
            # NOTE: groups 是 List[Dict]（Repository 手动构造含 member_count/task_count），
            # 不是 List[Group] 模型对象，不能用 [g.to_dict() for g in groups]
            return _serialize(groups)

    async def get_group(self, group_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            group = await svc.get_detail(group_id)
            if group is None:
                raise ValueError(f"Group '{group_id}' not found")
            # NOTE: group 是 dict（Repository 手动构造含关联数据），不是 Group 模型对象，不能用 .to_dict()
            return _serialize(group)

    async def update_group(
        self,
        group_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        autonomy_level: Optional[str] = None,
        auto_advance: Optional[bool] = None,
    ) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description
            if status is not None:
                update_data["status"] = status
            if autonomy_level is not None:
                update_data["autonomy_level"] = autonomy_level
            if auto_advance is not None:
                update_data["auto_advance"] = auto_advance
            group = await svc.update_group(group_id, update_data)
            if group is None:
                return {"error": "update_group 工具调用错误: 群聊不存在"}
            await db.commit()
            # v2 P2: 发 group_status_changed 事件（EventDispatcher 可触发 lead 推进下一阶段）
            try:
                from app.services.event_bus import event_bus
                await event_bus.publish(
                    "group_status_changed",
                    {
                        "group_id": str(group.id),
                        "project_id": str(group.project_id),
                        "new_status": group.status,
                        "name": group.name,
                    },
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("publish group_status_changed failed: %s", e)
            return _serialize(group.to_dict())

    async def delete_group(self, group_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            success = await svc.delete_group(group_id)
            if not success:
                raise ValueError(f"Group '{group_id}' not found")
            await db.commit()
            return _serialize({"deleted": True, "group_id": group_id})

    # ── Agent 邀请 ──

    async def invite_agent(self, project_id: str, agent_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = ProjectAgentService(db)
            pa = await svc.add_to_project(project_id, agent_id)
            await db.commit()
            return _serialize(pa.to_dict())

    async def list_project_agents(self, project_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = ProjectAgentService(db)
            agents = await svc.get_by_project(project_id)
            return _serialize([a.to_dict() for a in agents])

    # ── Group Member ──

    async def add_group_member(self, group_id: str, project_agent_id: str, role: str = "member") -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            member = await svc.add_member(group_id, project_agent_id, role)
            await db.commit()
            return _serialize(member.to_dict())

    async def list_group_members(self, group_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = GroupService(db)
            members = await svc.get_members(group_id)
            return _serialize([m.to_dict() for m in members])

    # ── Task ──

    async def create_task(
        self,
        group_id: str,
        title: str,
        description: str = "",
        assignee_id: Optional[str] = None,
        assignee_agent_name: Optional[str] = None,
        inherit_main_chain: bool = True,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建任务（v2 P2: 支持指定 assignee, lead 拆 task 时可直接指派给成员 agent）

        Args:
            group_id: 群聊ID
            title: 任务标题
            description: 任务描述
            assignee_id: 可选, project_agent_id (被指派的群成员)
            assignee_agent_name: 群成员 agent 的全名
            inherit_main_chain: 可选, 默认 True.
                True (默认): 任务链上下文继承主链截至分支点的历史,
                False (高敏感场景): task chain 完全隔离, 不读主链历史
            status: 可选, 默认 None (=todo)。
                传 "in_progress" 时, 创建后立即切 chain + 唤醒 assignee (一步到位)。
                等价于 create_task + update_task_status("in_progress") 两步合一,
                适用于需要立即启动的场景。

        v2 P2+: 同 group 内同 title 的 todo/in_progress task 视为重复, 直接返回已存在
        (避免 LLM 反复创建同名 task)
        """
        logger.info(
            "[create_task] called: group_id=%s, title=%s, assignee_agent_name=%s, "
            "inherit_main_chain=%s, status=%s",
            group_id, title, assignee_agent_name, inherit_main_chain, status,
        )
        if not group_id:
            return {"error": "create_task 工具调用错误: 缺少必填参数 'group_id'。请参考 schema 描述。"}
        if not title:
            return {"error": "create_task 工具调用错误: 缺少必填参数 'title'。请参考 schema 描述。"}
        if not assignee_id and not assignee_agent_name:
            return {
                "error": (
                    "create_task 工具调用错误: 缺少必填参数 'assignee_agent_name'。"
                    "请先调 list_group_members 查群成员, 然后传成员 agent 的全名。"
                )
            }

        # v2 P2+: 同 group 内同 title 的 todo/in_progress task 视为重复
        # （防 LLM 反复创建同名 task）
        async with self._session_factory() as db:
            from app.models.task import Task
            from sqlalchemy import select, and_
            existing_q = (
                select(Task)
                .where(
                    and_(
                        Task.group_id == group_id,
                        Task.title == title,
                        Task.status.in_(["todo", "in_progress"]),
                        Task.deleted_at.is_(None),
                    )
                )
            )
            existing = (await db.execute(existing_q)).scalars().first()
            if existing:
                return {
                    "success": True,
                    "id": existing.id,
                    "title": existing.title,
                    "status": existing.status,
                    "duplicate": True,
                    "message": (
                        f"已存在同标题的 task (id={existing.id}, status={existing.status}), "
                        "未重复创建, 请跳过本次 create_task。"
                    ),
                }

        # B2 加强: create_task 时如果 status="in_progress", 预检查同群是否已有 in_progress
        # （原 B2 只在 update_task_status 里检查, 但 create_task(status="in_progress")
        #  在并行工具调用下存在竞态——多个 create_task 同时执行都查到无 in_progress,
        #  于是都创建 task 并试图标 in_progress。提前到 create_task 开头检查, 缩小竞态窗口）
        if status == "in_progress":
            async with self._session_factory() as db:
                from sqlalchemy import select as _sel2, and_ as _and2
                from app.models.task import Task as TaskModel2
                existing_in_progress_q = (
                    _sel2(TaskModel2)
                    .where(_and2(
                        TaskModel2.group_id == group_id,
                        TaskModel2.status == "in_progress",
                        TaskModel2.deleted_at.is_(None),
                    ))
                )
                existing_in_progress = (await db.execute(existing_in_progress_q)).scalars().all()
                if existing_in_progress:
                    titles = " / ".join(t.title for t in existing_in_progress[:3])
                    return {
                        "error": (
                            f"群内任务必须串行, 同一时刻只允许 1 个 in_progress。"
                            f"当前群内已有 in_progress 任务: [{titles}]。"
                            f"请等当前任务被 assignee done 后, 系统唤醒你再创建下一个。"
                            f"不要反复重试, 不要自己 done 上一个任务。"
                        ),
                        "blocking_task_ids": [t.id for t in existing_in_progress],
                        "rule": "group_serial_in_progress",
                    }

        # v2 P2: 按 agent_name 查 project_agent_id
        resolved_assignee_id = assignee_id
        created_task_id: Optional[str] = None
        result: Dict[str, Any] = {}
        if not resolved_assignee_id and assignee_agent_name:
            async with self._session_factory() as db:
                from app.models.group import Group, GroupMember
                from app.models.agent import ProjectAgent, Agent
                from sqlalchemy import select
                from sqlalchemy.orm import selectinload
                # 加载 group 成员
                members_q = (
                    select(GroupMember)
                    .options(selectinload(GroupMember.project_agent).selectinload(ProjectAgent.agent))
                    .where(GroupMember.group_id == group_id)
                )
                members = (await db.execute(members_q)).scalars().all()
                # 找匹配的 agent
                matched = None
                for m in members:
                    if m.project_agent and m.project_agent.agent and m.project_agent.agent.name == assignee_agent_name:
                        matched = m.project_agent
                        break
                if matched is None:
                    return {
                        "error": (
                            f"create_task 工具调用错误: 指定的 assignee_agent_name "
                            f"'{assignee_agent_name}' 在该群成员中未找到。"
                            f"请先调 list_group_members 获取正确的 agent 全名。"
                        )
                    }
                resolved_assignee_id = matched.id
                # close this session, create a new one for the actual create
            # 重新开 session 创 task（避免长 session 持有 group 关系）
            async with self._session_factory() as db:
                svc = TaskService(db)
                try:
                    create_data = {
                        "title": title,
                        "description": description,
                        "inherit_main_chain": inherit_main_chain,
                        "status": "todo",
                    }
                    if resolved_assignee_id:
                        create_data["assignee_ids"] = [resolved_assignee_id]
                    # v2 P2: 自动回填 task.lead_agent_id = group.lead_agent.project_agent_id
                    # 这样 update_task_status 完成后, status=done 时可以自动唤醒 lead 继续推进
                    from app.models.group import Group
                    from app.models.agent import ProjectAgent
                    from sqlalchemy import select
                    from sqlalchemy.orm import selectinload
                    g = (await db.execute(
                        select(Group).options(selectinload(Group.lead_agent)).where(Group.id == group_id)
                    )).scalar_one_or_none()
                    if g and g.lead_agent_id:
                        create_data["lead_agent_id"] = g.lead_agent_id
                    task = await svc.create_task(group_id, create_data)
                    # v2 P2: 补建 task chain（结构性 metadata, 非状态推进）
                    # 之前 create_task 工具不建 chain, 后果: Task.chain=None → has_chain=False
                    # 现在所有 create_task 路径都建 chain, 与 create_task API 行为对齐
                    try:
                        from app.services.chat_service import ChatService
                        chat_svc = ChatService(self._session_factory)
                        g2 = (await db.execute(
                            select(Group).where(Group.id == group_id)
                        )).scalar_one_or_none()
                        if g2:
                            await chat_svc.create_task_chain(
                                db, g2, task.id,
                                # v2 P2+ 隐私修复: 不在主群写 task.title (title 经常含身份)
                                # 改用"任务创建"+ task_id 短前缀, 想看详情的 agent 调 get_task
                                request_content=f"任务创建: {task.id[:8]}",
                            )
                    except Exception as chain_err:
                        import logging
                        logging.getLogger(__name__).warning(
                            "create_task: 补建 task chain 失败 (task_id=%s): %s",
                            task.id, chain_err,
                        )
                    await db.commit()
                    created_task_id = task.id
                    result = {
                        "success": True,
                        "id": task.id,
                        "title": title,
                        "status": "todo",
                        "assignee_ids": [a.project_agent_id for a in (task.assignees or [])],
                        "lead_agent_id": task.lead_agent_id,
                        "assignee_resolved_from": "agent_name" if assignee_agent_name else None,
                        "next_step": "调 update_task_status(task_id, 'in_progress') 切 chain + 唤醒 assignee",
                    }
                except Exception as e:
                    return {"error": f"Failed to create task: {str(e)[:200]}"}

        # 普通路径: assignee_id 或无 assignee (仅当第一条路径未创建 task 时执行)
        if created_task_id is None:
            async with self._session_factory() as db:
                svc = TaskService(db)
                try:
                    create_data = {
                        "title": title,
                        "description": description,
                        "inherit_main_chain": inherit_main_chain,
                        "status": "todo",
                    }
                    if resolved_assignee_id:
                        create_data["assignee_ids"] = [resolved_assignee_id]
                    # v2 P2: 同样回填 lead_agent_id
                    from app.models.group import Group
                    from sqlalchemy import select
                    from sqlalchemy.orm import selectinload
                    g = (await db.execute(
                        select(Group).options(selectinload(Group.lead_agent)).where(Group.id == group_id)
                    )).scalar_one_or_none()
                    if g and g.lead_agent_id:
                        create_data["lead_agent_id"] = g.lead_agent_id
                    task = await svc.create_task(group_id, create_data)
                    # v2 P2: 补建 task chain（与 assign-by-name 路径行为一致）
                    try:
                        from app.services.chat_service import ChatService
                        chat_svc = ChatService(self._session_factory)
                        g2 = (await db.execute(
                            select(Group).where(Group.id == group_id)
                        )).scalar_one_or_none()
                        if g2:
                            await chat_svc.create_task_chain(
                                db, g2, task.id,
                                # v2 P2+ 隐私修复: 不在主群写 task.title (title 经常含身份)
                                # 改用"任务创建"+ task_id 短前缀, 想看详情的 agent 调 get_task
                                request_content=f"任务创建: {task.id[:8]}",
                            )
                    except Exception as chain_err:
                        import logging
                        logging.getLogger(__name__).warning(
                            "create_task (no-assignee path): 补建 task chain 失败 (task_id=%s): %s",
                            task.id, chain_err,
                        )
                    await db.commit()
                    created_task_id = task.id
                    result = {
                        "success": True,
                        "id": task.id,
                        "title": title,
                        "status": "todo",
                        "assignee_ids": [a.project_agent_id for a in (task.assignees or [])],
                        "lead_agent_id": task.lead_agent_id,
                        "next_step": "调 update_task_status(task_id, 'in_progress') 切 chain + 唤醒 assignee",
                    }
                except Exception as e:
                    return {"error": f"Failed to create task: {str(e)[:200]}"}

        # status="in_progress" 时, 创建后立即切 chain + 唤醒 assignee (一步到位)
        # 等价于 create_task(todo) + update_task_status("in_progress"), 避免两步调用
        if status == "in_progress" and created_task_id:
            handover_result = await self.update_task_status(created_task_id, "in_progress")
            if "error" not in handover_result:
                result["status"] = "in_progress"
                result.pop("next_step", None)
                result["handover"] = "chain 已切换, assignee 已唤醒"
            else:
                # handover 失败 (如群内串行守卫拦截), task 仍以 todo 状态存在
                result["handover_error"] = handover_result["error"]
                result["next_step"] = "稍后调 update_task_status(task_id, 'in_progress') 重试切 chain"

        return result

    async def list_tasks(self, group_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = TaskService(db)
            tasks = await svc.get_by_group(group_id)
            return _serialize([t.to_dict() for t in tasks])

    async def update_task_status(self, task_id: str, status: str, result: str = "") -> Dict[str, Any]:
        """
        更新任务状态（外部入口, 加锁串行化, 防止 B2 TOCTOU 竞态）

        AllModelPlugin 并行工具调用下, 多个 create_task(status="in_progress") 会
        并行触发各自的 update_task_status("in_progress"), 各自独立 session 查询同群
        in_progress 时都查到空 (因为其他 task 还没 commit), 全部通过 B2 检查 →
        同群出现多个 in_progress 任务, 破坏串行约束.

        修复: 用 asyncio.Lock 串行化整个 update_task_status. 第一个调用完整提交后,
        后续调用才进入临界区, 此时再查同群 in_progress 就能看到刚提交的 task, B2 拦截.

        实际执行委托给 _update_task_status_impl.
        """
        async with self._get_task_lock():
            return await self._update_task_status_impl(task_id, status, result=result)

    async def _update_task_status_impl(self, task_id: str, status: str, result: str = "") -> Dict[str, Any]:
        """
        更新任务状态的实际实现（v2 P2: 任务接管主链核心机制 + 事件驱动, 不再直接唤起 agent）

        状态流转（与 TaskService.update_status 保持一致）:
          todo        -> in_progress / done
          in_progress -> done
          done        -> reopened
          reopened    -> in_progress / done

        可选参数 result:
          - 仅 status=done 时生效
          - 简短描述（一两句话），会作为一条 system 消息挂载到主链
          - task chain 里的过程不会泄露到主链，只有 result 会被看到
          - 不传则只挂"任务完成"事件本身
          - 写小说/生成长内容等场景：传资源标题/字数/章节号等关键信息
          - 轻量场景：传简短状态即可

        v2 P2 任务接管主链（核心机制）:
          - in_progress 时: 主链 status="paused", task chain status="active" (接管)
          - done 时: task chain 折叠成 summary packet 挂回主链,
                     task chain status="archived", 主链 status="active" (恢复)
          - 整个 group 同一时刻只有 0 或 1 个 status="active" 的 chain
          - 派发路径（send_message / chat send / event_dispatcher 唤起 session）
            统一调 get_active_chain_for_group, 不再硬编码 group chain

        v2 P2 群内串行守卫:
          - 群内任务必须串行（同一时刻只允许 1 个 in_progress）
          - 如果要标 in_progress, 但同群已有其他 in_progress 任务, 返回 error, 不变更
        """
        if not task_id:
            return {"error": "update_task_status 工具调用错误: 缺少必填参数 'task_id'。请参考 schema 描述。"}
        if not status:
            return {"error": "update_task_status 工具调用错误: 缺少必填参数 'status'。请参考 schema 描述。"}
        if status not in ("todo", "in_progress", "done", "reopened"):
            return {"error": f"update_task_status 工具调用错误: status 非法值 '{status}'。必须是: todo, in_progress, done, reopened"}
        async with self._session_factory() as db:
            svc = TaskService(db)
            try:
                # 1) 先取出当前 task, 拿到 group_id
                task = await svc.get_detail(task_id)
                if task is None:
                    return {"error": f"Task '{task_id}' not found"}

                # 2) 群内串行守卫: 标 in_progress 前, 检查同群是否有其他 in_progress
                if status == "in_progress":
                    from sqlalchemy import select, and_
                    from app.models.task import Task as TaskModel
                    other_in_progress_q = (
                        select(TaskModel)
                        .where(and_(
                            TaskModel.group_id == task.group_id,
                            TaskModel.id != task_id,
                            TaskModel.status == "in_progress",
                            TaskModel.deleted_at.is_(None),
                        ))
                    )
                    other_in_progress = (await db.execute(other_in_progress_q)).scalars().all()
                    if other_in_progress:
                        titles = " / ".join(t.title for t in other_in_progress[:3])
                        return {
                            "error": (
                                f"群内任务必须串行, 同一时刻只允许 1 个 in_progress。"
                                f"当前群内已有 in_progress 任务: [{titles}]。"
                                f"请等当前任务被 assignee done 后（系统会自动唤醒你）, "
                                f"再标本 task 为 in_progress。不要自己代为 done 上一个任务。"
                            ),
                            "blocking_task_ids": [t.id for t in other_in_progress],
                            "rule": "group_serial_in_progress",
                        }

                # B4: assignee 权限配套——done 只能由 assignee 自己改
                # 指定了 assignee 的任务，lead 不能代为 done（防止法官抢先 done 玩家任务）
                # 注意：直接查 task_assignees 表，不依赖 task.assignees lazy load
                # （v4 测试发现 task.assignees 关系在某些路径下未加载，导致 B4 漏拦截）
                if status == "done" and getattr(self, '_current_agent_id', None):
                    caller_agent_id = self._current_agent_id
                    from app.models.task import TaskAssignee
                    from sqlalchemy import select as _sel
                    assignee_pa_ids = [
                        row[0] for row in
                        (await db.execute(
                            _sel(TaskAssignee.project_agent_id).where(TaskAssignee.task_id == task_id)
                        )).all()
                    ]
                    if assignee_pa_ids:
                        from app.models.agent import ProjectAgent
                        caller_pa_q = (
                            _sel(ProjectAgent.id)
                            .where(
                                ProjectAgent.id.in_(assignee_pa_ids),
                                ProjectAgent.agent_id == caller_agent_id,
                            )
                        )
                        caller_is_assignee = (await db.execute(caller_pa_q)).first() is not None
                        if not caller_is_assignee:
                            return {
                                "error": (
                                    "该任务已指派给其他成员负责，你不能代为 done。"
                                    "请等负责人自己 done（系统会自动唤醒你处理 result）。"
                                ),
                                "rule": "assignee_only_done",
                            }

                # 群级开关: 跳过 deliverable 存在性检查
                #   bypass_deliverable_required=True 时, 允许 done 不带 deliverable
                #   (适用: 群 description 写"必出 deliverable"但 agent 工作流是写资源)
                bypass = False
                if status == "done":
                    from app.models.group import Group as GroupModel
                    bypass_q = _sel_d(GroupModel).where(GroupModel.id == task.group_id)
                    group_row = (await db.execute(bypass_q)).scalar_one_or_none()
                    bypass = bool(group_row and group_row.bypass_deliverable_required)

                # P0 修复 (Bug 2: update_task_status(done) 强制检查 deliverable 存在)
                # 业务闭环: 任务"完成"必须有可交付资源 (deliverable/resource)
                # 否则: 任务会被错误标 done 但实际没产物 → 下游依赖任务无法拿到资源 → 全链路卡住
                # 这里检查最严格的口径: Deliverable 表里有 task_id=task_id 且未删除的记录
                # 群级开关 bypass_deliverable_required=True 时跳过此检查 (见上)
                if status == "done" and not bypass:
                    from app.models.deliverable import Deliverable
                    from sqlalchemy import select as _sel_d, and_ as _and_d
                    deliverable_q = _sel_d(Deliverable).where(_and_d(
                        Deliverable.task_id == task_id,
                        Deliverable.deleted_at.is_(None),
                    ))
                    has_deliverable = (await db.execute(deliverable_q)).scalar_one_or_none() is not None
                    if not has_deliverable:
                        return {
                            "error": (
                                "P0 强制约束: 任务 done 前必须先创建 deliverable 资源。\n"
                                "请先用 create_deliverable(group_id, title, content) 工具落地成果，"
                                "或用 write_resource 写入资源（会自动归属到本任务的 deliverable）。\n"
                                "规则: 任务完成 = 实际产物落地，没有产物的任务不算完成。"
                            ),
                            "rule": "deliverable_required_for_done",
                            "task_id": task_id,
                        }

                # 3) 真正更新状态
                task = await svc.update_status(task_id, status)
                if task is None:
                    return {"error": f"Task '{task_id}' not found"}

                # 4) v2 P2+ 统一服务路径: chain 流转 + 事件发布 收敛到
                #    ChainHandoverService.apply_task_status_transition
                #    (REST API 与 agent 工具共用同一条路径, 行为不再分裂)
                from app.services.chain_handover_service import ChainHandoverService
                handover_svc = ChainHandoverService(db)
                transition = await handover_svc.apply_task_status_transition(
                    task, status, result=result,
                )

                # 5) commit (apply_task_status_transition 内部 flush 但没 commit)
                await db.commit()

                return {
                    "success": True,
                    "id": task.id,
                    "status": status,
                    "assignee_ids": [a.project_agent_id for a in (task.assignees or [])],
                    "result_mounted": bool(status == "done"),
                    "result": result if status == "done" else None,
                    "action": transition.get("action"),
                    "task_chain_id": transition.get("task_chain_id"),
                    "note": "P2+: 统一服务路径 (ChainHandoverService.apply_task_status_transition)。通知已由 EventDispatcher 处理。",
                }
            except Exception as e:
                return {"error": f"Failed to update task: {str(e)[:200]}"}

    async def _mount_task_result_to_main_chain(self, db, task: Any, result: str = "") -> None:
        """
        [已废弃] v2 P2 起由 ChainHandoverService.fold_task_chain_to_main 替代。
        保留此方法仅为兼容旧调用方, 内部直接调用新服务。
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "_mount_task_result_to_main_chain is deprecated, use ChainHandoverService.fold_task_chain_to_main"
        )
        from app.services.chain_handover_service import ChainHandoverService
        from app.models.chain import Chain as ChainModel
        from sqlalchemy import select
        task_chain = (await db.execute(
            select(ChainModel).where(
                ChainModel.task_id == task.id,
                ChainModel.chain_type == "task",
                ChainModel.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if task_chain:
            handover = ChainHandoverService(db)
            await handover.fold_task_chain_to_main(task, task_chain, summary_content=result)

    # ── Deliverable ──

    async def create_deliverable(self, group_id: str, title: str, content: str = "", scope: str = "project") -> Dict[str, Any]:
        import logging
        logger = logging.getLogger(__name__)

        if not group_id:
            return {"error": "group_id is required"}
        if not title:
            return {"error": "title is required"}

        async with self._session_factory() as db:
            svc = DeliverableService(db)
            try:
                deliverable = await svc.create_deliverable({
                    "group_id": group_id,
                    "title": title,
                    "content": content,
                    "scope": scope,
                })
                await db.commit()
                return {"success": True, "id": deliverable.id, "title": title, "scope": scope}
            except Exception as e:
                logger.warning(f"create_deliverable failed: {e}")
                return {"error": f"Failed to create deliverable: {str(e)[:200]}"}

    async def list_deliverables(self, group_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = DeliverableService(db)
            deliverables = await svc.get_by_group(group_id)
            return _serialize([d.to_dict() for d in deliverables])

    # ── Packet ──

    async def send_message(self, group_id: str, content: str) -> Dict[str, Any]:
        import logging
        logger = logging.getLogger(__name__)

        async with self._session_factory() as db:
            from sqlalchemy import select, and_
            from app.models.chain import Chain, Packet
            from app.models.group import Group

            # v2 P1: 先校验 group 是否存在
            group = (await db.execute(
                select(Group).where(Group.id == group_id)
            )).scalar_one_or_none()
            if group is None:
                raise ValueError(
                    f"send_message failed: group '{group_id[:8]}...' 不存在。"
                    f"请用 list_groups 获取正确 group_id，不要猜测或记忆旧项目的 ID。"
                )

            # auto-activate pending group so后续 agent 调度能跑
            was_pending = group.status == "pending"
            if was_pending:
                group.status = "active"
                logger.info("send_message: auto-activated group '%s' (%s)", group.name, group_id[:8])
                await db.flush()

            # P0 修复 (Bug 1: send_message 冷启动死循环):
            #   之前只看 chain_type="group" + status="active" 的根链,
            #   当 task in_progress 触发 handover 把主链置为 paused 时,
            #   找不到 group 根链, send_message 抛 "无活跃链" 失败.
            #   实际意图: send_message 应该写到"群当前 active chain"——可能是
            #   主链(无 task 接管时)也可能是 task chain(有 task 接管时).
            #   改用 ChainHandoverService.get_active_chain_for_group 统一找活跃链,
            #   与 chat_service._get_or_create_chain 的语义保持一致.
            from app.services.chain_handover_service import ChainHandoverService
            handover = ChainHandoverService(db)
            chain = await handover.get_active_chain_for_group(group_id)
            if chain is None:
                # 没有活跃链: 兜底创建/恢复主链 (与 _get_or_create_chain 行为一致)
                chain = await handover.get_or_create_main_chain(group_id)
                if chain.status == "paused":
                    chain.status = "active"
                    chain.completed_at = None
                    logger.info(
                        "send_message: 兜底恢复 paused 主链 → active, group=%s chain=%s",
                        group_id[:8], chain.id[:8],
                    )
                    await db.flush()

            if chain is None:
                raise ValueError(
                    f"send_message failed: group '{group.name}' 无活跃链且无法创建。"
                    f"请确认该群已激活 (status=active)。"
                )

            prev_result = await db.execute(
                select(Packet)
                .where(and_(Packet.chain_id == chain.id, Packet.deleted_at.is_(None)))
                .order_by(Packet.created_at.desc())
                .limit(1)
            )
            last_packet = prev_result.scalar_one_or_none()

            # 用真实 agent 身份写入 sender, 让群聊历史能区分发言者 (agent.py _packet_to_message 依赖 sender_name 加前缀)
            real_agent_id = getattr(self, '_current_agent_id', None) or "agent"
            real_agent_name = getattr(self, '_current_agent_name', None) or "Agent"
            packet = Packet(
                chain_id=chain.id,
                prev_packet_id=last_packet.id if last_packet else None,
                packet_type="agent_text",
                sender_type="agent",
                sender_id=real_agent_id,
                sender_name=real_agent_name,
                content=content,
                content_type="text",
            )
            db.add(packet)

            if not chain.head_packet_id:
                chain.head_packet_id = packet.id
            chain.tail_packet_id = packet.id
            chain.packet_count = (chain.packet_count or 0) + 1

            await db.commit()
            await db.refresh(packet)

            # 广播 send_message 的消息到目标群的 WebSocket，让前端实时看到
            try:
                from app.orchestrator.websocket_manager import ws_manager
                await ws_manager.broadcast(str(group_id), {
                    "type": "agent_message",
                    "payload": {
                        "chain_id": chain.id,
                        "sender_id": real_agent_id,
                        "sender_name": real_agent_name,
                        "content": content,
                        "metadata": {"packet_id": packet.id},
                    },
                })
            except Exception as ws_err:
                logger.debug("send_message: ws broadcast of incoming msg failed: %s", ws_err)

            # *** 同步模式：等待目标群 lead_agent 响应后返回 ***
            # send_message 是跨群发消息（不是当前 dispatch 群）。
            # 目标群 lead_agent 被同步 dispatch 处理这条新消息。
            # 如果 content 含 @X 提及，额外 fire-and-forget 触发 @X 在该群被 dispatch。
            # LLM 自己用"输出文字"在当前 dispatch 群说话；send_message 用来发到其他群。

            # self-trigger 检查：sender == 目标群 lead_agent → 跳过 lead 触发
            is_self_lead = False
            sender_id = self._current_agent_id
            if sender_id:
                try:
                    from app.models.agent import ProjectAgent
                    from sqlalchemy import select as sa_select
                    pa = (await db.execute(
                        sa_select(ProjectAgent).where(ProjectAgent.id == group.lead_agent_id)
                    )).scalar_one_or_none() if group.lead_agent_id else None
                    if pa and pa.agent_id == sender_id:
                        is_self_lead = True
                except Exception as e:
                    logger.debug("self-trigger check failed in send_message: %s", e)

            target_response = {"status": "ok", "sender_name": "", "content": "", "tool_calls_made": []}
            if is_self_lead:
                logger.info("send_message: 跳过 self-trigger (sender == lead), group=%s", group_id[:8])
            else:
                target_response = await self._dispatch_target_group_sync(
                    group_id=group_id,
                    content=content,
                    chain_id=chain.id,
                )

            return _serialize({
                "status": target_response.get("status", "ok"),
                "packet_id": packet.id,
                "group_id": group_id,
                "group_name": group.name,
                "target_response": target_response.get("content", ""),
                "target_sender_name": target_response.get("sender_name", ""),
                "target_tool_calls": target_response.get("tool_calls_made", []),
                "error": target_response.get("error", ""),
                "message": "消息已发送, 目标 agent 已响应",
            })

    async def _dispatch_target_group_sync(
        self,
        group_id: str,
        content: str,
        chain_id: str,
    ) -> Dict[str, Any]:
        """
        同步触发目标群 lead_agent 响应，等待其完成后返回结果。
        同时将响应广播到目标群的 WebSocket，让前端实时看到。

        返回：
        {
            "status": "ok" | "error",
            "sender_name": "<目标 agent 名称>",
            "content": "<目标 agent 回复内容>",
            "tool_calls_made": ["set_memory", "send_message"],
            "error": "..." (status=error 时)
        }
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            from app.orchestrator.message_dispatcher import MessageDispatcher
            from app.orchestrator.websocket_manager import ws_manager

            dispatcher = MessageDispatcher(self._session_factory)

            # 构建 on_message 回调：将目标 agent 的响应实时广播到目标群的 WebSocket
            async def on_message(message: dict):
                await ws_manager.broadcast(group_id, message)

            async def on_typing(agent_id: str, agent_name: str):
                await ws_manager.broadcast(group_id, {
                    "type": "agent_typing",
                    "payload": {
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                    },
                })

            response = await dispatcher.dispatch(
                chain_id=chain_id,
                user_message=content,
                on_message=on_message,
                on_typing=on_typing,
                skip_user_message_save=True,
            )
            logger.info(
                "_dispatch_target_group_sync: group=%s chain=%s status=%s sender=%s content_preview=%s",
                group_id[:8], chain_id[:8],
                response.get("status", "?"),
                response.get("sender_name", "?"),
                (response.get("content", "") or "")[:80],
            )
            return response
        except Exception as e:
            logger.exception("send_message: sync dispatch failed for group %s: %s", group_id[:8], e)
            return {
                "status": "error",
                "error": str(e)[:200],
                "sender_name": "",
                "content": "",
                "tool_calls_made": [],
            }

    # ── Memory ──

    async def set_memory(
        self,
        agent_id: str,
        project_id: str,
        content: str,
        slug: str = "default",
        tags: Optional[List[str]] = None,
        mode: str = "replace",
        find: Optional[str] = None,
        replace_with: Optional[str] = None,
        section_heading: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        创建或更新 Agent 笔记（按 slug 分类）

        mode 参数控制更新策略：
        - "replace": 全量替换 content（默认，兼容旧用法）
        - "append": 追加到已有内容末尾
        - "replace_globally": 全文查找替换，需配合 find + replace_with
        - "rewrite_section": 按 Markdown 标题替换整个 section，需配合 section_heading

        标准 slug：
        - decisions / watchouts / state_snapshot / references / open_questions / group_focus
        """
        # B6: slug 规范化——连字符转下划线（LLM 常把 game_state 写成 game-state）
        slug = (slug or "default").replace('-', '_')
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "[set_memory] CALLED: agent_id=%s project_id=%s slug=%s mode=%s content_preview=%s",
            agent_id[:8] if agent_id else "NONE",
            project_id[:8] if project_id else "NONE",
            slug,
            mode,
            (content or "")[:100],
        )
        async with self._session_factory() as db:
            svc = MemoryService(db)
            memory = await svc.upsert(
                agent_id, project_id, content, tags, slug,
                mode=mode, find=find, replace_with=replace_with, section_heading=section_heading,
            )
            await db.commit()
            result = _serialize(memory.to_dict())
            logger.info(
                "[set_memory] DONE: id=%s slug=%s mode=%s",
                result.get("id", "?")[:8] if result.get("id") else "?",
                slug,
                mode,
            )
            return result

    # 向后兼容别名
    async def create_memory(self, **kwargs) -> Dict[str, Any]:
        """向后兼容：create_memory → set_memory(mode='replace')"""
        return await self.set_memory(**kwargs)

    async def get_memory(
        self,
        agent_id: str,
        project_id: str,
        slug: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """获取 Agent 笔记（按 slug）"""
        # B6: slug 规范化——与 set_memory 保持一致
        slug = (slug or "default").replace('-', '_')
        async with self._session_factory() as db:
            svc = MemoryService(db)
            memory = await svc.get_by_agent_and_project(agent_id, project_id, slug)
            if memory is None:
                return None
            return _serialize(memory.to_dict())

    async def list_memories(
        self,
        agent_id: str,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """列出 Agent 在项目下的所有笔记（按 slug）"""
        async with self._session_factory() as db:
            svc = MemoryService(db)
            memories = await svc.list_by_agent_and_project(agent_id, project_id)
            return _serialize([m.to_dict() for m in memories])

    # ── v2 P1: 原子能力（系统给能力, skill 决定怎么用） ──

    async def query_activity(self, project_id: str) -> Dict[str, Any]:
        """
        原子能力：查询项目活动状态（v2 §0.5 原则 6）

        返回:
          - last_message_at: 最近一条消息时间
          - last_tool_call_at: 最近一次工具调用时间
          - active_agent_ids: 最近 60s 活跃的 agent id 列表
          - pending_tool_calls: 进行中的 tool call 数
          - idle_seconds: 项目空闲时长（秒）

        用法:
          - agent 自由决定"什么时候调"（skill 写"如果 60s 无活动就调"）
          - 拿到结果后自己决定下一步（ping? send_message? 不动作?）
        """
        from datetime import timedelta
        from sqlalchemy import select, and_, func
        from app.models.chain import Chain, Packet
        from app.models.group import Group

        threshold = datetime.utcnow() - timedelta(seconds=60)
        async with self._session_factory() as db:
            # 先取项目下所有 group_id
            grp_q = select(Group.id).where(
                and_(Group.project_id == project_id, Group.deleted_at.is_(None))
            )
            group_ids = [r[0] for r in (await db.execute(grp_q)).all()]
            if not group_ids:
                return {
                    "project_id": project_id,
                    "last_message_at": None,
                    "last_tool_call_at": None,
                    "active_agent_ids": [],
                    "active_agent_count": 0,
                    "recent_message_count": 0,
                    "pending_tool_calls": 0,
                    "idle_seconds": 0,
                }

            # 1. 最近 60s 的消息
            recent_msgs_q = (
                select(Packet.sender_id, Packet.sender_name, Packet.sender_type, Packet.created_at)
                .where(and_(
                    Packet.chain_id.in_(
                        select(Chain.id).where(Chain.group_id.in_(group_ids), Chain.deleted_at.is_(None))
                    ),
                    Packet.deleted_at.is_(None),
                    Packet.created_at > threshold,
                ))
                .order_by(Packet.created_at.desc())
                .limit(50)
            )
            recent_msgs = (await db.execute(recent_msgs_q)).all()
            active_agent_ids = list({m.sender_id for m in recent_msgs if m.sender_type == "agent"})

            # 2. 项目最近一条消息
            last_msg_q = (
                select(Packet.created_at)
                .where(and_(
                    Packet.chain_id.in_(
                        select(Chain.id).where(Chain.group_id.in_(group_ids), Chain.deleted_at.is_(None))
                    ),
                    Packet.deleted_at.is_(None),
                ))
                .order_by(Packet.created_at.desc())
                .limit(1)
            )
            last_msg_row = (await db.execute(last_msg_q)).first()
            last_message_at = last_msg_row[0] if last_msg_row else None

            # 3. 最近一次工具调用
            tc_q = (
                select(Packet.metadata_json, Packet.created_at)
                .where(and_(
                    Packet.chain_id.in_(
                        select(Chain.id).where(Chain.group_id.in_(group_ids), Chain.deleted_at.is_(None))
                    ),
                    Packet.deleted_at.is_(None),
                    Packet.metadata_json.isnot(None),
                ))
                .order_by(Packet.created_at.desc())
                .limit(50)
            )
            tc_rows = (await db.execute(tc_q)).all()
            last_tool_call_at = None
            for row in tc_rows:
                meta = row[0] or {}
                if isinstance(meta, dict) and meta.get("tool_calls"):
                    last_tool_call_at = row[1]
                    break

            # 4. 空闲时长
            now = datetime.utcnow()
            idle_seconds = int((now - last_message_at).total_seconds()) if last_message_at else 0

            return {
                "project_id": project_id,
                "group_count": len(group_ids),
                "last_message_at": last_message_at.isoformat() if last_message_at else None,
                "last_tool_call_at": last_tool_call_at.isoformat() if last_tool_call_at else None,
                "active_agent_ids": active_agent_ids,
                "active_agent_count": len(active_agent_ids),
                "recent_message_count": len(recent_msgs),
                "pending_tool_calls": 0,
                "idle_seconds": idle_seconds,
            }

    async def ping(
        self,
        group_id: str,
        to_agent_id: Optional[str] = None,
        reason: str = "ping",
        context: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        原子能力：系统/agent 给指定 agent 发"催促"（v2 §0.5 原则 6）

        行为:
          - 在群聊里发一条 sender_type=system, sender_id='ping_origin' 的消息
          - 内容是 ping 提示（reason + context + 候选 agent）
          - LLM 收到后按自己 skill 决定怎么响应

        关键:
          - **不**自动调 update_task_status / update_group
          - **不**改任何状态
          - 只是发消息, 让 agent 自己决定
        """
        ctx = context or {}
        if message is None:
            message = (
                f"[ping]\n"
                f"原因: {reason}\n"
                f"上下文: {ctx}\n"
                f"目标 agent: {to_agent_id or '(群内任意 lead)'}\n\n"
                f"请按你的 skill 决定如何响应。"
            )
        # 直接调 send_message, 发到群里
        return await self.send_message(
            group_id=group_id,
            content=message,
        )

    async def subscribe_event(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        原子能力：订阅事件（v2 §0.5 原则 6）

        行为:
          - 注册订阅：event_type 在 (project_id, group_id) 范围内发生时通知 subscriber
          - target_agent_id 不传时 = subscriber_agent_id（默认通知订阅者自己）
          - 由 EventDispatcher 在事件 fire 时: 写 system packet + 启动新 session
          - 同一 (subscriber, event_type) 60s 冷却一次（防重复打扰）

        支持事件:
          - "task_status_changed"
          - "resource_created"
          - "resource_updated"
          - "group_status_changed"
        """
        if not event_type:
            return {"error": "subscribe_event 工具调用错误: 缺少必填参数 'event_type'。请参考 schema 描述。"}
        if not project_id:
            return {"error": "subscribe_event 工具调用错误: 缺少必填参数 'project_id'。请参考 schema 描述。"}
        if not subscriber_agent_id:
            return {"error": "subscribe_event 工具调用错误: 缺少必填参数 'subscriber_agent_id'。请传你自己的 agent id。"}
        if target_agent_id is None:
            target_agent_id = subscriber_agent_id  # 默认通知自己

        from app.services.event_bus import event_bus
        await event_bus.subscribe(
            event_type=event_type,
            subscriber_agent_id=subscriber_agent_id,
            project_id=project_id,
            group_id=group_id,
        )
        return {
            "success": True,
            "event_type": event_type,
            "subscriber_agent_id": subscriber_agent_id,
            "target_agent_id": target_agent_id,
            "project_id": project_id,
            "group_id": group_id,
            "note": "P2 内存订阅（重启会丢）。EventDispatcher 会按默认通知策略唤醒 target_agent_id。",
        }

    async def unsubscribe_event(
        self,
        event_type: str,
        subscriber_agent_id: str,
        project_id: str,
        group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        原子能力：取消订阅
        """
        from app.services.event_bus import event_bus
        removed = await event_bus.unsubscribe(
            event_type=event_type,
            subscriber_agent_id=subscriber_agent_id,
            project_id=project_id,
            group_id=group_id,
        )
        return {
            "success": True,
            "removed": removed,
            "event_type": event_type,
            "subscriber_agent_id": subscriber_agent_id,
        }

    async def list_subscriptions(
        self,
        subscriber_agent_id: str,
    ) -> List[Dict[str, Any]]:
        """
        原子能力：列出某 agent 的所有订阅（调试/查看用）
        """
        from app.services.event_bus import event_bus
        return await event_bus.list_subscriptions(subscriber_agent_id)

    # ── Resource ──

    async def read_resource(self, resource_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = ResourceService(db)
            resource = await svc.get_by_id(resource_id)
            if resource is None:
                raise ValueError(f"Resource '{resource_id}' not found")
            return _serialize(resource.to_dict())

    async def write_resource(
        self,
        project_id: str,
        title: str,
        content: str,
        resource_type: str = "note",
        content_type: Optional[str] = None,
        group_id: Optional[str] = None,
        is_required: bool = False,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        import logging
        logger = logging.getLogger(__name__)

        if not project_id:
            return {"error": "project_id is required"}
        if not title:
            return {"error": "title is required"}
        if not content:
            return {"error": "content is required"}

        # 兜底：LLM 不传 tags 时基于 title 关键词智能补全
        if not tags:
            tags = _infer_tags_from_title(title, resource_type, content)

        # 兜底：LLM 不传 group_id 时尝试从 _current_group_id 上下文注入
        if not group_id:
            group_id = getattr(self, "_current_group_id", None)
            if group_id:
                logger.debug(
                    "[write_resource] LLM omitted group_id, auto-injected from context: %s",
                    group_id[:8],
                )

        # v2 P1: 资源归入文件夹（自动）
        parent_id = await self._auto_locate_folder(
            project_id=project_id,
            group_id=group_id,
            title=title,
            resource_type=resource_type,
        )

        # v2 P2: 自动挂 task_id = 群内当前 in_progress 任务（被动关联, 非状态推进）
        # 之前 write_resource 不挂 task_id, 后果: Task.has_deliverable 永远 False
        # 现在找群内 in_progress 任务（仅 1 个, 群内串行约束保证）, 挂到它的 task_id
        # LLM 也可以显式传 task_id 覆盖（虽然 schema 里没暴露, 这里支持内部覆盖）
        resolved_task_id = None
        if group_id:
            try:
                from app.models.task import Task as TaskModel
                from sqlalchemy import select, and_
                async with self._session_factory() as db2:
                    active_q = (
                        select(TaskModel)
                        .where(and_(
                            TaskModel.group_id == group_id,
                            TaskModel.status == "in_progress",
                            TaskModel.deleted_at.is_(None),
                        ))
                        .order_by(TaskModel.created_at.desc())
                        .limit(1)
                    )
                    active = (await db2.execute(active_q)).scalars().first()
                    if active:
                        resolved_task_id = active.id
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("write_resource 查 active task 失败: %s", e)

        async with self._session_factory() as db:
            svc = ResourceService(db)
            # content_type 是存储格式，不是显示格式
            # agent 可能传入 render view 类型（如 "document"），需要映射为存储格式
            _STORAGE_TYPES = {"markdown", "json", "map", "text"}
            if content_type not in _STORAGE_TYPES:
                content_type = "map" if resource_type == "map" else "markdown"

            # Upsert 逻辑：避免 LLM 重复写入相同 title 导致资源重复
            # 匹配规则：同 project + 同 group + 同 title → 视为更新，否则创建
            try:
                from sqlalchemy import select, and_
                from app.models.resource import Resource
                where_clauses = [
                    Resource.project_id == project_id,
                    Resource.title == title,
                    Resource.deleted_at.is_(None),
                ]
                if group_id:
                    where_clauses.append(Resource.group_id == group_id)
                else:
                    where_clauses.append(Resource.group_id.is_(None))
                existing = (await db.execute(
                    select(Resource).where(and_(*where_clauses)).limit(1)
                )).scalar_one_or_none()

                if existing:
                    # 更新已存在资源
                    update_data = {
                        "content": content,
                        "content_type": content_type,
                        "type": resource_type,
                        "tags": tags,
                    }
                    if is_required:
                        update_data["is_required"] = is_required
                    if parent_id:
                        update_data["parent_id"] = parent_id
                    if resolved_task_id:
                        update_data["task_id"] = resolved_task_id
                    resource = await svc.update_resource(existing.id, update_data)
                    await db.commit()
                    # v2 P2: 发 resource_updated 事件
                    try:
                        from app.services.event_bus import event_bus
                        await event_bus.publish(
                            "resource_updated",
                            {
                                "resource_id": str(resource.id),
                                "project_id": str(project_id),
                                "group_id": str(group_id) if group_id else None,
                                "title": title,
                                "resource_type": resource_type,
                                "tags": tags or [],
                            },
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning("publish resource_updated failed: %s", e)
                    return {
                        "success": True, "id": resource.id, "title": title,
                        "content_type": content_type, "tags": tags,
                        "parent_id": resource.parent_id,
                        "action": "updated",
                    }
                else:
                    resource = await svc.create_resource({
                        "project_id": project_id,
                        "group_id": group_id,
                        "parent_id": parent_id,
                        "task_id": resolved_task_id,
                        "title": title,
                        "content": content,
                        "type": resource_type,
                        "content_type": content_type,
                        "tags": tags,
                        "is_required": is_required,
                        "created_by": "agent",
                    })
                    await db.commit()
                    # v2 P2: 发 resource_created 事件
                    try:
                        from app.services.event_bus import event_bus
                        await event_bus.publish(
                            "resource_created",
                            {
                                "resource_id": str(resource.id),
                                "project_id": str(project_id),
                                "group_id": str(group_id) if group_id else None,
                                "title": title,
                                "resource_type": resource_type,
                                "tags": tags or [],
                            },
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning("publish resource_created failed: %s", e)
                    return {
                        "success": True, "id": resource.id, "title": title,
                        "content_type": content_type, "tags": tags,
                        "parent_id": resource.parent_id,
                        "action": "created",
                    }
            except Exception as e:
                logger.warning(f"write_resource failed: {e}")
                return {"error": f"Failed to create/update resource: {str(e)[:200]}"}

    async def _auto_locate_folder(
        self,
        project_id: str,
        group_id: Optional[str],
        title: str,
        resource_type: str,
    ) -> Optional[str]:
        """
        v2 P1: 资源自动归入文件夹。

        策略:
        1. 如果资源是 group 级（group_id 不为空） → 找/建该 group 对应的文件夹
        2. 如果资源是 project 级（group_id 为空） → 不归入 group 文件夹，留作顶级

        命名规则: 文件夹 title = "<group_name>📁" 或 "项目资源📁"
        """
        from sqlalchemy import select, and_
        from app.models.resource import Resource
        from app.models.group import Group
        from app.services.resource_service import ResourceService

        if not group_id:
            # 项目级资源不归入任何 group 文件夹
            return None

        async with self._session_factory() as db:
            # 取 group name
            grp = (await db.execute(
                select(Group).where(Group.id == group_id)
            )).scalar_one_or_none()
            if not grp:
                return None
            folder_name = f"📁 {grp.name}"

            # 找/建文件夹
            existing_folder = (await db.execute(
                select(Resource).where(and_(
                    Resource.project_id == project_id,
                    Resource.group_id == group_id,
                    Resource.is_folder == True,
                    Resource.title == folder_name,
                    Resource.deleted_at.is_(None),
                ))
            )).scalar_one_or_none()

            if existing_folder:
                return existing_folder.id

            # 创建文件夹
            svc = ResourceService(db)
            folder = await svc.create_resource({
                "project_id": project_id,
                "group_id": group_id,
                "is_folder": True,
                "title": folder_name,
                "content": f"# {folder_name}\n\n本文件夹自动归入本群产出的资源。",
                "type": "custom",  # 避开 type check 约束（folder 用 is_folder=True 标识）
                "content_type": "markdown",
                "tags": ["folder", "auto-generated"],
                "is_required": False,
                "created_by": "system",
            })
            await db.commit()
            return folder.id

    async def search_resources(self, project_id: str, query: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            from sqlalchemy import select, and_
            from app.models.resource import Resource
            stmt = select(Resource).where(
                and_(
                    Resource.project_id == project_id,
                    Resource.deleted_at.is_(None),
                    Resource.content.ilike(f"%{query}%"),
                )
            )
            result = await db.execute(stmt)
            resources = list(result.scalars().all())
            return _serialize([r.to_dict() for r in resources])

    # ── Agent Skill ──

    async def list_agent_skills(self, agent_id: str) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            repo = AgentSkillRepository(db)
            skills = await repo.get_skills_by_agent(agent_id)
            return _serialize([s.to_dict() for s in skills])

    async def read_agent_skill(self, agent_id: str, skill_name: str, file_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        async with self._session_factory() as db:
            repo = AgentSkillRepository(db)
            skills = await repo.get_skills_by_agent(agent_id)
            for skill in skills:
                if skill.name == skill_name:
                    if file_path:
                        # 读取技能内的指定附加文件
                        files = skill.files or {}
                        if file_path in files:
                            return {"skill_name": skill.name, "file_path": file_path, "content": files[file_path]}
                        return {"error": f"File '{file_path}' not found in skill '{skill_name}'. Available: {list(files.keys())}"}
                    # 不指定 file_path 时只返回主 content（摘要），不携带 files 全量
                    return {"skill_name": skill.name, "content": skill.content or "", "has_files": bool(skill.files)}
            return None

    async def list_skill_files(self, agent_id: str, skill_name: str) -> Optional[Dict[str, Any]]:
        async with self._session_factory() as db:
            repo = AgentSkillRepository(db)
            skills = await repo.get_skills_by_agent(agent_id)
            for skill in skills:
                if skill.name == skill_name:
                    files = skill.files or {}
                    return {
                        "skill_name": skill.name,
                        "files": list(files.keys()),
                        "total": len(files),
                    }
            return None

    # ── Agent 管理 ──

    async def list_agents(self, active_only: bool = False) -> List[Dict[str, Any]]:
        async with self._session_factory() as db:
            svc = AgentService(db)
            if active_only:
                agents = await svc.get_all_active()
            else:
                agents = await svc.get_all()
            return _serialize([a.to_dict() for a in agents])

    async def get_agent(self, agent_id: str) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = AgentService(db)
            agent = await svc.get_detail(agent_id)
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found")
            return _serialize(agent.to_dict())

    async def create_agent(
        self,
        name: str,
        system_prompt: str,
        role: str = "custom",
        description: str = "",
        avatar: str = "🤖",
        llm_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = AgentService(db)
            agent = await svc.create_agent({
                "name": name,
                "system_prompt": system_prompt,
                "role": role,
                "description": description,
                "avatar": avatar,
                "llm_config": llm_config or {},
                "capabilities": capabilities or [],
            })
            await db.commit()
            return _serialize(agent.to_dict())

    async def update_agent(
        self,
        agent_id: str,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        role: Optional[str] = None,
        description: Optional[str] = None,
        avatar: Optional[str] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        async with self._session_factory() as db:
            svc = AgentService(db)
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if system_prompt is not None:
                update_data["system_prompt"] = system_prompt
            if role is not None:
                update_data["role"] = role
            if description is not None:
                update_data["description"] = description
            if avatar is not None:
                update_data["avatar"] = avatar
            if llm_config is not None:
                update_data["llm_config"] = llm_config
            if capabilities is not None:
                update_data["capabilities"] = capabilities
            if is_active is not None:
                update_data["is_active"] = is_active
            agent = await svc.update_agent(agent_id, update_data)
            if agent is None:
                raise ValueError(f"Agent '{agent_id}' not found")
            await db.commit()
            return _serialize(agent.to_dict())

    # ── Web ──

    async def web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """搜索网页，返回结果列表"""
        import logging
        import httpx
        logger = logging.getLogger(__name__)

        try:
            # 使用 DuckDuckGo HTML 版本（无需 API Key）
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                resp.raise_for_status()

            # 简单解析 HTML 提取结果
            from html.parser import HTMLParser

            class DDGParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.results = []
                    self._current = {}
                    self._in_title = False
                    self._in_snippet = False
                    self._depth = 0

                def handle_starttag(self, tag, attrs):
                    attrs_dict = dict(attrs)
                    cls = attrs_dict.get("class") or ""
                    if tag == "a" and "result__a" in cls:
                        self._in_title = True
                        self._current = {"url": attrs_dict.get("href", ""), "title": ""}
                    if tag == "a" and "result__snippet" in cls:
                        self._in_snippet = True

                def handle_endtag(self, tag):
                    if tag == "a" and self._in_title:
                        self._in_title = False
                    if tag == "a" and self._in_snippet:
                        self._in_snippet = False
                        if self._current.get("title"):
                            self.results.append(self._current)
                            self._current = {}

                def handle_data(self, data):
                    if self._in_title:
                        self._current["title"] = self._current.get("title", "") + data.strip()
                    if self._in_snippet:
                        self._current["snippet"] = self._current.get("snippet", "") + data.strip()

            parser = DDGParser()
            parser.feed(resp.text)
            results = parser.results[:max_results]

            if not results:
                return {"results": [], "message": "No results found"}

            return {"results": results, "count": len(results)}

        except Exception as e:
            logger.warning("web_search failed: %s", e)
            return {"results": [], "error": str(e)[:200]}

    async def fetch_url(self, url: str, max_chars: int = 8000) -> Dict[str, Any]:
        """获取网页内容，提取正文文本"""
        import logging
        import httpx
        logger = logging.getLogger(__name__)

        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")

            # 如果是 JSON，直接返回
            if "json" in content_type:
                import json
                try:
                    data = json.loads(resp.text)
                    text = json.dumps(data, ensure_ascii=False, indent=2)[:max_chars]
                    return {"url": url, "content_type": "json", "content": text}
                except Exception:
                    pass

            # HTML 提取正文
            if "html" in content_type or resp.text.strip().startswith("<"):
                from html.parser import HTMLParser

                class TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self._text_parts = []
                        self._skip = False
                        self._skip_tags = {"script", "style", "nav", "header", "footer", "aside"}

                    def handle_starttag(self, tag, _attrs):
                        if tag in self._skip_tags:
                            self._skip = True

                    def handle_endtag(self, tag):
                        if tag in self._skip_tags:
                            self._skip = False

                    def handle_data(self, data):
                        if not self._skip:
                            text = data.strip()
                            if text:
                                self._text_parts.append(text)

                    def get_text(self):
                        return "\n".join(self._text_parts)

                extractor = TextExtractor()
                extractor.feed(resp.text)
                text = extractor.get_text()[:max_chars]

                return {
                    "url": url,
                    "content_type": "html",
                    "title": _extract_html_title(resp.text),
                    "content": text,
                    "truncated": len(extractor.get_text()) > max_chars,
                }

            # 纯文本
            return {
                "url": url,
                "content_type": "text",
                "content": resp.text[:max_chars],
            }

        except Exception as e:
            logger.warning("fetch_url failed for %s: %s", url, e)
            return {"url": url, "error": str(e)[:200]}

    # ── Page Inject ──

    async def page_inject(self, js_code: str, description: str = "") -> Dict[str, Any]:
        """向前端页面注入 JavaScript 代码

        代码会通过 render_spec 的 inject_js 字段传递给前端，
        前端在渲染时自动执行。
        """
        return {
            "success": True,
            "inject_js": js_code,
            "description": description,
        }

    # ── Template（项目模板，引导 agent 用） ──

    async def list_templates(self) -> List[Dict[str, Any]]:
        """列出所有可用的项目模板"""
        async with self._session_factory() as db:
            svc = TemplateService(db)
            templates = await svc.list_templates()
            return _serialize([t.to_dict() for t in templates])

    async def apply_template(
        self,
        template_id: str,
        project_name: str,
        project_description: Optional[str] = None,
        project_targets: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """应用模板创建项目（含 agents/groups/skills/resources）"""
        async with self._session_factory() as db:
            svc = TemplateService(db)
            result = await svc.apply_template(
                template_id=template_id,
                project_name=project_name,
                project_description=project_description,
                project_targets=project_targets,
            )
            await db.commit()
            return _serialize(result.to_dict())

    # ── Subscriptions (订阅机制 v1, DB 持久化) ──────────────────────
    # 注意: 这组方法 (create/delete/query_subscription) 与上面的内存版
    # subscribe_event/unsubscribe_event/list_subscriptions 是两个不同抽象:
    #   - 内存版: agent 侧订阅自身事件 (event_bus.subscribe), EventDispatcher 轮询分发
    #   - DB 版:  群/agent 通用订阅 (持久化), SubscriptionTrigger 监听 event_bus 自动触发
    # 两者共存, 互不干扰. 新模板/动态工具应优先使用 DB 版.

    async def create_subscription(
        self,
        subscriber_type: str,
        subscriber_id: str,
        event_type: str,
        filter: Optional[Dict[str, Any]] = None,
        action: str = "trigger_as_message",
        message_template: Optional[str] = None,
        one_shot: bool = False,
    ) -> Dict[str, Any]:
        """创建事件订阅 (DB 持久化)

        让群/agent 订阅某个事件，事件触发时执行预定义动作（注入消息/通知/创建任务）。

        Args:
            subscriber_type: 订阅者类型，"group" 或 "agent"
            subscriber_id: 订阅者 ID（群 ID 或 agent ID）
            event_type: 事件类型，可选值：
                - group_status_changed: 群状态变化（如 G4 完成）
                - task_status_changed: 任务状态变化
                - resource_created: 资源创建
                - resource_updated: 资源更新
            filter: 事件过滤条件（JSON object），用于精确匹配事件
                例: {"group_id": "G4", "new_status": "completed"}
            action: 触发动作:
                - trigger_as_message: 渲染消息模板并注入到订阅者（默认）
                - trigger_as_notification: 仅发 WS 通知，不启动 agent
                - trigger_as_task: 创建任务（暂未实现）
            message_template: 消息模板，支持 {field} 占位符
                例: "G{group_id} 已 {new_status}，请基于其产出开始你的工作"
            one_shot: 是否一次性（true=触发后自动禁用，false=持续）

        Returns:
            dict: 创建的订阅信息

        Examples:
            # 让 G5 群订阅 G4 群完成事件
            create_subscription(
                subscriber_type="group",
                subscriber_id="G5_id",
                event_type="group_status_changed",
                filter={"group_id": "G4_id", "new_status": "completed"},
                message_template="G4 已完成，请开始 G5 的工作"
            )

            # 让某 agent 订阅资源创建事件（一次性）
            create_subscription(
                subscriber_type="agent",
                subscriber_id="A1_id",
                event_type="resource_created",
                filter={"resource_type": "outline"},
                message_template="大纲已创建",
                one_shot=True
            )
        """
        # 项目 ID 从 subscriber 推断（查 group 或 agent 所属项目）
        project_id = await self._resolve_subscriber_project_id(subscriber_type, subscriber_id)
        if not project_id:
            raise ValueError(
                f"create_subscription failed: 无法解析 {subscriber_type}={subscriber_id[:8]} 所属项目"
            )

        async with self._session_factory() as db:
            from app.services.subscription_service import SubscriptionService
            svc = SubscriptionService(db)
            result = await svc.create_subscription(
                project_id=project_id,
                config={
                    "subscriber_type": subscriber_type,
                    "subscriber_id": subscriber_id,
                    "event_type": event_type,
                    "filter": filter,
                    "action": action,
                    "message_template": message_template,
                    "one_shot": one_shot,
                },
            )
            if not result.get("success"):
                raise ValueError(f"create_subscription failed: {result.get('error')}")
            return _serialize(result["data"])

    async def delete_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """删除事件订阅 (DB)

        Args:
            subscription_id: 订阅 ID

        Returns:
            dict: {"success": true}
        """
        async with self._session_factory() as db:
            from app.services.subscription_service import SubscriptionService
            svc = SubscriptionService(db)
            result = await svc.delete_subscription(subscription_id)
            if not result.get("success"):
                raise ValueError(f"delete_subscription failed: {result.get('error')}")
            return _serialize({"success": True})

    async def query_subscriptions(
        self,
        subscriber_type: Optional[str] = None,
        subscriber_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出订阅 (DB)

        Args:
            subscriber_type: 可选，按订阅者类型过滤
            subscriber_id: 可选，按订阅者 ID 过滤
                - 不传则列出当前项目所有订阅
                - 传 subscriber_type+subscriber_id 列出该订阅者的订阅

        Returns:
            list[dict]: 订阅列表
        """
        # 解析项目 ID（按 subscriber 推断，不传则报错引导用户传 subscriber）
        if not (subscriber_type and subscriber_id):
            raise ValueError(
                "query_subscriptions requires subscriber_type+subscriber_id "
                "to filter subscriptions for a specific subscriber"
            )

        project_id = await self._resolve_subscriber_project_id(subscriber_type, subscriber_id)
        if not project_id:
            raise ValueError(
                f"query_subscriptions failed: 无法解析 {subscriber_type}={subscriber_id[:8]} 所属项目"
            )

        async with self._session_factory() as db:
            from app.services.subscription_service import SubscriptionService
            svc = SubscriptionService(db)
            result = await svc.list_subscriptions(
                project_id=project_id,
                subscriber_type=subscriber_type,
                subscriber_id=subscriber_id,
            )
            if not result.get("success"):
                raise ValueError(f"query_subscriptions failed: {result.get('error')}")
            return _serialize(result["data"])

    async def _resolve_subscriber_project_id(
        self,
        subscriber_type: str,
        subscriber_id: str,
    ) -> Optional[str]:
        """根据订阅者类型和 ID 解析所属项目 ID"""
        async with self._session_factory() as db:
            from sqlalchemy import select
            if subscriber_type == "group":
                from app.models.group import Group
                result = await db.execute(
                    select(Group.project_id).where(Group.id == subscriber_id)
                )
                return result.scalar_one_or_none()
            if subscriber_type == "agent":
                # agent 可能是全局 Agent 或 ProjectAgent
                # 先查 ProjectAgent（项目级 agent 关联表）
                from app.models.group import GroupMember
                result = await db.execute(
                    select(GroupMember.group_id)
                    .where(GroupMember.project_agent_id == subscriber_id)
                    .limit(1)
                )
                group_id = result.scalar_one_or_none()
                if not group_id:
                    return None
                from app.models.group import Group
                result = await db.execute(
                    select(Group.project_id).where(Group.id == group_id)
                )
                return result.scalar_one_or_none()
            return None


def _extract_html_title(html: str) -> str:
    """从 HTML 中提取 <title>"""
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""
