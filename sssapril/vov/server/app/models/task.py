"""
任务模型模块

定义任务(Task)和任务指派(TaskAssignee)相关的数据库模型。
"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy import String, Text, JSON, Integer, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Task(BaseModel):
    """
    任务模型

    任务是群聊内的具体工作单元，有明确的验收标准和状态。

    Attributes:
        group_id: 所属群聊ID
        lead_agent_id: 任务主导Agent ID
        title: 任务标题
        description: 任务描述
        status: 任务状态（todo/in_progress/done/reopened）
        order_index: 排序索引
        acceptance_criteria: 验收标准
        started_at: 开始时间
        completed_at: 完成时间

    Relationships:
        group: 所属群聊
        lead_agent: 主导Agent
        assignees: 指派的Agent列表
        chain: 讨论链
        deliverable: 交付物
    """

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'reopened')",
            name="tasks_status_check"
        ),
        {"comment": "任务表"}
    )

    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属群聊ID"
    )

    lead_agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("project_agents.id"),
        nullable=True,
        comment="任务主导Agent ID"
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="任务标题"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="任务描述"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="todo",
        nullable=False,
        comment="任务状态: todo/in_progress/done/reopened"
    )

    order_index: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="排序索引"
    )

    acceptance_criteria: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="验收标准"
    )

    context_data: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="任务上下文数据"
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="开始时间"
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="完成时间"
    )

    # ★ v2 P1: 可选 hint 字段（按 §0.5 原则, 不锁死流程, agent 自己决定用不用）
    verify_hint: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="验证方式 hint（自然语言描述, 如 '建议由群内 lead 互评'）, agent 可忽略"
    )

    max_revisions_hint: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="建议重做次数 hint, agent 可自行决定"
    )

    suggested_reviewer_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("project_agents.id"),
        nullable=True,
        comment="建议的 reviewer agent id (hint), agent 可自行决定换人"
    )

    # ★ v2 P2: inherit_main_chain —— 任务链是否继承主链历史
    # True (默认): task chain 上下文 = 主链截至分支点的历史 + task chain 自身历史
    #              适合狼人杀等需要看到法官之前公告的场景
    # False:       task chain 完全隔离, 只看 task chain 自身历史
    #              适合身份下发等高敏感场景（避免玩家看到法官/其他玩家在主链的交流）
    inherit_main_chain: Mapped[bool] = mapped_column(
        # SQLite 没有 boolean, 用 Integer
        Integer,
        default=1,
        nullable=False,
        comment="v2 P2: 任务链是否继承主链截至分支点的历史。1=继承(默认), 0=完全隔离"
    )

    # 关系
    group: Mapped["Group"] = relationship(
        "Group",
        back_populates="tasks"
    )
    lead_agent = relationship("ProjectAgent", foreign_keys=[lead_agent_id])
    suggested_reviewer = relationship("ProjectAgent", foreign_keys=[suggested_reviewer_id])
    assignees: Mapped[List["TaskAssignee"]] = relationship(
        "TaskAssignee",
        back_populates="task",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    chain: Mapped[Optional["Chain"]] = relationship(
        "Chain",
        back_populates="task",
        uselist=False,
        lazy="selectin"
    )
    deliverable = relationship("Deliverable", back_populates="task", uselist=False, lazy="selectin")


class TaskAssignee(BaseModel):
    """
    任务指派模型

    记录Agent被指派到任务的信息。

    Attributes:
        task_id: 任务ID
        project_agent_id: 项目Agent ID
    """

    __tablename__ = "task_assignees"
    __table_args__ = (
        UniqueConstraint("task_id", "project_agent_id", name="task_assignees_unique"),
        {"comment": "任务指派表"}
    )

    task_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID"
    )

    project_agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目Agent ID"
    )

    # 关系
    task: Mapped["Task"] = relationship(
        "Task",
        back_populates="assignees"
    )
    project_agent: Mapped["ProjectAgent"] = relationship(
        "ProjectAgent",
        lazy="selectin"
    )
