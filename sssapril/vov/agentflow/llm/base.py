"""
LLM 抽象基类定义

提供统一的 LLM 接口抽象，支持多种 LLM 提供商的实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, TYPE_CHECKING, Union


class MessageRole(Enum):
    """消息角色枚举"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ChatMessage:
    """
    聊天消息数据类
    
    Attributes:
        role: 消息角色（system/user/assistant/tool）
        content: 消息内容（assistant 带 tool_calls 时可为 None）
        name: 可选的消息发送者名称
        tool_call_id: tool 角色消息对应的工具调用 ID
        tool_calls: assistant 角色消息中的工具调用列表
    """
    role: MessageRole
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result: Dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            result["content"] = self.content
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        return result


@dataclass
class ToolCall:
    """
    工具调用数据类
    
    Attributes:
        id: 工具调用ID
        name: 工具名称
        arguments: 工具参数（JSON字符串或字典）
    """
    id: str
    name: str
    arguments: Union[str, Dict[str, Any]]
    
    def get_arguments_dict(self) -> Dict[str, Any]:
        """获取参数的字典形式"""
        if isinstance(self.arguments, dict):
            return self.arguments
        import json
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return {}


@dataclass
class LLMResponse:
    """
    LLM 响应数据类
    
    Attributes:
        content: 响应内容
        finish_reason: 完成原因（stop/length/content_filter/tool_calls等）
        usage: 可选的使用统计信息（prompt_tokens, completion_tokens, total_tokens）
        model: 使用的模型名称
        tool_calls: 可选的工具调用列表
    """
    content: str
    finish_reason: str
    usage: Optional[Dict[str, int]] = None
    model: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    
    def has_tool_calls(self) -> bool:
        """检查是否包含工具调用"""
        return self.tool_calls is not None and len(self.tool_calls) > 0


class BaseLLM(ABC):
    """
    LLM 抽象基类
    
    定义了所有 LLM 适配器必须实现的接口。
    支持同步和流式两种调用方式。
    """
    
    def __init__(
        self,
        model: str,
        temperature: float = 1.0,
        max_tokens: Optional[int] = None,
        **kwargs
    ):
        """
        初始化 LLM 基类
        
        Args:
            model: 模型名称
            temperature: 生成温度（0.0-2.0）
            max_tokens: 最大生成 token 数
            **kwargs: 其他模型特定参数
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_params = kwargs

    @abstractmethod
    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        同步聊天接口
        
        Args:
            messages: 消息列表
            tools: 可用的 tool schema 列表（OpenAI 格式）
            **kwargs: 额外参数，可覆盖初始化时的参数
            
        Returns:
            LLMResponse: LLM 响应对象
        """
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_token: Optional[callable] = None,
        **kwargs
    ) -> 'LLMResponse':
        """
        流式聊天接口
        
        通过 on_token 回调实时输出文本片段，最终返回完整响应。
        
        Args:
            messages: 消息列表
            tools: 可用的 tool schema 列表（OpenAI 格式）
            on_token: 文本片段回调函数，签名为 on_token(token: str)
            **kwargs: 额外参数，可覆盖初始化时的参数
            
        Returns:
            LLMResponse: 完整的 LLM 响应（包含内容和工具调用）
        """
        pass

    def _merge_kwargs(self, **kwargs) -> Dict[str, Any]:
        """
        合并默认参数和调用时参数
        
        Args:
            **kwargs: 调用时传入的参数
            
        Returns:
            合并后的参数字典
        """
        merged = {
            "model": self.model,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            merged["max_tokens"] = self.max_tokens
        merged.update(self.extra_params)
        merged.update(kwargs)
        return merged

    @staticmethod
    def _convert_messages(messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        """
        将 ChatMessage 列表转换为字典列表（支持 OpenAI 原生 tool calling 格式）
        """
        converted: List[Dict[str, Any]] = []
        for msg in messages:
            payload: Dict[str, Any] = {"role": msg.role.value}

            if msg.content is not None:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                if content.strip():
                    payload["content"] = content

            if msg.name:
                payload["name"] = msg.name
            if msg.tool_call_id:
                payload["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                payload["tool_calls"] = msg.tool_calls

            # 跳过既无有效 content 又无 tool 信息的空消息
            has_content = "content" in payload
            has_tool_info = bool(msg.tool_call_id or msg.tool_calls)
            if not has_content and not has_tool_info:
                continue

            converted.append(payload)
        return converted
