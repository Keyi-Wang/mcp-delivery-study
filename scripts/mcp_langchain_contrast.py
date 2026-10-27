"""Pinned LangChain adapter repair: intended artifact recipient and content.

Original converter tests execute unchanged. Whole historical adapter modules use
one fixed installed dependency environment. Session is controlled; no provider.
"""
import ast
import asyncio
import hashlib
import importlib.util
import json
import traceback
from importlib.metadata import version
from pathlib import Path

import pytest
import mcp.types as mt
from dirty_equals import IsStr
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-acceptance-study'


def load(label):
    p = OUT / 'sources' / ('langchain-' + label) / 'langchain_mcp_adapters/tools.py'
    spec = importlib.util.spec_from_file_location('lc_' + label, p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    """Remove only generated content-block IDs from replay comparisons."""
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()
                if not (k == 'id' and isinstance(v, str) and v.startswith('lc_'))}
    if isinstance(value, list):
        return [canonical(x) for x in value]
    return value


class Session:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def call_tool(self, name, args, **kwargs):
        assert name == 'read_record' and args == {}
        self.calls += 1
        return self.result.model_copy(deep=True)


def main():
    modules = {label: load(label) for label in ['before', 'after']}
    util = OUT / 'sources/langchain-after/tests/utils.py'
    assignment = next(n for n in ast.parse(util.read_text()).body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'IsLangChainID' for t in n.targets))
    bindings = {'IsStr': IsStr}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(util), 'exec'), bindings)
    test_rows = []
    for test_version in ['before', 'after']:
        path = OUT / 'sources' / ('langchain-' + test_version) / 'tests/test_tools.py'
        nodes = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef)
                 and n.name.startswith('test_convert') and not n.args.args
                 and any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == '_convert_call_tool_result'
                         for x in ast.walk(n))]
        for label, module in modules.items():
            env = {**vars(mt), 'pytest': pytest, 'ToolException': ToolException,
                   '_convert_call_tool_result': module._convert_call_tool_result,
                   'MCPToolArtifact': modules['after'].MCPToolArtifact,
                   'IsLangChainID': bindings['IsLangChainID']}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
            for node in nodes:
                row = {'test_version': test_version, 'implementation': label, 'test': node.name, 'status': 'pass'}
                try:
                    env[node.name]()
                except (AssertionError, pytest.fail.Exception):
                    row.update(status='assertion_failure', traceback=traceback.format_exc())
                except Exception as exc:
                    # Original tests expecting conversion can legitimately fail because
                    # a historical implementation raises its documented unsupported error.
                    row.update(status='execution_exception', exception_type=type(exc).__name__, traceback=traceback.format_exc())
                test_rows.append(row)
    groups = []
    for tv in ['before', 'after']:
        for label in modules:
            group = [r for r in test_rows if r['test_version'] == tv and r['implementation'] == label]
            groups.append({'test_version': tv, 'implementation': label, 'total': len(group),
                           'passed': sum(r['status'] == 'pass' for r in group),
                           'exceptions': sum(r['status'] == 'execution_exception' for r in group)})
    assert len(test_rows) == 42
    assert next(g for g in groups if g['test_version'] == 'before' and g['implementation'] == 'before')['passed'] == 5
    assert next(g for g in groups if g['test_version'] == 'after' and g['implementation'] == 'after')['passed'] == 16

    answer = 'ARTIFACT_ANSWER_47'
    data = {'record_id': 'shared-design-42', 'status': answer}
    text = lambda s: mt.TextContent(type='text', text=s)
    # Valid 1x1 PNG reused from the independently checked media fixture.
    media = json.loads((ROOT / 'artifacts/mcp-preservation-followup/webui-media-probe.json').read_text())
    png = next(c['input']['content'][0]['data'] for c in media['cells'] if c['fixture'] == 'image')
    cases = {
        'structured_only': mt.CallToolResult(content=[], structuredContent=data),
        'summary_plus_data': mt.CallToolResult(content=[text('Record read; details are structured.')], structuredContent=data),
        'equivalent_dual': mt.CallToolResult(content=[text(json.dumps(data))], structuredContent=data),
        'image': mt.CallToolResult(content=[mt.ImageContent(type='image', mimeType='image/png', data=png)]),
        'embedded_text': mt.CallToolResult(content=[mt.EmbeddedResource(type='resource', resource=mt.TextResourceContents(uri='resource://shared/design', mimeType='text/plain', text=answer))]),
        'text_error': mt.CallToolResult(content=[text('Read denied')], isError=True),
        'audio_explicit_unsupported': mt.CallToolResult(content=[mt.AudioContent(type='audio', mimeType='audio/wav', data='ZmFrZQ==')]),
    }
    rows = []
    for label, module in modules.items():
        for name, source in cases.items():
            session = Session(source)
            tool = module.convert_mcp_tool_to_langchain_tool(session, mt.Tool(name='read_record', inputSchema={'type': 'object', 'properties': {}}))
            row = {'implementation': label, 'fixture': name, 'source': source.model_dump(mode='json', by_alias=True, exclude_none=True)}
            try:
                message = asyncio.run(tool.ainvoke({'name': 'read_record', 'args': {}, 'id': 'contrast-call', 'type': 'tool_call'}))
                assert isinstance(message, ToolMessage)
                dumped = message.model_dump(mode='json')
                row.update(status='returned_tool_message', message=canonical(dumped),
                           answer_in_content=answer in json.dumps(dumped['content']),
                           answer_in_artifact=answer in json.dumps(dumped['artifact']),
                           png_in_content=png in json.dumps(dumped['content']),
                           png_in_artifact=png in json.dumps(dumped['artifact']))
            except (ToolException, NotImplementedError) as exc:
                row.update(status='explicit_exception', exception_type=type(exc).__name__, message=str(exc))
            assert session.calls == 1
            rows.append(row)
    idx = {(r['implementation'],r['fixture']):r for r in rows}
    for fixture in ['structured_only','summary_plus_data']:
        assert idx['after',fixture]['answer_in_artifact'] and not idx['after',fixture]['answer_in_content']
        assert not idx['before',fixture]['answer_in_artifact'] and not idx['before',fixture]['answer_in_content']
    assert idx['before','image']['png_in_artifact'] and not idx['before','image']['png_in_content']
    assert idx['after','image']['png_in_content'] and not idx['after','image']['png_in_artifact']
    assert idx['after','audio_explicit_unsupported']['exception_type'] == 'NotImplementedError'
    assert all(idx[v,'text_error']['exception_type'] == 'ToolException' for v in modules)
    assert all(idx[v,'equivalent_dual']['answer_in_content'] for v in modules)
    assert idx['after','embedded_text']['answer_in_content'] and not idx['before','embedded_text']['answer_in_content']
    report = {'protocol': 'research/mcp-acceptance-strengthening-protocol.json',
              'test_rows': test_rows, 'test_groups': groups, 'rows': rows,
              'dependency_versions': {p:version(p) for p in ['langchain-mcp-adapters','langchain-core','mcp','pytest','dirty-equals']},
              'boundary': 'Whole pinned adapter modules, native StructuredTool.ainvoke and ToolMessage, controlled session; no provider serialization or inference.',
              'source_requirement': 'Merged PR379 explicitly assigns structured data to MCPToolArtifact and media/resource data to chat content.',
              'limits': ['Artifact retention succeeds under the documented recipient contract even where ToolMessage.content lacks the structured answer.',
                         'Both historical modules share one modern dependency environment, not full historical releases.',
                         'Original tests selected by direct converter invocation; not full upstream CI.',
                         'Only auto-generated lc_ content-block IDs are removed for deterministic comparison.',
                         'Audio is an explicit unsupported-path control, not a silent-loss defect.'],
              'paid_calls':0}
    (OUT/'langchain-contrast.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'test_groups':groups,'rows':[{k:v for k,v in r.items() if k not in ['source','message']} for r in rows]},indent=2))


if __name__ == '__main__':
    main()
