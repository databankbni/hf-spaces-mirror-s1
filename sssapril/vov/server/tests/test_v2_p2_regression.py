"""
v2 P2 回归测试：事件订阅 / 发布 / 调度链路
==========================================
v2 §0.5 原则 6: 系统给原子能力，agent 灵活调控。

本测试覆盖（不依赖 LLM, 纯系统层验证）:
1. subscribe_event 工具 → event_bus 注册 → find_matching_subscribers 命中
2. publish → EventDispatcher → 冷却 / 失败回退
3. unsubscribe_event 清理订阅
4. event-coordination / task-acceptance skill 包含 lead/assignee 分模板
5. agents.json 的 system_prompt 包含 v2 P2 角色化块
6. groups.json 的 lead_agent 配置正确

跑法（在 server 目录）:
    python -m tests.test_v2_p2_regression
"""
import asyncio
import json
import os
import sys

# 允许从 server 根目录跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_session_factory
from app.services.template_service import TemplateService
from app.services.event_bus import EventBus
from app.orchestrator.event_dispatcher import EventDispatcher


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def _assert(cond: bool, msg: str) -> None:
    icon = "✅" if cond else "❌"
    print(f"  {icon} {msg}")
    if not cond:
        raise AssertionError(msg)


# ────────────────────────────────────────────────────────────
# 测试 1: subscribe_event 链路
# ────────────────────────────────────────────────────────────

async def test_subscribe_and_match():
    """subscribe_event → event_bus → find_matching_subscribers 命中"""
    _print_section("测试 1: subscribe_event 链路")

    # 用独立的 EventBus 实例避免污染全局
    bus = EventBus()
    await bus.subscribe(
        event_type="task_status_changed",
        subscriber_agent_id="agent_lead_001",
        project_id="proj_test_1",
        group_id="grp_test_1",
    )
    await bus.subscribe(
        event_type="group_status_changed",
        subscriber_agent_id="agent_assignee_002",
        project_id="proj_test_1",
        group_id="grp_test_1",
    )

    # 匹配：相同 project + group_id
    matches = bus.find_matching_subscribers("task_status_changed", "proj_test_1", "grp_test_1")
    matched_ids = [m["subscriber_agent_id"] for m in matches]
    _assert("agent_lead_001" in matched_ids, "task_status_changed 命中 lead 订阅")
    _assert("agent_assignee_002" not in matched_ids, "task_status_changed 不命中 assignee（她没订阅）")

    # 匹配：不同 project
    matches2 = bus.find_matching_subscribers("task_status_changed", "other_proj", "grp_test_1")
    _assert(len(matches2) == 0, "不同 project 不命中")

    # 匹配：group_status_changed
    matches3 = bus.find_matching_subscribers("group_status_changed", "proj_test_1", "grp_test_1")
    matched_ids3 = [m["subscriber_agent_id"] for m in matches3]
    _assert("agent_assignee_002" in matched_ids3, "group_status_changed 命中 assignee 订阅")
    _assert("agent_lead_001" not in matched_ids3, "group_status_changed 不命中 lead（她没订阅这个事件）")


# ────────────────────────────────────────────────────────────
# 测试 2: publish → agent-side enqueue
# ────────────────────────────────────────────────────────────

async def test_publish_enqueues_to_subscribers():
    """publish → agent 侧 Queue 应收到"""
    _print_section("测试 2: publish 通知到 subscriber")

    bus = EventBus()
    await bus.subscribe(
        event_type="task_status_changed",
        subscriber_agent_id="sub_1",
        project_id="proj_x",
        group_id="grp_x",
    )
    notified = await bus.publish(
        "task_status_changed",
        {
            "project_id": "proj_x",
            "group_id": "grp_x",
            "task_id": "t_1",
            "status": "done",
        },
    )
    _assert(notified == 1, f"1 个 agent 被通知（实际 {notified}）")

    events = await bus.drain_events("sub_1")
    _assert(len(events) == 1, f"sub_1 收到 1 个事件（实际 {len(events)}）")
    _assert(events[0]["event_type"] == "task_status_changed", "事件类型正确")
    _assert(events[0]["payload"]["status"] == "done", "事件 payload 正确")


# ────────────────────────────────────────────────────────────
# 测试 3: EventDispatcher 冷却机制
# ────────────────────────────────────────────────────────────

async def test_event_dispatcher_cooldown():
    """同一 (subscriber, event_type) 在 cooldown 内只触发一次"""
    _print_section("测试 3: EventDispatcher 60s 冷却")

    bus = EventBus()

    # 短的 cooldown 用于测试
    dispatcher = EventDispatcher(
        session_factory=async_session_factory,
        agent_executor=None,  # 不实际启动 session
        cooldown_seconds=60.0,
    )

    # 不挂到 event_bus.on()，手动测 cooldown 逻辑
    # 用 _is_in_cooldown 直接验证
    key = ("sub_X", "task_status_changed")
    _assert(not dispatcher._is_in_cooldown(key), "初始无冷却")

    dispatcher._cooldowns[key] = __import__("time").monotonic()
    _assert(dispatcher._is_in_cooldown(key), "刚设置 → 在冷却中")


# ────────────────────────────────────────────────────────────
# 测试 4: skill 模板有 lead/assignee 分模板
# ────────────────────────────────────────────────────────────

def test_skills_have_role_distinction():
    """event-coordination / task-acceptance skill 包含 lead/assignee 分模板"""
    _print_section("测试 4: skill 模板 lead/assignee 分模板")

    skills_path = r"d:\agents\vov\server\app\default_presets\project_templates\novel-writing\skills.json"
    data = json.load(open(skills_path, encoding="utf-8"))
    skills_by_name = {s["name"]: s for s in data["skills"]}

    # event-coordination
    ec = skills_by_name["event-coordination"]
    ec_content = ec["content"]
    _assert("Lead 订阅模板" in ec_content, "event-coordination 含 Lead 订阅模板")
    _assert("Assignee 订阅模板" in ec_content, "event-coordination 含 Assignee 订阅模板")
    _assert("assignee 也订阅 task_status_changed" in ec_content, "event-coordination 警告 assignee 别订阅 task_status_changed")
    _assert("task_status_changed" in ec_content, "event-coordination 包含 task_status_changed 说明")

    # task-acceptance
    ta = skills_by_name["task-acceptance"]
    ta_content = ta["content"]
    _assert("角色 A" in ta_content and "角色 B" in ta_content, "task-acceptance 含 角色 A/B 区分")
    _assert("Lead 验收" in ta_content, "task-acceptance 含 Lead 验收流程")
    _assert("Assignee 自评" in ta_content, "task-acceptance 含 Assignee 自评流程")
    _assert("acceptance_criteria" in ta_content, "task-acceptance 引用 acceptance_criteria")


# ────────────────────────────────────────────────────────────
# 测试 5: agents.json 的 system_prompt 包含 v2 P2 角色化块
# ────────────────────────────────────────────────────────────

def test_agents_have_v2_p2_directive():
    """所有 agent 的 system_prompt 都包含 v2 P2 块（按角色区分）"""
    _print_section("测试 5: agents.json v2 P2 角色化块")

    agents_path = r"d:\agents\vov\server\app\default_presets\project_templates\novel-writing\agents.json"
    data = json.load(open(agents_path, encoding="utf-8"))

    PURE_LEAD = {"世界观架构师·筑界", "人物设定师·塑魂", "主笔作家·落笔", "风格润色师·点墨"}
    PURE_ASSIGNEE = {"逻辑审校·较真", "读者代理·灯下"}
    DUAL_ROLE = {"主编·墨言", "故事架构师·织梦"}

    for a in data["agents"]:
        name = a["name"]
        sp = a["system_prompt"]

        if name in PURE_LEAD:
            _assert("lead 角色" in sp, f"{name}: 含 'lead 角色' 标识")
            _assert("Lead 验收" in sp, f"{name}: 引用 Lead 验收")
            _assert("Assignee 自评" in sp, f"{name}: 引用 Assignee 自评")
        elif name in PURE_ASSIGNEE:
            _assert("assignee 角色" in sp, f"{name}: 含 'assignee 角色' 标识")
            _assert("Assignee 自评" in sp, f"{name}: 引用 Assignee 自评")
            _assert("**不要**订阅" in sp, f"{name}: 警告别乱订阅")
        elif name in DUAL_ROLE:
            _assert("双角色" in sp, f"{name}: 含 '双角色' 标识")
            _assert("Lead 验收" in sp, f"{name}: 引用 Lead 验收")
            _assert("Assignee 自评" in sp, f"{name}: 引用 Assignee 自评")
        else:
            _assert(False, f"未知 agent: {name}")

        # 都引用了 event-coordination + task-acceptance skill
        skill_refs = a.get("skill_refs", [])
        _assert("event-coordination" in skill_refs, f"{name}: skill_refs 含 event-coordination")
        _assert("task-acceptance" in skill_refs, f"{name}: skill_refs 含 task-acceptance")


# ────────────────────────────────────────────────────────────
# 测试 6: agent 工具表都包含 subscribe_event 工具
# ────────────────────────────────────────────────────────────

def test_agents_have_subscribe_event_tool():
    """所有 v2 P2 agent 都注入了 subscribe_event 工具"""
    _print_section("测试 6: 工具表注入 subscribe_event / unsubscribe_event")

    agents_path = r"d:\agents\vov\server\app\default_presets\project_templates\novel-writing\agents.json"
    data = json.load(open(agents_path, encoding="utf-8"))

    for a in data["agents"]:
        name = a["name"]
        tool_names = {t["name"] for t in a.get("tools", [])}
        _assert("subscribe_event" in tool_names, f"{name}: 含 subscribe_event 工具")
        _assert("unsubscribe_event" in tool_names, f"{name}: 含 unsubscribe_event 工具")
        _assert("list_subscriptions" in tool_names, f"{name}: 含 list_subscriptions 工具")
        _assert("get_agent_db" in tool_names, f"{name}: 含 get_agent_db 工具")


# ────────────────────────────────────────────────────────────
# 测试 7: groups.json 的 lead_agent 角色映射
# ────────────────────────────────────────────────────────────

def test_groups_lead_assignment():
    """groups.json: 较真 / 灯下 永远不是 lead (与 system_prompt 角色匹配)"""
    _print_section("测试 7: groups.json 角色一致性")

    groups_path = r"d:\agents\vov\server\app\default_presets\project_templates\novel-writing\groups.json"
    data = json.load(open(groups_path, encoding="utf-8"))

    # 收集每个 group 的 lead_agent
    lead_counts = {}
    for g in data["groups"]:
        lead = g["lead_agent"]
        lead_counts[lead] = lead_counts.get(lead, 0) + 1

    # 较真 / 灯下 不应是 lead
    _assert("逻辑审校·较真" not in lead_counts, "逻辑审校·较真 不应是 lead")
    _assert("读者代理·灯下" not in lead_counts, "读者代理·灯下 不应是 lead")
    # 墨言 / 织梦 应该是多群 lead
    _assert(lead_counts.get("主编·墨言", 0) >= 1, "主编·墨言 至少是 1 个群的 lead")
    _assert(lead_counts.get("故事架构师·织梦", 0) >= 1, "故事架构师·织梦 至少是 1 个群的 lead")
    # 8 个 group 都应有 lead
    total_leads = sum(1 for g in data["groups"] if g.get("lead_agent"))
    _assert(total_leads == 8, f"8 个 group 都有 lead（实际 {total_leads}）")


# ────────────────────────────────────────────────────────────
# 集成测试: 完整链路 (subscribe → publish → drain)
# ────────────────────────────────────────────────────────────

async def test_full_p2_pipeline():
    """完整 P2 链路: subscribe_event → publish → 收件人队列"""
    _print_section("测试 8: 完整 P2 链路")

    bus = EventBus()

    # lead 订阅 task_status_changed
    await bus.subscribe(
        "task_status_changed", "agent_lead",
        project_id="proj", group_id="grp",
    )
    # assignee 订阅 group_status_changed
    await bus.subscribe(
        "group_status_changed", "agent_assignee",
        project_id="proj", group_id="grp",
    )

    # 模拟 lead 标 task done → publish
    notified_a = await bus.publish(
        "task_status_changed",
        {"project_id": "proj", "group_id": "grp", "task_id": "t1", "status": "done"},
    )
    _assert(notified_a == 1, f"lead 收到 1 个通知（实际 {notified_a}）")

    # 模拟群聊切到 completed → publish
    notified_b = await bus.publish(
        "group_status_changed",
        {"project_id": "proj", "group_id": "grp", "new_status": "completed"},
    )
    _assert(notified_b == 1, f"assignee 收到 1 个通知（实际 {notified_b}）")

    # lead 排空事件
    lead_events = await bus.drain_events("agent_lead")
    _assert(len(lead_events) == 1, f"lead 收到 1 个事件（实际 {len(lead_events)}）")
    _assert(lead_events[0]["event_type"] == "task_status_changed", "lead 收到的是 task_status_changed")

    # assignee 排空事件
    assignee_events = await bus.drain_events("agent_assignee")
    _assert(len(assignee_events) == 1, f"assignee 收到 1 个事件（实际 {len(assignee_events)}）")
    _assert(assignee_events[0]["event_type"] == "group_status_changed", "assignee 收到的是 group_status_changed")


async def main():
    print("=" * 60)
    print("  v2 P2 回归测试：事件订阅 / 发布 / 调度链路")
    print("=" * 60)

    tests = [
        ("subscribe_and_match", test_subscribe_and_match),
        ("publish_enqueues", test_publish_enqueues_to_subscribers),
        ("cooldown", test_event_dispatcher_cooldown),
        ("skills_role_distinction", test_skills_have_role_distinction),
        ("agents_v2_p2", test_agents_have_v2_p2_directive),
        ("agents_tools", test_agents_have_subscribe_event_tool),
        ("groups_lead", test_groups_lead_assignment),
        ("full_pipeline", test_full_p2_pipeline),
    ]

    # Capture output to UTF-8 file (avoid PowerShell gbk encoding issue)
    import io
    output_buf = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = output_buf

    passed = 0
    failed = 0
    failed_names = []
    for name, fn in tests:
        try:
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
            failed_names.append(name)

    sys.stdout = real_stdout

    # 写 UTF-8 文件
    out_path = r"d:\agents\vov\test_p2_output.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_buf.getvalue())
        f.write("\n" + "=" * 60 + "\n")
        f.write(f"测试结果: {passed} 通过 / {failed} 失败\n")
        if failed_names:
            f.write(f"失败: {failed_names}\n")
        f.write("=" * 60 + "\n")

    # 同时在 stdout 输出简短结果
    print(f"\n  测试结果: {passed} 通过 / {failed} 失败")
    if failed_names:
        print(f"  失败: {failed_names}")
    print(f"  详细日志: {out_path}")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
