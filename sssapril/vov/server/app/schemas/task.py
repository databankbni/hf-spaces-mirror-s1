"""
任务Schema模块

定义任务(Task)相关的Pydantic schemas。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .common import TimestampMixin


class TaskBase(BaseModel):
    """任务基础Schema"""
    title: str = Field(..., min_length=1, max_length=255, description="任务标题")
    description: Optional[str] = Field(None, description="任务描述")
    lead_agent_id: Optional[str] = Field(None, description="主导Agent ID")
    status: str = Field("todo", description="状态: todo/in_progress/done/reopened")
    order_index: int = Field(0, description="排序索引")
    acceptance_criteria: Optional[str] = Field(None, description="验收标准")
    context_data: Dict[str, Any] = Field(default_factory=dict, description="任务上下文数据")
    # v2 P2: 任务级开关 —— 任务链是否继承主链截至分支点的历史
    # true (默认, 适合狼人杀/公告场景): 玩家能看到法官在主链发过的公告
    # false (高敏感场景如身份下发): task chain 完全隔离, 不读主链历史
    inherit_main_chain: bool = Field(
        True,
        description="v2 P2: 任务链是否继承主链截至分支点的历史. true=继承(默认), false=完全隔离"
    )


class TaskCreate(TaskBase):
    """创建任务请求"""
    assignee_ids: List[str] = Field(default_factory=list, description="指派Agent ID列表")


class TaskUpdate(BaseModel):
    """更新任务请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=255, description="任务标题")
    description: Optional[str] = Field(None, description="任务描述")
    lead_agent_id: Optional[str] = Field(None, description="主导Agent ID")
    status: Optional[str] = Field(None, description="状态")
    order_index: Optional[int] = Field(None, description="排序索引")
    acceptance_criteria: Optional[str] = Field(None, description="验收标准")
    context_data: Optional[Dict[str, Any]] = Field(None, description="任务上下文数据")
    assignee_ids: Optional[List[str]] = Field(None, description="指派Agent ID列表")
    inherit_main_chain: Optional[bool] = Field(None, description="v2 P2: 任务链是否继承主链历史")


class TaskUpdateStatus(BaseModel):
    """更新任务状态请求"""
    status: str = Field(..., description="新状态: in_progress/done/reopened")


class TaskResponse(TaskBase, TimestampMixin):
    """任务响应"""
    id: str = Field(..., description="任务ID")
    group_id: str = Field(..., description="群聊ID")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")

    class Config:
        from_attributes = True


class TaskListItem(BaseModel):
    """任务列表项"""
    id: str = Field(..., description="任务ID")
    group_id: str = Field(..., description="群聊ID")
    title: str = Field(..., description="任务标题")
    status: str = Field(..., description="状态")
    order_index: int = Field(..., description="排序索引")
    lead_agent_id: Optional[str] = Field(None, description="主导Agent ID")
    assignee_count: int = Field(0, description="指派数量")
    has_chain: bool = Field(False, description="是否有讨论链")
    has_deliverable: bool = Field(False, description="是否有交付物")
    created_at: datetime = Field(..., description="创建时间")

    @classmethod
    def from_task(cls, task, resources_by_task: Optional[Dict[str, int]] = None) -> "TaskListItem":
        """
        v2 P2: 从 Task ORM 模型构造列表项，显式计算 assignee_count / has_chain / has_deliverable。
        之前 assignee_count/has_chain 默认是 0/False, 列表显示永远是"无指派/无链"。
        现在从 ORM 关系直接读（selectinload 已加载），避免 N+1 查询。

        has_chain: Task.chain 存在（task chain 是 v2 P2 才补建的, 之前 API 才建）
        has_deliverable: 满足任一条件即视为有交付物
          - Task.deliverable 关系存在（旧路径, 显式 create_deliverable）
          - 该 task 关联了任意非文件夹 Resource（v2 P2 新路径, write_resource 自动挂 task_id）

        Args:
            task: Task ORM 实例
            resources_by_task: {task_id: 资源数(非folder)} 预计算的 dict, 避免 N+1
        """
        from app.models.resource import Resource  # noqa: F401  仅用作 hint

        assignees = getattr(task, "assignees", None) or []
        chain = getattr(task, "chain", None)
        deliverable = getattr(task, "deliverable", None)

        # 计算 has_deliverable: 也算上挂到本 task 的资源（v2 P2 write_resource 自动挂 task_id）
        resource_count = 0
        if resources_by_task is not None:
            resource_count = resources_by_task.get(task.id, 0)
        has_resource = resource_count > 0

        return cls(
            id=task.id,
            group_id=task.group_id,
            title=task.title,
            status=task.status,
            order_index=task.order_index,
            lead_agent_id=task.lead_agent_id,
            assignee_count=len(assignees),
            has_chain=chain is not None,
            has_deliverable=(deliverable is not None) or has_resource,
            created_at=task.created_at,
        )

    class Config:
        from_attributes = True


class TaskAssigneeResponse(BaseModel):
    """任务指派响应"""
    id: str = Field(..., description="指派ID")
    task_id: str = Field(..., description="任务ID")
    project_agent_id: str = Field(..., description="项目Agent ID")
    agent_name: Optional[str] = Field(None, description="Agent名称")
    created_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True
