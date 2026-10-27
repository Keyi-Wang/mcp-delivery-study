"""Historical acceptance-policy comparison; native bodies, controlled lifecycle.

No provider call, full Hermes application, or production data is involved.
The branch removal is a causal control, not a recommended deployable patch.
"""
import ast
import asyncio
import copy
import difflib
import hashlib
import json
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcp.types import CallToolResult
from mcp_repair_chain_probe import load as load_old
from mcp_guidance_matrix import evaluate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-obligation-study'
SRC = OUT / 'sources/september/tools'
HANDLER = ROOT / 'artifacts/mcp-preservation-study/sources/hermes-september/tools/mcp_tool_handlers.py'


def source_nodes(path):
    return ast.parse(path.read_text()).body


def execute(path, env, names=None, revert=False):
    nodes = source_nodes(path)
    if names is not None:
        nodes = [n for n in nodes if getattr(n, 'name', None) in names or
                 isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in names for t in n.targets)]
    else:
        nodes = [n for n in nodes if not isinstance(n, ast.ImportFrom) or
                 not (n.module == 'tools' or (n.module or '').startswith('tools.'))]
    if revert:
        renderer = next(n for n in nodes if getattr(n, 'name', '') == '_render_call_tool_result')
        matches = [n for n in renderer.body if isinstance(n, ast.If) and
                   ast.unparse(n.test) == 'structured is not None and usable_parts > 0']
        assert len(matches) == 1
        renderer.body.remove(matches[0])
        original = next(n for n in source_nodes(path) if getattr(n, 'name', '') == renderer.name)
        (OUT / 'branch-removal.diff').write_text(''.join(difflib.unified_diff(
            ast.unparse(original).splitlines(True), ast.unparse(renderer).splitlines(True),
            fromfile='native-renderer', tofile='branch-removal-control')))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)


def unexpected(*args, **kwargs):
    raise RuntimeError('Unexercised external recovery/resource path reached')


def load_september(revert=False):
    records = json.loads((OUT / 'source-manifest.json').read_text())
    for path in [HANDLER] + list(SRC.glob('*.py')):
        record = next(r for r in records if r['path'] == str(path.relative_to(ROOT)))
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
    env = {'__name__': 'pinned_hermes_obligation'}
    for name in ['mcp_tool_common.py', 'ansi_strip.py', 'tool_output_truncate.py']:
        execute(SRC / name, env)
    env['mcp_prefixed_tool_name'] = unexpected
    execute(SRC / 'mcp_tool_content.py', env)
    env['json'] = json
    execute(SRC / 'registry.py', env, {'tool_error', '_bound_error_text',
                                     '_MAX_TOOL_ERROR_CHARS', '_TOOL_ERROR_TRUNCATION_MARKER'})
    execute(HANDLER, env, revert=revert)
    servers = {}
    async def run(call):
        for server in servers.values():
            server._rpc_lock = asyncio.Lock()
        return await call()
    env.update(_trust_gate_check=lambda *a: None,
               _check_circuit_breaker=lambda *a: None,
               _acquire_call_server=lambda name, timeout: (servers[name], None),
               _tool_is_read_only=lambda *a: True,
               _core=SimpleNamespace(_bump_server_error=lambda *a, **kw: None,
                                     _reset_server_error=lambda *a: None),
               _loop=SimpleNamespace(_run_on_mcp_loop=lambda call, timeout: asyncio.run(run(call))),
               _handle_stdio_child_exited_and_retry=unexpected,
               _handle_auth_error_and_retry=unexpected,
               _handle_session_expired_and_retry=unexpected)
    return SimpleNamespace(**env, _servers=servers)


def load_version(label):
    if label == 'combined':
        module = load_old('hermes-combined')
        module._run_on_mcp_loop = lambda coro, timeout: asyncio.run(coro)
        return module
    return load_september(revert=label == 'branch-removal')


def observe(module, source):
    response = CallToolResult.model_validate(source)
    session = SimpleNamespace(call_tool=AsyncMock(return_value=response))
    module._servers['test-server'] = SimpleNamespace(session=session)
    output = module._make_tool_handler('test-server', 'my-tool', 30.0)({})
    assert session.call_tool.await_count == 1
    return output


def run_original_tests(module, path, classes):
    env = dict(json=json, AsyncMock=AsyncMock, mcp_tool=module, _mcp_handlers=module)
    execute(path, env, set(classes) | {'_FakeContentBlock', '_FakeCallToolResult'})
    rows = []
    for cls in classes:
        instance = env[cls]()
        for name in sorted(n for n in dir(instance) if n.startswith('test_')):
            session = SimpleNamespace()
            module._servers['test-server'] = SimpleNamespace(session=session)
            row = dict(test=cls + '.' + name, status='pass')
            try:
                getattr(instance, name)(session)
                assert session.call_tool.await_count == 1
            except (AssertionError, KeyError) as exc:
                frames = traceback.extract_tb(exc.__traceback__)
                assert any(Path(f.filename) == path and (f.line or '').lstrip().startswith('assert ')
                           for f in frames), traceback.format_exc()
                row.update(status='assertion_failure', traceback=traceback.format_exc())
            rows.append(row)
    return rows


def history():
    paths = {name: OUT / f'sources/{name}/tests/tools/test_mcp_structured_content.py'
             for name in ['before-prune', 'after-prune', 'dedup', 'september']}
    functions = {label: {n.name for n in ast.walk(ast.parse(p.read_text()))
                        if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')}
                 for label, p in paths.items()}
    return {'removed_at_prune': sorted(functions['before-prune'] - functions['after-prune']),
            'introduced_since_prune': sorted(functions['dedup'] - functions['after-prune']),
            'test_names_by_version': {k: sorted(v) for k, v in functions.items()},
            'limits': 'Temporal order and verified ancestry do not establish that test pruning caused the later policy change.'}


def main():
    fixtures = json.loads((ROOT / 'artifacts/mcp-paper-evidence/guidance-fixtures.json').read_text())
    test_rows, cells = [], []
    test_sources = [
        ('combined', ROOT / 'artifacts/mcp-paper-evidence/sources/hermes-combined-tests.py',
         ['TestStructuredContentPreservation']),
        ('september', OUT / 'sources/september/tests/tools/test_mcp_structured_content.py',
         ['TestStructuredContentPreservation', 'TestContentStructuredArbitration'])]
    for version in ['combined', 'september', 'branch-removal']:
        module = load_version(version)
        for label, path, classes in test_sources:
            test_rows.extend(dict(r, implementation=version, test_source=label)
                             for r in run_original_tests(module, path, classes))
        for fixture in fixtures:
            output = observe(module, fixture['source'])
            cells.append(dict(implementation=version, fixture=fixture['name'], output=output,
                              utf8_bytes=len(output.encode()),
                              **evaluate(output, fixture['requirements'], fixture['forbidden'])))
    groups = [dict(implementation=v, test_source=s, passed=sum(r['status'] == 'pass' for r in test_rows
                    if r['implementation'] == v and r['test_source'] == s),
                   total=sum(r['implementation'] == v and r['test_source'] == s for r in test_rows))
              for v in ['combined', 'september', 'branch-removal'] for s, _, _ in test_sources]
    expected = [(5, 5), (5, 7), (3, 5), (7, 7), (5, 5), (5, 7)]
    assert [(r['passed'], r['total']) for r in groups] == expected, groups
    producer = json.loads((OUT / 'native-producer-results.json').read_text())
    composed = []
    for version in ['combined', 'september', 'branch-removal']:
        module = load_version(version)
        for row in producer['rows']:
            output = observe(module, row['source_result'])
            requirement = {'kind': 'json_subset', 'value': row['tool_payload']}
            composed.append(dict(implementation=version, force_full_text=row['force_full_text'],
                                 task=row['task'], answer=row['answer'], output=output,
                                 utf8_bytes=len(output.encode()),
                                 **evaluate(output, [requirement], [])))
    pairs = []
    for version in ['combined', 'september', 'branch-removal']:
        for force_full in [False, True]:
            for task in ['wan_status', 'wlan_record']:
                pair = [r for r in composed if (r['implementation'], r['force_full_text'], r['task']) ==
                        (version, force_full, task)]
                assert len(pair) == 2 and pair[0]['answer'] != pair[1]['answer']
                collision = pair[0]['output'] == pair[1]['output']
                assert collision == (version == 'september' and not force_full)
                assert all(r['required_information_present'] != collision for r in pair)
                pairs.append(dict(implementation=version, force_full_text=force_full, task=task,
                                  different_answers_same_handler_output=collision))
    report = dict(groups=groups, test_rows=test_rows, cells=cells, history=history(), paid_model_calls=0,
                  producer_consumer_cells=composed, producer_consumer_pairs=pairs,
                  limits=['Unchanged original test bodies and assertions; controlled session fixture bindings.',
                          'Native September handler, dispatch and rendering bodies execute with pinned native helpers.',
                          'Lifecycle gates, bookkeeping, session and scheduler are controlled; recovery fails closed if reached.',
                          'No complete Hermes installation, provider request, model inference or production trace.',
                          'Producer-consumer composition replays serialized client-observed MCP results into a controlled Hermes session; not one continuous distributed session.',
                          'Combined-version comparisons overlap earlier evidence; do not add them as independent observations.',
                          'Branch removal isolates arbitration, but duplicates payload and does not solve recipient privacy.',
                          'Application-private metadata fixture is an authored policy requirement, not a universal MCP rule.'])
    paths = list(SRC.glob('*.py')) + [HANDLER] + [p for _, p, _ in test_sources]
    report['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (OUT / 'obligation-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'groups': groups, 'history': report['history'], 'cells': len(cells)}, indent=2))


if __name__ == '__main__':
    main()
