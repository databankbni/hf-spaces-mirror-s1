"""
群聊模型模块

定义群聊(Group)和群聊成员(GroupMember)相关的数据库模型。
"""

from typing import Optional, List
from sqlalchemy import String, Text, JSON, Boolean, Integer, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Group(BaseModel):
    """
    群聊模型

    群聊是项目内的协作阶段，包含任务和成员Agent。

    Attributes:
        project_id: 所属项目ID
        lead_agent_id: 主导Agent ID（群主）
        name: 群聊名称
        description: 群聊描述
        status: 群聊状态（pending/active/completed）
        order_index: 排序索引
        autonomy_level: 自主级别（full_auto/semi_auto/manual）
        auto_advance: 完成后是否自动推进

    Relationships:
        project: 所属项目
        lead_agent: 主导Agent
        members: 群聊成员列表
        tasks: 群聊任务列表
        resources: 群聊资源列表
        deliverables: 群聊交付物列表
    """

    __tablename__ = "groups"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'completed')",
            name="groups_status_check"
        ),
        CheckConstraint(
            "autonomy_level IN ('full_auto', 'semi_auto', 'manual')",
            name="groups_autonomy_check"
        ),
        {"comment": "群聊表"}
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID"
    )

    lead_agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("project_agents.id"),
        nullable=True,
        comment="主导Agent ID"
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="群聊名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="群聊描述"
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        comment="群聊状态: pending/active/completed"
    )

    order_index: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="排序索引"
    )

    autonomy_level: Mapped[str] = mapped_column(
        String(20),
        default="semi_auto",
        nullable=False,
        comment="自主级别: full_auto/semi_auto/manual"
    )

    auto_advance: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="完成后是否自动推进到下一个群聊"
    )

    # v2 P2: 群级工作流配置 (执行变体 / 反馈模式 / pipeline 节点元数据等)
    # 之前 context_builder 已用 getattr 安全读 (or {} 兜底), 现在补上 model 字段
    # 真正可写。结构由 agent / 模板自由约定, 如:
    #   {
    #     "execution_variant": "A",          # 配合 ExecutionModeService A/B 测试
    #     "pipeline_node_id": "g3",           # 关联到项目 pipeline 资源
    #     "feedback_overrides": {...}         # 群级覆盖项目级 feedback
    #   }
    workflow_config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="群级工作流配置 (执行变体 / pipeline 节点元数据)"
    )

    # 群级开关：true 时, update_task_status(done) 不再强制要求存在 deliverable。
    # 适用场景: 群 description 写了"必出 deliverable", 但实际工作流是写资源到
    # resources 表 (write_resource), agent 不知道要先调 create_deliverable。
    # 默认 false 保留 P0 强约束, 由项目/模板按需开启。
    bypass_deliverable_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="true: 跳过 update_task_status(done) 的 deliverable 存在性检查"
    )

    # 空闲 Watchdog 群级开关: true 时 EventDispatcher 的 idle watchdog 监控本群,
    # false 时跳过 (避免用户暂时不关心的群被反复激活 lead 消耗 LLM token)。
    # 默认 true 保持向后兼容, 用户在 EditGroupModal 可关闭。
    watchdog_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="true: 空闲 watchdog 监控该群; false: 跳过"
    )

    # 关系
    project = relationship("Project", back_populates="groups")
    lead_agent = relationship("ProjectAgent", foreign_keys=[lead_agent_id])
    members: Mapped[List["GroupMember"]] = relationship(
        "GroupMember",
        back_populates="group",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task",
        back_populates="group",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    resources = relationship("Resource", back_populates="group", lazy="selectin")
    deliverables = relationship("Deliverable", back_populates="group", lazy="selectin")


class GroupMember(BaseModel):
    """
    群聊成员模型

    记录Agent加入群聊的信息。

    Attributes:
        group_id: 群聊ID
        project_agent_id: 项目Agent ID
        role: 成员角色（lead/participant）

    Relationships:
        group: 所属群聊
        project_agent: 关联的项目Agent
    """

    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "project_agent_id", name="group_members_unique"),
        {"comment": "群聊成员表"}
    )

    group_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="群聊ID"
    )

    project_agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("project_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目Agent ID"
    )

    role: Mapped[str] = mapped_column(
        String(20),
        default="participant",
        nullable=False,
        comment="成员角色: lead/participant"
    )

    # 关系
    group: Mapped["Group"] = relationship(
        "Group",
        back_populates="members"
    )
    project_agent: Mapped["ProjectAgent"] = relationship(
        "ProjectAgent",
        lazy="selectin"
    )

    @property
    def agent(self):
        """便捷访问关联的Agent"""
        return self.project_agent.agent if self.project_agent else None
