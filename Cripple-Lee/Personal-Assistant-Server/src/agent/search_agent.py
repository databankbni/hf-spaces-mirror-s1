import asyncio

from web.login import get_or_create_agent

from langchain.tools import tool
from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

from tool.search import load_search_tools

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SEARCH_SYSTEM_PROMPT = """You are a search specialist agent with access to Tavily web search tools.

Your primary directive is to USE the available web search tools whenever possible rather than answering from your own knowledge. Prefer calling a tool over generating an answer yourself.

Available tools:
- Tavily web search tools for looking up facts, news, articles, product details, general knowledge, and up-to-date information from the web.

Guidelines:
1. Default to tool use: For any information lookup query, you MUST call the relevant Tavily search tool instead of answering from memory. Real-world information changes frequently, and your training data may be outdated.
2. Craft effective queries: Formulate clear, specific search queries from the user's request. Break complex questions into multiple targeted searches if needed.
3. Trust tool output: Base your answer on the search results (titles, snippets, URLs, content). Do not invent facts or substitute your own knowledge for the search results.
4. Cite sources: When presenting results, include relevant source URLs or titles so the user can verify the information.
5. Summarize results clearly: Synthesize the search results into a concise, well-organized answer. Highlight the most relevant and authoritative information.
6. Ask for missing info: If the search query is too vague to produce useful results, ask the user a short clarifying question before searching.
7. Avoid answering directly: Only respond without a tool for trivial cases (e.g., greetings, or questions about your own capabilities).
"""


async def init_search_agent(hf_token: str):
    """Initialize the search agent."""
    # Initialize the model with the token from runtime context
    # Using asyncio.to_thread to avoid blocking calls in async context
    llm = await asyncio.to_thread(
        HuggingFaceEndpoint,
        repo_id="meta-llama/Llama-3.1-8B-Instruct",
        huggingfacehub_api_token=hf_token,
    )
    
    model = ChatHuggingFace(llm=llm)
    
    search_tools = await load_search_tools()

    logger.info(f"Search Tools: {search_tools}")

    search_agent = create_agent(
        model=model,
        tools=search_tools,
        system_prompt=SEARCH_SYSTEM_PROMPT,
        middleware=[
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
        ],
    )

    return search_agent


@tool(
    "search",
    description=(
        "Handle information search requests using web search tools. "
        "Use this for looking up facts, news, articles, product details, "
        "general knowledge questions, or any query requiring up-to-date "
        "information from the web. Returns structured search results such as "
        "titles, snippets, URLs, and relevant content. Prefer this tool for "
        "any query involving online search or information retrieval."
    ),
)
async def call_search_agent(query: str):

    search_agent = await get_or_create_agent("search")

    logger.info(f'[Search Agent] - Input: {query}')
    result = await search_agent.ainvoke({"messages": [{"role": "human", "content": query}]})
    logger.info(f'[Search Agent] - Output: {result}')

    return result["messages"][-1].content
