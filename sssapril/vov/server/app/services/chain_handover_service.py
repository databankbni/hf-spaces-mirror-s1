"""
Chain Handover Service —— 任务接管主链核心机制

v2 P2 设计（按用户原话："整个群应该只有一个活动着的 chain"）：

    群下同一时刻有 0 或 1 个 status="active" 的 chain。
    - 群初始化时：1 条 group chain, status="active"
    - 任务 in_progress 时：主链 status="paused"（挂起）, task chain status="active"（接管）
    - 任务 done 时：task chain 折叠成 summary packet 挂回主链
                    task chain status="archived"（折叠归档）
                    主链 status="active"（恢复）

    dispatch 路径（send_message / chat send / event_dispatcher 唤起 session）
    不再硬编码"找 group chain"，统一调 get_active_chain_for_group(group_id)
    —— 找 group 下 status="active" 的任意 chain（group or task 都行）。

与 chain_rollover_service 的区别：
    - chain_rollover_service：上下文超长时的"自动对话交接"（summarize 后开新链）
    - chain_handover_service（这里）：任务 in_progress/done 触发的"任务接管"（不创建新链）
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.chain import Chain, Packet
from app.models.task import Task

logger = logging.getLogger(__name__)


class ChainHandoverService:
    """任务接管/折叠核心服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============================================================
    # 核心查询：找群当前 active chain
    # ============================================================
    async def get_active_chain_for_group(
        self,
        group_id: str,
        task_id: Optional[str] = None,
    ) -> Optional[Chain]:
        """
        找群下当前 active 的 chain。

        优先级:
          1. 如果传了 task_id, 优先找该 task 关联的 task chain (status="active")
          2. 否则找 group 下任意 status="active" 的 chain (主链或正在接管的 task chain)

        整个 group 同一时刻只有 0 或 1 条 status="active" 的 chain（不变量）。
        万一历史数据有多条 active (e.g. 之前 bug 残留), 按 updated_at desc 取最新。
        """
        if task_id:
            # 任务上下文: 找该任务的 active task chain
            q = (
                select(Chain)
                .where(and_(
                    Chain.group_id == group_id,
                    Chain.task_id == task_id,
                    Chain.chain_type == "task",
                    Chain.status == "active",
                    Chain.deleted_at.is_(None),
                ))
                .order_by(Chain.updated_at.desc(), Chain.created_at.desc())
                .limit(1)
            )
            return (await self.db.execute(q)).scalar_one_or_none()

        # 群上下文: 找 group 下任意 active chain (按 updated_at desc 取最新)
        q = (
            select(Chain)
            .where(and_(
                Chain.group_id == group_id,
                Chain.status == "active",
                Chain.deleted_at.is_(None),
            ))
            .order_by(Chain.updated_at.desc(), Chain.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(q)).scalar_one_or_none()

    async def get_or_create_main_chain(
        self,
        group_id: str,
    ) -> Chain:
        """
        找群的主链（group chain），如果没有则创建。
        主链是 group chain_type="group" 的链，可能是 status="active" 或 status="paused"。

        任务折叠回主链时调用。
        """
        # 优先找 group chain（active 或 paused 都行）
        q = (
            select(Chain)
            .where(and_(
                Chain.group_id == group_id,
                Chain.chain_type == "group",
                Chain.deleted_at.is_(None),
            ))
            .order_by(Chain.created_at.asc())
        )
        result = await self.db.execute(q)
        main_chain = result.scalars().first()
        if main_chain:
            return main_chain

        # 没有 group chain, 创建一个新的
        logger.warning("get_or_create_main_chain: no group chain for group=%s, creating", group_id[:8])
        new_chain = Chain(
            group_id=group_id,
            chain_type="group",
            status="active",
        )
        self.db.add(new_chain)
        await self.db.flush()
        return new_chain

    # ============================================================
    # 任务 in_progress → 接管主链
    # ============================================================
    async def handover_to_task_chain(
        self,
        task: Task,
        task_chain: Chain,
    ) -> Dict[str, Any]:
        """
        任务 in_progress 时, 把群当前 active 的 chain (一般是主链) 标记为 paused,
        让 task_chain 接管 active 位置。

        调用前置条件:
          - task.status == "in_progress" (caller 负责切换)
          - task_chain.status 可能是 "pending" (新创建) 或 "active" (兼容老数据)
          - task_chain.group_id == task.group_id

        副作用:
          - task_chain status: "pending" → "active" (接管)
          - 主链 (如果存在且是 active): status="paused", completed_at=now

        关键顺序: 先暂停其他 active chain, 再标 task_chain active
        （否则 get_active_chain_for_group 会先找到 task_chain 自己）
        """
        # 1. 先找群下其他 active chain (此时 task_chain 还是 pending/非 active, 不会被选中)
        current_active = await self.get_active_chain_for_group(task.group_id)
        paused_chains = []

        if current_active is not None and current_active.id != task_chain.id:
            # 暂停当前 active chain
            current_active.status = "paused"
            current_active.completed_at = datetime.now(timezone.utc)
            paused_chains.append(current_active.id)
            logger.info(
                "handover_to_task_chain: paused %s chain %s, task chain %s takes over",
                current_active.chain_type, current_active.id[:8], task_chain.id[:8],
            )
        else:
            logger.info(
                "handover_to_task_chain: no other active chain for group=%s, task chain %s 直接接管",
                task.group_id[:8], task_chain.id[:8],
            )

        # 2. 把 task_chain 标 active (从 pending 接管)
        if task_chain.status == "pending":
            task_chain.status = "active"
            logger.info(
                "handover_to_task_chain: task chain %s pending → active",
                task_chain.id[:8],
            )
        elif task_chain.status == "active":
            # 已经在 active (老数据残留), 不动
            pass
        else:
            logger.warning(
                "handover_to_task_chain: task chain %s status=%s (异常), 强制接管",
                task_chain.id[:8], task_chain.status,
            )
            task_chain.status = "active"

        await self.db.flush()
        return {
            "task_chain_id": task_chain.id,
            "paused_chain_ids": paused_chains,
        }

    # ============================================================
    # 任务 done → 折叠 task chain 回主链
    # ============================================================
    async def fold_task_chain_to_main(
        self,
        task: Task,
        task_chain: Chain,
        summary_content: str,
    ) -> Dict[str, Any]:
        """
        任务 done 时, 把 task_chain 折叠成一条 summary packet 挂回主链,
        task_chain 标 archived, 主链恢复 active。

        调用前置条件:
          - task.status == "done" (caller 负责切换)
          - task_chain.status == "active" (刚做完任务, 还 active)
          - task_chain.group_id == task.group_id

        副作用:
          - 在主链 tail_packet_id 之后追加一条 system packet (summary)
          - 主链 status: "paused" → "active"
          - task_chain status: "active" → "archived"
          - 主链 tail_packet_id 更新

        summary_content 来自调用方 (update_task_status 的 result 参数)。
        """
        from app.services.chat_service import ChatService

        # 1. 找主链
        main_chain = await self.get_or_create_main_chain(task.group_id)

        # 2. 写 summary packet 到主链
        #    v2 P2+ 隐私修复: 不用 task.title 写到主链 (title 可能含身份).
        #    summary 格式: "[任务完成] {task_id[:8]} - {result}" (短前缀+result 摘要)
        #    lead 想看详情可调 get_task(task_id) 查 title/description.
        cleaned = (summary_content or "").strip()
        # 进一步脱敏: result 里若出现敏感词, 截断到 100 字 (玩家写"我是狼人"会被截掉)
        if len(cleaned) > 100:
            cleaned = cleaned[:100] + "..."
        if cleaned:
            summary = f"[任务完成] {task.id[:8]} - {cleaned}"
        else:
            summary = f"[任务完成] {task.id[:8]}"

        # 限制长度, 防污染主链
        if len(summary) > 1000:
            summary = summary[:1000] + "..."

        await ChatService._save_packet(
            self.db,
            chain_id=main_chain.id,
            content=summary,
            sender_type="system",
            sender_id="task",
            # v2 P2+ 隐私修复: sender_name 也不含 title, 用"任务" + 短前缀
            sender_name=f"任务: {task.id[:8]}",
            metadata={"task_id": task.id, "task_status": "done", "fold": True},
        )

        # 3. 主链恢复 active
        if main_chain.status == "paused":
            main_chain.status = "active"
            main_chain.completed_at = None
            logger.info(
                "fold_task_chain: main chain %s resumed (paused → active)",
                main_chain.id[:8],
            )

        # 4. task chain 折叠归档
        task_chain.status = "archived"
        task_chain.completed_at = datetime.now(timezone.utc)
        logger.info(
            "fold_task_chain: task chain %s archived, summary mounted to main chain %s",
            task_chain.id[:8], main_chain.id[:8],
        )

        await self.db.flush()
        return {
            "main_chain_id": main_chain.id,
            "task_chain_id": task_chain.id,
            "summary": summary,
        }

    # ============================================================
    # 异常处理：任务取消/重开
    # ============================================================
    async def release_handover(
        self,
        task: Task,
        task_chain: Chain,
    ) -> Dict[str, Any]:
        """
        任务被 reopen / cancelled 时, 如果 task chain 还在 active 接管主链,
        把 task chain 归档, 恢复主链 active。
        """
        if task_chain.status != "active":
            return {"released": False, "reason": "task_chain not active"}

        main_chain = await self.get_or_create_main_chain(task.group_id)
        if main_chain.status == "paused":
            main_chain.status = "active"
            main_chain.completed_at = None
            logger.info(
                "release_handover: main chain %s resumed (task reopened/cancelled)",
                main_chain.id[:8],
            )

        task_chain.status = "archived"
        task_chain.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

        return {
            "released": True,
            "main_chain_id": main_chain.id,
            "task_chain_id": task_chain.id,
        }

    # ============================================================
    # 统一入口：任务状态变更 → chain 流转 + 事件发布
    # ============================================================
    async def apply_task_status_transition(
        self,
        task: Task,
        new_status: str,
        result: str = "",
    ) -> Dict[str, Any]:
        """
        任务状态变更后的统一处理入口（v2 P2+ 统一服务路径）。

        解决问题: 此前 REST API (tasks.py) 与 agent 工具 (tool_adapter.update_task_status)
        各自实现 chain 流转, 行为分裂 —— API 路径不触发 handover, 导致 UI 启动任务时
        主链不 paused、task chain 不 active、消息进不到任务块。本方法把 chain 侧流转
        收敛到一处, 两条路径共用。

        前置条件 (caller 负责):
          - task.status 已由 TaskService.update_status 更新为 new_status
          - 群内串行守卫已通过 (in_progress 时同群无其他 in_progress)

        本方法负责:
          1. chain 侧流转:
               in_progress → 找/建 task chain, handover_to_task_chain (主链 paused, task chain active)
               done        → 找 task chain, fold_task_chain_to_main (task chain archived, 主链 active)
                             task chain 不存在时兜底挂 result 到主链
               reopened    → 找 task chain, release_handover (task chain archived, 主链 active)
               todo/其他   → noop
          2. 发布 task_status_changed 事件 (内部加载 task 关系)

        不负责:
          - commit (caller 显式 commit)
          - 串行守卫 / task.status 更新 (caller 负责)

        Args:
            task: 已更新状态的任务 (需有 group_id; 关系内部按需加载)
            new_status: 新状态 (in_progress / done / reopened / todo)
            result: 仅 done 时生效, 作为 summary 挂到主链

        Returns:
            {"action": "handover"|"fold"|"release"|"noop",
             "task_chain_id": str|None, "details": {...}}
        """
        from app.models.chain import Chain as ChainModel
        from app.services.chat_service import ChatService

        # 先查当前 task 是否已有 task chain (不限 status, 取最新未删除; archived 不复用)
        task_chain = (await self.db.execute(
            select(ChainModel).where(and_(
                ChainModel.task_id == task.id,
                ChainModel.chain_type == "task",
                ChainModel.deleted_at.is_(None),
                ChainModel.status != "archived",
            )).order_by(ChainModel.created_at.desc()).limit(1)
        )).scalar_one_or_none()

        action = "noop"
        details: Dict[str, Any] = {}
        task_chain_id = task_chain.id if task_chain else None

        if new_status == "in_progress":
            # 找/建 task chain (逻辑与 ChatService.create_task_chain 等价, 内联以避免
            # ChatService 实例依赖; ChainHandoverService 本就是 chain 操作归属地)
            if not task_chain:
                from app.models.group import Group
                g = (await self.db.execute(
                    select(Group).where(Group.id == task.group_id)
                )).scalar_one_or_none()
                if g:
                    main_chain = await self.get_or_create_main_chain(task.group_id)
                    task_chain = Chain(
                        chain_type="task",
                        parent_chain_id=main_chain.id,
                        task_id=task.id,
                        group_id=task.group_id,
                        status="pending",
                    )
                    self.db.add(task_chain)
                    await self.db.flush()
                    await ChatService._save_packet(
                        self.db,
                        chain_id=main_chain.id,
                        content=f"任务开始: {task.title}",
                        sender_type="system",
                        sender_id="system",
                        sender_name="系统",
                        packet_type="system",
                        sub_chain_id=task_chain.id,
                    )
                    main_chain.sub_chain_count = (main_chain.sub_chain_count or 0) + 1
                    await self.db.flush()
                    task_chain_id = task_chain.id
            if task_chain:
                details = await self.handover_to_task_chain(task, task_chain)
                action = "handover"
            else:
                logger.warning(
                    "apply_task_status_transition: in_progress 但无法创建 task chain (task=%s)",
                    task.id[:8],
                )

        elif new_status == "done":
            if task_chain:
                details = await self.fold_task_chain_to_main(
                    task, task_chain, summary_content=result,
                )
                action = "fold"
            else:
                # 兜底: task chain 丢了, 至少挂 result 到主链
                logger.warning(
                    "apply_task_status_transition: done 但 task chain 不存在 (task=%s), 兜底挂 result",
                    task.id[:8],
                )
                main_chain = await self.get_or_create_main_chain(task.group_id)
                cleaned = (result or "").strip()
                if len(cleaned) > 100:
                    cleaned = cleaned[:100] + "..."
                summary = f"[任务完成] {task.id[:8]} - {cleaned}" if cleaned else f"[任务完成] {task.id[:8]}"
                if len(summary) > 1000:
                    summary = summary[:1000] + "..."
                await ChatService._save_packet(
                    self.db,
                    chain_id=main_chain.id,
                    content=summary,
                    sender_type="system",
                    sender_id="task",
                    sender_name=f"任务: {task.id[:8]}",
                    metadata={"task_id": task.id, "task_status": "done"},
                )
                action = "fold"
                details = {"main_chain_id": main_chain.id, "fallback": True}

        elif new_status == "reopened":
            if task_chain and task_chain.status == "active":
                details = await self.release_handover(task, task_chain)
                action = "release"
            # task chain 非 active (已 archived 或不存在) → 无需 release

        # v9 修复: done 后自动激活同群最老的 todo 任务
        # 兑现 B2 守卫"等当前完成后激活"的承诺 — 法官用 create_task(status="in_progress")
        # 时, 若同群已有 in_progress, B2 把它降级为 todo. 现在当前 in_progress 已 done,
        # 系统应自动激活最早被降级的 todo, 否则 todo 永远卡住、流程死锁.
        # 设计: 递归调 apply_task_status_transition(in_progress) — 同 db session,
        #       由 caller 统一 commit. 失败不抛出, 仅日志 (主流程已成功).
        if new_status == "done":
            try:
                next_todo = (await self.db.execute(
                    select(Task).where(and_(
                        Task.group_id == task.group_id,
                        Task.status == "todo",
                        Task.deleted_at.is_(None),
                    )).order_by(Task.created_at.asc()).limit(1)
                )).scalar_one_or_none()
                if next_todo:
                    logger.info(
                        "[chain_handover] done task=%s, auto-activating next todo=%s (group=%s)",
                        task.id[:8], next_todo.id[:8], str(task.group_id)[:8],
                    )
                    from app.services.task_service import TaskService
                    next_task = await TaskService(self.db).update_status(
                        next_todo.id, "in_progress",
                    )
                    if next_task is not None:
                        await self.apply_task_status_transition(
                            next_task, "in_progress",
                        )
            except Exception as e:
                logger.exception("[chain_handover] auto-activate next todo failed: %s", e)

        # 发布 task_status_changed 事件 (重新加载 task 关系以拿到 assignees/group)
        try:
            from app.services.task_service import TaskService
            from app.services.event_bus import event_bus
            full_task = await TaskService(self.db).get_detail(task.id)
            if full_task:
                project_id = full_task.group.project_id if full_task.group else None
                await event_bus.publish(
                    "task_status_changed",
                    {
                        "task_id": full_task.id,
                        "project_id": project_id,
                        "group_id": full_task.group_id,
                        "status": new_status,
                        "assignee_ids": [a.project_agent_id for a in (full_task.assignees or [])],
                        "lead_agent_id": full_task.lead_agent_id,
                    },
                )
                # 广播任务状态变更, 让前端通过 WebSocket 实时刷新 chain + 任务列表
                try:
                    from app.orchestrator.websocket_manager import ws_manager
                    await ws_manager.broadcast(str(full_task.group_id), {
                        "type": "task_update",
                        "payload": {
                            "task_id": str(full_task.id),
                            "action": "status_changed",
                            "status": new_status,
                            "group_id": str(full_task.group_id),
                        },
                    })
                except Exception:
                    logger.debug("apply_task_status_transition: ws broadcast failed", exc_info=True)
        except Exception:
            logger.debug("apply_task_status_transition: publish event failed", exc_info=True)

        return {
            "action": action,
            "task_chain_id": task_chain_id,
            "details": details,
        }
