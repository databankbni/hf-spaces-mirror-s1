"""LangChain / LangGraph: bind the Space's tools to any chat model."""
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

SPACE = "https://YOUR-SPACE.hf.space"

async def main():
    client = MultiServerMCPClient({
        "swmm": {"url": f"{SPACE}/mcp", "transport": "streamable_http"},
    })
    tools = await client.get_tools()
    print([t.name for t in tools])
    # from langgraph.prebuilt import create_react_agent
    # agent = create_react_agent("anthropic:claude-sonnet-4-5", tools)
    # result = await agent.ainvoke({"messages": "Upload and analyse my model ..."})

asyncio.run(main())
