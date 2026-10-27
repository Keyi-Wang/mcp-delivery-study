"""Pinned UniFi response middleware in real local negotiated MCP sessions.

Tools return authored domain-shaped records; this is not the UniFi application,
controller, a recorded incident payload, or an actual LLM evaluation.
"""
import ast
import asyncio
import hashlib
import importlib.util
import inspect
import json
import platform
from importlib.metadata import version
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-obligation-study'
SOURCE = OUT / 'sources/unifi/src/mcp_unifi/responses.py'
TESTS = OUT / 'sources/unifi/tests/test_adaptive_responses.py'


def load():
    records = json.loads((OUT / 'source-manifest.json').read_text())
    for path in [SOURCE, TESTS]:
        record = next(r for r in records if r['path'] == str(path.relative_to(ROOT)))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
    spec = importlib.util.spec_from_file_location('pinned_unifi_responses', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main():
    module = load()
    env = dict(vars(module), pytest=pytest)
    # Keep original unit-test bodies, decorators and local context doubles.
    # Exclude application construction and all build_server-dependent E2E tests.
    nodes = [n for n in ast.parse(TESTS.read_text()).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
             and n.name != 'stdio_server' and not n.name.startswith('test_end_to_end_')]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(TESTS), 'exec'), env)
    tests = []
    for node in nodes:
        if not node.name.startswith('test_'):
            continue
        fn = env[node.name]
        parameter_marks = [m for m in getattr(fn, 'pytestmark', []) if m.name == 'parametrize']
        arguments = parameter_marks[0].args[1] if parameter_marks else [()]
        for args in arguments:
            value = fn(*args)
            if inspect.isawaitable(value):
                await value
            tests.append({'test': node.name, 'parameters': list(args), 'status': 'pass'})
    rows = []
    for force_full in [False, True]:
        for task in ['wan_status', 'wlan_record']:
            for answer in ['ALPHA_PROBE', 'BETA_PROBE']:
                payload = ({'wan2': {'state': answer}} if task == 'wan_status' else
                           [{'_id': 'w1', 'name': answer, 'enabled': True, 'security': 'wpa2',
                             'wlan_band': 'both', 'x_passphrase': '[REDACTED]'}])
                server = FastMCP('controlled-native-producer')
                server.add_middleware(module.AdaptiveResponseMiddleware(force_full_text=force_full))
                @server.tool(name='get_wan_status' if task == 'wan_status' else 'list_wlans')
                def read_record() -> str:
                    return json.dumps(payload, indent=2)
                async with Client(server) as client:
                    negotiated = client.initialize_result.protocolVersion
                    assert module.supports_structured_content(negotiated)
                    listed = await client.list_tools()
                    result = await client.call_tool(listed[0].name, {})
                    # Preserve the client-observed MCP fields, not a re-summarized result.
                    source = {'content': [b.model_dump(by_alias=True, exclude_none=True) for b in result.content],
                              'structuredContent': result.structured_content, 'isError': result.is_error}
                    text = ''.join(b.text for b in result.content)
                    expected = payload if isinstance(payload, dict) else {'result': payload}
                    retained = json.loads(text) == payload if force_full else result.structured_content == expected
                    assert retained
                    assert (answer in text) == force_full
                    rows.append({'force_full_text': force_full, 'task': task, 'answer': answer,
                                 'tool_payload': payload, 'negotiated_protocol_version': negotiated,
                                 'listed_output_schema': listed[0].outputSchema,
                                 'source_result': source, 'producer_client_retains_full_payload': retained})
    report = dict(unit_tests=tests, rows=rows, paid_model_calls=0,
                  environment={'python': platform.python_version(), 'fastmcp': version('fastmcp'), 'mcp': version('mcp')},
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [SOURCE, TESTS]},
                  limits=['Whole pinned response middleware; exact declared FastMCP 3.4.7 dependency.',
                          'Component executes on Python 3.10; full UniFi application declares Python >=3.13 and is not installed.',
                          'Real in-memory MCP initialization/list_tools/call_tool; no stdio, HTTP, UniFi controller or LLM.',
                          'Authored records and local tool callbacks; not production recordings or real WAN measurements.',
                          'Original revision-floor and middleware tests execute; original build_server E2E tests excluded.',
                          'Legacy/unknown-revision behavior is covered by original controlled-context unit tests, not old-client transport.'])
    (OUT / 'native-producer-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'original_unit_executions': len(tests), 'native_negotiated_sessions': len(rows),
                      'full_payload_retained_at_client': sum(r['producer_client_retains_full_payload'] for r in rows)}))


if __name__ == '__main__':
    asyncio.run(main())
