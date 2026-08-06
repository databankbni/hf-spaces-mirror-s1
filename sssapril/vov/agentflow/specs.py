from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any, Dict, List, Optional, Union

from dotenv import dotenv_values

from .llm.base import BaseLLM
from .llm.openai_adapter import OpenAIAdapter


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: Optional[str] = None
    api_key_env: Optional[str] = "API_KEY"
    base_url: Optional[str] = None
    base_url_env: Optional[str] = "BASE_URL"
    organization: Optional[str] = None
    organization_env: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key": self.api_key,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "base_url_env": self.base_url_env,
            "organization": self.organization,
            "organization_env": self.organization_env,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["LLMConfig"]:
        if data is None:
            return None
        return cls(
            provider=data.get("provider", "openai"),
            model=data.get("model", "gpt-4o-mini"),
            api_key=data.get("api_key"),
            api_key_env=data.get("api_key_env", "API_KEY"),
            base_url=data.get("base_url"),
            base_url_env=data.get("base_url_env", "BASE_URL"),
            organization=data.get("organization"),
            organization_env=data.get("organization_env"),
            temperature=data.get("temperature", 0.2),
            max_tokens=data.get("max_tokens"),
            extra=dict(data.get("extra", {})),
        )


@dataclass
class PluginConfig:
    kind: str
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "config": dict(self.config)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginConfig":
        return cls(kind=data["kind"], config=dict(data.get("config", {})))


@dataclass
class BuiltinProcessorConfig:
    kind: str
    name: Optional[str] = None
    description: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "config": dict(self.config),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BuiltinProcessorConfig":
        return cls(
            kind=data["kind"],
            name=data.get("name"),
            description=data.get("description"),
            config=dict(data.get("config", {})),
        )


@dataclass
class AgentSpec:
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    stream_mode: bool = False
    force_tool_choice_on_first_turn: bool = False
    llm_config: Optional[LLMConfig] = None
    plugins: List[PluginConfig] = field(default_factory=list)
    builtin_tools: List[BuiltinProcessorConfig] = field(default_factory=list)
    tool_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "stream_mode": self.stream_mode,
            "force_tool_choice_on_first_turn": self.force_tool_choice_on_first_turn,
            "llm_config": self.llm_config.to_dict() if self.llm_config else None,
            "plugins": [plugin.to_dict() for plugin in self.plugins],
            "builtin_tools": [tool.to_dict() for tool in self.builtin_tools],
            "tool_names": list(self.tool_names),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSpec":
        return cls(
            name=data["name"],
            description=data.get("description"),
            system_prompt=data.get("system_prompt"),
            stream_mode=data.get("stream_mode", False),
            force_tool_choice_on_first_turn=data.get("force_tool_choice_on_first_turn", False),
            llm_config=LLMConfig.from_dict(data.get("llm_config")),
            plugins=[PluginConfig.from_dict(item) for item in data.get("plugins", [])],
            builtin_tools=[BuiltinProcessorConfig.from_dict(item) for item in data.get("builtin_tools", [])],
            tool_names=list(data.get("tool_names", [])),
        )


def load_env_values(env_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    if env_path is None:
        return {key: value for key, value in os.environ.items() if isinstance(value, str)}

    resolved_path = Path(env_path)
    values = dotenv_values(resolved_path)
    return {key: value for key, value in values.items() if isinstance(value, str)}


def _resolve_config_value(
    direct_value: Optional[str],
    env_name: Optional[str],
    env_values: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    if direct_value:
        return direct_value
    if env_name is None:
        return None
    if env_values and env_name in env_values:
        return env_values[env_name]
    return os.environ.get(env_name)


def build_llm_from_config(
    llm_config: Union[LLMConfig, Dict[str, Any]],
    env_values: Optional[Dict[str, str]] = None,
) -> BaseLLM:
    config = llm_config if isinstance(llm_config, LLMConfig) else LLMConfig.from_dict(llm_config)
    if config is None:
        raise ValueError("LLM config is required to build an LLM instance.")

    provider = config.provider.lower()

    if provider != "openai":
        raise ValueError(f"Unsupported LLM provider '{config.provider}'.")

    api_key = _resolve_config_value(config.api_key, config.api_key_env, env_values)
    base_url = _resolve_config_value(config.base_url, config.base_url_env, env_values)
    organization = _resolve_config_value(config.organization, config.organization_env, env_values)

    return OpenAIAdapter(
        model=config.model,
        api_key=api_key,
        base_url=base_url,
        organization=organization,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        **config.extra,
    )
