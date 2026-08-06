import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from agent.navigate_agent import call_navigate_agent
from agent.search_agent import call_search_agent

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """You are a supervisor agent responsible for orchestrating two specialized subagents: `navigate` and `search`.

Your primary directive is to DELEGATE to subagents whenever possible rather than answering directly. Prefer routing user requests to the appropriate subagent over generating an answer yourself.

Available subagents:
- `navigate`: Handles location-based and navigation requests (geocoding, reverse geocoding, points of interest, route planning, distance/duration, nearby places) using AMap (Gaode Maps).
- `search`: Handles information search requests (facts, news, articles, product details, general knowledge, up-to-date web information).

Guidelines:
1. Default to delegation: For any request that could be answered by a subagent, you MUST call the relevant subagent tool instead of answering from your own knowledge.
2. Route by intent: Route navigation/geographic queries to `navigate`, and information lookup queries to `search`. If a query spans both, call both subagents.
3. Avoid answering directly: Only respond from your own knowledge when a subagent genuinely cannot help (e.g., trivial greetings, small talk, or meta questions about the assistant itself).
4. Preserve subagent output: When a subagent returns a result, relay its content to the user with minimal rewriting. Do not substitute your own answer for the subagent's result.
5. Clarify ambiguous requests: If the user's intent is unclear, ask a short clarifying question before delegating.
6. Be concise: Keep your own messages short. The bulk of the response should come from the subagents.
"""


async def init_supervisor_agent(hf_token: str):
    """Initialize the supervisor agent."""
    # Initialize the model with the token from runtime context
    # Using asyncio.to_thread to avoid blocking calls in async context
    llm = await asyncio.to_thread(
        HuggingFaceEndpoint,
        repo_id="meta-llama/Llama-3.1-8B-Instruct",
        huggingfacehub_api_token=hf_token,
    )
    
    model = ChatHuggingFace(llm=llm)

    supervisor_agent = create_agent(
        model=model,
        tools=[call_navigate_agent, call_search_agent],
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        middleware=[
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
        ],
    )

    return supervisor_agent
    