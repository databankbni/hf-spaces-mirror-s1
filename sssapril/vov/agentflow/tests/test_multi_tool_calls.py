"""
Unit tests for multi-tool call aggregation via AllModelPlugin.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytest

from agentflow.agent import Agent
from agentflow.async_bridge import set_main_loop
from agentflow.llm.base import BaseLLM, ChatMessage, LLMResponse, MessageRole, ToolCall
from agentflow.packet import InfoPacket, PacketType
from agentflow.plugins.allmodel_plugin import AllModelPlugin
from agentflow.plugins.memory_plugin import MemoryPlugin
from agentflow.processor import Processor


class MockLLM(BaseLLM):
    """Mock LLM that returns scripted responses."""

    def __init__(self, responses: List[LLMResponse]):
        super().__init__(model="mock")
        self.responses = responses
        self.call_index = 0
        self.chat_calls: List[List[ChatMessage]] = []

    async def chat(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.chat_calls.append(messages)
        response = self.responses[self.call_index]
        self.call_index = min(self.call_index + 1, len(self.responses) - 1)
        return response

    async def chat_stream(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        on_token=None,
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError

    def build_tool_response(
        self,
        messages: List[ChatMessage],
        tool_results: List[Dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError


class SimpleToolProcessor(Processor):
    """A simple synchronous tool that returns its argument."""

    def __init__(self, name: str, delay: float = 0.0):
        super().__init__(name)
        self.delay = delay
        self.call_count = 0

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        self.call_count += 1
        if self.delay:
            time.sleep(self.delay)
        content = packet.content if isinstance(packet.content, dict) else {}
        args = content.get("arguments", {})
        return packet.create_child(
            sender_id=self.sender_id,
            content={"result": f"{self.name}({args.get('value')})"},
            packet_type=PacketType.RESPONSE,
        )

    def get_schema(self) -> Optional[Dict[str, Any]]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"Tool {self.name}",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }


class ResultCollector(Processor):
    """Collects the final NORMAL packet and signals completion."""

    def __init__(self):
        super().__init__(name="result_collector")
        self._event = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        self.final_content: Optional[str] = None
        self.tool_results: List[Any] = []

    def input(self, packet: InfoPacket) -> None:
        self._handle_packet(packet)

    def _handle_packet(self, packet: InfoPacket) -> None:
        if packet.type == PacketType.RESPONSE:
            self.tool_results.append(packet.content)
        elif packet.type == PacketType.NORMAL:
            self.final_content = str(packet.content) if packet.content is not None else ""
            if not packet.get_metadata("has_pending_tool_calls"):
                self._loop.call_soon_threadsafe(self._event.set)

    async def wait(self, timeout: float = 10.0) -> Optional[str]:
        await asyncio.wait_for(self._event.wait(), timeout=timeout)
        return self.final_content


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    set_main_loop(loop)
    yield loop
    set_main_loop(None)
    loop.close()


@pytest.mark.asyncio
async def test_agent_aggregates_multiple_tool_results(event_loop):
    """Agent should call two tools in parallel and receive a final summary."""
    tool_a = SimpleToolProcessor("tool_a")
    tool_b = SimpleToolProcessor("tool_b")

    first_response = LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[
            ToolCall(id="call_1", name="tool_a", arguments='{"value": "x"}'),
            ToolCall(id="call_2", name="tool_b", arguments='{"value": "y"}'),
        ],
    )
    second_response = LLMResponse(content="Done with both tools.", finish_reason="stop")
    llm = MockLLM([first_response, second_response])

    agent = Agent(name="test_agent", llm=llm)
    agent.add_plugin(MemoryPlugin(max_history=20))
    agent.add_plugin(AllModelPlugin(timeout=5.0))
    agent.register_call_target(tool_a)
    agent.register_call_target(tool_b)

    collector = ResultCollector()
    agent.to(collector)

    user_packet = InfoPacket(
        id="user_1",
        sender_id="user",
        parent_id=None,
        chain_id="chain_1",
        content="call both tools",
        type=PacketType.NORMAL,
        timestamp=datetime.now(),
    )
    agent.input(user_packet)

    final = await collector.wait(timeout=10.0)

    assert tool_a.call_count == 1
    assert tool_b.call_count == 1
    assert final == "Done with both tools."
    assert len(llm.chat_calls) == 2

    # The second LLM call should include tool results for both tools.
    second_messages = llm.chat_calls[1]
    tool_messages = [m for m in second_messages if m.role == MessageRole.TOOL]
    assert len(tool_messages) == 2


class AsyncBridgeToolProcessor(Processor):
    """Tool that uses async_bridge to schedule async work on the main loop."""

    def __init__(self, name: str, delay: float = 0.0):
        super().__init__(name)
        self.delay = delay
        self.call_count = 0

    async def _async_work(self, packet: InfoPacket) -> InfoPacket:
        self.call_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        content = packet.content if isinstance(packet.content, dict) else {}
        args = content.get("arguments", {})
        return packet.create_child(
            sender_id=self.sender_id,
            content={"result": f"{self.name}({args.get('value')})"},
            packet_type=PacketType.RESPONSE,
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        # This is sync, but the real work is async. In the server, tools use
        # safe_run_async which calls async_bridge.run_async internally.
        from agentflow.async_bridge import run_async
        return run_async(self._async_work(packet), timeout=10.0, context=self.name)

    def get_schema(self) -> Optional[Dict[str, Any]]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"Tool {self.name}",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }


@pytest.mark.asyncio
async def test_async_tools_aggregate(event_loop):
    """Async tools using async_bridge should aggregate correctly."""
    tool_a = AsyncBridgeToolProcessor("tool_a", delay=0.05)
    tool_b = AsyncBridgeToolProcessor("tool_b", delay=0.05)

    first_response = LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[
            ToolCall(id="call_1", name="tool_a", arguments='{"value": "x"}'),
            ToolCall(id="call_2", name="tool_b", arguments='{"value": "y"}'),
        ],
    )
    second_response = LLMResponse(content="Async done.", finish_reason="stop")
    llm = MockLLM([first_response, second_response])

    agent = Agent(name="test_agent", llm=llm)
    agent.add_plugin(MemoryPlugin(max_history=20))
    agent.add_plugin(AllModelPlugin(timeout=5.0))
    agent.register_call_target(tool_a)
    agent.register_call_target(tool_b)

    collector = ResultCollector()
    agent.to(collector)

    user_packet = InfoPacket(
        id="user_2",
        sender_id="user",
        parent_id=None,
        chain_id="chain_2",
        content="call async tools",
        type=PacketType.NORMAL,
        timestamp=datetime.now(),
    )
    agent.input(user_packet)

    final = await collector.wait(timeout=10.0)

    assert tool_a.call_count == 1
    assert tool_b.call_count == 1
    assert final == "Async done."
    assert len(llm.chat_calls) == 2


class HangingToolProcessor(Processor):
    """Tool that never returns (simulates a stuck async operation)."""

    def __init__(self, name: str):
        super().__init__(name)
        self.call_count = 0

    async def _async_work(self, packet: InfoPacket) -> InfoPacket:
        self.call_count += 1
        await asyncio.sleep(3600)  # never returns in practice
        return packet.create_child(
            sender_id=self.sender_id,
            content={"result": "should not see this"},
            packet_type=PacketType.RESPONSE,
        )

    def core_process(self, packet: InfoPacket) -> InfoPacket:
        from agentflow.async_bridge import run_async
        return run_async(self._async_work(packet), timeout=10.0, context=self.name)

    def get_schema(self) -> Optional[Dict[str, Any]]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"Tool {self.name}",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }


@pytest.mark.asyncio
async def test_hanging_tool_is_finalized_by_batch_timeout(event_loop):
    """One hanging tool should not block the other tool's result forever."""
    fast_tool = AsyncBridgeToolProcessor("fast_tool", delay=0.05)
    hanging_tool = HangingToolProcessor("hanging_tool")

    first_response = LLMResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[
            ToolCall(id="call_1", name="fast_tool", arguments='{"value": "x"}'),
            ToolCall(id="call_2", name="hanging_tool", arguments='{"value": "y"}'),
        ],
    )
    second_response = LLMResponse(content="Recovered from timeout.", finish_reason="stop")
    llm = MockLLM([first_response, second_response])

    agent = Agent(name="test_agent", llm=llm)
    agent.add_plugin(MemoryPlugin(max_history=20))
    agent.add_plugin(AllModelPlugin(timeout=1.0))
    agent.register_call_target(fast_tool)
    agent.register_call_target(hanging_tool)

    collector = ResultCollector()
    agent.to(collector)

    user_packet = InfoPacket(
        id="user_3",
        sender_id="user",
        parent_id=None,
        chain_id="chain_3",
        content="call fast and hanging tools",
        type=PacketType.NORMAL,
        timestamp=datetime.now(),
    )
    agent.input(user_packet)

    final = await collector.wait(timeout=10.0)

    assert fast_tool.call_count == 1
    assert hanging_tool.call_count == 1
    assert final == "Recovered from timeout."
    assert len(llm.chat_calls) == 2

    # The second LLM call should include the fast tool result and a timeout
    # error for the hanging tool.
    second_messages = llm.chat_calls[1]
    tool_messages = [m for m in second_messages if m.role == MessageRole.TOOL]
    assert any("fast_tool(x)" in str(m.content) for m in tool_messages)

    all_contents = " ".join(str(m.content) for m in second_messages)
    assert "hanging_tool" in all_contents and "Tool Timeout" in all_contents
