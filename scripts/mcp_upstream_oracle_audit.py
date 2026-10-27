"""Execute selected unmodified upstream tests, not full upstream suites."""
import ast
import asyncio
import hashlib
import importlib.util
import inspect
import json
import sys
import traceback
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agno.tools.function import ToolResult
from mcp.types import CallToolResult, TextContent

from mcp_visibility_probe import load_source
from mcp_repair_chain_probe import load as load_hermes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/mcp-paper-evidence'


def classify_exception(exc, test_path):
    # KeyError/JSONDecodeError inside an original assertion is a failed test
    # oracle, not a broken test runner. Preserve the exception either way.
    frames = traceback.extract_tb(exc.__traceback__)
    assertion_context = any(Path(f.filename) == test_path and (f.line or '').lstrip().startswith('assert ')
                            for f in frames)
    return {'status': 'assertion_evaluation_failure' if assertion_context else 'harness_or_runtime_error',
            'exception_type': type(exc).__name__, 'traceback': traceback.format_exc()}


def main():
    rows = []
    for label in ['agno-before-tests', 'agno-after-tests']:
        path = OUT / 'sources' / (label + '.py')
        nodes = [n for n in ast.parse(path.read_text()).body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')
                 and ('structured_content' in n.name or 'preserves_meta' in n.name or 'preserves_metadata' in n.name)]
        for version in ['before', 'after']:
            adapter = load_source(version)
            env = dict(pytest=pytest, AsyncMock=AsyncMock, MagicMock=MagicMock, patch=patch,
                       json=json, CallToolResult=CallToolResult, TextContent=TextContent,
                       ToolResult=ToolResult, get_entrypoint_for_tool=adapter.get_entrypoint_for_tool)
            exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), env)
            for node in nodes:
                result = {'project': 'Agno', 'test_source': label, 'implementation': version,
                          'test': node.name, 'source_line': node.lineno, 'status': 'pass'}
                try:
                    value = env[node.name]()
                    if inspect.isawaitable(value):
                        asyncio.run(value)
                except AssertionError:
                    result.update(status='assertion_failure', traceback=traceback.format_exc())
                except Exception as exc:
                    result.update(classify_exception(exc, path))
                rows.append(result)

    for label in ['hermes-first-tests', 'hermes-combined-tests']:
        path = OUT / 'sources' / (label + '.py')
        for version in ['hermes-before', 'hermes-structured-first', 'hermes-combined']:
            handler_module = load_hermes(version)
            tools_package = types.ModuleType('tools')
            tools_package.mcp_tool = handler_module
            # Original test imports and patch targets resolve to the pinned native module.
            with patch.dict(sys.modules, {'tools': tools_package, 'tools.mcp_tool': handler_module}):
                spec = importlib.util.spec_from_file_location(label.replace('-', '_'), path)
                tests = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(tests)
                instance = tests.TestStructuredContentPreservation()
                for name in sorted(n for n in dir(instance) if n.startswith('test_')):
                    fixture = tests._patch_mcp_server.__wrapped__()
                    session = next(fixture)
                    result = {'project': 'Hermes', 'test_source': label, 'implementation': version,
                              'test': name, 'status': 'pass'}
                    try:
                        getattr(instance, name)(session)
                    except AssertionError:
                        result.update(status='assertion_failure', traceback=traceback.format_exc())
                    except Exception as exc:
                        result.update(classify_exception(exc, path))
                    finally:
                        fixture.close()
                    rows.append(result)

    groups = []
    for project, test_source, implementation in sorted({(r['project'], r['test_source'], r['implementation']) for r in rows}):
        group = [r for r in rows if (r['project'], r['test_source'], r['implementation']) == (project, test_source, implementation)]
        groups.append(dict(project=project, test_source=test_source, implementation=implementation,
                           total=len(group), passed=sum(r['status'] == 'pass' for r in group),
                           assertion_failures=sum(r['status'] in ['assertion_failure', 'assertion_evaluation_failure'] for r in group),
                           runtime_errors=sum(r['status'] == 'harness_or_runtime_error' for r in group)))
    report = {'protocol': 'research/mcp-paper-evidence-protocol.json', 'rows': rows, 'groups': groups,
              'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT / 'sources').glob('*tests.py')},
              'limits': ['Selected original upstream tests only, not complete CI suites or historical environments.',
                         'Agno original function AST bodies and decorators executed; imports bound to existing native dependencies.',
                         'Hermes complete test modules executed with their own fixtures, importing each pinned handler module.',
                         'Expected assertions may fail across repair versions; this is a measured oracle comparison, not harness success rate.',
                         'Later Agno adapter transplanted into Agno2.6.20; no later-release installation claim.'],
              'paid_api_calls': 0}
    (OUT / 'upstream-test-execution.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(groups, indent=2))
    assert not any(r['status'] == 'harness_or_runtime_error' for r in rows)


if __name__ == '__main__':
    main()
