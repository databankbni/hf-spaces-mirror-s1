import os
from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
        {
            'AMap': {
                'transport': 'http',
                'url': f'https://mcp.amap.com/mcp?key={os.environ["AMAP_API_KEY"]}'
            },
        }
    )

async def load_map_tools():
    return await client.get_tools()