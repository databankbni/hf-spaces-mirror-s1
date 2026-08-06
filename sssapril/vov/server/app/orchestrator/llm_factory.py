"""
LLM工厂模块

提供统一的LLM模型创建接口，支持多种LLM Provider。
"""

from typing import Optional, Any
from enum import Enum

from app.core.config import settings


class LLMProvider(str, Enum):
    """LLM Provider枚举"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    LOCAL = "local"


class LLMFactory:
    """
    LLM工厂类

    根据配置创建不同的LLM实例。
    支持OpenAI、Anthropic、Azure OpenAI等Provider。

    Example:
        factory = LLMFactory()
        llm = factory.create("gpt-4", temperature=0.7)
    """

    # Provider默认配置
    PROVIDER_CONFIGS = {
        LLMProvider.OPENAI: {
            "default_model": "gpt-4",
            "supports_streaming": True,
            "supports_functions": True,
        },
        LLMProvider.ANTHROPIC: {
            "default_model": "claude-3-sonnet-20240229",
            "supports_streaming": True,
            "supports_functions": True,
        },
        LLMProvider.AZURE: {
            "default_model": "gpt-4",
            "supports_streaming": True,
            "supports_functions": True,
        },
    }

    def __init__(self):
        """初始化LLM工厂"""
        self._provider = LLMProvider(settings.LLM_PROVIDER)
        self._api_key = settings.get_llm_api_key()
        self._api_base = settings.get_llm_api_base()

    def create(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        创建LLM实例

        根据model_name自动选择Provider，或使用默认Provider。

        Args:
            model_name: 模型名称，如 "gpt-4", "claude-3-sonnet"
            temperature: 温度参数，控制输出随机性
            max_tokens: 最大输出token数
            **kwargs: 其他配置参数

        Returns:
            LLM实例（具体类型取决于Provider）

        Raises:
            ValueError: 不支持的Provider或模型
        """
        # 自动检测Provider
        provider = self._detect_provider(model_name)

        if provider == LLMProvider.OPENAI:
            return self._create_openai(model_name, temperature, max_tokens, **kwargs)
        elif provider == LLMProvider.ANTHROPIC:
            return self._create_anthropic(model_name, temperature, max_tokens, **kwargs)
        elif provider == LLMProvider.AZURE:
            return self._create_azure(model_name, temperature, max_tokens, **kwargs)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    def _detect_provider(self, model_name: Optional[str] = None) -> LLMProvider:
        """
        检测LLM Provider

        根据模型名称自动检测Provider。

        Args:
            model_name: 模型名称

        Returns:
            LLMProvider: 检测到的Provider
        """
        if not model_name:
            return self._provider

        model_lower = model_name.lower()

        if model_lower.startswith("gpt") or model_lower.startswith("text-davinci"):
            return LLMProvider.OPENAI
        elif model_lower.startswith("claude"):
            return LLMProvider.ANTHROPIC
        elif model_lower.startswith("azure/"):
            return LLMProvider.AZURE
        else:
            return self._provider

    def _create_openai(
        self,
        model_name: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> Any:
        """
        创建OpenAI LLM实例

        Args:
            model_name: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            OpenAI LLM实例
        """
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai is required for OpenAI provider. Install it with: pip install langchain-openai")

        config = {
            "model": model_name or "gpt-4",
            "temperature": temperature,
            "openai_api_key": self._api_key,
        }

        if self._api_base:
            config["openai_api_base"] = self._api_base
        if max_tokens:
            config["max_tokens"] = max_tokens

        config.update(kwargs)
        return ChatOpenAI(**config)

    def _create_anthropic(
        self,
        model_name: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> Any:
        """
        创建Anthropic LLM实例

        Args:
            model_name: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            Anthropic LLM实例
        """
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError("langchain-anthropic is required for Anthropic provider. Install it with: pip install langchain-anthropic")

        config = {
            "model": model_name or "claude-3-sonnet-20240229",
            "temperature": temperature,
            "anthropic_api_key": self._api_key,
        }

        if max_tokens:
            config["max_tokens"] = max_tokens

        config.update(kwargs)
        return ChatAnthropic(**config)

    def _create_azure(
        self,
        model_name: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs
    ) -> Any:
        """
        创建Azure OpenAI LLM实例

        Args:
            model_name: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            **kwargs: 其他参数

        Returns:
            Azure OpenAI LLM实例
        """
        try:
            from langchain_openai import AzureChatOpenAI
        except ImportError:
            raise ImportError("langchain-openai is required for Azure provider. Install it with: pip install langchain-openai")

        config = {
            "model": model_name.replace("azure/", "") if model_name else "gpt-4",
            "temperature": temperature,
            "openai_api_key": self._api_key,
            "azure_endpoint": self._api_base,
            "api_version": kwargs.get("api_version", "2024-02-15-preview"),
        }

        if max_tokens:
            config["max_tokens"] = max_tokens

        config.update(kwargs)
        return AzureChatOpenAI(**config)

    def get_default_model(self) -> str:
        """
        获取默认模型名称

        Returns:
            str: 默认模型名称
        """
        return self.PROVIDER_CONFIGS[self._provider]["default_model"]

    def supports_streaming(self, model_name: Optional[str] = None) -> bool:
        """
        检查模型是否支持流式输出

        Args:
            model_name: 模型名称

        Returns:
            bool: 是否支持流式输出
        """
        provider = self._detect_provider(model_name)
        return self.PROVIDER_CONFIGS.get(provider, {}).get("supports_streaming", False)

    def supports_functions(self, model_name: Optional[str] = None) -> bool:
        """
        检查模型是否支持函数调用

        Args:
            model_name: 模型名称

        Returns:
            bool: 是否支持函数调用
        """
        provider = self._detect_provider(model_name)
        return self.PROVIDER_CONFIGS.get(provider, {}).get("supports_functions", False)
