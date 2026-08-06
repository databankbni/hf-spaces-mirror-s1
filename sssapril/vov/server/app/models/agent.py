"""
Agent模型模块

定义Agent相关的数据库模型，包括全局Agent、Agent工具、Agent技能。
"""

from typing import Optional, List
from sqlalchemy import String, Text, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import BaseModel


class Agent(BaseModel):
    """
    全局Agent模型

    Agent是可复用的AI角色定义，可在多个项目中使用。

    Attributes:
        name: Agent名称
        avatar: 头像（URL或emoji）
        description: 描述（给其他Agent和用户看）
        system_prompt: 系统提示词
        llm_config: 模型配置（model、temperature等）
        capabilities: 能力描述列表
        is_active: 是否启用

    Relationships:
        tools: Agent绑定的工具列表
        skills: Agent绑定的技能列表
        project_agents: Agent在各项目中的实例

    v2 P3: 删除 role 字段. 设计反思: role 原本是"职业分类"枚举
    (writer/critic/...), 但实际**没有代码依赖它做逻辑**——只用作显示标签.
    这是把"分类标签"硬编码为"枚举类型"的反模式. 删除后:
    - agent 的"职业身份"由 system_prompt + tools + skill_refs 表达
    - "分类/标签"留给项目层通过 capabilities 描述
    - 不再有数据库层硬编码的白名单
    """

    __tablename__ = "agents"
    __table_args__ = (
        {"comment": "全局Agent表"}
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Agent名称"
    )

    avatar: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="头像URL或emoji"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Agent描述"
    )

    system_prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="系统提示词"
    )

    llm_config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="模型配置，如 {model: 'gpt-4o', temperature: 0.7}"
    )

    capabilities: Mapped[list] = mapped_column(
        JSON,
        default=list,
        comment="能力描述列表"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="是否启用"
    )

    # v2 P2: 是否强制首轮 LLM 调用 tool（tool_choice="required"）。
    # 用途: 某些 agent（如项目总控 / 协调者）必须调工具才能完成工作,
    #      不能让 LLM 自由选（否则它可能只回文本不动状态）。
    # 设计原则: 这是**机制开关**, 由 agent 定义者显式声明.
    #      不是平台根据 capability 文本"猜"出来的.
    force_tool_choice: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="首轮 LLM 是否必须调用工具（tool_choice=required）"
    )

    # 关系
    tools: Mapped[List["AgentTool"]] = relationship(
        "AgentTool",
        back_populates="agent",
        lazy="selectin",
        cascade="all, delete-orphan"
    )

    skills: Mapped[List["Skill"]] = relationship(
        "Skill",
        secondary="agent_skills",
        back_populates="agents",
        lazy="selectin",
    )


class AgentTool(BaseModel):
    """
    Agent工具绑定模型

    定义Agent可以调用的工具。

    Attributes:
        agent_id: 关联的Agent ID
        name: 工具名称（显示用）
        kind: 工具处理器标识（对应 agentflow processor kind，如 search_resources）
        description: 工具描述
        tool_type: 工具类型（builtin/function/api）
        config: 工具配置
    """

    __tablename__ = "agent_tools"
    __table_args__ = (
        UniqueConstraint("agent_id", "name", name="agent_tools_unique"),
        {"comment": "Agent工具绑定表"}
    )

    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的Agent ID"
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="工具名称"
    )

    kind: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="工具处理器标识，对应 agentflow processor kind"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="工具描述"
    )

    tool_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="工具类型: builtin/function/api"
    )

    config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="工具配置"
    )

    # 关系
    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="tools"
    )


class Skill(BaseModel):
    """
    独立技能模型

    技能是可复用的能力模块，可被多个Agent绑定。

    Attributes:
        name: 技能名称
        description: 技能描述
        skill_type: 技能类型（prompt/template/function）
        content: 技能内容（提示词模板等）
        config: 技能配置
    """

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("name", name="skills_name_unique"),
        {"comment": "独立技能表"}
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="技能名称"
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="技能描述"
    )

    skill_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="技能类型: prompt/template/function"
    )

    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="技能内容"
    )

    config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="技能配置"
    )

    files: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="附加文件 {filename: content}"
    )

    # 关系：多对多通过 junction 表关联到 Agent
    agents: Mapped[List["Agent"]] = relationship(
        "Agent",
        secondary="agent_skills",
        back_populates="skills",
        lazy="selectin",
    )


class AgentSkill(BaseModel):
    """
    Agent-技能关联表（多对多 junction）

    Attributes:
        agent_id: Agent ID
        skill_id: 技能ID
    """

    __tablename__ = "agent_skills"
    __table_args__ = (
        UniqueConstraint("agent_id", "skill_id", name="agent_skill_unique"),
        {"comment": "Agent技能关联表"}
    )

    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Agent ID"
    )

    skill_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="技能ID"
    )


class ProjectAgent(BaseModel):
    """
    项目级Agent模型

    将全局Agent关联到项目，可覆盖部分配置。

    Attributes:
        project_id: 项目ID
        agent_id: 全局Agent ID
        override_config: 项目内覆盖配置

    Relationships:
        agent: 关联的全局Agent
        group_members: Agent加入的群聊
    """

    __tablename__ = "project_agents"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", name="project_agents_unique"),
        {"comment": "项目级Agent关联表"}
    )

    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目ID"
    )

    agent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="全局Agent ID"
    )

    override_config: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        comment="项目内覆盖配置"
    )

    # 关系
    agent: Mapped["Agent"] = relationship(
        "Agent",
        lazy="selectin"
    )
    project = relationship("Project", back_populates="project_agents")

    group_members = relationship("GroupMember", back_populates="project_agent", lazy="selectin")
