"""
Agent Schema模块

定义Agent相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


# Agent Tool schemas
class AgentToolBase(BaseModel):
    """Agent工具基础Schema"""
    name: str = Field(..., min_length=1, max_length=100, description="工具名称")
    kind: Optional[str] = Field(None, description="工具处理器标识，对应 agentflow processor kind")
    description: Optional[str] = Field(None, description="工具说明")
    tool_type: str = Field("function", description="工具类型")
    config: Dict[str, Any] = Field(default_factory=dict, description="工具配置")


class AgentToolCreate(AgentToolBase):
    """创建Agent工具请求"""
    pass


class AgentToolResponse(AgentToolBase):
    """Agent工具响应"""
    id: str = Field(..., description="工具ID")
    agent_id: str = Field(..., description="Agent ID")

    class Config:
        from_attributes = True


# Skill schemas (独立技能)
class SkillBase(BaseModel):
    """技能基础Schema"""
    name: str = Field(..., min_length=1, max_length=100, description="技能名称")
    description: Optional[str] = Field(None, description="技能说明")
    skill_type: str = Field("prompt", description="技能类型")
    content: Optional[str] = Field(None, description="技能内容（提示词模板等）")
    config: Dict[str, Any] = Field(default_factory=dict, description="技能配置")
    files: Dict[str, str] = Field(default_factory=dict, description="附加文件 {filename: content}")


class SkillCreate(SkillBase):
    """创建技能请求"""
    pass


class SkillUpdate(BaseModel):
    """更新技能请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="技能名称")
    description: Optional[str] = Field(None, description="技能说明")
    skill_type: Optional[str] = Field(None, description="技能类型")
    content: Optional[str] = Field(None, description="技能内容")
    config: Optional[Dict[str, Any]] = Field(None, description="技能配置")
    files: Optional[Dict[str, str]] = Field(None, description="附加文件")


class SkillResponse(SkillBase):
    """技能响应"""
    id: str = Field(..., description="技能ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    class Config:
        from_attributes = True


# Agent schemas
class AgentBase(BaseModel):
    """Agent基础Schema"""
    name: str = Field(..., min_length=1, max_length=100, description="Agent名称")
    # v2 P3: 删除 role 字段. Agent 的"职业身份"由 system_prompt 表达, 分类由 capabilities 描述.
    avatar: Optional[str] = Field(None, description="头像URL或emoji")
    description: Optional[str] = Field(None, description="Agent描述")
    system_prompt: str = Field(..., description="系统提示词")
    llm_config: Dict[str, Any] = Field(default_factory=dict, description="模型配置，如 {model: 'gpt-4o', temperature: 0.7}")
    capabilities: List[str] = Field(default_factory=list, description="能力列表")
    is_active: bool = Field(True, description="是否启用")


class AgentCreate(AgentBase):
    """创建Agent请求"""
    tools: List[AgentToolCreate] = Field(default_factory=list, description="工具列表")
    skill_ids: List[str] = Field(default_factory=list, description="绑定的技能ID列表")


class AgentUpdate(BaseModel):
    """更新Agent请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Agent名称")
    # v2 P3: 删除 role 字段
    avatar: Optional[str] = Field(None, description="头像URL或emoji")
    description: Optional[str] = Field(None, description="Agent描述")
    system_prompt: Optional[str] = Field(None, description="系统提示词")
    llm_config: Optional[Dict[str, Any]] = Field(None, description="模型配置")
    capabilities: Optional[List[str]] = Field(None, description="能力列表")
    is_active: Optional[bool] = Field(None, description="是否启用")
    tools: Optional[List[AgentToolCreate]] = Field(None, description="工具列表")
    skill_ids: Optional[List[str]] = Field(None, description="绑定的技能ID列表")


class AgentResponse(AgentBase, TimestampMixin):
    """Agent响应"""
    id: str = Field(..., description="Agent ID")

    class Config:
        from_attributes = True


class AgentDetailResponse(AgentResponse):
    """Agent详情响应（包含工具和技能）"""
    tools: List[AgentToolResponse] = Field(default_factory=list, description="工具列表")
    skills: List[SkillResponse] = Field(default_factory=list, description="技能列表")


# Project Agent schemas
class ProjectAgentBase(BaseModel):
    """项目Agent基础Schema"""
    agent_id: str = Field(..., description="Agent ID")
    override_config: Dict[str, Any] = Field(default_factory=dict, description="覆盖配置")


class ProjectAgentCreate(ProjectAgentBase):
    """添加Agent到项目请求"""
    pass


class ProjectAgentResponse(BaseModel):
    """项目Agent响应"""
    id: str = Field(..., description="项目Agent ID")
    project_id: str = Field(..., description="项目ID")
    agent_id: str = Field(..., description="Agent ID")
    agent: Optional["AgentDetailResponse"] = Field(None, description="关联的Agent详情（含工具和技能）")
    override_config: Dict[str, Any] = Field(default_factory=dict, description="覆盖配置")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True
