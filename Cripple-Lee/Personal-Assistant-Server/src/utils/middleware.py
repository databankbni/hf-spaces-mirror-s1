from collections.abc import Callable
from collections.abc import Awaitable
from langchain.agents.middleware import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command
from typing import Any

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ToolMonitoringMiddleware(AgentMiddleware):
    async def awrap_tool_call(
            self,
            request: ToolCallRequest,
            handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        logger.info(f"Executing tool: {request.tool_call['name']}")
        logger.info(f"Arguments: {request.tool_call['args']}")
        try:
            result = await handler(request)
            logger.info(f"Tool({request.tool_call['name']} - {request.tool_call['args']}) completed successfully: {result}")
            return result
        except Exception as e:
            logger.info(f"Tool({request.tool_call['name']} - {request.tool_call['args']}) failed: {e}")
            raise