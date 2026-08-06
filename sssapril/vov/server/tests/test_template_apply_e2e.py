"""
E2E 测试：基于 novel-writing 模板创建项目，验证落库 + 上下文分层。

覆盖：
- 模板应用：skills/agents/groups/tasks/resources 全部正确落库
- 上下文分层：skills 仅元信息、资源分必读全文与目录
- Lead agent 路由：group_focus memory 驱动资源可见性
- 资源追溯：task_id 关联正确
"""
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, func

from app.core.database import async_session_factory
from app.models.project import Project
from app.models.group import Group, GroupMember
from app.models.agent import Agent, ProjectAgent, AgentSkill, AgentTool, Skill
from app.models.task import Task, TaskAssignee
from app.models.resource import Resource
from app.models.memory import Memory
from app.services.template_service import TemplateService
from app.orchestrator.context_builder import ContextBuilder


async def _create_project_via_template(name: str) -> tuple[str, "ApplyResult"]:
    async with async_session_factory() as db:
        svc = TemplateService(db)
        result = await svc.apply_template(
            template_id="novel-writing",
            project_name=name,
            project_description="E2E 模板应用测试",
            cover_color="from-purple-500 to-pink-600",
            project_tags=["e2e", "test"],
        )
        await db.commit()
        return result.project_id, result


async def _cleanup_project(project_id: str):
    async with async_session_factory() as db:
        await db.execute(delete(Memory).where(Memory.project_id == project_id))
        await db.execute(delete(Project).where(Project.id == project_id))
        await db.commit()


@pytest.mark.asyncio
async def test_template_apply_persistence():
    """Step 1-2: 模板应用与落库数量正确"""
    pid, result = await _create_project_via_template("[E2E] 仙侠长篇")
    try:
        d = result.to_dict()
        # 本次应用数量
        assert len(d["reused_skills"]) + len(d["created_skills"]) == 10, "10 skills"
        assert len(d["reused_agents"]) + len(d["created_agents"]) == 8, "8 agents"
        assert d["group_count"] == 8, "8 groups"
        assert d["task_count"] == 27, "27 tasks"
        assert d["resource_count"] == 5, "5 resources"
        assert d["project_agent_count"] == 8, "8 project-agent 关联"

        async with async_session_factory() as db:
            p = (await db.execute(select(Project).where(Project.id == pid))).scalar_one()
            assert p.workflow_config.get("template_id") == "novel-writing"
            assert p.status == "active"

            gs = (await db.execute(
                select(Group).where(Group.project_id == pid).order_by(Group.order_index)
            )).scalars().all()
            assert len(gs) == 8

            # 群聊 lead_agent_id 必须有效
            for g in gs:
                assert g.lead_agent_id is not None, f"群 {g.name} 缺 lead"
                # 至少 1 个成员
                mem_count = (await db.execute(
                    select(func.count(GroupMember.id)).where(GroupMember.group_id == g.id)
                )).scalar()
                assert mem_count >= 1, f"群 {g.name} 无成员"

            # 27 个任务全部落到群聊下
            tasks = (await db.execute(
                select(Task).join(Group, Group.id == Task.group_id)
                .where(Group.project_id == pid)
            )).scalars().all()
            assert len(tasks) == 27
            for t in tasks:
                assert t.status == "todo", f"任务 {t.title} 状态错"

            # 5 个项目级资源（v2 P1 还会预建 8 个 group 文件夹, 不计入此处）
            rs = (await db.execute(
                select(Resource).where(
                    Resource.project_id == pid,
                    Resource.is_folder == False,  # noqa: E712
                )
            )).scalars().all()
            assert len(rs) == 5
            for r in rs:
                assert r.task_id is not None, f"资源 {r.title} 未追溯到任务"
    finally:
        await _cleanup_project(pid)


@pytest.mark.asyncio
async def test_context_layering_fallback():
    """Step 3 Test A: 无 group_focus 时，fallback 到 is_required 全文/其他目录"""
    pid, _ = await _create_project_via_template("[E2E] 上下文-fallback")
    try:
        async with async_session_factory() as db:
            group = (await db.execute(
                select(Group).where(Group.project_id == pid).order_by(Group.order_index)
            )).scalars().first()

            lead_pa = (await db.execute(
                select(ProjectAgent).where(ProjectAgent.id == group.lead_agent_id)
            )).scalar_one()
            lead_agent = (await db.execute(
                select(Agent).where(Agent.id == lead_pa.agent_id)
            )).scalar_one()

            cb = ContextBuilder(db)
            ctx = await cb.build(agent=lead_agent, project_agent=lead_pa, group=group, include_history=False)

            # skills 仅元信息：不含 content 字段
            assert len(ctx["skills"]) > 0
            for s in ctx["skills"]:
                assert "content" not in s, f"skill {s['name']} 泄露 content"
                assert "name" in s and "description" in s

            # fallback 模式：routed_by_lead=False
            assert ctx.get("routed_by_lead") is False

            # 所有 is_required=True 的资源都在 resources 列表
            full_titles = {r["title"] for r in ctx["resources"]}
            assert "项目立项书" in full_titles
            assert "写作风格指南" in full_titles
    finally:
        await _cleanup_project(pid)


@pytest.mark.asyncio
async def test_context_layering_lead_routing():
    """Step 3 Test B: lead 维护 group_focus 后，skip / must_read 生效"""
    pid, _ = await _create_project_via_template("[E2E] 上下文-路由")
    try:
        # 1. 拿测试数据
        async with async_session_factory() as db:
            group = (await db.execute(
                select(Group).where(Group.project_id == pid).order_by(Group.order_index)
            )).scalars().first()
            lead_pa = (await db.execute(
                select(ProjectAgent).where(ProjectAgent.id == group.lead_agent_id)
            )).scalar_one()
            lead_agent = (await db.execute(
                select(Agent).where(Agent.id == lead_pa.agent_id)
            )).scalar_one()
            member = (await db.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group.id,
                    GroupMember.role == "participant",
                )
            )).scalars().first()
            member_pa = (await db.execute(
                select(ProjectAgent).where(ProjectAgent.id == member.project_agent_id)
            )).scalar_one()
            member_agent = (await db.execute(
                select(Agent).where(Agent.id == member_pa.agent_id)
            )).scalar_one()
            member_name = member_agent.name

        # 2. 给 lead 写 group_focus memory
        group_focus_md = f"""# {group.name} - 群焦点

## must_read
- [项目立项书] (G1 产出)
- [写作风格指南] (贯穿全程)

## skip
- [人物卡片模板] (本群用不上)

## member_roster
- {member_name}: 必读=[写作风格指南, 一致性检查清单]
"""
        async with async_session_factory() as db:
            # 清旧
            old = (await db.execute(
                select(Memory).where(
                    Memory.agent_id == lead_agent.id,
                    Memory.project_id == pid,
                    Memory.slug == "group_focus",
                )
            )).scalar_one_or_none()
            if old:
                await db.delete(old)
                await db.commit()
            db.add(Memory(
                agent_id=lead_agent.id,
                project_id=pid,
                slug="group_focus",
                content=group_focus_md,
                content_type="markdown",
                tags=["routing"],
            ))
            await db.commit()

        # 3. 重新构建上下文（新 session）
        async with async_session_factory() as db:
            cb = ContextBuilder(db)
            ctx = await cb.build(
                agent=member_agent, project_agent=member_pa, group=group, include_history=False,
            )
            # 路由生效
            assert ctx.get("routed_by_lead") is True

            # skip 资源不出现在任何地方
            all_titles = {r["title"] for r in ctx["resources"]} | {
                c["title"] for c in ctx["resource_catalog"]
            }
            assert "人物卡片模板" not in all_titles, "skip 资源应被过滤"

            # must_read 资源全文注入
            full_titles = {r["title"] for r in ctx["resources"]}
            assert "写作风格指南" in full_titles, "member_roster 必读应注入"
            assert "项目立项书" in full_titles, "顶层 must_read 应注入"

        # 4. format_for_llm 不含 skill 全文
        async with async_session_factory() as db:
            cb = ContextBuilder(db)
            ctx = await cb.build(
                agent=member_agent, project_agent=member_pa, group=group, include_history=False,
            )
            formatted = cb.format_for_llm(ctx)
            sys_msg = formatted["system_message"]
            # skill 全文标识（self-memory 的标志性内容）不应出现
            assert "## 标准 slug 模板" not in sys_msg, "skill content 不应注入 LLM 上下文"
            # 元信息目录段应出现
            assert "Agent Skills" in sys_msg
            # 路由生效后系统消息应含"上下文路由"提示
            assert "上下文路由" in sys_msg
            # "参考资源" 段必出现（must_read 全文在这里）
            assert "参考资源" in sys_msg
            # 且不应含 skip 资源的标题
            assert "人物卡片模板" not in sys_msg, "skip 资源不应注入"
    finally:
        await _cleanup_project(pid)


@pytest.mark.asyncio
async def test_resource_task_id_linkage():
    """Step 4: 5 个资源全部追溯到具体任务，可形成完整创作链路"""
    pid, _ = await _create_project_via_template("[E2E] 资源追溯")
    try:
        # 5 个项目级资源全部追溯到具体任务（v2 P1 还有 8 个 group 文件夹, 不计入）
        async with async_session_factory() as db:
            rs = (await db.execute(
                select(Resource).where(
                    Resource.project_id == pid,
                    Resource.is_folder == False,  # noqa: E712
                )
            )).scalars().all()
            assert len(rs) == 5
            for r in rs:
                # 追溯到的任务存在
                t = (await db.execute(select(Task).where(Task.id == r.task_id))).scalar_one()
                g = (await db.execute(select(Group).where(Group.id == t.group_id))).scalar_one()
                assert g.project_id == pid, f"资源 {r.title} 追溯到非本项目任务"
    finally:
        await _cleanup_project(pid)
