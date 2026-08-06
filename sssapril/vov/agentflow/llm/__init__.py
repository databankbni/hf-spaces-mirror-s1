"""
LLM 模块

提供统一的 LLM 接口抽象和多种实现。
"""

from .base import BaseLLM, ChatMessage, LLMResponse, MessageRole
from .openai_adapter import OpenAIAdapter
from .transformers_adapter import TransformersAdapter

__all__ = [
    "BaseLLM",
    "ChatMessage",
    "LLMResponse",
    "MessageRole",
    "OpenAIAdapter",
    "TransformersAdapter",
]
