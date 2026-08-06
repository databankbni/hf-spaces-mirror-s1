"""
Transformers 本地模型适配器实现

提供基于 Hugging Face Transformers 的本地模型调用支持。
"""

import asyncio
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from .base import BaseLLM, ChatMessage, LLMResponse


class TransformersAdapter(BaseLLM):
    """
    Transformers 本地模型适配器
    
    封装 Hugging Face Transformers，支持本地模型推理。
    使用延迟加载避免强制依赖 transformers 包。
    """
    
    def __init__(
        self,
        model: str = "gpt2",
        device: Optional[str] = None,
        temperature: float = 1.0,
        max_tokens: Optional[int] = 50,
        **kwargs
    ):
        """
        初始化 Transformers 适配器
        
        Args:
            model: 模型名称或路径（默认 gpt2）
            device: 运行设备（cuda/cpu/auto），None 表示自动选择
            temperature: 生成温度（0.0-2.0）
            max_tokens: 最大生成 token 数（默认 50）
            **kwargs: 其他 transformers 参数
        """
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens or 50,
            **kwargs
        )
        self.device = device
        self._model = None
        self._tokenizer = None

    def _ensure_model(self) -> None:
        """
        确保模型和分词器已加载
        
        使用延迟加载避免强制依赖 transformers 包。
        
        Raises:
            ImportError: 当 transformers 包未安装时
        """
        if self._model is None or self._tokenizer is None:
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                import torch
            except ImportError as e:
                raise ImportError(
                    "Transformers adapter requires the 'transformers' and 'torch' packages. "
                    "Install them with: pip install agentflow[transformers]"
                ) from e
            
            self._tokenizer = AutoTokenizer.from_pretrained(self.model)
            self._model = AutoModelForCausalLM.from_pretrained(self.model)
            
            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
            if self.device and self.device != "cpu":
                self._model.to(self.device)

    def _build_prompt(self, messages: List[ChatMessage]) -> str:
        """
        构建提示文本
        
        将消息列表转换为模型可理解的提示格式。
        
        Args:
            messages: 消息列表
            
        Returns:
            构建好的提示文本
        """
        prompt_parts = []
        for msg in messages:
            if msg.role.value == "system":
                prompt_parts.append(f"System: {msg.content}")
            elif msg.role.value == "user":
                prompt_parts.append(f"User: {msg.content}")
            elif msg.role.value == "assistant":
                prompt_parts.append(f"Assistant: {msg.content}")
        
        prompt_parts.append("Assistant:")
        return "\n".join(prompt_parts)

    async def chat(
        self,
        messages: List[ChatMessage],
        **kwargs
    ) -> LLMResponse:
        """
        同步聊天接口
        
        Args:
            messages: 消息列表
            **kwargs: 额外参数
            
        Returns:
            LLMResponse: LLM 响应对象
            
        Raises:
            ImportError: 当 transformers 包未安装时
        """
        self._ensure_model()
        
        import torch
        
        prompt = self._build_prompt(messages)
        
        inputs = self._tokenizer(prompt, return_tensors="pt")
        if self.device and self.device != "cpu":
            inputs = inputs.to(self.device)
        
        max_new_tokens = kwargs.get("max_tokens", self.max_tokens)
        temperature = kwargs.get("temperature", self.temperature)
        
        generation_kwargs = {
            "max_new_tokens": max_new_tokens,
            "temperature": max(temperature, 0.01),
            "do_sample": temperature > 0,
            "pad_token_id": self._tokenizer.eos_token_id,
        }
        
        def _generate():
            with torch.no_grad():
                outputs = self._model.generate(**inputs, **generation_kwargs)
            return outputs
        
        loop = asyncio.get_event_loop()
        outputs = await loop.run_in_executor(None, _generate)
        
        generated_text = self._tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )
        
        return LLMResponse(
            content=generated_text.strip(),
            finish_reason="stop",
            usage={
                "prompt_tokens": inputs["input_ids"].shape[1],
                "completion_tokens": outputs.shape[1] - inputs["input_ids"].shape[1],
                "total_tokens": outputs.shape[1],
            },
            model=self.model,
        )

    async def chat_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_token: Optional[Callable[[str], None]] = None,
        **kwargs
    ) -> LLMResponse:
        """
        流式聊天接口（简化实现）
        
        本地模型的流式输出需要更复杂的实现，
        这里提供一个简化的版本，通过回调输出文本。
        注意：TransformersAdapter 不支持工具调用。
        
        Args:
            messages: 消息列表
            tools: 可用的 tool schema 列表（不支持）
            on_token: 文本片段回调函数
            **kwargs: 额外参数
            
        Returns:
            LLMResponse: 完整的 LLM 响应
        """
        response = await self.chat(messages, **kwargs)
        
        words = response.content.split()
        for i, word in enumerate(words):
            token = word if i == 0 else f" {word}"
            if on_token:
                on_token(token)
            await asyncio.sleep(0.01)
        
        return response

    @property
    def raw_model(self) -> Any:
        """获取底层 Transformers 模型（用于高级用法）"""
        return self._model

    @property
    def raw_tokenizer(self) -> Any:
        """获取底层分词器（用于高级用法）"""
        return self._tokenizer
