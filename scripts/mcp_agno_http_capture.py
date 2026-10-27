"""Native Agno Agent loop -> real loopback HTTP provider requests, no LLM."""
import asyncio
import argparse
import hashlib
import json
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path

import httpx
from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.function import Function
from mcp.types import CallToolResult, TextContent, Tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_visibility_probe import LocalSession, load_source

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-paper-evidence'


def execute(label, fixture, answer, mcp_stdio=False, adapter_module=None,
            enforce_original_expectations=True):
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path': self.path, 'body': body})
            if len(requests) == 1:
                message = {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'call_record', 'type': 'function', 'function': {'name': 'get_record', 'arguments': '{}'}}]}
                reason = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': 'TRANSPORT_CAPTURE_COMPLETE_NOT_AN_LLM_ANSWER'}
                reason = 'stop'
            response = {'id': 'offline_completion', 'object': 'chat.completion', 'created': 0,
                        'model': 'offline-transport-receiver', 'choices': [{'index': 0, 'message': message, 'finish_reason': reason}],
                        'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    payload = {'record_id': 'work-package-42', 'status': answer}
    if fixture == 'structured_only':
        result = CallToolResult(content=[], structuredContent=payload)
    elif fixture == 'summary_plus_data':
        result = CallToolResult(content=[TextContent(type='text', text='Query completed; the work package is in structuredContent.')], structuredContent=payload)
    elif fixture == 'file_plus_metadata':
        result = CallToolResult(content=[TextContent(type='text', text='status=' + answer)], structuredContent={'fileName': 'work-package.txt', 'fileType': 'text'})
    else:
        result = CallToolResult(content=[TextContent(type='text', text=json.dumps(payload))], structuredContent=payload)
    adapter = adapter_module if adapter_module is not None else load_source(label)
    entry = adapter.get_entrypoint_for_tool(Tool(name='get_record', inputSchema={'type': 'object', 'properties': {}}), LocalSession(result))
    converted = []
    mcp_trace = []

    async def call_native_stdio():
        path = OUT / 'stdio-fixtures' / f'{label}-{fixture}-{answer}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(result.model_dump_json(by_alias=True, exclude_none=True))
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'scripts/mcp_result_fixture_server.py'), str(path)])
        with path.with_suffix('.stderr.log').open('w') as errlog:
            async with stdio_client(params, errlog=errlog) as (reader, writer):
                class CaptureSession(ClientSession):
                    async def call_tool(self, name, arguments=None, **kwargs):
                        actual = await super().call_tool(name, arguments, **kwargs)
                        mcp_trace.append(actual.model_dump(mode='json', by_alias=True, exclude_none=True))
                        return actual
                async with CaptureSession(reader, writer) as session:
                    await session.initialize()
                    discovered = await session.list_tools()
                    native_entry = adapter.get_entrypoint_for_tool(discovered.tools[0], session)
                    value = await native_entry()
        receipt = json.loads(path.with_suffix('.receipt.json').read_text())
        expected_source = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        assert len(mcp_trace) == 1 and mcp_trace[0] == receipt['returned'] == expected_source
        return value

    def get_record():
        value = asyncio.run(call_native_stdio() if mcp_stdio else entry())
        converted.append(value)
        return value

    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(trust_env=False, timeout=15) as client:
            model = OpenAIChat(id='offline-transport-receiver', api_key='offline-placeholder-not-a-credential',
                               base_url=f'http://127.0.0.1:{server.server_port}/v1', http_client=client,
                               max_retries=0, temperature=0, max_tokens=64)
            function = Function(name='get_record', description='Read the current work-package record.',
                                parameters={'type': 'object', 'properties': {}}, entrypoint=get_record)
            agent = Agent(model=model, tools=[function], telemetry=False, markdown=False)
            output = agent.run('Read the work-package record with get_record and report its exact status. Do not guess.')
        assert len(converted) == 1 and len(requests) == 2
        assert output.content == 'TRANSPORT_CAPTURE_COMPLETE_NOT_AN_LLM_ANSWER'
        messages = requests[1]['body']['messages']
        tool_messages = [m for m in messages if m['role'] == 'tool']
        assert len(tool_messages) == 1
        expected = label == 'after' and fixture == 'structured_only' or fixture in ['file_plus_metadata', 'equivalent_dual']
        preserved = answer in json.dumps(tool_messages, ensure_ascii=False)
        if enforce_original_expectations:
            assert preserved == expected
        return {'adapter': label, 'fixture': fixture, 'answer': answer,
                'source_result': result.model_dump(mode='json', by_alias=True, exclude_none=True),
                'mcp_transport': 'actual_stdio_server_and_ClientSession' if mcp_stdio else 'controlled_session',
                'mcp_received_results': mcp_trace,
                'metadata': converted[0].metadata, 'actual_http_requests': requests,
                'answer_in_actual_followup_tool_message': preserved,
                'model_inference_performed': False}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mcp-stdio', action='store_true')
    args = parser.parse_args()
    assert version('agno') == '2.6.20'
    rows, errors = [], []
    for label in ['before', 'after']:
        for fixture in ['structured_only', 'summary_plus_data', 'file_plus_metadata', 'equivalent_dual']:
            for answer in ['STATE_ALPHA_7K', 'STATE_BETA_9M']:
                try:
                    rows.append(execute(label, fixture, answer, mcp_stdio=args.mcp_stdio))
                except Exception:
                    errors.append({'adapter': label, 'fixture': fixture, 'answer': answer, 'traceback': traceback.format_exc()})
    pairs = []
    for label in ['before', 'after']:
        for fixture in ['structured_only', 'summary_plus_data', 'file_plus_metadata', 'equivalent_dual']:
            group = [r for r in rows if r['adapter'] == label and r['fixture'] == fixture]
            if len(group) == 2:
                first = group[0]['actual_http_requests'][1]['body']
                second = group[1]['actual_http_requests'][1]['body']
                pairs.append({'adapter': label, 'fixture': fixture,
                              'full_followup_request_collision': first == second,
                              'required_answers_differ': True,
                              'both_required_answers_present': all(r['answer_in_actual_followup_tool_message'] for r in group)})
    report = {'protocol': 'research/mcp-paper-evidence-protocol.json', 'kind': 'real_loopback_HTTP_with_scripted_provider',
              'versions': {p: version(p) for p in ['agno', 'mcp', 'openai', 'httpx']},
              'mcp_transport': 'actual_stdio' if args.mcp_stdio else 'controlled_session',
              'rows': rows, 'errors': errors, 'pairs': pairs, 'runs': len(rows),
              'http_requests': sum(len(r['actual_http_requests']) for r in rows),
              'limits': ['Real native Agent loop and provider client; MCP transport identified separately; scripted HTTP response.',
                         'No real LLM inference; no task accuracy result. Literal marker task is an authored diagnostic, not a production benchmark.',
                         'Summary-plus-data exclusion after fix is documented behavior; incompleteness is relative to a task requiring complementary structured values.',
                         'Fixed adapter swapped into2.6.20, not a complete later-release comparison.'],
              'paid_api_calls': 0}
    filename = 'agno-stdio-http-capture.json' if args.mcp_stdio else 'agno-http-capture.json'
    (OUT / filename).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'runs': report['runs'], 'http_requests': report['http_requests'], 'pairs': pairs, 'errors': errors}, indent=2))
    assert not errors


if __name__ == '__main__':
    main()
