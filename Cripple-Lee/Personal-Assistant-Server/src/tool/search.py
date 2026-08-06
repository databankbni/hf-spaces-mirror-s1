import os
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
        {
            'Tavily': {
                'transport': 'http',
                'url': f'https://mcp.tavily.com/mcp/?tavilyApiKey={os.environ["TAVILY_API_KEY"]}'
            },
        }
    )

async def load_search_tools():
    return await client.get_tools()