"""Direct MCP client example (also works from LangGraph/agno/pydantic-ai etc.)."""
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SPACE = "https://YOUR-SPACE.hf.space"

async def main():
    inp_text = open("model.inp").read()
    async with streamablehttp_client(f"{SPACE}/mcp") as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            up = json.loads((await s.call_tool("upload_model",
                {"inp_content": inp_text, "filename": "model.inp"})).content[0].text)
            sid = up["session_id"]
            run = json.loads((await s.call_tool("run_simulation",
                {"session_id": sid})).content[0].text)
            print("reconciliation:", run["rpt_reconciliation"])
            links = json.loads((await s.call_tool("get_link_results",
                {"session_id": sid, "limit": 5})).content[0].text)
            for row in links["rows"]:
                print(row["Link ID"], row.get("Peak Velocity (m/s)"))

asyncio.run(main())
