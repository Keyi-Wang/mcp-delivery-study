"""Replay public Agno adapter code through its native tool-message builder.

No model provider, live MCP server, credentials, or private records are used.
The local session is a controlled stand-in. This reproduces a known fixed bug;
it is not a new vulnerability, population estimate or downstream agent study.
"""
import asyncio
import hashlib
import importlib.util
import json
from importlib.metadata import version
from pathlib import Path

from agno.models.base import Model
from agno.tools.function import Function, FunctionCall
from mcp.types import CallToolResult, TextContent, Tool

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/empirical-directions-20261026'


class NoProviderModel(Model):
    def invoke(self, *args, **kwargs):
        raise AssertionError('Provider calls forbidden in this probe')

    ainvoke = invoke
    invoke_stream = invoke
    ainvoke_stream = invoke
    _parse_provider_response = invoke
    _parse_provider_response_delta = invoke


class LocalSession:
    def __init__(self, response):
        self.response = response

    async def send_ping(self):
        return None

    async def call_tool(self, name, args):
        assert name == 'get_record' and args == {}
        return self.response.model_copy(deep=True)


def load_source(label):
    path = OUT / 'sources' / label / 'mcp.py'
    spec = importlib.util.spec_from_file_location('visibility_' + label, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    import agno.models.base
    import agno.utils.mcp

    # Ensure the released environment agrees with the pinned audited sources.
    assert version('agno') == '2.6.20'
    assert Path(agno.utils.mcp.__file__).read_bytes() == (OUT / 'sources/before/mcp.py').read_bytes()
    assert Path(agno.models.base.__file__).read_bytes() == (OUT / 'sources/libs/agno/agno/models/base.py').read_bytes()
    for row in json.loads((OUT / 'source-manifest.json').read_text()):
        data = (ROOT / row['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row['sha256']
    data = {'id': 'record-42', 'status': 'ACTIVE'}
    fixtures = {
        'structured_only_success': CallToolResult(content=[], structuredContent=data, isError=False),
        'text_only_success': CallToolResult(content=[TextContent(type='text', text=json.dumps(data))], isError=False),
        'duplicated_success': CallToolResult(content=[TextContent(type='text', text=json.dumps(data))], structuredContent=data, isError=False),
        'structured_only_error': CallToolResult(content=[], structuredContent={'code': 'NOT_FOUND', 'record_id': 'record-42'}, isError=True),
    }
    tool = Tool(name='get_record', inputSchema={'type': 'object', 'properties': {}})
    records = []
    for label in ['before', 'after']:
        module = load_source(label)
        for name, result in fixtures.items():
            entrypoint = module.get_entrypoint_for_tool(tool, LocalSession(result))
            converted = asyncio.run(entrypoint())
            # Execute the real v2.6.20 message-building path on the converted result.
            function = Function(name='get_record', entrypoint=lambda: converted)
            function_call = FunctionCall(function=function, arguments={}, call_id='local-probe')
            messages = []
            list(NoProviderModel(id='offline-no-provider').run_function_call(function_call, messages))
            assert len(messages) == 1
            message = messages[0]
            records.append({'adapter': label, 'case': name,
                'wire_result': result.model_dump(mode='json', by_alias=True, exclude_none=True),
                'adapter_content': converted.content, 'adapter_metadata': converted.metadata,
                'native_tool_message_content': message.content,
                'native_tool_message_error': message.tool_call_error})
    def row(label, case):
        return next(x for x in records if x['adapter'] == label and x['case'] == case)
    before = row('before', 'structured_only_success')
    after = row('after', 'structured_only_success')
    assert before['adapter_metadata']['structured_content'] == data
    assert before['native_tool_message_content'] == ''
    assert json.loads(after['native_tool_message_content']) == data
    for label in ['before', 'after']:
        for case in ['text_only_success', 'duplicated_success']:
            assert json.loads(row(label, case)['native_tool_message_content']) == data
        # Diagnostic only: error cause survives in metadata, not in primary text.
        error = row(label, 'structured_only_error')
        assert error['adapter_metadata']['structured_content']['code'] == 'NOT_FOUND'
        assert 'NOT_FOUND' not in error['native_tool_message_content']
    report = {'kind': 'known_bug_component_reproduction_and_controlled_diagnostic',
        'source_issue': 'https://github.com/agno-agi/agno/issues/8653',
        'upstream_fix': 'https://github.com/agno-agi/agno/pull/8695',
        'versions': {p: version(p) for p in ['agno', 'mcp', 'pydantic']},
        'records': records, 'paid_api_calls': 0, 'live_server_calls': 0,
        'findings': ['Pinned release preserves structured-only success in metadata but produces an empty native tool message.',
            'The upstream patched adapter restores that success payload under the same message-building code.',
            'Structured-only error causes remain in metadata rather than primary message text in this controlled input. This is a follow-up diagnostic, not a newly confirmed production defect.'],
        'limits': ['Session and field values are authored, source-shaped controls, not production recordings.',
            'No complete Brex workflow, real UI, model inference or downstream action evaluated.',
            'After arm swaps the upstream adapter into v2.6.20 dependencies; it is not a complete later-release evaluation.',
            'The MCP specification recommends a serialized text fallback. Omission of that fallback and client presentation choices must be distinguished from MUST-level protocol violations.',
            'A known fixed bug is existence evidence, not sufficient research novelty.']}
    (OUT / 'agno-native-probe.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'component_cases': len(records), 'before_success_message': before['native_tool_message_content'],
                      'after_success_message': after['native_tool_message_content'], 'api_calls': 0}))


if __name__ == '__main__':
    main()
