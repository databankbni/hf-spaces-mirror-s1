"""
ToolServiceAdapter Protocol

定义 agentflow 工具处理器与外部服务之间的接口。
agentflow 的 CRUD/Resource/Skill 处理器通过此协议调用 server 服务，
保持 agentflow 与 server 的解耦。

server 端提供具体实现（ServerToolAdapter），
通过 Workspace.tool_adapter 注入到 agentflow 管线中。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class ToolServiceAdapter(Protocol):
    """
    工具服务适配器协议

    agentflow 的工具处理器通过此接口调用外部服务。
    每个方法对应一个 CRUD 操作，返回字典格式的结果。

    实现要求：
    - 方法必须是 async 的（工具处理器通过 asyncio.run() 调用）
    - 返回值统一为 dict，包含操作结果
    - 异常时抛出具体异常，由处理器捕获转为 ERROR 包
    """

    # ── Project ──

    async def create_project(self, name: str, description: str = "") -> Dict[str, Any]:
        """创建项目，返回项目信息"""
        ...

    async def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        ...

    async def list_user_projects(self) -> List[Dict[str, Any]]:
        """列出所有用户项目（排除 is_guide=True 的引导 project）"""
        ...

    async def get_project(self, project_id: str) -> Dict[str, Any]:
        """获取项目详情"""
        ...

    # ── Group ──

    async def create_group(self, project_id: str, name: str, description: str = "") -> Dict[str, Any]:
        """在项目下创建群聊"""
        ...

    async def list_groups(self, project_id: str) -> List[Dict[str, Any]]:
        """列出项目下的群聊"""
        ...

    async def get_group(self, group_id: str) -> Dict[str, Any]:
        """获取群聊详情"""
        ...

    async def update_group(self, group_id: str, name: Optional[str] = None, description: Optional[str] = None, status: Optional[str] = None, autonomy_level: Optional[str] = None, auto_advance: Optional[bool] = None) -> Dict[str, Any]:
        """更新群聊信息"""
        ...

    async def delete_group(self, group_id: str) -> Dict[str, Any]:
        """删除群聊"""
        ...

    # ── Agent 邀请 ──

    async def invite_agent(self, project_id: str, agent_id: str) -> Dict[str, Any]:
        """邀请 Agent 到项目"""
        ...

    async def list_project_agents(self, project_id: str) -> List[Dict[str, Any]]:
        """列出项目中的 Agent"""
        ...

    # ── Group Member ──

    async def add_group_member(self, group_id: str, project_agent_id: str, role: str = "member") -> Dict[str, Any]:
        """添加群聊成员"""
        ...

    async def list_group_members(self, group_id: str) -> List[Dict[str, Any]]:
        """列出群聊成员"""
        ...

    # ── Task ──

    async def create_task(
        self,
        group_id: str,
        title: str,
        description: str = "",
        assignee_agent_name: Optional[str] = None,
        inherit_main_chain: bool = True,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建任务。inherit_main_chain 决定 task chain 是否继承主链截至分支点的历史。
        status='in_progress' 时创建后立即切 chain + 唤醒 assignee。"""
        ...

    async def list_tasks(self, group_id: str) -> List[Dict[str, Any]]:
        """列出群聊下的任务"""
        ...

    async def update_task_status(self, task_id: str, status: str, result: str = "") -> Dict[str, Any]:
        """更新任务状态。可选 result 在 status=done 时挂到主链。"""
        ...

    # ── Deliverable ──

    async def create_deliverable(self, group_id: str, title: str, content: str = "", scope: str = "project") -> Dict[str, Any]:
        """创建交付物"""
        ...

    async def list_deliverables(self, group_id: str) -> List[Dict[str, Any]]:
        """列出交付物"""
        ...

    # ── Message ──

    async def send_message(self, group_id: str, content: str) -> Dict[str, Any]:
        """发送消息到群聊"""
        ...

    # ── Memory ──

    async def set_memory(
        self,
        agent_id: str,
        project_id: str,
        content: str,
        slug: str = "default",
        tags: Optional[List[str]] = None,
        mode: str = "replace",
        find: Optional[str] = None,
        replace_with: Optional[str] = None,
        section_heading: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建/更新 Agent 笔记（支持多种更新模式）"""
        ...

    async def create_memory(self, **kwargs) -> Dict[str, Any]:
        """向后兼容：create_memory → set_memory"""
        return await self.set_memory(**kwargs)

    async def get_memory(self, agent_id: str, project_id: str) -> Optional[Dict[str, Any]]:
        """获取 Agent 笔记"""
        ...

    # ── Resource（替代文件系统） ──

    async def read_resource(self, resource_id: str) -> Dict[str, Any]:
        """读取资源内容"""
        ...

    async def write_resource(
        self,
        project_id: str,
        title: str,
        content: str,
        resource_type: str = "note",
        content_type: Optional[str] = None,
        group_id: Optional[str] = None,
        is_required: bool = False,
    ) -> Dict[str, Any]:
        """创建/更新资源"""
        ...

    async def search_resources(self, project_id: str, query: str) -> List[Dict[str, Any]]:
        """搜索资源"""
        ...

    # ── Agent Skill（DB 存储） ──

    async def list_agent_skills(self, agent_id: str) -> List[Dict[str, Any]]:
        """列出 Agent 的技能"""
        ...

    async def read_agent_skill(self, agent_id: str, skill_name: str, file_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """读取指定技能内容，file_path 可指定读取技能内的某个附加文件"""
        ...

    async def list_skill_files(self, agent_id: str, skill_name: str) -> Optional[Dict[str, Any]]:
        """列出技能的附加文件列表"""
        ...

    # ── Agent 管理 ──

    async def list_agents(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """列出所有全局 Agent"""
        ...

    async def get_agent(self, agent_id: str) -> Dict[str, Any]:
        """获取 Agent 详情（含工具和技能）"""
        ...

    async def create_agent(
        self,
        name: str,
        system_prompt: str,
        role: str = "custom",
        description: str = "",
        avatar: str = "🤖",
        llm_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """创建全局 Agent"""
        ...

    async def update_agent(
        self,
        agent_id: str,
        name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        role: Optional[str] = None,
        description: Optional[str] = None,
        avatar: Optional[str] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """更新全局 Agent"""
        ...

    # ── Web ──

    async def web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """搜索网页，返回结果列表"""
        ...

    async def fetch_url(self, url: str, max_chars: int = 8000) -> Dict[str, Any]:
        """获取网页内容，提取正文文本"""
        ...

    async def page_inject(self, js_code: str, description: str = "") -> Dict[str, Any]:
        """向前端页面注入 JavaScript 代码"""
        ...

    # ── Template（项目模板，引导 agent 用） ──

    async def list_templates(self) -> List[Dict[str, Any]]:
        """列出所有可用的项目模板"""
        ...

    async def apply_template(
        self,
        template_id: str,
        project_name: str,
        project_description: Optional[str] = None,
        project_targets: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """应用模板创建项目（含 agents/groups/skills/resources）"""
        ...
