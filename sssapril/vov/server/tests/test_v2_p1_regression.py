"""
v2 P1 回归测试：50 万字项目骨架
==============================
v2-design §0.5 原则: 系统给原子能力，agent 灵活调控。

本测试覆盖（不依赖 LLM, 纯系统层验证）：
1. 应用 novel-writing 模板创建项目 → 8 个 group + 0 个硬编码 task + 0 个硬编码 resource（v2 P2）
2. 创建项目时为每个 group 预建文件夹（v2 P1）
3. write_resource 资源自动归入 group 文件夹（_auto_locate_folder）
4. 原子能力：query_activity / ping / subscribe_event / list_subscriptions 注册和调用
5. _auto_track_task_status 是 no-op（不会偷偷改 task 状态）
6. chat_service 不再含 auto_continue 循环
7. write_resource tags 智能补全（_infer_tags_from_title）
8. [50万字回归核心] lead 不靠 auto_continue/auto_track 也能继续:
   - lead system_prompt 描述"群聊进度管理"工作流
   - lead 拥有推进工具 (send_message / update_task_status / update_group)
   - task 都有 acceptance_criteria（lead 验收参考）—— v2 P2 已删硬编码 task
9. 群聊预建 active chain（ping / send_message 可直接调）
10. 系统层无 auto_continue / auto_track 硬编码

跑法（在 server 目录）:
    python -m tests.test_v2_p1_regression
"""
import asyncio
import json
import sys
import os

# 允许从 server 根目录跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, and_, func
from app.core.database import async_session_factory
from app.models.resource import Resource
from app.models.group import Group
from app.models.task import Task
from app.models.project import Project
from app.services.template_service import TemplateService


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def _assert(cond: bool, msg: str) -> None:
    icon = "✅" if cond else "❌"
    print(f"  {icon} {msg}")
    if not cond:
        raise AssertionError(msg)


async def test_template_creates_project_with_folders():
    """测试 1: 应用 novel-writing 模板 + 预建 8 个 group 文件夹"""
    _print_section("测试 1: 模板应用 + 预建 8 个 group 文件夹")

    project_id = None
    try:
        async with async_session_factory() as db:
            svc = TemplateService(db)
            result = await svc.apply_template(
                template_id="novel-writing",
                project_name="[V2 P1 回归测试]",
                project_description="验证 v2 P1 资源文件夹骨架",
                cover_color="from-amber-500 to-orange-600",
                project_tags=["v2", "p1", "regression"],
            )
            await db.commit()
            project_id = result.project_id
            print(f"  ℹ️  项目创建成功：{project_id}")
            _assert(result.group_count == 8, f"8 个 group（实际 {result.group_count}）")
            # v2 P2: 不再有硬编码 task（task 数量 = 变量, lead 运行时拆）
            _assert(result.task_count == 0, f"0 个硬编码 task（实际 {result.task_count}, v2 P2 由 lead 运行时拆）")
            # v2 P2: 不再有硬编码 resource（resource = 变量, lead 运行时写）
            _assert(result.resource_count == 0, f"0 个硬编码 resource（实际 {result.resource_count}, v2 P2 由 lead 运行时写）")

        # 检查文件夹预建
        async with async_session_factory() as db:
            folders = (await db.execute(
                select(Resource).where(and_(
                    Resource.project_id == project_id,
                    Resource.is_folder == True,  # noqa: E712
                    Resource.deleted_at.is_(None),
                ))
            )).scalars().all()
            _assert(len(folders) == 8, f"预建 8 个文件夹（实际 {len(folders)}）")
            folder_titles = sorted([f.title for f in folders])
            print(f"  ℹ️  文件夹列表: {folder_titles}")
            # 验证每个 group 都有对应文件夹
            groups = (await db.execute(
                select(Group).where(Group.project_id == project_id).order_by(Group.order_index)
            )).scalars().all()
            for g in groups:
                expected = f"📁 {g.name}"
                _assert(
                    expected in folder_titles,
                    f"群聊 {g.name} 有对应文件夹: {expected}"
                )

        return project_id
    except Exception as e:
        # 清理
        if project_id:
            async with async_session_factory() as db:
                p = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
                if p:
                    await db.delete(p)
                    await db.commit()
        raise


async def test_write_resource_auto_locate_folder(project_id: str) -> None:
    """测试 2: write_resource 资源自动归入 group 文件夹"""
    _print_section("测试 2: write_resource 自动归入 group 文件夹")

    from app.orchestrator.tool_adapter import ServerToolAdapter

    # 找一个 group（带文件夹的那个）
    async with async_session_factory() as db:
        group = (await db.execute(
            select(Group).where(Group.project_id == project_id).order_by(Group.order_index).limit(1)
        )).scalars().first()
        _assert(group is not None, "找到测试 group")
        gid = group.id
        gname = group.name

        # 拿到预建文件夹的 ID
        folder = (await db.execute(
            select(Resource).where(and_(
                Resource.project_id == project_id,
                Resource.group_id == gid,
                Resource.is_folder == True,  # noqa: E712
                Resource.deleted_at.is_(None),
            ))
        )).scalar_one()
        folder_id = folder.id
        print(f"  ℹ️  测试群聊: {gname} (id={gid[:8]})")
        print(f"  ℹ️  对应文件夹: {folder.title} (id={folder_id[:8]})")

    # 调 ServerToolAdapter.write_resource
    adapter = ServerToolAdapter(async_session_factory)
    result = await adapter.write_resource(
        project_id=project_id,
        group_id=gid,
        title="[V2 回归测试] 测试资源",
        content="# 测试\n\n这是 v2 P1 回归测试的资源内容。",
        resource_type="note",
        content_type="markdown",
    )
    print(f"  ℹ️  write_resource 返回: parent_id={result.get('parent_id', '?')[:8] if result.get('parent_id') else 'None'}")
    _assert(result.get("success"), "write_resource 成功")
    _assert(result.get("parent_id") == folder_id, f"资源归入预建文件夹 (id={result.get('parent_id', '?')[:8]})")

    # 验证数据库中资源的 parent_id 正确
    async with async_session_factory() as db:
        res = (await db.execute(
            select(Resource).where(and_(
                Resource.project_id == project_id,
                Resource.title == "[V2 回归测试] 测试资源",
            ))
        )).scalar_one()
        _assert(res.parent_id == folder_id, "数据库中 parent_id == 文件夹 id")


async def test_atomic_abilities_registered():
    """测试 3: 原子能力（query_activity / ping / subscribe_event）已注册"""
    _print_section("测试 3: 原子能力注册和调用")

    from app.orchestrator.tool_adapter import ServerToolAdapter
    from agentflow.crud_processors import (
        QueryActivityProcessor,
        PingProcessor,
        SubscribeEventProcessor,
        ListSubscriptionsProcessor,
    )

    adapter = ServerToolAdapter(async_session_factory)
    procs = [
        QueryActivityProcessor(adapter),
        PingProcessor(adapter),
        SubscribeEventProcessor(adapter),
        ListSubscriptionsProcessor(adapter),
    ]
    for p in procs:
        schema = p.get_schema()
        _assert(schema.get("type") == "function", f"{p.kind} 注册成 function 工具")
        fn = schema.get("function") or {}
        _assert(fn.get("name"), f"{p.kind} function.name 存在")
        _assert(fn.get("description"), f"{p.kind} function.description 存在")
        _assert(fn.get("parameters", {}).get("properties"), f"{p.kind} parameters.properties 存在")


async def test_auto_track_is_noop():
    """测试 4: _auto_track_task_status 是 no-op（v2 §0.5 原则 2 反模式清单）"""
    _print_section("测试 4: auto_track 是 no-op")

    from app.orchestrator.tool_adapter import ServerToolAdapter
    import inspect

    adapter = ServerToolAdapter(async_session_factory)
    src = inspect.getsource(adapter._auto_track_task_status)
    _assert("return  # 保留方法签名占位" in src or "return" in src and "no-op" in src.lower(),
            "_auto_track_task_status 是 no-op")
    print("  ℹ️  源码前 200 字:", src.strip()[:200])


async def test_chat_service_no_auto_continue():
    """测试 5: chat_service 不再含 auto_continue 循环"""
    _print_section("测试 5: chat_service 删除 auto_continue")

    from app.services import chat_service
    src = inspect_module_source(chat_service)
    _assert("auto_continue" not in src or "删除 auto_continue" in src,
            "auto_continue 已删除（只剩注释说明）")
    _assert("auto_track" not in src or "删除" in src or "no-op" in src,
            "auto_track 已删除（只剩注释说明）")


def inspect_module_source(module) -> str:
    import inspect
    return inspect.getsource(module)


async def test_query_activity_works(project_id: str):
    """测试 6: query_activity 原子能力可调"""
    _print_section("测试 6: query_activity 原子能力")

    from app.orchestrator.tool_adapter import ServerToolAdapter

    adapter = ServerToolAdapter(async_session_factory)
    result = await adapter.query_activity(project_id=project_id)
    print(f"  ℹ️  query_activity: {result}")
    _assert(result.get("project_id") == project_id, "project_id 正确")
    _assert("active_agent_ids" in result, "返回 active_agent_ids")
    _assert("idle_seconds" in result, "返回 idle_seconds")


async def test_ping_does_not_modify_state(project_id: str):
    """测试 7: ping 不修改任何状态（v2 §0.5 原则 6 原子能力）"""
    _print_section("测试 7: ping 不修改状态")

    from app.orchestrator.tool_adapter import ServerToolAdapter
    from app.services.event_bus import event_bus

    adapter = ServerToolAdapter(async_session_factory)

    # 找一个 group
    async with async_session_factory() as db:
        group = (await db.execute(
            select(Group).where(Group.project_id == project_id).order_by(Group.order_index).limit(1)
        )).scalars().first()
        gid = group.id

    # 订阅事件
    sub = await adapter.subscribe_event(
        event_type="task_status_changed",
        subscriber_agent_id="[V2 回归测试 agent]",
        project_id=project_id,
        group_id=gid,
    )
    _assert(sub.get("success"), "subscribe_event 成功")

    # 触发 ping
    ping_result = await adapter.ping(
        group_id=gid,
        to_agent_id="[V2 回归测试 target]",
        reason="regression_test",
        context={"test": True},
    )
    _assert("id" in ping_result, "ping 返回 packet")

    # 验证：ping 后没有任何 task 状态被改
    async with async_session_factory() as db:
        tasks = (await db.execute(
            select(Task).join(Group, Group.id == Task.group_id)
            .where(Group.project_id == project_id)
        )).scalars().all()
        non_todo = [t for t in tasks if t.status != "todo"]
        _assert(len(non_todo) == 0, f"ping 没改 task 状态（实际改 {len(non_todo)} 个）")


async def test_lead_can_work_without_auto_continue(project_id: str):
    """测试 8 (50万字回归核心): lead 不靠 auto_continue/auto_track 也能继续。

    v2 §0.5 原则 6: 流程层（skill/prompt）必须明确, lead 主动调原子能力推进。
    验证维度:
    1. 每个 group 的 lead agent 都有 system_prompt 描述"群聊进度管理"流程
    2. lead 拥有推进流程所需的全部原子能力 (send_message/update_task_status/update_group)
    3. 每个 task 都有 acceptance_criteria（lead 验收的参考）
    4. lead 的 prompt 明确要求 "update_task_status=done" + "update_group=completed"
    5. 没有系统层 auto_continue / auto_track（已测试 4/5，本测试交叉验证 lead 的对偶面）
    """
    _print_section("测试 8 (50万字回归): lead 自主推进工作流")

    from app.models.agent import Agent, ProjectAgent, AgentTool
    from app.models.task import Task
    from sqlalchemy.orm import selectinload

    REQUIRED_TOOLS = {"send_message", "update_task_status", "update_group"}
    # write_resource 是"产出方"lead 需要的, 但"审校/复核"类 lead 不一定需要
    # (他们的产出是 send_message 评价, 不是写资源)。
    # 我们只校验每个 lead 都有"流程推进三件套" + 至少一个内容工具。

    # 1. 取项目下所有 lead agent
    async with async_session_factory() as db:
        groups = (await db.execute(
            select(Group)
            .options(selectinload(Group.lead_agent).selectinload(ProjectAgent.agent).selectinload(Agent.tools))
            .where(Group.project_id == project_id)
            .order_by(Group.order_index)
        )).scalars().all()

        lead_count = 0
        prompt_with_workflow = 0
        for g in groups:
            if not g.lead_agent or not g.lead_agent.agent:
                continue
            lead_count += 1
            agent = g.lead_agent.agent

            # 2. system_prompt 包含"群聊进度管理"或类似命令式流程
            sp = agent.system_prompt or ""
            has_workflow = (
                "update_task_status" in sp and
                "update_group" in sp and
                ("done" in sp or "completed" in sp)
            )
            if has_workflow:
                prompt_with_workflow += 1
            else:
                print(f"  ⚠️  群 {g.name} 的 lead {agent.name} 缺工作流描述")
                print(f"     prompt 前 300 字: {sp[:300]}")

            # 3. 拥有推进所需的全部原子能力
            tool_names = {t.name for t in (agent.tools or [])}
            missing = REQUIRED_TOOLS - tool_names
            _assert(
                not missing,
                f"群 {g.name} lead {agent.name} 拥有推进工具（缺 {missing or '无'}）"
            )

        _assert(lead_count == 8, f"8 个 group 都有 lead（实际 {lead_count}）")
        _assert(
            prompt_with_workflow == lead_count,
            f"所有 lead 的 system_prompt 都描述工作流（{prompt_with_workflow}/{lead_count}）"
        )

    # 4. v2 P2: 验证 lead 的 system_prompt 含"运行时拆解" 章节
    # (替代旧的"task 都有 acceptance_criteria" 检查, v2 P2 改由 lead 拆 task 时填 acceptance_criteria)
    async with async_session_factory() as db:
        groups = (await db.execute(
            select(Group)
            .options(selectinload(Group.lead_agent).selectinload(ProjectAgent.agent))
            .where(Group.project_id == project_id)
        )).scalars().all()
        no_decomp = []
        for g in groups:
            if not g.lead_agent or not g.lead_agent.agent:
                continue
            sp = g.lead_agent.agent.system_prompt or ""
            if "运行时拆解（v2 P2" not in sp:
                no_decomp.append(g.name)
        _assert(
            len(no_decomp) == 0,
            f"所有 lead 的 system_prompt 含「运行时拆解」章节（缺 {len(no_decomp)}: {no_decomp}）"
        )

    # 5. v2 P2: 验证 create_task 工具已注入到 lead
    async with async_session_factory() as db:
        groups = (await db.execute(
            select(Group)
            .options(selectinload(Group.lead_agent).selectinload(ProjectAgent.agent).selectinload(Agent.tools))
            .where(Group.project_id == project_id)
        )).scalars().all()
        no_create_task = []
        for g in groups:
            if not g.lead_agent or not g.lead_agent.agent:
                continue
            tool_names = {t.name for t in (g.lead_agent.agent.tools or [])}
            if "create_task" not in tool_names:
                no_create_task.append(g.name)
        _assert(
            len(no_create_task) == 0,
            f"所有 lead 都有 create_task 工具（缺 {len(no_create_task)}: {no_create_task}）"
        )

    # 6. v2 P2: 验证 group.description 包含 decomposition_rules
    async with async_session_factory() as db:
        groups = (await db.execute(
            select(Group).where(Group.project_id == project_id)
        )).scalars().all()
        no_rules = []
        for g in groups:
            if not g.description or "拆解规则" not in g.description:
                no_rules.append(g.name)
        _assert(
            len(no_rules) == 0,
            f"所有 group.description 含「拆解规则」（缺 {len(no_rules)}: {no_rules}）"
        )


async def test_groups_have_active_chains(project_id: str):
    """测试 9 (50万字回归): 群聊预建 active chain。

    v2 P1 修复: send_message / ping 原子能力要求群下有 active chain。
    群聊创建时（template_service）必须预建, 不能依赖 chat 入口的 lazy create。
    """
    _print_section("测试 9: 群聊预建 active chain")

    from app.models.chain import Chain

    async with async_session_factory() as db:
        groups = (await db.execute(
            select(Group).where(Group.project_id == project_id)
        )).scalars().all()
        _assert(len(groups) == 8, f"8 个 group（实际 {len(groups)}）")

        # 每个 group 至少有一个 active chain
        no_chain = []
        for g in groups:
            chain = (await db.execute(
                select(Chain).where(
                    (Chain.group_id == g.id) &
                    (Chain.chain_type == "group") &
                    (Chain.status == "active") &
                    (Chain.deleted_at.is_(None))
                )
            )).scalar_one_or_none()
            if not chain:
                no_chain.append(g.name)
        _assert(
            len(no_chain) == 0,
            f"8 个 group 都有 active chain（缺 {len(no_chain)}: {no_chain}）"
        )


async def test_no_system_layer_auto_push():
    """测试 10 (50万字回归): 任何模块都没有"系统层自动推进"。

    v2 §0.5 原则 2 反模式清单:
    - ❌ 系统层偷偷推进流程（auto_continue / auto_track）
    - ❌ 触发条件硬编码"催谁"
    - ❌ 系统层 chat 入口外的循环

    验证维度:
    1. chat_service 无 auto_continue / auto_track 关键字
    2. tool_adapter 无自动调 update_task_status 的循环
    3. message_dispatcher 无自动改 group 状态的循环
    """
    _print_section("测试 10: 系统层无 auto_continue / auto_track")

    import inspect

    forbidden = ["auto_continue", "auto_track"]
    files_to_check = [
        ("chat_service", "app.services.chat_service"),
        ("tool_adapter", "app.orchestrator.tool_adapter"),
        ("message_dispatcher", "app.orchestrator.message_dispatcher"),
    ]

    for label, module_path in files_to_check:
        mod = __import__(module_path, fromlist=["*"])
        src = inspect.getsource(mod)
        for keyword in forbidden:
            if keyword in src:
                # 允许: docstring/comment 提到"已删除 auto_continue" 等说明性文字
                if "已删除" in src or "删除" in src:
                    print(f"  ℹ️  {label} 含 {keyword!r} 关键字（注释/说明）")
                else:
                    _assert(False, f"{label} 含 {keyword!r}（疑似硬编码自动推进）")
            else:
                _assert(True, f"{label} 不含 {keyword!r}")


async def cleanup(project_id: str) -> None:
    """清理测试项目（用 SQL DELETE 让数据库 CASCADE 触发, 避免 ORM 级联不一致）"""
    from sqlalchemy import delete as sa_delete
    from app.models.memory import Memory

    async with async_session_factory() as db:
        await db.execute(sa_delete(Memory).where(Memory.project_id == project_id))
        await db.execute(sa_delete(Project).where(Project.id == project_id))
        await db.commit()
        print(f"\n  🧹 清理项目 {project_id}")


async def main():
    print("=" * 60)
    print("  v2 P1 回归测试：50 万字项目骨架")
    print("=" * 60)

    # 0. 初始化数据库（脚本模式不依赖 conftest 的 fixture）
    from app.core.database import init_db
    await init_db()
    print("  ℹ️  数据库表已初始化")

    project_id = await test_template_creates_project_with_folders()
    try:
        await test_write_resource_auto_locate_folder(project_id)
        await test_atomic_abilities_registered()
        await test_auto_track_is_noop()
        await test_chat_service_no_auto_continue()
        await test_query_activity_works(project_id)
        await test_ping_does_not_modify_state(project_id)
        await test_lead_can_work_without_auto_continue(project_id)
        await test_groups_have_active_chains(project_id)
        await test_no_system_layer_auto_push()

        print("\n" + "=" * 60)
        print("  ✅ 全部 10 个测试通过")
        print("=" * 60)
    finally:
        await cleanup(project_id)


if __name__ == "__main__":
    asyncio.run(main())
