"""Pinned Superset middleware class in a minimal real MCP HTTP stack.

Does not boot Superset or its full middleware chain. Extraction preserves class
code; unrelated application logging/sanitization dependencies are substituted.
"""
import ast
import asyncio
import hashlib
import json
from contextvars import ContextVar
from importlib.metadata import version
from pathlib import Path
from typing import Awaitable, Callable, Sequence

import httpx
import mcp.types as mt
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.middleware.middleware import CallNext
from fastmcp.tools.tool import Tool, ToolResult

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-preservation-study-20261026'


def middleware(label):
    rec = next(r for r in json.loads((OUT/'source-manifest.json').read_text()) if r['label']==label)
    path = OUT/rec['local']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==rec['sha256']
    node = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name=='StructuredContentStripperMiddleware')
    env = dict(globals(), _mcp_call_id_var=ContextVar('offline_id', default=None),
               _sanitize_error_for_logging=str, _invoke_error_hook=lambda *args: None)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'),env)
    return env['StructuredContentStripperMiddleware']()


async def run(label):
    server = FastMCP('preservation-probe', middleware=[middleware(label)])
    @server.tool
    def health_check() -> str:
        return 'OK_PROBE'
    @server.tool
    def denied() -> str:
        raise ToolError('DENIED_PROBE')
    app = server.http_app(transport='streamable-http', json_response=True, stateless_http=True)
    captured=[]
    async def capture(scope, receive, send):
        chunks=[]
        async def send_record(message):
            if message['type']=='http.response.body':
                chunks.append(message.get('body',b''))
            await send(message)
        await app(scope,receive,send_record)
        raw=b''.join(chunks)
        if raw:
            try: captured.append(json.loads(raw))
            except ValueError: pass
    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=capture),**kwargs)
    transport=StreamableHttpTransport('http://offline.invalid/mcp',httpx_client_factory=factory)
    rows=[]
    async with app.router.lifespan_context(app):
        async with Client(transport) as client:
            await client.list_tools()
            for name in ['health_check','denied','no_such_tool']:
                result=await client.call_tool(name,{},raise_on_error=False)
                wire=[r['result'] for r in captured if isinstance(r,dict) and isinstance(r.get('result'),dict) and 'content' in r['result']][-1]
                rows.append({'version':label,'tool':name,'client_is_error':result.is_error,
                             'client_content':[b.model_dump(exclude_none=True) for b in result.content], 'wire_result':wire})
                assert wire.get('isError',False)==result.is_error
    return rows


async def main():
    rows=[]
    for label in ['superset-before','superset-after']:
        rows.extend(await run(label))
    for row in rows:
        if row['tool']=='health_check':
            assert row['client_is_error'] is False
            assert row['client_content'][0]['text']=='OK_PROBE'
        else:
            assert row['client_is_error']==(row['version']=='superset-after')
            assert row['client_content'][0]['text'].startswith('Error:')
    report={'kind':'extracted_native_middleware_with_real_asgi_mcp_transport','rows':rows,
            'versions':{p:version(p) for p in ['fastmcp','mcp','httpx']},
            'paid_api_calls':0,'external_server_calls':0,
            'limits':['Original middleware class extracted unchanged from pinned source; application sanitizer replaced by str for fixed non-sensitive fixture messages and optional application error hook disabled.',
                      'Minimal FastMCP stack, not the full Superset middleware list, database, authorization system or Claude bridge.',
                      'Actual initialize/list/call HTTP JSON-RPC serialized through ASGITransport; no TCP sockets.',
                      'Stateless JSON transport is a controlled test configuration, not a claim about every production transport.',
                      'No downstream model behavior or new residual production defect claimed.']}
    (OUT/'superset-wire-probe.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([{'version':r['version'],'tool':r['tool'],'isError':r['client_is_error']} for r in rows],indent=2))


if __name__=='__main__':
    asyncio.run(main())
