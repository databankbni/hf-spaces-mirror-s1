"""
项目模型模块

定义项目(Project)相关的数据库模型。
"""

from typing import Optional, List
from sqlalchemy import String, Text, JSON, Integer, Boolean, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Project(BaseModel):
    """
    项目模型

    项目是最顶层的组织单元，包含群聊、Agent、资料等。

    Attributes:
        name: 项目名称
        description: 项目描述
        cover_color: 封面渐变色
        tags: 项目标签列表
        status: 项目状态（active/paused/completed/archived）
        workflow_config: 工作流配置

    Relationships:
        groups: 项目下的群聊列表
        project_agents: 项目关联的Agent
        resources: 项目全局资源
        tags_definitions: 项目自定义标签
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name="projects_status_check"
        ),
        {"comment": "项目表"}
    )

    # 基本信息
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="项目名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="项目描述"
    )

    cover_color: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="封面渐变色，如 'from-violet-500 to-purple-600'"
    )

    tags: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="项目标签列表"
    )

    # 状态
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
        comment="项目状态: active/paused/completed/archived"
    )

    # 用途标记：是否为引导 project（每用户一个，用于承载引导 agent，不在"我的项目"列表展示）
    is_guide: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="是否为引导 project（引导 agent 工作容器，不在项目列表展示）"
    )

    # 工作流配置
    workflow_config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="工作流配置，如自动推进设置"
    )

    # ★ v2 P1: 可选 hint 字段（按 §0.5 原则, 不锁死流程, agent 自己决定用不用）
    autonomy_hint: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="自动化级别 hint（自然语言描述, 如 'full 用户离线时全自动'/'semi 关键决策等用户'/'manual 每步等用户'）, agent 自己解读"
    )

    review_mode_hint: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="review 模式 hint（自然语言描述, 如 '本项目用 peer review'）, agent 自由选择"
    )

    idle_threshold_seconds: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
        comment="agent 多久无活动视为'卡住'（系统 query_activity 用）"
    )

    # 关系（延迟导入避免循环引用）
    groups = relationship("Group", back_populates="project", lazy="selectin")
    project_agents = relationship("ProjectAgent", back_populates="project", lazy="selectin")
    resources = relationship("Resource", back_populates="project", lazy="selectin")
