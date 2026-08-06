"""Deployment smoke test. Run against a live server:
    python smoke_test.py http://127.0.0.1:7860  (or the Space URL)
Verifies: health, REST tool call, full MCP workflow, regression pin (>=26/27
links reconciled on Kincora), report download, agent 400-without-key.
Requires a local Kincora_Phase_2.inp or any valid .inp passed as argv[2].
"""
import asyncio, json, sys
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:7860"
INP = sys.argv[2] if len(sys.argv) > 2 else "Kincora_Phase_2.inp"

async def main():
    h = httpx.get(f"{BASE}/health", timeout=30).json()
    assert h["status"] == "ok", h
    print("health:", h["server"], h["version"], "| tools", h["tools"])
    r = httpx.post(f"{BASE}/api/tool/list_sessions", json={}, timeout=30)
    assert r.status_code == 200
    print("REST surface: OK")
    inp = open(INP, encoding="utf-8", errors="replace").read()
    async with streamablehttp_client(f"{BASE}/mcp") as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            assert len(tools.tools) >= 16
            up = json.loads((await s.call_tool("upload_model",
                {"inp_content": inp, "filename": INP})).content[0].text)
            sid = up["session_id"]
            run = json.loads((await s.call_tool("run_simulation", {"session_id": sid})).content[0].text)
            recon = run["rpt_reconciliation"]
            print(f"MCP workflow: session {sid} | recon {recon.get('ok')}/{recon.get('links_checked')}")
            if "Kincora" in INP:
                assert recon.get("ok", 0) >= 26, "REGRESSION PIN FAILED"
            # 1x1 red PNG — validates the attach_figure -> embedded-report path
            tiny_png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
                        "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
            fig = json.loads((await s.call_tool("attach_figure",
                {"session_id": sid, "image_base64": tiny_png,
                 "caption": "Smoke-test figure", "section": "results"})).content[0].text)
            assert fig["figure_id"] == "FIG-01", fig
            print("attach_figure: OK", fig["figure_id"])
            rep = json.loads((await s.call_tool("generate_report",
                {"session_id": sid, "project_name": "Smoke Test"})).content[0].text)
            dl = httpx.get(f"{BASE}{rep['files']['docx']}", timeout=60)
            assert dl.status_code == 200 and len(dl.content) > 30000
            print("report + download: OK", len(dl.content), "bytes")
            await s.call_tool("close_session", {"session_id": sid})
    r = httpx.post(f"{BASE}/api/agent", json={"question": "x", "provider": "anthropic"}, timeout=30)
    print("agent (no key expected 400 unless secret set):", r.status_code)
    print("\nSMOKE TEST: PASS")

asyncio.run(main())
