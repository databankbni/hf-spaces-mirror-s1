import asyncio

from web.login import get_or_create_agent

from langchain.tools import tool
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from tool.map import load_map_tools

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NAVIGATE_SYSTEM_PROMPT = """You are a navigation specialist agent with access to AMap (Gaode Maps) tools.

Your primary directive is to USE the available map tools whenever possible rather than answering from your own knowledge. Prefer calling a tool over generating an answer yourself.

Available tools:
- AMap (Gaode Maps) tools for geocoding, reverse geocoding, points of interest search, route planning (driving/walking/transit/cycling), distance/duration estimation, and nearby place retrieval.

Guidelines:
1. Default to tool use: For any location, navigation, or geographic query, you MUST call the relevant AMap tool instead of answering from memory. Your own geographic knowledge may be outdated or incomplete.
2. Be specific in queries: Pass clear, well-formed inputs to tools (full addresses, place names, coordinates, origin/destination pairs). Resolve ambiguities in the user query before calling a tool.
3. Trust tool output: Base your answer on the tool's returned data (coordinates, addresses, route steps, place details). Do not invent or substitute your own data.
4. Summarize results clearly: After receiving tool output, present it to the user in a clear, structured way (e.g., list route steps, show coordinates, highlight nearby places). Keep formatting concise.
5. Handle Chinese context: AMap primarily covers China. Inputs and outputs may be in Chinese; preserve the language of the user's query when possible.
6. Ask for missing info: If a required parameter is missing (e.g., destination for route planning), ask the user a short clarifying question before calling a tool.
7. Avoid answering directly: Only respond without a tool for trivial cases (e.g., greetings, or questions about your own capabilities).
"""


async def init_navigate_agent(hf_token: str):
    """Initialize the navigate agent."""
    # Initialize the model with the token from runtime context
    # Using asyncio.to_thread to avoid blocking calls in async context
    llm = await asyncio.to_thread(
        HuggingFaceEndpoint,
        repo_id="meta-llama/Llama-3.1-8B-Instruct",
        huggingfacehub_api_token=hf_token,
    )
    
    model = ChatHuggingFace(llm=llm)
    
    map_tools = await load_map_tools()

    logger.info(f"Map Tools: {map_tools}")

    navigate_agent = create_agent(
        model=model,
        tools=map_tools,
        system_prompt=NAVIGATE_SYSTEM_PROMPT,
        middleware=[
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
        ],
    )

    return navigate_agent


@tool(
    "navigate",
    description=(
        "Handle location-based and navigation requests using AMap (Gaode Maps) tools. "
        "Use this for geocoding addresses, reverse geocoding coordinates, searching for "
        "points of interest (restaurants, hotels, shops, etc.), route planning "
        "(driving, walking, transit, cycling), distance/duration estimation, and "
        "retrieving nearby places or area information. Returns structured map "
        "results such as coordinates, addresses, route steps, and place details. "
        "Prefer this tool for any query involving maps, directions, or geographic "
        "lookups."
    ),
)
async def call_navigate_agent(query: str):
    navigate_agent = await get_or_create_agent("navigate")

    logger.info(f'[Navigate Agent] - Input: {query}')
    result = await navigate_agent.ainvoke({"messages": [{"role": "human", "content": query}]})
    logger.info(f'[Navigate Agent] - Output: {result}')

    return result["messages"][-1].content