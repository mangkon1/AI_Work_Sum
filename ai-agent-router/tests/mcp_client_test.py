"""
MCP client smoke test (streamable HTTP, SSE, stdio). Works with mcp SDK v1 or v2.

Prerequisite: an agent named "echo" of type http pointing at tests/mock_echo_server.py
(python tests/mock_echo_server.py 9001), and an API key bound to opencode.

    set KEY=<your key>   (PowerShell: $env:KEY="<your key>")
    python tests/mcp_client_test.py http
    python tests/mcp_client_test.py sse
    python tests/mcp_client_test.py http-badkey
    python tests/mcp_client_test.py stdio python main.py --mcp-stdio
"""
import asyncio, sys, os
from contextlib import asynccontextmanager
import mcp
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

V2 = hasattr(mcp, "Client") and not hasattr(__import__("mcp.client.streamable_http", fromlist=["x"]), "streamablehttp_client")
KEY = os.environ.get("KEY", "oc-secret-123")
URL = os.environ.get("URL", "http://127.0.0.1:8080")

@asynccontextmanager
async def http_streams(key):
    if V2:
        import httpx2
        from mcp.client.streamable_http import streamable_http_client
        async with httpx2.AsyncClient(headers={"X-API-Key": key}, timeout=60) as c:
            async with streamable_http_client(URL + "/mcp", http_client=c) as s:
                yield s[0], s[1]
    else:
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(URL + "/mcp", headers={"X-API-Key": key}) as (r, w, _):
            yield r, w

@asynccontextmanager
async def sse_streams(key):
    from mcp.client.sse import sse_client
    if V2:
        import httpx2, inspect
        params = inspect.signature(sse_client).parameters
        if "headers" in params:
            cm = sse_client(URL + "/sse", headers={"X-API-Key": key})
        else:
            cm = sse_client(URL + "/sse", http_client=httpx2.AsyncClient(headers={"X-API-Key": key}))
    else:
        cm = sse_client(URL + "/sse", headers={"X-API-Key": key})
    async with cm as s:
        yield s[0], s[1]

@asynccontextmanager
async def stdio_streams(cmd):
    params = StdioServerParameters(command=cmd[0], args=cmd[1:], cwd=os.getcwd())
    async with stdio_client(params) as s:
        yield s[0], s[1]

def show(res):
    txt = " ".join(getattr(c, "text", "") for c in res.content)
    return f"isError={res.isError if hasattr(res,'isError') else res.is_error} structured={getattr(res,'structuredContent',None) or getattr(res,'structured_content',None)} text={txt[:220]}"

async def run(label, streams):
    async with streams as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            pv = getattr(init, "protocolVersion", None) or getattr(init, "protocol_version", None)
            tools = await s.list_tools()
            print(f"[{label}] protocol={pv} tools={[t.name for t in tools.tools]}")
            r1 = await s.call_tool("list_agents", {})
            print(f"[{label}] list_agents -> {show(r1)[:200]}")
            r2 = await s.call_tool("invoke_agent", {"target": "echo", "message": "hello via MCP", "context": {"k": 1}, "from_agent": "opencode"})
            print(f"[{label}] invoke_agent echo -> {show(r2)}")
            r3 = await s.call_tool("delegate", {"target": "nosuch", "message": "x"})
            print(f"[{label}] delegate nosuch -> {show(r3)}")
            r4 = await s.call_tool("invoke_agent", {"target": "grok", "message": "x"})
            print(f"[{label}] invoke_agent grok -> {show(r4)}")

async def main():
    mode = sys.argv[1]
    if mode == "http":
        await run("http", http_streams(KEY))
    elif mode == "http-badkey":
        try:
            await run("http-badkey", http_streams("wrong"))
            print("[http-badkey] UNEXPECTED success")
        except BaseException as e:
            print(f"[http-badkey] rejected as expected: {type(e).__name__}: {str(e)[:150]}")
    elif mode == "sse":
        await run("sse", sse_streams(KEY))
    elif mode == "stdio":
        await run("stdio", stdio_streams(sys.argv[2:]))

asyncio.run(main())
